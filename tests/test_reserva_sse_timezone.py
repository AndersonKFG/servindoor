"""Regressão do prazo SSE com PostgreSQL e esquema isolado, sem dados reais."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.security import TZ_SAO_PAULO
from app.db.session import engine, migrar_fuso_reservas
from app.models.all_models import ReservaIngresso
from app.routers.public import _obter_prazo_reserva_sse
from app.routers.resgate import desistir_reserva, status_reserva


class TestReservaSSETimezone(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await engine.connect()
        self.transaction = await self.conn.begin()
        # O identificador é gerado aqui, sem entrada externa. O rollback remove
        # o esquema inteiro e nenhum registro da aplicação é alterado.
        self.schema = f"test_reserva_sse_{uuid.uuid4().hex}"
        await self.conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        await self.conn.execute(text(f'SET LOCAL search_path TO "{self.schema}", public'))
        await self.conn.execute(text("""
            CREATE TABLE reservas_ingressos (
                id INTEGER PRIMARY KEY,
                token VARCHAR NOT NULL,
                lote_id INTEGER NOT NULL,
                criada_em TIMESTAMP NOT NULL,
                expira_em TIMESTAMP NOT NULL,
                utilizada BOOLEAN NOT NULL DEFAULT FALSE,
                ip_origem VARCHAR,
                device_id VARCHAR,
                cpf VARCHAR,
                status VARCHAR NOT NULL DEFAULT 'ativa',
                browser_token_hash VARCHAR,
                device_fingerprint VARCHAR
            )
        """))
        self.agora = datetime.now(timezone.utc)
        self.request = Request({
            "type": "http", "headers": [], "scheme": "http",
            "server": ("localhost", 8000), "path": "/api/resgate/desistir",
            "query_string": b"",
        })

    async def asyncTearDown(self):
        await self.transaction.rollback()
        await self.conn.close()
        await engine.dispose()

    async def inserir_legada(self):
        criada = (self.agora - timedelta(seconds=45)).astimezone(TZ_SAO_PAULO)
        expira = criada + timedelta(minutes=5)
        await self.conn.execute(text("""
            INSERT INTO reservas_ingressos
                (id, token, lote_id, criada_em, expira_em, device_fingerprint)
            VALUES (1, 'reserva-legada', 10000, :criada, :expira, 'hw_regressao')
        """), {"criada": criada.replace(tzinfo=None), "expira": expira.replace(tzinfo=None)})
        return expira.astimezone(timezone.utc)

    async def test_migracao_preserva_instante_e_nao_converte_duas_vezes(self):
        expira_esperada = await self.inserir_legada()
        await migrar_fuso_reservas(self.conn)
        await migrar_fuso_reservas(self.conn)
        tipos = (await self.conn.execute(text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'reservas_ingressos'
              AND column_name IN ('criada_em', 'expira_em')
        """))).scalars().all()
        self.assertEqual(tipos, ["timestamp with time zone"] * 2)
        async with AsyncSession(bind=self.conn) as session:
            reserva = await session.get(ReservaIngresso, 1)
            self.assertEqual(reserva.expira_em, expira_esperada)
            self.assertEqual(reserva.expira_em - reserva.criada_em, timedelta(minutes=5))

    async def test_sse_retoma_prazo_restante_sem_reiniciar(self):
        expira_esperada = await self.inserir_legada()
        await migrar_fuso_reservas(self.conn)
        async with AsyncSession(bind=self.conn) as session:
            primeiro = await _obter_prazo_reserva_sse(
                session, self.request, 10000, 'hw_regressao', self.agora,
            )
        # Outra sessão simula a leitura feita por uma nova conexão após F5.
        async with AsyncSession(bind=self.conn) as session:
            retomado = await _obter_prazo_reserva_sse(
                session, self.request, 10000, 'hw_regressao',
                self.agora + timedelta(seconds=20),
            )
        self.assertEqual(primeiro["minha_reserva_segundos"], 255)
        self.assertEqual(retomado["minha_reserva_segundos"], 235)
        self.assertEqual(retomado["minha_reserva_milissegundos"], 235000)
        self.assertEqual(primeiro["minha_reserva_expira_em_ms"], int(expira_esperada.timestamp() * 1000))
        self.assertEqual(primeiro["minha_reserva_expira_em_ms"], retomado["minha_reserva_expira_em_ms"])

    async def test_nova_reserva_preserva_utc_e_desistencia_remove_prazo(self):
        await migrar_fuso_reservas(self.conn)
        expira = self.agora + timedelta(minutes=5)
        async with AsyncSession(bind=self.conn, expire_on_commit=False) as session:
            reserva = ReservaIngresso(
                id=1, token='reserva-nova', lote_id=10000,
                criada_em=self.agora, expira_em=expira,
                device_fingerprint='hw_regressao', status='ativa', utilizada=False,
            )
            session.add(reserva)
            await session.flush()
            await session.refresh(reserva)
            self.assertEqual(reserva.criada_em, self.agora)
            self.assertEqual(reserva.expira_em, expira)
            prazo = await _obter_prazo_reserva_sse(
                session, self.request, 10000, 'hw_regressao', self.agora,
            )
            self.assertEqual(prazo["minha_reserva_segundos"], 300)
            vencida = await _obter_prazo_reserva_sse(
                session, self.request, 10000, 'hw_regressao', expira,
            )
            self.assertIsNone(vencida["minha_reserva_segundos"])
            reserva.status = 'cancelada'
            await session.flush()
            cancelada = await _obter_prazo_reserva_sse(
                session, self.request, 10000, 'hw_regressao', self.agora,
            )
            self.assertIsNone(cancelada["minha_reserva_segundos"])
            self.assertIsNone(cancelada["minha_reserva_expira_em_ms"])

    async def test_rota_desistir_persiste_cancelamento_e_publica_liberacao(self):
        await self.inserir_legada()
        await migrar_fuso_reservas(self.conn)
        async with AsyncSession(bind=self.conn, expire_on_commit=False) as session:
            ativa = await status_reserva(self.request, 'reserva-legada', session)
            self.assertEqual(ativa.status_code, 200)
            self.assertIn(b'"ativa":true', ativa.body)
            with patch('app.routers.resgate.lote_event_hub.broadcast', new_callable=AsyncMock) as broadcast:
                resposta = await desistir_reserva(self.request, 'reserva-legada', session)
            self.assertEqual(resposta.status_code, 200, resposta.body)
            self.assertIn(b'"sucesso":true', resposta.body)
            reserva = await session.get(ReservaIngresso, 1)
            await session.refresh(reserva)
            self.assertEqual(reserva.status, 'cancelada')
            self.assertIsNotNone(reserva.expira_em.tzinfo)
            self.assertLess(reserva.expira_em, self.agora)
            broadcast.assert_awaited_once()
            self.assertEqual(broadcast.call_args.args[1]['tipo'], 'reserva_liberada')
            self.assertEqual(broadcast.call_args.args[1]['motivo'], 'desistencia')
            prazo = await _obter_prazo_reserva_sse(
                session, self.request, 10000, 'hw_regressao', self.agora,
            )
            self.assertIsNone(prazo['minha_reserva_expira_em_ms'])
            cancelada = await status_reserva(self.request, 'reserva-legada', session)
            self.assertEqual(cancelada.status_code, 200)
            self.assertIn(b'"status":"desistida"', cancelada.body)
            # Repetir a desistência mantém o resultado e não gera outra liberação.
            with patch('app.routers.resgate.lote_event_hub.broadcast', new_callable=AsyncMock) as repetido:
                resposta = await desistir_reserva(self.request, 'reserva-legada', session)
            self.assertEqual(resposta.status_code, 200)
            repetido.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
