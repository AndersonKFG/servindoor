"""Batches com SQL real e tabelas/índices em esquema PostgreSQL descartável."""

import asyncio
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings
from app.db.session import engine
from app.models.all_models import Lote
from app.services.reserva_batch import ReservaBatchService


BATCH_INDEXES = (
    "CREATE INDEX idx_batch_browser ON reservas_ingressos (browser_token_hash, expira_em DESC) WHERE status = 'ativa'",
    "CREATE INDEX idx_batch_rate ON rate_limit_tentativas (ip, acao, criado_em)",
    "CREATE INDEX idx_batch_cap ON reservas_ingressos (lote_id, expira_em) WHERE status = 'ativa'",
    "CREATE INDEX idx_batch_fp ON reservas_ingressos (device_fingerprint, expira_em DESC) WHERE status = 'ativa'",
    "CREATE INDEX idx_batch_device ON reservas_ingressos (device_id, expira_em DESC) WHERE status = 'ativa'",
)


class TestReservaBatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = "test_batch_" + uuid.uuid4().hex
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.pool = create_async_engine(settings.DATABASE_URL, pool_size=4, max_overflow=0,
            pool_timeout=2, connect_args={"server_settings": {"search_path": self.schema}})
        self.sessions = sessionmaker(self.pool, class_=AsyncSession, expire_on_commit=False)
        async with self.pool.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            for index in BATCH_INDEXES:
                await conn.execute(text(index))
        async with self.sessions() as session:
            session.add(Lote(id=1, nome="Batch isolado", quantidade_total=100, ativo=True))
            session.add(Lote(id=2, nome="Outro lote isolado", quantidade_total=100, ativo=True))
            await session.commit()
        self.services = []
        self.service = self.new_service()

    async def asyncTearDown(self):
        for service in self.services:
            await service.stop()
        await self.pool.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await engine.dispose()

    def new_service(self, **kwargs):
        service = ReservaBatchService(self.sessions, **kwargs)
        self.services.append(service)
        return service

    async def reserve(self, number, *, service=None, lote_id=1, cpf=None, fp=None, browser=None, rate=None, token=None):
        return await (service or self.service).reserve(lote_id=lote_id,
            fp=fp or f"batch_fp_{number}", device_id=f"batch_device_{number}",
            browser_hash=browser or f"batch_browser_{number}", cpf=cpf,
            ip="192.0.2.33", rate_key=rate or f"batch_rate_{number}", token=token)

    async def scalar(self, sql):
        async with self.sessions() as session:
            return await session.scalar(text(sql))

    async def execute(self, sql):
        async with self.sessions() as session:
            await session.execute(text(sql))
            await session.commit()

    async def test_capacidade_entre_quatro_actors_e_commit_em_grupos(self):
        services = [self.service] + [self.new_service() for _ in range(3)]
        results = await asyncio.wait_for(asyncio.gather(*(
            self.reserve(i, service=services[i % 4]) for i in range(140)
        )), 10)
        self.assertEqual(sum(item.status_code == 200 for item in results), 100)
        self.assertEqual(sum(item.codigo == "em_preenchimento" for item in results), 40)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos WHERE status='ativa'"), 100)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM rate_limit_tentativas"), 140)
        self.assertEqual(len({item.reserva.token for item in results if item.reserva}), 100)
        self.assertTrue(all(item.lote.nome == "Batch isolado" for item in results))

    async def test_f5_e_repetidos_no_batch_preservam_token_e_prazo(self):
        first = await self.reserve(1)
        results = await asyncio.gather(*(self.reserve(1, token=first.reserva.token) for _ in range(30)))
        self.assertEqual(sum(item.created for item in results), 0)
        self.assertEqual(len({item.reserva.token for item in results}), 1)
        expiry = results[0].reserva.expira_em
        again = await self.reserve(1, token=first.reserva.token)
        self.assertEqual(again.reserva.token, results[0].reserva.token)
        self.assertEqual(again.reserva.expira_em, expiry)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM rate_limit_tentativas"), 1)

    async def test_cpf_duplicado_no_batch_permite_duas_reservas(self):
        results = await asyncio.gather(self.reserve(1, cpf="52998224725"), self.reserve(2, cpf="52998224725"))
        self.assertEqual([item.status_code for item in results], [200, 200])
        self.assertNotEqual(results[0].reserva.token, results[1].reserva.token)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos"), 2)

    async def test_mesmo_browser_recupera_reserva_e_outro_browser_nao(self):
        first = await self.reserve(1)
        same_browser = await self.reserve(2, browser="batch_browser_1", token=first.reserva.token)
        self.assertEqual(same_browser.reserva.token, first.reserva.token)
        unauthorized = await self.reserve(3, token=first.reserva.token)
        self.assertEqual(unauthorized.status_code, 403)
        other_browser = await self.reserve(3, fp="batch_fp_1")
        self.assertEqual(other_browser.status_code, 200)
        self.assertIsNotNone(other_browser.reserva)

    async def test_dispositivo_permite_reservas_em_outro_lote(self):
        first = await self.reserve(1)
        result = await self.reserve(1, lote_id=2, service=self.new_service())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos"), 2)
        self.assertEqual(first.reserva.lote_id, 1)

    async def test_mesmo_dispositivo_em_lotes_concorrentes_cria_duas_reservas(self):
        first_actor, second_actor = self.service, self.new_service()
        results = await asyncio.wait_for(asyncio.gather(
            self.reserve(1, lote_id=1, service=first_actor, rate="ip_a"),
            self.reserve(1, lote_id=2, service=second_actor, rate="ip_b"),
        ), 5)
        self.assertEqual(sum(item.status_code == 200 for item in results), 2)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos"), 2)

    async def test_mesmo_cpf_browser_dispositivo_sem_limite_de_reservas(self):
        results = await asyncio.gather(*(self.reserve(1, cpf="52998224725") for _ in range(30)))
        self.assertTrue(all(item.created and item.status_code == 200 for item in results))
        self.assertEqual(len({item.reserva.token for item in results}), 30)
        self.assertTrue(all((item.reserva.expira_em - item.reserva.criada_em).total_seconds() == 300 for item in results))
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos WHERE status='ativa'"), 30)

    async def test_rate_limit_conta_batch_e_coordena_actors(self):
        await self.execute("UPDATE lotes SET quantidade_total=500 WHERE id=1")
        services = [self.service, self.new_service()]
        results = await asyncio.gather(*(self.reserve(i, service=services[i % 2], rate="same_ip") for i in range(350)))
        self.assertEqual(sum(item.status_code == 200 for item in results), 300)
        self.assertEqual(sum(item.status_code == 429 for item in results), 50)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM rate_limit_tentativas"), 300)
        again = await self.reserve(1, rate="same_ip", token=results[1].reserva.token)
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.created)

    async def test_expirada_nao_renova_antiga(self):
        first = await self.reserve(1, cpf="52998224725")
        await self.execute("UPDATE reservas_ingressos SET expira_em=NOW()-INTERVAL '1 second'")
        second = await self.reserve(1, cpf="52998224725")
        self.assertTrue(second.created)
        self.assertNotEqual(second.reserva.token, first.reserva.token)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos WHERE status='ativa'"), 1)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos WHERE status='expirada'"), 1)

    async def test_reavalia_pausa_antes_de_processar(self):
        service = self.new_service(window_seconds=0.05)
        task = asyncio.create_task(self.reserve(1, service=service))
        await asyncio.sleep(0)
        await self.execute("UPDATE lotes SET ativo=FALSE WHERE id=1")
        result = await task
        self.assertEqual(result.codigo, "lote_inativo")
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos"), 0)

    async def test_fila_limitada_cancelamento_pendente_e_stop(self):
        service = self.new_service(max_queue=1, window_seconds=0.05)
        first = asyncio.create_task(self.reserve(1, service=service))
        await asyncio.sleep(0)
        second = await self.reserve(2, service=service)
        self.assertEqual(second.status_code, 503)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        await service.stop()
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos"), 0)
        self.assertEqual((await self.reserve(3, service=service)).status_code, 503)

    async def test_cancelamento_durante_commit_permite_nova_reserva(self):
        committing = asyncio.Event()
        release = asyncio.Event()

        class SlowCommit(AsyncSession):
            async def commit(self):
                committing.set()
                await release.wait()
                await super().commit()

        sessions = sessionmaker(self.pool, class_=SlowCommit, expire_on_commit=False)
        service = self.new_service()
        service.session_factory = sessions
        task = asyncio.create_task(self.reserve(1, service=service))
        await asyncio.wait_for(committing.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        release.set()
        recovered = await self.reserve(1, service=service)
        self.assertEqual(recovered.status_code, 200)
        self.assertTrue(recovered.created)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos"), 2)

    async def test_falha_sql_reverte_batch_inteiro_sem_respostas_sucesso(self):
        service = self.new_service()
        original = service._transaction

        async def failing(session, requests):
            await original(session, requests)
            raise RuntimeError("falha de banco controlada")

        with patch.object(service, "_transaction", failing):
            results = await asyncio.gather(*(self.reserve(i, service=service) for i in range(30)))
        self.assertTrue(all(item.status_code == 503 for item in results))
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM rate_limit_tentativas"), 0)

    async def test_commit_sem_resposta_permite_nova_reserva_com_expiracao_da_anterior(self):
        class UnknownCommit(AsyncSession):
            async def commit(self):
                await super().commit()
                raise ConnectionError("resposta do commit perdida")

        service = self.new_service()
        service.session_factory = sessionmaker(self.pool, class_=UnknownCommit, expire_on_commit=False)
        result = await self.reserve(1, service=service)
        self.assertEqual(result.status_code, 503)
        service.session_factory = self.sessions
        recovered = await self.reserve(1, service=service)
        self.assertEqual(recovered.status_code, 200)
        self.assertTrue(recovered.created)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM reservas_ingressos"), 2)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM rate_limit_tentativas"), 2)

    async def test_factory_expire_on_commit_entrega_dto_desanexado(self):
        service = self.new_service()
        service.session_factory = sessionmaker(self.pool, class_=AsyncSession, expire_on_commit=True)
        result = await self.reserve(1, service=service)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.reserva.token)
        self.assertEqual(result.lote.nome, "Batch isolado")
        self.assertEqual(result.reserva.status, "ativa")
