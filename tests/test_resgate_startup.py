"""Migrações em schemas descartáveis; lifespan sem serviços externos."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.db import session as db
from app import main


class TestResgateMigrations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = "test_startup_" + uuid.uuid4().hex
        async with db.engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.pool = create_async_engine(settings.DATABASE_URL, pool_size=2, max_overflow=0,
            connect_args={"server_settings": {"search_path": self.schema}})

    async def asyncTearDown(self):
        await self.pool.dispose()
        async with db.engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await db.engine.dispose()

    async def migrate(self):
        with patch.object(db, "engine", self.pool):
            await db.init_db()

    async def test_migracao_fresh_repetida_preserva_dados_e_indices(self):
        await self.migrate()
        async with self.pool.begin() as conn:
            await conn.execute(text("INSERT INTO eixos(nome) VALUES ('Preservar eixo')"))
        await self.migrate()
        async with self.pool.connect() as conn:
            self.assertEqual(await conn.scalar(text("SELECT COUNT(*) FROM eixos")), 1)
            self.assertEqual(await conn.scalar(text("SELECT COUNT(*) FROM resgate_jobs")), 0)
            indexes = (await conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname=:schema"), {"schema": self.schema})).scalars().all()
            for name in ("uq_solicitacao_reserva", "idx_resgate_jobs_pending",
                         "idx_reserva_capacidade_ativa", "idx_reserva_fingerprint_ativa", "idx_reserva_device_ativa"):
                self.assertIn(name, indexes)

    async def test_migracao_adiciona_vinculo_reserva_em_banco_existente(self):
        await self.migrate()
        async with self.pool.begin() as conn:
            await conn.execute(text("ALTER TABLE solicitacoes_validacao DROP COLUMN reserva_id CASCADE"))
            await conn.execute(text("DROP TABLE resgate_jobs"))
        await self.migrate()
        async with self.pool.connect() as conn:
            self.assertEqual(await conn.scalar(text("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema=:schema AND table_name='solicitacoes_validacao'
                  AND column_name='reserva_id'
            """), {"schema": self.schema}), "integer")
            self.assertEqual(await conn.scalar(text("SELECT COUNT(*) FROM resgate_jobs")), 0)


class TestResgateLifespan(unittest.IsolatedAsyncioTestCase):
    async def test_inicia_e_encerra_todas_tarefas(self):
        started, stopped = set(), set()

        def worker(name):
            async def run(stop):
                started.add(name)
                try:
                    await stop.wait()
                finally:
                    stopped.add(name)
            return run

        batch_start, batch_stop = AsyncMock(), AsyncMock()
        with patch.object(main, "init_db", AsyncMock()), \
             patch.object(main, "validar_configuracao_producao"), \
             patch.object(settings, "DATABASE_URL", "sqlite+aiosqlite://"), \
             patch("app.services.email_queue.email_queue_worker", worker("email")), \
             patch("app.services.resgate_jobs.resgate_jobs_worker", worker("external")), \
             patch.object(main.resgate, "reserva_maintenance_worker", worker("maintenance")), \
             patch.object(main.resgate.reserva_batch_service, "start", batch_start), \
             patch.object(main.resgate.reserva_batch_service, "stop", batch_stop):
            async with main.lifespan(main.app):
                await asyncio.sleep(0)
                self.assertEqual(started, {"email", "external", "maintenance"})
                self.assertEqual(len(main.lote_event_hub._publisher_tasks), 2)
            self.assertEqual(stopped, started)
            self.assertEqual(main.lote_event_hub._publisher_tasks, [])
            batch_start.assert_awaited_once()
            batch_stop.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
