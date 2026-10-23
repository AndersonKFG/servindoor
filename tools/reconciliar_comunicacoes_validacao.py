#!/usr/bin/env python3
"""Recupera a marcação de ingressos enviados conferindo o QR do anexo histórico.

Diagnóstico por padrão. Não inicializa o banco, não gera ingressos e não envia e-mails.
"""

import argparse
import asyncio
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select, text, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.all_models import SolicitacaoValidacao
from app.services.validacao_comunicacao import chave_comunicacao, email_queue


def decodificar_tokens(*anexos):
    from PIL import Image
    import zxingcpp

    tokens = set()
    for anexo in anexos:
        if anexo:
            with Image.open(io.BytesIO(anexo)) as imagem:
                tokens.update(codigo.text for codigo in zxingcpp.read_barcodes(
                    imagem.convert("RGB"), formats=zxingcpp.BarcodeFormat.QRCode,
                ))
    return tokens


async def diagnosticar(conn, decodificar=decodificar_tokens):
    # O endereço limita a leitura dos anexos. Somente o token exato do ingresso
    # comprova o vínculo, inclusive quando várias pessoas compartilham e-mail.
    candidatos = (await conn.execute(text("""
        SELECT s.id AS solicitacao_id, i.qr_code_token, e.id AS email_id,
               e.status, e.sent_at, e.created_at
        FROM solicitacoes_validacao s
        JOIN usuarios u ON u.id = s.usuario_id
        JOIN ingressos i ON i.usuario_id = s.usuario_id AND i.lote_id = s.lote_id
                         AND i.deleted_at IS NULL
        JOIN email_queue e ON lower(trim(e.recipient)) = lower(trim(u.email))
        WHERE s.status = 'aprovado' AND s.comunicado IS FALSE
          AND e.sender_type = 'ticket' AND e.status IN ('sent', 'queued', 'sending')
          AND e.idempotency_key IS NULL
          AND NOT EXISTS (SELECT 1 FROM email_queue existente
              WHERE existente.idempotency_key = 'validacao:' || CAST(s.id AS VARCHAR) || ':' || s.status)
        ORDER BY s.id, e.id
    """))).mappings().all()
    pendentes = (await conn.execute(text("""
        SELECT COUNT(*) FROM solicitacoes_validacao s
        WHERE s.status IN ('aprovado', 'rejeitado') AND s.comunicado IS FALSE
          AND NOT EXISTS (SELECT 1 FROM email_queue existente
              WHERE existente.idempotency_key = 'validacao:' || CAST(s.id AS VARCHAR) || ':' || s.status)
    """))).scalar_one()
    cache = {}
    grupos = defaultdict(dict)
    for candidato in candidatos:
        email_id = candidato["email_id"]
        if email_id not in cache:
            anexos = (await conn.execute(text("""
                SELECT ticket_image, qr_image FROM email_queue WHERE id = :id
            """), {"id": email_id})).one()
            try:
                cache[email_id] = decodificar(*anexos)
            except ImportError:
                raise
            except Exception:
                # Anexo inválido ou QR ilegível nunca autoriza marcar como comunicado.
                cache[email_id] = set()
        if cache[email_id] == {candidato["qr_code_token"]}:
            grupos[candidato["solicitacao_id"]][email_id] = dict(candidato)

    recuperaveis = []
    for solicitacao_id, mensagens in grupos.items():
        enviados = [m for m in mensagens.values() if m["status"] == "sent" and m["sent_at"]]
        if not enviados:
            continue
        enviado = min(enviados, key=lambda m: m["email_id"])
        recuperaveis.append({
            "solicitacao_id": solicitacao_id, "email_id": enviado["email_id"],
            "duplicatas_na_fila": sorted(m["email_id"] for m in mensagens.values()
                                        if m["status"] in ("queued", "sending")),
        })
    return {
        "pendentes_antes": pendentes, "recuperaveis": len(recuperaveis),
        "sem_comprovacao": pendentes - len(recuperaveis),
        "duplicatas_na_fila": sum(len(r["duplicatas_na_fila"]) for r in recuperaveis),
        "registros": recuperaveis,
    }


async def aplicar(conn, diagnostico):
    for registro in diagnostico["registros"]:
        parametros = {
            "solicitacao_id": registro["solicitacao_id"], "email_id": registro["email_id"],
            "chave": chave_comunicacao(registro["solicitacao_id"], "aprovado"),
        }
        resultado = await conn.execute(text("""
            UPDATE email_queue SET idempotency_key = :chave
            WHERE id = :email_id AND status = 'sent' AND sent_at IS NOT NULL
              AND (idempotency_key IS NULL OR idempotency_key = :chave)
        """), parametros)
        if resultado.rowcount != 1:
            raise ValueError("Histórico de envio mudou. Gere outro diagnóstico.")
        criado_em = (await conn.execute(
            select(email_queue.c.created_at).where(email_queue.c.id == registro["email_id"])
        )).scalar_one()
        # Usa o tipo de data do ORM para preservar UTC também nas colunas legadas.
        resultado = await conn.execute(update(SolicitacaoValidacao).where(
            SolicitacaoValidacao.id == registro["solicitacao_id"],
            SolicitacaoValidacao.status == "aprovado", SolicitacaoValidacao.comunicado.is_(False),
        ).values(comunicado=True, comunicado_em=criado_em))
        if resultado.rowcount != 1:
            raise ValueError("Solicitação mudou. Gere outro diagnóstico.")
        for email_id in registro["duplicatas_na_fila"]:
            await conn.execute(text("""
                UPDATE email_queue SET status = 'cancelled', last_error = 'duplicate_already_sent'
                WHERE id = :id AND status IN ('queued', 'sending')
            """), {"id": email_id})


async def executar(args):
    from app.db.session import engine
    from app.services.email_queue import _LEADER_LOCK_ID

    engine.echo = False
    try:
        async with engine.begin() as conn:
            if conn.dialect.name != "postgresql":
                raise ValueError("O CLI exige PostgreSQL. Os testes usam bancos isolados.")
            if args.aplicar:
                adquirido = await conn.scalar(text("SELECT pg_try_advisory_xact_lock(:id)"),
                                               {"id": _LEADER_LOCK_ID})
                if not adquirido:
                    raise ValueError("Pare todos os workers da aplicação antes de aplicar a reconciliação.")
                await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                await conn.execute(text("LOCK TABLE email_queue, solicitacoes_validacao, ingressos, usuarios IN SHARE ROW EXCLUSIVE MODE"))
            else:
                await conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            diagnostico = await diagnosticar(conn)
            if args.aplicar:
                await aplicar(conn, diagnostico)
        diagnostico["estado"] = "aplicado" if args.aplicar else "diagnostico"
        print(json.dumps(diagnostico, ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aplicar", action="store_true", help="Recupera marcações comprovadas; exige workers parados.")
    args = parser.parse_args()
    try:
        asyncio.run(executar(args))
    except Exception as exc:
        # Exceções SQL podem carregar parâmetros e anexos; não imprimir o conteúdo.
        mensagem = str(exc) if isinstance(exc, (ValueError, ImportError)) else type(exc).__name__
        parser.exit(1, f"Reconciliação interrompida: {mensagem}\n")


if __name__ == "__main__":
    main()
