"""Confirma formulários concorrentes em esquema PostgreSQL e fotos descartáveis.

Reserva vagas com atores independentes, envia os formulários de uma vez e
confere a persistência de participante, solicitação, foto, e-mail e tarefa.
Não usa HTTP/Cloudflare, não inicia workers e não chama SMTP nem API externa.
"""

import argparse
import asyncio
import base64
import io
import json
import logging
import math
import random
import sys
import tempfile
import time
import uuid
from collections import Counter
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from starlette.requests import Request

from app.core.config import settings
from app.db.session import engine
from app.models.all_models import Lote, Secretaria
from app.routers import resgate
from app.services import email_service
from app.services.resgate_jobs import RESGATE_JOBS_DDL, RESGATE_JOBS_INDEX_DDL
from app.services.reserva_batch import ReservaBatchService


class WorkerQueues:
    """Simula as filas de quatro processos sem compartilhar locks Python."""

    def __init__(self, workers):
        self.worker = ContextVar("confirmation_benchmark_worker", default=0)
        self.queues = [{} for _ in range(workers)]

    def get(self, key):
        return self.queues[self.worker.get()].get(key)

    def __setitem__(self, key, value):
        self.queues[self.worker.get()][key] = value


def percentile95(samples):
    if not samples:
        return None
    values = sorted(samples)
    return round(values[max(0, math.ceil(len(values) * 0.95) - 1)], 2)


def synthetic_cpf(number):
    digits = [int(value) for value in f"{700000000 + number:09d}"]
    for length in (9, 10):
        check = (sum(value * (length + 1 - index) for index, value in enumerate(digits)) * 10) % 11
        digits.append(0 if check == 10 else check)
    return "".join(map(str, digits))


def synthetic_photo(side):
    pixels = random.Random(421).randbytes(side * side * 3)
    image = Image.frombytes("RGB", (side, side), pixels)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    data = buffer.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode(), len(data)


async def create_tables(pool):
    async with pool.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        for statement in (
            "CREATE UNIQUE INDEX uq_reserva_cpf_ativa ON reservas_ingressos (cpf) WHERE status='ativa'",
            "CREATE UNIQUE INDEX uq_reserva_browser_ativa ON reservas_ingressos (browser_token_hash) WHERE status='ativa'",
            "CREATE UNIQUE INDEX uq_solicitacao_usuario_ativo ON solicitacoes_validacao (usuario_id) WHERE status IN ('pendente_analise','aprovado')",
            "CREATE UNIQUE INDEX uq_ingresso_usuario_ativo ON ingressos (usuario_id) WHERE deleted_at IS NULL",
            "CREATE INDEX idx_rate_limit_ip_acao_ts ON rate_limit_tentativas (ip,acao,criado_em)",
            "CREATE INDEX idx_reserva_capacidade_ativa ON reservas_ingressos (lote_id,expira_em) WHERE status='ativa'",
            "CREATE INDEX idx_reserva_fingerprint_ativa ON reservas_ingressos (device_fingerprint,expira_em DESC) WHERE status='ativa'",
            "CREATE INDEX idx_reserva_device_ativa ON reservas_ingressos (device_id,expira_em DESC) WHERE status='ativa'",
            """CREATE TABLE email_queue (
                id BIGSERIAL PRIMARY KEY, recipient VARCHAR NOT NULL,
                subject VARCHAR NOT NULL, html_body TEXT NOT NULL,
                sender_type VARCHAR NOT NULL DEFAULT 'ticket', qr_image BYTEA,
                ticket_image BYTEA, status VARCHAR NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), sent_at TIMESTAMPTZ, last_error TEXT
            )""",
            RESGATE_JOBS_DDL, RESGATE_JOBS_INDEX_DDL,
        ):
            await conn.execute(text(statement))


async def benchmark(args):
    schema = "benchmark_confirmacao_" + uuid.uuid4().hex
    pool = create_async_engine(
        settings.DATABASE_URL, pool_size=args.pool_size, max_overflow=0, pool_timeout=30,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = sessionmaker(pool, class_=AsyncSession, expire_on_commit=False)
    actors = [ReservaBatchService(sessions) for _ in range(args.workers)]
    queues = WorkerQueues(args.workers)
    upload_slots = [asyncio.Semaphore(args.uploads_per_worker) for _ in actors]
    photo, photo_bytes = synthetic_photo(args.photo_side)
    owner_prefix = uuid.uuid4().hex
    reservations = {}
    reserve_outcomes, form_outcomes, errors = Counter(), Counter(), Counter()
    reserve_times, form_times, retry_times = [], [], []
    sql_stage_times = {}
    receipt_ids = {}
    start = asyncio.Event()
    patches = []
    provider = AsyncMock(side_effect=AssertionError("A confirmação chamou API externa"))
    smtp = Mock(side_effect=AssertionError("A confirmação chamou SMTP"))
    schema_created = False
    photos = tempfile.TemporaryDirectory(prefix="benchmark_confirmation_photos_")

    async def reserve(number):
        browser_payload = f"benchmark_owner_{owner_prefix}_{number}"
        fingerprint = f"loadtest_benchmark_{owner_prefix}_{number}"
        began = time.perf_counter()
        result = await actors[number % args.workers].reserve(
            lote_id=1, fp=fingerprint, device_id=fingerprint,
            browser_hash=resgate.hash_token(browser_payload), cpf=None,
            ip="192.0.2.22", rate_key=f"loadtest:192.0.2.22:{fingerprint}",
        )
        reserve_times.append((time.perf_counter() - began) * 1000)
        if result.status_code == 200 and result.reserva:
            cookie = f"{resgate.COOKIE_BROWSER_ID}={resgate.assinar_browser_token(browser_payload)}"
            reservations[number] = (result.reserva.token, cookie)
            reserve_outcomes["accepted"] += 1
        elif result.status_code == 400 and result.codigo in ("em_preenchimento", "esgotado"):
            reserve_outcomes["capacity"] += 1
        else:
            reserve_outcomes["technical_error"] += 1
            errors[f"reserve_http_{result.status_code}_{result.codigo}"] += 1

    async def confirm(number, retry=False):
        token, cookie = reservations[number]
        worker = number % args.workers
        queues.worker.set(worker)
        request = Request({
            "type": "http", "method": "POST", "scheme": "http",
            "path": "/api/lote/1/resgatar", "query_string": b"",
            "headers": [(b"cookie", cookie.encode())],
            "server": ("benchmark.invalid", 8000), "client": ("192.0.2.22", 12345),
        })
        await start.wait()
        began = time.perf_counter()
        try:
            # Inclui a espera da fila de upload na latência percebida pelo VU.
            async with upload_slots[worker], sessions() as session:
                response = await resgate.processar_resgate(
                    request, 1, token_reserva=token, cpf=synthetic_cpf(number),
                    nome=f"Participante sintético {number}", data_nascimento="1990-01-01",
                    setor="Benchmark descartável", secretaria_id=1, vinculo="Efetivo",
                    telefone="81999990000", email=f"benchmark{number}@example.invalid",
                    foto_base64=photo, session=session,
                )
            payload = json.loads(response.body)
            if response.status_code == 200 and payload.get("sucesso") and payload.get("solicitacao_id"):
                form_outcomes["retry_ok" if retry else "confirmed"] += 1
                receipt_ids.setdefault(number, set()).add(payload["solicitacao_id"])
            else:
                form_outcomes["technical_error"] += 1
                errors[f"form_http_{response.status_code}_{payload.get('codigo', 'unknown')}"] += 1
        except HTTPException as exc:
            form_outcomes["technical_error"] += 1
            errors[f"form_http_{exc.status_code}"] += 1
        except asyncio.CancelledError:
            form_outcomes["interrupted"] += 1
            raise
        except Exception as exc:
            form_outcomes["technical_error"] += 1
            errors[f"form_{type(exc).__name__}"] += 1
        finally:
            (retry_times if retry else form_times).append((time.perf_counter() - began) * 1000)
            for name, value in getattr(request.state, "reserva_tempos", {}).items():
                sql_stage_times.setdefault(name, []).append(value)

    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            schema_created = True
        await create_tables(pool)
        async with sessions() as session:
            session.add(Secretaria(id=1, nome="Secretaria isolada", sigla="TESTE"))
            session.add(Lote(id=1, nome="Confirmação descartável", quantidade_total=args.slots, ativo=True))
            await session.commit()

        patches = [
            patch.object(resgate, "async_session", sessions),
            patch.object(resgate, "_filas_criacao_reserva", queues),
            patch.object(resgate, "FOTOS_DIR", photos.name),
            patch.object(resgate, "_ultima_varredura_expiracao", time.monotonic() + args.deadline),
            patch.object(resgate, "_publicar_mudanca_reserva", return_value=None),
            patch.object(resgate.ServidorValidationService, "verificar_servidor", provider),
            patch.object(email_service, "_send_smtp_email_sync", smtp),
        ]
        for item in patches:
            item.start()
        logging.getLogger("app.routers.resgate").setLevel(logging.ERROR)
        logging.getLogger("app.services.email_queue").setLevel(logging.ERROR)
        await asyncio.gather(*(actor.start() for actor in actors))
        reserve_began = time.perf_counter()
        await asyncio.wait_for(asyncio.gather(*(reserve(number) for number in range(args.visitors))), args.deadline)
        reserve_elapsed = time.perf_counter() - reserve_began
        print(json.dumps({"phase": "reservations_complete", "outcomes": dict(reserve_outcomes),
                          "seconds": round(reserve_elapsed, 3)}, ensure_ascii=False), flush=True)

        tasks = []
        for index, number in enumerate(reservations):
            tasks.append(asyncio.create_task(confirm(number)))
            if index < args.duplicates:
                tasks.append(asyncio.create_task(confirm(number, retry=True)))
        began = time.perf_counter()
        start.set()
        timed_out = False
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), args.deadline)
        except asyncio.TimeoutError:
            timed_out = True
            await asyncio.gather(*tasks, return_exceptions=True)
        form_elapsed = time.perf_counter() - began

        async with sessions() as session:
            stored = (await session.execute(text("""
                SELECT (SELECT COUNT(*) FROM usuarios) AS users,
                    (SELECT COUNT(*) FROM solicitacoes_validacao) AS requests,
                    (SELECT COUNT(*) FROM reservas_ingressos WHERE status='concluida') AS completed,
                    (SELECT COUNT(*) FROM reservas_ingressos WHERE status='ativa') AS active,
                    (SELECT quantidade_resgatada FROM lotes WHERE id=1) AS lot_counter,
                    (SELECT COUNT(*) FROM email_queue) AS emails,
                    (SELECT COUNT(*) FROM resgate_jobs) AS jobs,
                    (SELECT COUNT(*) FROM usuarios u JOIN solicitacoes_validacao s ON s.usuario_id=u.id
                        JOIN reservas_ingressos r ON s.reserva_id=r.id
                        WHERE r.status='concluida' AND r.utilizada=TRUE
                            AND r.cpf=u.cpf AND u.foto_rosto_url IS NOT NULL) AS full_rows
            """))).mappings().one()
            paths = (await session.execute(text("SELECT foto_rosto_url FROM usuarios"))).scalars().all()
        files = list(Path(photos.name).iterdir())
        missing_photos = sum(not (Path(photos.name) / Path(path).name).is_file() for path in paths)
        expected = min(args.visitors, args.slots)
        retries_expected = min(args.duplicates, expected)
        consistent = (
            reserve_outcomes["accepted"] == expected
            and reserve_outcomes["capacity"] == max(0, args.visitors - args.slots)
            and form_outcomes["confirmed"] == expected
            and form_outcomes["retry_ok"] == retries_expected
            and all(stored[key] == expected for key in (
                "users", "requests", "completed", "lot_counter", "emails", "jobs", "full_rows"))
            and stored["active"] == 0 and len(files) == expected and missing_photos == 0
            and len(receipt_ids) == expected and all(len(ids) == 1 for ids in receipt_ids.values())
            and provider.await_count == 0 and smtp.call_count == 0
        )
        return {
            "visitors": args.visitors, "slots": args.slots, "workers_simulated": args.workers,
            "uploads_per_worker": args.uploads_per_worker, "pool_size": args.pool_size,
            "photo_bytes_each": photo_bytes, "same_token_retries": retries_expected,
            "reserve_seconds": round(reserve_elapsed, 3), "reserve_p95_ms": percentile95(reserve_times),
            "form_seconds": round(form_elapsed, 3), "form_p95_ms": percentile95(form_times),
            "form_max_ms": round(max(form_times, default=0), 2), "retry_p95_ms": percentile95(retry_times),
            "forms_per_second": round(form_outcomes["confirmed"] / max(form_elapsed, 0.001), 2),
            "reserve_outcomes": dict(reserve_outcomes), "form_outcomes": dict(form_outcomes),
            "persisted": dict(stored), "photo_files": len(files), "missing_photos": missing_photos,
            "stages_p95_ms": {name: percentile95(values) for name, values in sql_stage_times.items()},
            "errors": dict(errors), "timed_out": timed_out, "all_data_consistent": consistent,
            "external_calls": provider.await_count, "smtp_calls": smtp.call_count,
            "limitations": "SQL/foto/fsync/outboxes reais; um event loop e filas de workers simuladas. Exclui HTTP, rede, Cloudflare, SSE e execução posterior dos jobs/e-mails. Repetições usam o mesmo token e CPF, não CPFs iguais em reservas diferentes.",
        }
    finally:
        await asyncio.gather(*(actor.stop() for actor in actors))
        for item in reversed(patches):
            item.stop()
        photos.cleanup()
        await pool.dispose()
        if schema_created:
            assert schema.startswith("benchmark_confirmacao_") and len(schema) == 54
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visitors", type=int, default=2000)
    parser.add_argument("--slots", type=int, default=1500)
    parser.add_argument("--duplicates", type=int, default=200)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--uploads-per-worker", type=int, default=16)
    parser.add_argument("--pool-size", type=int, default=20)
    parser.add_argument("--photo-side", type=int, default=512)
    parser.add_argument("--deadline", type=int, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not (1 <= args.visitors <= 4000 and 1 <= args.slots <= 4000 and 0 <= args.duplicates <= 1000
            and 1 <= args.workers <= 8 and 1 <= args.uploads_per_worker <= 64
            and 2 <= args.pool_size <= 80 and 32 <= args.photo_side <= 1024 and 1 <= args.deadline <= 300):
        parser.error("Parâmetros fora dos limites do benchmark local isolado.")
    result = asyncio.run(benchmark(args))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["all_data_consistent"] and not result["errors"] and not result["timed_out"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
