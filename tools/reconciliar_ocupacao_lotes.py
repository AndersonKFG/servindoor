#!/usr/bin/env python3
"""Diagnóstico por padrão; aplicação exige um plano revisado e ainda válido.

Não inicializa/migra o banco. Usa DATABASE_URL da aplicação apenas no CLI.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
VERSAO = 1


def digest(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def diagnosticar(dados):
    """Reconstrói resgates sem somar ingresso e solicitação do mesmo resgate.

    Solicitações legadas sem reserva também consomem cota. Rejeitadas e
    pendentes continuam contando, conforme a confirmação atual do resgate.
    Vínculos ambíguos exigem revisão, nunca uma correção por aproximação.
    """
    lote = dados["lote"]
    reservas = {r["id"]: r for r in dados["reservas"]}
    solicitacoes = dados["solicitacoes"]
    ingressos = dados["ingressos"]
    bloqueios = set()
    avisos = []
    por_usuario = Counter(s["usuario_id"] for s in solicitacoes)
    if any(total > 1 for total in por_usuario.values()):
        bloqueios.add("multiplas_solicitacoes_do_mesmo_usuario_no_lote")
    if any(total > 1 for total in Counter(i["usuario_id"] for i in ingressos).values()):
        bloqueios.add("multiplos_ingressos_do_mesmo_usuario_no_lote")

    vinculadas = []
    for solicitacao in solicitacoes:
        if solicitacao["status"] not in {"pendente_analise", "aprovado", "rejeitado"}:
            bloqueios.add("status_de_solicitacao_desconhecido")
        reserva_id = solicitacao["reserva_id"]
        if reserva_id is None:
            continue
        vinculadas.append(reserva_id)
        reserva = reservas.get(reserva_id)
        if (reserva is None or reserva["lote_id"] != lote["id"] or
                reserva["status"] != "concluida" or not reserva["utilizada"]):
            bloqueios.add("solicitacao_com_reserva_inconsistente")
    if len(vinculadas) != len(set(vinculadas)):
        bloqueios.add("reserva_vinculada_a_multiplas_solicitacoes")

    concluidas = {r["id"] for r in reservas.values()
                 if r["lote_id"] == lote["id"] and r["status"] == "concluida" and r["utilizada"]}
    orfas = concluidas - set(vinculadas)
    if orfas:
        bloqueios.add("reservas_concluidas_sem_solicitacao")
    if any(r["lote_id"] == lote["id"] and
           ((r["status"] == "concluida") != bool(r["utilizada"])) for r in reservas.values()):
        bloqueios.add("estado_de_reserva_inconsistente")

    legados = sum(i["usuario_id"] not in por_usuario for i in ingressos)
    por_titular = {s["usuario_id"]: s for s in solicitacoes}
    for ingresso in ingressos:
        solicitacao = por_titular.get(ingresso["usuario_id"])
        if solicitacao is None:
            continue
        # Não presumir que um ingresso legado pertence a um resgate posterior.
        emissao = datetime.fromisoformat(str(ingresso["data_resgate"]))
        confirmacao = datetime.fromisoformat(str(solicitacao["criado_em"]))
        if emissao.tzinfo is None:
            emissao = emissao.replace(tzinfo=timezone.utc)
        if confirmacao.tzinfo is None:
            confirmacao = confirmacao.replace(tzinfo=timezone.utc)
        if solicitacao["status"] != "aprovado" or emissao < confirmacao:
            bloqueios.add("vinculo_entre_ingresso_e_solicitacao_ambiguo")
    reconstruida = len(solicitacoes) + legados + len(orfas)
    cancelados = sum(i["cancelado"] for i in ingressos)
    atual = lote["quantidade_resgatada"]
    if atual < 0 or lote["quantidade_total"] < 0:
        bloqueios.add("contador_ou_capacidade_negativa")
    if reconstruida < atual:
        bloqueios.add("historico_insuficiente_para_explicar_contador_atual")
    if reconstruida - atual > cancelados:
        bloqueios.add("diferenca_nao_explicada_por_ingressos_cancelados")
    if reconstruida > lote["quantidade_total"]:
        avisos.append("ocupacao_historica_superior_a_capacidade_nao_sera_truncada")

    return {
        "lote_id": lote["id"],
        "capacidade": lote["quantidade_total"],
        "contador_atual": atual,
        "ocupacao_reconstruida": reconstruida,
        "contador_proposto": max(atual, reconstruida),
        "acrescimo": max(0, reconstruida - atual),
        "solicitacoes": len(solicitacoes),
        "ingressos_sem_solicitacao": legados,
        "ingressos_cancelados_ou_extraviados": cancelados,
        "reservas_concluidas_sem_solicitacao": len(orfas),
        "bloqueios": sorted(bloqueios),
        "avisos": avisos,
        "fingerprint": digest(dados),
    }


async def ler_diagnostico(conn, lote_id):
    lote = (await conn.execute(text("""
        SELECT id, quantidade_total, quantidade_resgatada, ativo,
               data_abertura, data_fechamento, deleted_at
        FROM lotes WHERE id = :id
    """), {"id": lote_id})).mappings().first()
    if lote is None or lote["deleted_at"] is not None:
        raise ValueError(f"Lote {lote_id} inexistente ou excluído.")
    reservas = (await conn.execute(text("""
        SELECT id, lote_id, status, utilizada FROM reservas_ingressos
        WHERE lote_id = :id OR id IN (
            SELECT reserva_id FROM solicitacoes_validacao WHERE lote_id = :id
        ) ORDER BY id
    """), {"id": lote_id})).mappings().all()
    solicitacoes = (await conn.execute(text("""
        SELECT id, usuario_id, reserva_id, status, criado_em FROM solicitacoes_validacao
        WHERE lote_id = :id ORDER BY id
    """), {"id": lote_id})).mappings().all()
    ingressos = (await conn.execute(text("""
        SELECT id, usuario_id, data_resgate, deleted_at IS NOT NULL AS cancelado
        FROM ingressos WHERE lote_id = :id ORDER BY id
    """), {"id": lote_id})).mappings().all()
    return diagnosticar({
        "lote": dict(lote), "reservas": [dict(r) for r in reservas],
        "solicitacoes": [dict(s) for s in solicitacoes],
        "ingressos": [dict(i) for i in ingressos],
    })


async def gerar_plano(conn, lote_ids, origem):
    return {
        "versao": VERSAO, "origem": origem,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "lotes": [await ler_diagnostico(conn, identifier) for identifier in sorted(set(lote_ids))],
    }


def ids_do_plano(plano):
    if (not isinstance(plano, dict) or plano.get("versao") != VERSAO or
            not isinstance(plano.get("lotes"), list) or not plano["lotes"] or
            any(not isinstance(item, dict) for item in plano["lotes"])):
        raise ValueError("Plano vazio ou com versão inválida.")
    ids = [item.get("lote_id") for item in plano["lotes"]]
    if (any(type(identifier) is not int or identifier < 1 for identifier in ids) or
            len(ids) != len(set(ids)) or len(ids) > 100):
        raise ValueError("IDs inválidos ou duplicados no plano (máximo de 100 lotes).")
    return ids


async def aplicar_plano(conn, plano, origem):
    """O chamador deve manter a transação e os locks até o commit."""
    ids = ids_do_plano(plano)
    if plano.get("origem") != origem:
        raise ValueError("Plano pertence a outro banco/servidor/schema.")
    atual = await gerar_plano(conn, ids, origem)
    if atual["lotes"] != plano["lotes"]:
        raise ValueError("Dados mudaram ou o plano foi editado. Gere e revise um novo diagnóstico.")
    if any(item["bloqueios"] for item in atual["lotes"]):
        raise ValueError("Plano contém ambiguidades bloqueantes. Revise o histórico antes de aplicar.")
    for item in atual["lotes"]:
        if not item["acrescimo"]:
            continue
        resultado = await conn.execute(text("""
            UPDATE lotes SET quantidade_resgatada = :depois
            WHERE id = :id AND quantidade_resgatada = :antes AND deleted_at IS NULL
        """), {"id": item["lote_id"], "antes": item["contador_atual"],
               "depois": item["contador_proposto"]})
        if resultado.rowcount != 1:
            raise ValueError("Contador mudou durante a aplicação. Transação deve ser revertida.")
    return atual


async def origem_do_banco(conn, engine):
    identidade = (await conn.execute(text("""
        SELECT current_database(), current_schema(), inet_server_addr()::text, inet_server_port()
    """))).one()
    return digest({"conexao": engine.url.render_as_string(hide_password=True),
                   "banco": list(identidade)})


async def executar(args, plano):
    from app.db.session import engine

    engine.echo = False
    try:
        if engine.dialect.name != "postgresql":
            raise ValueError("O CLI de produção exige PostgreSQL.")
        async with engine.begin() as conn:
            if not args.aplicar:
                await conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            await conn.execute(text("SET LOCAL statement_timeout = '30s'"))
            if args.aplicar:
                # Congela as evidências e os contadores durante a validação/UPDATE.
                # Usar em janela de manutenção: impede escritas nestas tabelas.
                await conn.execute(text("""
                    LOCK TABLE lotes, reservas_ingressos, solicitacoes_validacao, ingressos
                    IN SHARE ROW EXCLUSIVE MODE
                """))
            origem = await origem_do_banco(conn, engine)
            if args.aplicar:
                return await aplicar_plano(conn, plano, origem)
            return await gerar_plano(conn, args.lote_id, origem)
    finally:
        await engine.dispose()


def salvar(arquivo, value):
    arquivo.seek(0)
    json.dump(value, arquivo, ensure_ascii=False, indent=2)
    arquivo.write("\n")
    arquivo.truncate()
    arquivo.flush()
    os.fsync(arquivo.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--lote-id", type=int, action="append", help="Lote a diagnosticar; pode repetir.")
    modo.add_argument("--aplicar", type=Path, help="Plano JSON já revisado.")
    parser.add_argument("--saida", type=Path, required=True, help="Novo arquivo de plano ou recibo; não sobrescreve.")
    args = parser.parse_args()
    plano = None
    try:
        if args.aplicar:
            plano = json.loads(args.aplicar.read_text(encoding="utf-8"))
            ids_do_plano(plano)
        elif any(identifier < 1 for identifier in args.lote_id) or len(args.lote_id) > 100:
            raise ValueError("Informe entre 1 e 100 IDs positivos.")
        # Reserva o recibo antes de qualquer escrita no banco. Se o processo cair,
        # 'verificar_banco' indica resultado incerto; conferir os contadores.
        with args.saida.open("x+", encoding="utf-8") as arquivo:
            salvar(arquivo, {"estado": "verificar_banco" if args.aplicar else "diagnostico_iniciado",
                             "plano": plano})
            resultado = asyncio.run(executar(args, plano))
            salvar(arquivo, {"estado": "aplicado", "plano": resultado} if args.aplicar else resultado)
        print(f"{'Aplicação concluída' if args.aplicar else 'Diagnóstico sem alterações'}: {args.saida}")
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print("Falha ao acessar/aplicar no banco. Consulte o recibo e confira o estado antes de repetir.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
