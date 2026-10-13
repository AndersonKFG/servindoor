"""Mede um pico de reservas com SQL real em esquema PostgreSQL descartável.

Não acessa o site, não chama init_db e não altera tabelas/dados da aplicação.
Exercita a função de reserva e seu limitador; não mede HTTP, SSE ou formulário.
"""

import argparse
import asyncio
import json
import logging
import math
import sys
import time
import uuid
from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from starlette.requests import Request

from app.core.config import settings
from app.db.session import engine
from app.models.all_models import Lote
from app.routers import resgate
from app.services.reserva_batch import ReservaBatchService


class WorkerServices:
    """Actors independentes compartilham somente o PostgreSQL do esquema isolado."""

    def __init__(self, workers, session_factory):
        self.worker = ContextVar("benchmark_worker", default=0)
        self.services = [ReservaBatchService(session_factory) for _ in range(workers)]

    async def reserve(self, **kwargs):
        return await self.services[self.worker.get()].reserve(**kwargs)

    async def stop(self):
        await asyncio.gather(*(service.stop() for service in self.services))


def p95(samples):
    if not samples:
        return None
    ordered = sorted(samples)
    return round(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)], 2)


async def benchmark(args):
    schema = "benchmark_reserva_" + uuid.uuid4().hex
    pool = create_async_engine(
        settings.DATABASE_URL, pool_size=args.pool_size, max_overflow=0, pool_timeout=30,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = sessionmaker(pool, class_=AsyncSession, expire_on_commit=False)
    actors = WorkerServices(args.workers, sessions)
    secret = uuid.uuid4().hex + uuid.uuid4().hex
    run_id = uuid.uuid4().hex[:12]
    stage_times = {}
    timings = []
    outcomes = Counter()
    errors = Counter()
    start = asyncio.Event()

    async def visitor(number):
        actors.worker.set(number % args.workers)
        fingerprint = f"loadtest_benchmark_{run_id}_{number}"
        request = Request({
            "type": "http", "method": "POST", "scheme": "http",
            "path": "/api/lote/1/reservar", "query_string": b"",
            "headers": [(b"x-load-test-key", secret.encode())],
            "server": ("benchmark.invalid", 8000), "client": ("192.0.2.22", 12345),
        })
        await start.wait()
        begin = time.perf_counter()
        try:
            if args.service_direct:
                result = await actors.reserve(lote_id=1, fp=fingerprint, device_id=fingerprint,
                    browser_hash="browser_" + fingerprint, cpf=None, ip="192.0.2.22",
                    rate_key="loadtest:192.0.2.22:" + fingerprint)
                status_code = result.status_code
                payload = {"codigo": result.codigo, "token_reserva": result.reserva.token if result.reserva else None}
            else:
                async with sessions() as session:
                    response = await resgate.pagina_resgate(
                        request, 1, device_fingerprint=fingerprint,
                        device_id=fingerprint, cpf=None, session=session,
                    )
                status_code = response.status_code
                payload = json.loads(response.body)
            if status_code == 200 and payload.get("token_reserva"):
                outcomes["accepted"] += 1
            elif status_code == 400 and payload.get("codigo") in ("em_preenchimento", "esgotado"):
                outcomes["capacity"] += 1
            else:
                outcomes["technical_error"] += 1
                errors[f"http_{status_code}_{payload.get('codigo', 'unknown')}"] += 1
        except Exception as exc:
            outcomes["technical_error"] += 1
            errors[type(exc).__name__] += 1
        finally:
            timings.append((time.perf_counter() - begin) * 1000)
            for name, duration in getattr(request.state, "reserva_tempos", {}).items():
                stage_times.setdefault(name, []).append(duration)

    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with pool.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            for index in (
                "CREATE UNIQUE INDEX uq_reserva_cpf_ativa ON reservas_ingressos (cpf) WHERE status = 'ativa'",
                "CREATE UNIQUE INDEX uq_reserva_browser_ativa ON reservas_ingressos (browser_token_hash) WHERE status = 'ativa'",
                "CREATE INDEX idx_rate_limit_ip_acao_ts ON rate_limit_tentativas (ip, acao, criado_em)",
                "CREATE INDEX idx_reserva_capacidade_ativa ON reservas_ingressos (lote_id, expira_em) WHERE status = 'ativa'",
                "CREATE INDEX idx_reserva_fingerprint_ativa ON reservas_ingressos (device_fingerprint, expira_em DESC) WHERE status = 'ativa'",
                "CREATE INDEX idx_reserva_device_ativa ON reservas_ingressos (device_id, expira_em DESC) WHERE status = 'ativa'",
            ):
                await conn.execute(text(index))
        async with sessions() as session:
            session.add(Lote(id=1, nome="Benchmark isolado", quantidade_total=args.slots, ativo=True))
            await session.commit()

        # Disponibiliza conexões antes do pico, como uma aplicação já iniciada.
        async def warm_connection():
            async with pool.connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.gather(*(warm_connection() for _ in range(args.pool_size)))
        logging.getLogger("app.routers.resgate").setLevel(logging.ERROR)
        patches = [
            patch.object(resgate, "async_session", sessions),
            patch.object(resgate, "reserva_batch_service", actors),
            patch.object(resgate, "_ultima_varredura_expiracao", time.monotonic() + args.deadline),
            patch.object(resgate, "_publicar_mudanca_reserva", return_value=None),
            patch.object(settings, "LOAD_TEST_SECRET", secret),
            patch.object(settings, "LOAD_TEST_LOTE_ID", 1),
            patch.object(settings, "LOAD_TEST_UNTIL", (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat()),
        ]
        for item in patches:
            item.start()
        try:
            tasks = [asyncio.create_task(visitor(i)) for i in range(args.visitors)]
            begin = time.perf_counter()
            start.set()
            await asyncio.wait_for(asyncio.gather(*tasks), args.deadline)
            elapsed = time.perf_counter() - begin
        finally:
            await actors.stop()
            for item in reversed(patches):
                item.stop()

        async with sessions() as session:
            reserves = await session.scalar(text("SELECT COUNT(*) FROM reservas_ingressos WHERE status = 'ativa'"))
            rate_records = await session.scalar(text("SELECT COUNT(*) FROM rate_limit_tentativas"))
        return {
            "visitors": args.visitors, "slots": args.slots, "worker_queues": args.workers,
            "entrypoint": "batch_service" if args.service_direct else "route_function",
            "pool_size": args.pool_size, "elapsed_seconds": round(elapsed, 3),
            "end_to_end_p95_ms": p95(timings), "end_to_end_max_ms": round(max(timings), 2),
            "latency_target_ms": args.latency_target_ms,
            "latency_target_met": p95(timings) < args.latency_target_ms,
            "outcomes": dict(outcomes), "errors": dict(errors),
            "persisted_active_reserves": reserves, "rate_limit_records": rate_records,
            "stages_p95_ms": {name: p95(values) for name, values in stage_times.items()},
            "capacity_correct": outcomes["accepted"] == min(args.visitors, args.slots)
                and reserves == min(args.visitors, args.slots)
                and outcomes["capacity"] == max(0, args.visitors - args.slots),
            "limitations": "SQL real, um event loop e filas de workers simuladas; exclui HTTP, Cloudflare, fanout SSE, foto e formulário.",
        }
    finally:
        await actors.stop()
        await pool.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visitors", type=int, default=2000)
    parser.add_argument("--slots", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--pool-size", type=int, default=20)
    parser.add_argument("--deadline", type=int, default=120)
    parser.add_argument("--latency-target-ms", type=int, default=3000)
    parser.add_argument("--service-direct", action="store_true")
    args = parser.parse_args()
    if not (1 <= args.visitors <= 4000 and 1 <= args.slots <= 4000
            and 1 <= args.workers <= 8 and 2 <= args.pool_size <= 80
            and 1 <= args.deadline <= 300 and 1 <= args.latency_target_ms <= 30000):
        parser.error("Parâmetros fora dos limites de segurança do benchmark local.")
    result = asyncio.run(benchmark(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["capacity_correct"] and not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
