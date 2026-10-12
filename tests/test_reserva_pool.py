"""Regressões com PostgreSQL, pool de duas conexões e esquema descartável.

Não executa init_db, não acessa HTTP e não altera tabelas/dados da aplicação.
"""

import asyncio
import json
import time
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, select
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.db.session import engine
from app.models.all_models import Lote, RateLimitTentativa, ReservaIngresso
from app.routers import resgate
from app.routers.public import _obter_prazo_reserva_sse


class TestMedicaoReserva(unittest.IsolatedAsyncioTestCase):
    async def test_registra_tempo_sem_identificadores_e_preserva_resposta(self):
        request = Request({"type": "http", "headers": []})

        @resgate._medir_fluxo_reserva
        async def fluxo(request):
            with resgate._medir_etapa_reserva(request, "lock_lote"):
                pass
            return JSONResponse({"token_reserva": "nao_deve_aparecer_no_log"})

        with patch.object(resgate.time, "perf_counter", side_effect=[0, 0, 1.1, 1.2]), \
             patch.object(resgate.logger, "warning") as log:
            resposta = await fluxo(request)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(request.state.reserva_tempos, {"lock_lote": 1100.0})
        log.assert_called_once()
        self.assertNotIn("nao_deve_aparecer_no_log", str(log.call_args))

    async def test_assinaturas_http_preservadas(self):
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(resgate.router)
        schema = app.openapi()
        parametros = schema["paths"]["/api/lote/{lote_id}/reservar"]["post"]["parameters"]
        self.assertEqual({p["name"] for p in parametros}, {
            "lote_id", "device_fingerprint", "device_id", "cpf"
        })
        self.assertIn("requestBody", schema["paths"]["/api/resgate/desistir"]["post"])


class TestReservaPool(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = f"test_reserva_pool_{uuid.uuid4().hex}"
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.pool = create_async_engine(
            settings.DATABASE_URL, pool_size=2, max_overflow=0, pool_timeout=1,
            connect_args={"server_settings": {"search_path": self.schema}},
        )
        self.sessions = sessionmaker(self.pool, class_=AsyncSession, expire_on_commit=False)
        async with self.pool.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        async with self.sessions() as session:
            session.add(Lote(id=1, nome="Pool isolado", quantidade_total=10, ativo=True))
            await session.commit()
        self.patches = [
            patch.object(resgate, "async_session", self.sessions),
            patch.object(resgate, "_ultima_varredura_expiracao", time.monotonic() + 60),
            patch.object(resgate.secrets, "randbelow", return_value=1),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()
        await self.pool.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await engine.dispose()

    def request(self, path="/api/lote/1/reservar"):
        return Request({
            "type": "http", "method": "POST", "scheme": "http", "path": path,
            "headers": [], "query_string": b"", "server": ("localhost", 8000),
            "client": ("192.0.2.1", 12345),
        })

    async def reservar(self, fingerprint):
        async with self.sessions() as session:
            return await resgate.pagina_resgate(
                self.request(), 1, device_fingerprint=fingerprint,
                device_id=fingerprint, cpf=None, session=session,
            )

    async def test_limitador_preserva_lock_e_rollback_do_chamador(self):
        async with self.sessions() as session:
            await session.execute(select(Lote).where(Lote.id == 1).with_for_update())
            with patch.object(resgate, "async_session") as outra_sessao:
                self.assertTrue(await resgate.verificar_e_registrar_rate_limit_db("192.0.2.1", session))
                outra_sessao.assert_not_called()
            # O savepoint não pode liberar o lock do lote nem comitar a tentativa.
            async with self.pool.connect() as conn:
                with self.assertRaises(Exception) as erro:
                    await conn.execute(text("SELECT id FROM lotes WHERE id=1 FOR UPDATE NOWAIT"))
                self.assertEqual(getattr(erro.exception.orig, "sqlstate", None), "55P03")
            await session.rollback()
        async with self.sessions() as session:
            self.assertEqual((await session.execute(select(RateLimitTentativa))).scalars().all(), [])

    async def test_duas_conexoes_ocupadas_nao_travam_limitador(self):
        segundo_bloqueio = asyncio.Event()
        chegou_limitador = asyncio.Event()
        consultas_lock = 0
        registrar_original = resgate.verificar_e_registrar_rate_limit_db

        def observar(conn, cursor, statement, parameters, context, executemany):
            nonlocal consultas_lock
            if "FOR UPDATE" in statement:
                consultas_lock += 1
                if consultas_lock == 2:
                    segundo_bloqueio.set()

        async def registrar(ip, session=None):
            chegou_limitador.set()
            await asyncio.wait_for(segundo_bloqueio.wait(), timeout=2)
            return await registrar_original(ip, session)

        async def publicar(tipo, dados):
            # Reproduz NOTIFY solicitando uma conexão separada. A rota deve
            # ter devolvido sua conexão de leitura antes de publicar.
            async with self.pool.connect() as conn:
                await conn.execute(text("SELECT 1"))

        event.listen(self.pool.sync_engine, "before_cursor_execute", observar)
        try:
            with patch.object(resgate, "verificar_e_registrar_rate_limit_db", registrar), \
                 patch.object(resgate.lote_event_hub, "broadcast", publicar):
                primeira = asyncio.create_task(self.reservar("pool_primeira"))
                await asyncio.wait_for(chegou_limitador.wait(), timeout=2)
                respostas = await asyncio.wait_for(asyncio.gather(
                    primeira, self.reservar("pool_segunda"),
                ), timeout=5)
            self.assertEqual([r.status_code for r in respostas], [200, 200])
            async with self.sessions() as session:
                tentativas = (await session.execute(select(RateLimitTentativa))).scalars().all()
                self.assertEqual(len(tentativas), 2)
        finally:
            event.remove(self.pool.sync_engine, "before_cursor_execute", observar)

    async def test_f5_recupera_reserva_mesmo_com_lote_bloqueado(self):
        async def publicar(tipo, dados):
            pass

        with patch.object(resgate.lote_event_hub, "broadcast", publicar):
            resposta = await self.reservar("pool_f5_sem_lock")
        token = json.loads(resposta.body)["token_reserva"]
        async with self.sessions() as session:
            original = (await session.execute(select(ReservaIngresso).where(
                ReservaIngresso.token == token
            ))).scalars().one()
            prazo_original = original.expira_em

        async with self.pool.connect() as bloqueador:
            await bloqueador.execute(text("SELECT id FROM lotes WHERE id=1 FOR UPDATE"))
            # A outra conexão precisa recuperar a reserva sem esperar este lock.
            # Confere tanto a busca por fingerprint quanto o fallback por device_id.
            for fingerprint in ("pool_f5_sem_lock", "fingerprint_diferente"):
                request = self.request()
                async with self.sessions() as session:
                    atualizada = await asyncio.wait_for(resgate.pagina_resgate(
                        request, 1, device_fingerprint=fingerprint,
                        device_id="pool_f5_sem_lock", cpf=None, session=session,
                    ), timeout=1)
                self.assertEqual(atualizada.status_code, 200)
                self.assertEqual(json.loads(atualizada.body)["token_reserva"], token)
                self.assertIn("consulta_lote", request.state.reserva_tempos)
                self.assertNotIn("lock_lote", request.state.reserva_tempos)
            await bloqueador.rollback()

        async with self.sessions() as session:
            reservas = (await session.execute(select(ReservaIngresso))).scalars().all()
            self.assertEqual(len(reservas), 1)
            self.assertEqual(reservas[0].expira_em, prazo_original)

    async def test_criacao_simultanea_mesmo_dispositivo_ocupa_uma_vaga(self):
        buscas_iniciais = 0
        ambas_buscaram = asyncio.Event()
        buscar_original = resgate._buscar_reserva_ativa_dispositivo

        async def buscar(session, request, fingerprint, device_id, sufixo=""):
            nonlocal buscas_iniciais
            reserva = await buscar_original(session, request, fingerprint, device_id, sufixo)
            if not sufixo:
                # Força ambas a encontrar nenhuma reserva antes de disputar o lock.
                self.assertIsNone(reserva)
                buscas_iniciais += 1
                if buscas_iniciais == 2:
                    ambas_buscaram.set()
                await asyncio.wait_for(ambas_buscaram.wait(), timeout=2)
            return reserva

        async def publicar(tipo, dados):
            async with self.pool.connect() as conn:
                await conn.execute(text("SELECT 1"))

        with patch.object(resgate, "_buscar_reserva_ativa_dispositivo", buscar), \
             patch.object(resgate.lote_event_hub, "broadcast", publicar):
            respostas = await asyncio.wait_for(asyncio.gather(
                self.reservar("pool_mesmo_dispositivo"),
                self.reservar("pool_mesmo_dispositivo"),
            ), timeout=5)
        self.assertEqual([r.status_code for r in respostas], [200, 200])
        tokens = {json.loads(r.body)["token_reserva"] for r in respostas}
        self.assertEqual(len(tokens), 1)
        async with self.sessions() as session:
            reservas = (await session.execute(select(ReservaIngresso))).scalars().all()
            tentativas = (await session.execute(select(RateLimitTentativa))).scalars().all()
            self.assertEqual(len(reservas), 1)
            self.assertEqual(len(tentativas), 1)

    async def test_concorrencia_capacidade_f5_sse_e_desistencia(self):
        async def publicar(tipo, dados):
            async with self.pool.connect() as conn:
                await conn.execute(text("SELECT 1"))

        with patch.object(resgate.lote_event_hub, "broadcast", publicar):
            respostas = await asyncio.wait_for(asyncio.gather(*(
                self.reservar(f"pool_{i}") for i in range(40)
            )), timeout=10)
            aceitas = [i for i, r in enumerate(respostas) if r.status_code == 200]
            self.assertEqual(len(aceitas), 10)
            for resposta in respostas:
                if resposta.status_code != 200:
                    self.assertEqual(resposta.status_code, 400)
                    self.assertEqual(json.loads(resposta.body)["codigo"], "em_preenchimento")
            for i in aceitas:
                token = json.loads(respostas[i].body)["token_reserva"]
                async with self.sessions() as session:
                    original = (await session.execute(select(ReservaIngresso).where(
                        ReservaIngresso.token == token
                    ))).scalars().one()
                    prazo_original = original.expira_em
                atualizada = await self.reservar(f"pool_{i}")
                self.assertEqual(json.loads(atualizada.body)["token_reserva"], token)
                async with self.sessions() as session:
                    prazo = await _obter_prazo_reserva_sse(
                        session, self.request(), 1, f"pool_{i}", datetime.now(timezone.utc)
                    )
                    self.assertEqual(prazo["minha_reserva_expira_em_ms"], int(prazo_original.timestamp() * 1000))
                    self.assertGreater(prazo["minha_reserva_segundos"], 0)
                async with self.sessions() as session:
                    resposta = await resgate.desistir_reserva(self.request("/api/resgate/desistir"), token, session)
                    self.assertTrue(json.loads(resposta.body)["sucesso"])
            async with self.sessions() as session:
                ativas = (await session.execute(select(ReservaIngresso).where(
                    ReservaIngresso.status == "ativa"
                ))).scalars().all()
                self.assertEqual(ativas, [])
