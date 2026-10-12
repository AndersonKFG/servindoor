"""Regressão do uso de conexões de banco pelo SSE; consultas somente SELECT 1.

Requer PostgreSQL configurado. Não cria tabelas nem altera dados.
SSE_PUBLIC_SOURCE permite testar o arquivo atual em um container já existente.
"""
import asyncio
import ast
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import settings
from app.core.events import LoteEventHub
from app.routers import public

if os.environ.get("SSE_PUBLIC_SOURCE"):
    # Permite exercitar a implementação atual em uma imagem local antiga, sem
    # sobrescrever os arquivos do serviço nem importar módulos novos não usados
    # pela rota. Todas as consultas do coletor são substituídas por SELECT 1.
    source = os.environ["SSE_PUBLIC_SOURCE"]
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "stream_lote_eventos")
    function.decorator_list = []
    exec(compile(ast.Module(body=[function], type_ignores=[]), source, "exec"), public.__dict__)


class TestSSEPoolLifetime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Duas conexões bastam para servir dezenas de streams se forem devolvidas
        # logo após o snapshot. O limite baixo torna a regressão reproduzível.
        self.engine = create_async_engine(settings.DATABASE_URL, pool_size=2,
                                          max_overflow=0, pool_timeout=0.5)
        self.factory = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.sessions = []
        self.responses = []
        self.hub = LoteEventHub()
        self.request = Request({"type": "http", "method": "GET", "path": "/api/lote/stream",
                                "headers": [], "query_string": b""})
        self.hub_patch = patch.object(public, "lote_event_hub", self.hub)
        self.hub_patch.start()

    async def asyncTearDown(self):
        for response in self.responses:
            await response.body_iterator.aclose()
        for session in self.sessions:
            await session.close()
        self.hub_patch.stop()
        await self.engine.dispose()

    async def collector(self, session, request, **kwargs):
        await session.execute(text("SELECT 1"))
        return {"has_lote": True, "id": 99, "server_time_ms": 1000,
                "minha_reserva_token": "token_teste", "minha_reserva_expira_em_ms": 301000,
                "minha_reserva_segundos": 300, "state_version": self.hub.state_version}

    async def open_stream(self):
        session = self.factory()
        self.sessions.append(session)
        response = await public.stream_lote_eventos(self.request, last_version=None,
                                                    device_fingerprint="teste", lote_id=99,
                                                    session=session)
        self.responses.append(response)
        return response

    async def test_snapshot_devolve_conexao_antes_de_enviar_o_stream(self):
        with patch.object(public, "coletar_dados_live_status", self.collector):
            response = await self.open_stream()
        self.assertEqual(self.engine.pool.checkedout(), 0)
        handshake = await anext(response.body_iterator)
        snapshot = await anext(response.body_iterator)
        self.assertIn("event: conectado", handshake)
        payload = json.loads(next(line[6:] for line in snapshot.splitlines() if line.startswith("data: ")))
        self.assertEqual(payload["minha_reserva_token"], "token_teste")
        self.assertEqual(payload["minha_reserva_expira_em_ms"], 301000)
        self.assertEqual(self.engine.pool.checkedout(), 0)
        await self.hub.broadcast("LOTE_ATUALIZADO", {"tipo": "teste"})
        event = await asyncio.wait_for(anext(response.body_iterator), 1)
        self.assertIn('"tipo": "teste"', event)
        await response.body_iterator.aclose()
        self.assertEqual(len(self.hub._listeners), 0)

    async def test_cinquenta_streams_compartilham_duas_conexoes(self):
        with patch.object(public, "coletar_dados_live_status", self.collector):
            results = await asyncio.gather(*(self.open_stream() for _ in range(50)), return_exceptions=True)
        failures = [type(result).__name__ for result in results if isinstance(result, BaseException)]
        self.assertEqual(failures, [])
        self.assertEqual(self.engine.pool.checkedout(), 0)
        for response in self.responses:
            await anext(response.body_iterator)
            await anext(response.body_iterator)
        self.assertEqual(len(self.hub._listeners), 50)

    async def test_falha_no_snapshot_libera_conexao_e_inscricao(self):
        async def broken(session, request, **kwargs):
            await session.execute(text("SELECT 1"))
            raise RuntimeError("falha de snapshot simulada")

        with patch.object(public, "coletar_dados_live_status", broken):
            with self.assertRaisesRegex(RuntimeError, "falha de snapshot simulada"):
                await self.open_stream()
        self.assertEqual(self.engine.pool.checkedout(), 0)
        self.assertEqual(len(self.hub._listeners), 0)

    async def test_cancelamento_no_snapshot_libera_conexao_e_inscricao(self):
        started = asyncio.Event()

        async def blocked(session, request, **kwargs):
            await session.execute(text("SELECT 1"))
            started.set()
            await asyncio.Event().wait()

        with patch.object(public, "coletar_dados_live_status", blocked):
            task = asyncio.create_task(self.open_stream())
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.engine.pool.checkedout(), 0)
        self.assertEqual(len(self.hub._listeners), 0)


if __name__ == "__main__":
    unittest.main()
