"""Fila durável em esquema PostgreSQL descartável; nunca altera dados do app."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import engine
from app.services import resgate_jobs as jobs
from app.services.email_service import send_validation_pending_email_async


class TestResgateJobs(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = f"test_resgate_jobs_{uuid.uuid4().hex}"
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.pool = create_async_engine(
            settings.DATABASE_URL, pool_size=2, max_overflow=0, pool_timeout=0.5,
            connect_args={"server_settings": {"search_path": self.schema}},
        )
        self.sessions = sessionmaker(self.pool, class_=AsyncSession, expire_on_commit=False)
        async with self.pool.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE usuarios (
                    id INTEGER PRIMARY KEY, cpf VARCHAR NOT NULL,
                    ativo BOOLEAN NOT NULL DEFAULT TRUE,
                    validado BOOLEAN NOT NULL DEFAULT FALSE, deleted_at TIMESTAMPTZ
                )
            """))
            await conn.execute(text("""
                CREATE TABLE solicitacoes_validacao (
                    id INTEGER PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                    status VARCHAR NOT NULL DEFAULT 'pendente_analise',
                    identificado_api BOOLEAN NOT NULL DEFAULT FALSE
                )
            """))
            await conn.execute(text(jobs.RESGATE_JOBS_DDL))
            await conn.execute(text(jobs.RESGATE_JOBS_INDEX_DDL))
            await conn.execute(text("INSERT INTO usuarios (id, cpf) VALUES (1, '12345678901')"))
            await conn.execute(text("INSERT INTO solicitacoes_validacao (id, usuario_id) VALUES (1, 1)"))

    async def asyncTearDown(self):
        await self.pool.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await engine.dispose()

    async def enqueue(self, request_id=1):
        async with self.sessions() as session:
            await jobs.enqueue_external_validation(session, request_id)
            await session.commit()

    async def execute(self, statement, parameters=None):
        async with self.sessions() as session:
            await session.execute(text(statement), parameters or {})
            await session.commit()

    async def scalar(self, statement):
        async with self.sessions() as session:
            return await session.scalar(text(statement))

    async def process(self, validator):
        return await jobs.process_next_external_validation(
            session_factory=self.sessions, validator=validator,
        )

    async def test_enqueue_participa_da_transacao_e_deduplica(self):
        async with self.sessions() as session:
            await jobs.enqueue_external_validation(session, 1)
            await session.rollback()
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM resgate_jobs"), 0)
        await self.enqueue()
        await self.enqueue()
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM resgate_jobs"), 1)
        async with self.sessions() as session:
            self.assertEqual(await jobs.get_external_validation_status(session, 1), "queued")
            self.assertIsNone(await jobs.get_external_validation_status(session, 99))

    async def test_api_sem_conexao_e_positivo_sem_autoaprovar(self):
        await self.enqueue()

        async def validator(cpf):
            self.assertEqual(cpf, "12345678901")
            self.assertEqual(self.pool.pool.checkedout(), 0)
            return {"is_servidor": True, "modo": "api_oficial"}

        self.assertTrue(await self.process(validator))
        self.assertEqual(await self.scalar("SELECT status FROM resgate_jobs"), "done")
        self.assertTrue(await self.scalar("SELECT validado FROM usuarios WHERE id = 1"))
        self.assertTrue(await self.scalar("SELECT identificado_api FROM solicitacoes_validacao WHERE id = 1"))
        self.assertEqual(await self.scalar("SELECT status FROM solicitacoes_validacao WHERE id = 1"), "pendente_analise")
        self.assertFalse(await self.process(validator))

    async def test_negativo_nao_revoga_validacao_manual(self):
        await self.enqueue()
        await self.execute("UPDATE usuarios SET validado = TRUE WHERE id = 1")
        await self.process(AsyncMock(return_value={"is_servidor": False, "modo": "api_oficial"}))
        self.assertTrue(await self.scalar("SELECT validado FROM usuarios WHERE id = 1"))
        self.assertFalse(await self.scalar("SELECT identificado_api FROM solicitacoes_validacao WHERE id = 1"))

    async def test_fallback_repete_ate_limite_sem_perder_pendencia(self):
        await self.enqueue()
        validator = AsyncMock(return_value={"is_servidor": False, "modo": "fallback"})
        for attempt in range(1, jobs.MAX_ATTEMPTS + 1):
            self.assertTrue(await self.process(validator))
            self.assertEqual(await self.scalar("SELECT attempts FROM resgate_jobs"), attempt)
            expected = "failed" if attempt == jobs.MAX_ATTEMPTS else "queued"
            self.assertEqual(await self.scalar("SELECT status FROM resgate_jobs"), expected)
            await self.execute("UPDATE resgate_jobs SET next_attempt_at = NOW()")
        self.assertFalse(await self.process(validator))
        self.assertEqual(await self.scalar("SELECT status FROM solicitacoes_validacao"), "pendente_analise")
        self.assertEqual(await self.scalar("SELECT last_error FROM resgate_jobs"), "ConnectionError")

    async def test_rejeicao_durante_api_impede_aplicacao(self):
        await self.enqueue()

        async def validator(cpf):
            await self.execute("UPDATE solicitacoes_validacao SET status = 'rejeitado' WHERE id = 1")
            return {"is_servidor": True}

        await self.process(validator)
        self.assertEqual(await self.scalar("SELECT status FROM resgate_jobs"), "skipped")
        self.assertFalse(await self.scalar("SELECT validado FROM usuarios WHERE id = 1"))
        self.assertFalse(await self.scalar("SELECT identificado_api FROM solicitacoes_validacao WHERE id = 1"))

    async def test_edicao_cpf_durante_api_impede_aplicacao(self):
        await self.enqueue()

        async def validator(cpf):
            await self.execute("UPDATE usuarios SET cpf = '98765432100' WHERE id = 1")
            return {"is_servidor": True}

        await self.process(validator)
        self.assertEqual(await self.scalar("SELECT status FROM resgate_jobs"), "skipped")
        self.assertFalse(await self.scalar("SELECT validado FROM usuarios WHERE id = 1"))

    async def test_solicitacao_nova_impede_validacao_da_antiga(self):
        await self.enqueue()
        await self.execute("INSERT INTO solicitacoes_validacao (id, usuario_id) VALUES (2, 1)")
        validator = AsyncMock(return_value={"is_servidor": True})
        await self.process(validator)
        validator.assert_not_awaited()
        self.assertEqual(await self.scalar("SELECT status FROM resgate_jobs"), "skipped")

    async def test_claim_lease_recuperavel_e_resultado_antigo_ignorado(self):
        await self.enqueue()
        old = await jobs._claim_job(self.sessions)
        self.assertIsNone(await jobs._claim_job(self.sessions))
        snapshot = await jobs._validation_snapshot(self.sessions, 1)
        await self.execute("UPDATE resgate_jobs SET lease_expires_at = NOW() - INTERVAL '1 second'")
        current = await jobs._claim_job(self.sessions)
        self.assertEqual(current["attempts"], 2)
        self.assertNotEqual(old["lease_token"], current["lease_token"])
        self.assertFalse(await jobs._finish_job(self.sessions, old, snapshot, True))
        self.assertFalse(await self.scalar("SELECT validado FROM usuarios WHERE id = 1"))
        self.assertTrue(await jobs._finish_job(self.sessions, current, snapshot, True))

    async def test_claims_concorrentes_nao_duplicam_tarefa(self):
        async with self.sessions() as session:
            for request_id in range(2, 11):
                await session.execute(text("INSERT INTO solicitacoes_validacao (id, usuario_id) VALUES (:id, 1)"), {"id": request_id})
                await jobs.enqueue_external_validation(session, request_id)
            await session.commit()
        claims = await asyncio.gather(*(jobs._claim_job(self.sessions) for _ in range(15)))
        ids = [job["id"] for job in claims if job]
        self.assertEqual(len(ids), 9)
        self.assertEqual(len(set(ids)), 9)

    async def test_cancelamento_de_worker_deixa_lease_para_retomada(self):
        await self.enqueue()
        started = asyncio.Event()

        async def validator(cpf):
            started.set()
            await asyncio.Future()

        task = asyncio.create_task(self.process(validator))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.pool.pool.checkedout(), 0)
        self.assertEqual(await self.scalar("SELECT status FROM resgate_jobs"), "processing")
        await self.execute("UPDATE resgate_jobs SET lease_expires_at = NOW() - INTERVAL '1 second'")
        self.assertTrue(await self.process(AsyncMock(return_value={"is_servidor": True})))
        self.assertEqual(await self.scalar("SELECT status FROM resgate_jobs"), "done")

    async def test_crash_na_ultima_tentativa_encerra_job(self):
        await self.enqueue()
        await self.execute("""
            UPDATE resgate_jobs SET status = 'processing', attempts = 5,
                lease_expires_at = NOW() - INTERVAL '1 second', lease_token = 'antigo'
        """)
        self.assertIsNone(await jobs._claim_job(self.sessions))
        self.assertEqual(await self.scalar("SELECT status FROM resgate_jobs"), "failed")

    async def test_worker_ocioso_para_com_evento(self):
        stop = asyncio.Event()
        task = asyncio.create_task(jobs.resgate_jobs_worker(stop, session_factory=self.sessions))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, 1)


class TestEmailTransacional(unittest.IsolatedAsyncioTestCase):
    async def test_email_pendente_encaminha_sessao_do_cadastro(self):
        session = object()
        with patch("app.services.email_service.enqueue_email", new_callable=AsyncMock, return_value=True) as enqueue:
            self.assertTrue(await send_validation_pending_email_async(
                "Teste", "teste@example.invalid", "Lote", session=session,
            ))
        self.assertIs(enqueue.await_args.kwargs["session"], session)

    async def test_email_pendente_preserva_compatibilidade_sem_sessao(self):
        with patch("app.services.email_service.enqueue_email", new_callable=AsyncMock, return_value=False) as enqueue:
            self.assertFalse(await send_validation_pending_email_async(
                "Teste", "teste@example.invalid", "Lote",
            ))
        self.assertIsNone(enqueue.await_args.kwargs["session"])
