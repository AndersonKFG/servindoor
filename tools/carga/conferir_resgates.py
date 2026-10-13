#!/usr/bin/env python3
"""Auditoria somente de leitura de um resgate de carga, sem dados pessoais na saída."""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _positive_id(value):
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("O ID deve ser positivo.")
    return parsed


def _run_id(value):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}", value):
        raise argparse.ArgumentTypeError("Identificação de teste inválida.")
    return value


def _photo_state(url, photo_root):
    prefix = "/static/uploads/fotos/"
    if not url or not url.startswith(prefix):
        return "caminho_invalido"
    try:
        candidate = (photo_root / url[len(prefix):]).resolve()
        if not candidate.is_relative_to(photo_root):
            return "caminho_invalido"
        if not candidate.is_file() or candidate.stat().st_size < 4:
            return "ausente_ou_vazio"
        with candidate.open("rb") as photo:
            return "presente_jpeg" if photo.read(3) == b"\xff\xd8\xff" else "formato_invalido"
    except OSError:
        return "ausente_ou_vazio"


async def audit(run_id, lot_id, expected_confirmations=None):
    from sqlalchemy import text
    from app.db.session import async_session, engine

    # Nenhum SQL ou parâmetro precisa aparecer no console da auditoria.
    engine.echo = False
    parameters = {
        "lot_id": lot_id,
        "fingerprint_prefix": f"loadtest_{run_id}_",
        "user_marker": f"TESTE_CARGA_{run_id}",
        "email_marker": f"TESTE CARGA {run_id} VU ",
    }
    try:
        async with async_session() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            await session.execute(text("SET LOCAL statement_timeout = '15s'"))
            lot = (await session.execute(text("""
                SELECT quantidade_total, quantidade_resgatada FROM lotes WHERE id = :lot_id
            """), parameters)).mappings().first()
            if lot is None:
                raise ValueError("Lote não encontrado.")
            reservation_states = dict((await session.execute(text("""
                SELECT status, COUNT(*) FROM reservas_ingressos
                WHERE lote_id = :lot_id
                  AND LEFT(device_fingerprint, LENGTH(:fingerprint_prefix)) = :fingerprint_prefix
                GROUP BY status
            """), parameters)).all())
            active_total = await session.scalar(text("""
                SELECT COUNT(*) FROM reservas_ingressos
                WHERE lote_id = :lot_id AND status = 'ativa' AND utilizada = FALSE
                  AND expira_em > NOW() AND criada_em < NOW()
            """), parameters)
            requests = (await session.execute(text("""
                SELECT s.id, s.reserva_id, s.usuario_id, s.status,
                       u.cpf, u.foto_rosto_url, r.status AS reserva_status, r.utilizada,
                       r.device_fingerprint
                FROM solicitacoes_validacao s JOIN usuarios u ON u.id = s.usuario_id
                LEFT JOIN reservas_ingressos r ON r.id = s.reserva_id
                WHERE s.lote_id = :lot_id AND u.setor = :user_marker
                LIMIT 5001
            """), parameters)).mappings().all()
            if len(requests) > 5000:
                raise ValueError("Quantidade fora do escopo deste teste.")
            job_states = dict((await session.execute(text("""
                SELECT j.status, COUNT(*) FROM resgate_jobs j
                JOIN solicitacoes_validacao s ON s.id = j.solicitacao_id
                JOIN usuarios u ON u.id = s.usuario_id
                WHERE s.lote_id = :lot_id AND u.setor = :user_marker
                GROUP BY j.status
            """), parameters)).all())
            email_states = dict((await session.execute(text("""
                SELECT status, COUNT(*) FROM email_queue
                WHERE STRPOS(html_body, :email_marker) > 0
                GROUP BY status
            """), parameters)).all())
            # A transação de diagnóstico termina antes de ler o disco.
            await session.rollback()

        photo_root = (PROJECT_ROOT / "app/static/uploads/fotos").resolve()
        photo_states = {}
        for row in requests:
            state = _photo_state(row["foto_rosto_url"], photo_root)
            photo_states[state] = photo_states.get(state, 0) + 1
        reservation_ids = {row["reserva_id"] for row in requests if row["reserva_id"] is not None}
        photo_urls = {row["foto_rosto_url"] for row in requests if row["foto_rosto_url"]}
        checks = {
            "ha_cadastros_do_teste": len(requests) > 0,
            "cpfs_unicos": len({row["cpf"] for row in requests}) == len(requests),
            "uma_solicitacao_por_reserva": len(reservation_ids) == len(requests),
            "reservas_concluidas_vinculadas": all(
                row["reserva_status"] == "concluida" and row["utilizada"]
                and (row["device_fingerprint"] or "").startswith(parameters["fingerprint_prefix"])
                for row in requests
            ),
            "fotos_unicas": len(photo_urls) == len(requests),
            "fotos_presentes_jpeg": photo_states.get("presente_jpeg", 0) == len(requests),
            "contador_nao_excede_lotacao": 0 <= lot["quantidade_resgatada"] <= lot["quantidade_total"],
            "ocupacao_nao_excede_lotacao": lot["quantidade_resgatada"] + active_total <= lot["quantidade_total"],
            "uma_tarefa_externa_por_cadastro": sum(job_states.values()) == len(requests),
            "um_email_por_cadastro": sum(email_states.values()) == len(requests),
        }
        if expected_confirmations is not None:
            checks["cadastros_conferem_com_resumo_http"] = len(requests) == expected_confirmations
        return {
            "teste": run_id, "lote_id": lot_id,
            "capacidade": lot["quantidade_total"], "contador_resgatado": lot["quantidade_resgatada"],
            "reservas_ativas_no_lote": active_total, "reservas_deste_teste": reservation_states,
            "solicitacoes_deste_teste": len(requests),
            "usuarios_distintos": len({row["usuario_id"] for row in requests}),
            "fotos": photo_states, "validacao_externa": job_states, "emails": email_states,
            "verificacoes": checks, "consistente": all(checks.values()),
            "limites": "Somente leitura. O estado do banco é um snapshot; fotos são conferidas depois. JPEG verifica assinatura, não rosto. E-mail sent indica aceite SMTP, não entrega na caixa. Não procura fotos órfãs fora dos cadastros do teste.",
        }
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("teste", type=_run_id, help="Identificação exibida no resumo do k6")
    parser.add_argument("lote_id", type=_positive_id)
    parser.add_argument("--confirmados", type=int, help="resgates_confirmados do resumo HTTP")
    args = parser.parse_args()
    if args.confirmados is not None and not 0 <= args.confirmados <= 2000:
        parser.error("--confirmados deve estar entre 0 e 2000.")
    try:
        report = asyncio.run(audit(args.teste, args.lote_id, args.confirmados))
    except Exception as exc:
        # Exceções do driver podem conter SQL/parâmetros: não as imprime.
        print(json.dumps({"erro": "Não foi possível concluir a auditoria.", "tipo": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["consistente"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
