"""Confirmação concorrente em esquema PostgreSQL/fotos descartáveis.

Não chama init_db, SMTP nem API externa e não altera os dados da aplicação.
"""

import asyncio
import base64
import json
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from starlette.requests import Request

from app.core.config import settings
from app.db.session import engine
from app.models.all_models import Lote, Secretaria
from app.routers import resgate
from app.services.resgate_jobs import RESGATE_JOBS_DDL, RESGATE_JOBS_INDEX_DDL
from app.services.reserva_batch import ReservaBatchService


CPF_A = "52998224725"
CPF_B = "11144477735"
PHOTO = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xfffixture\xff\xd9").decode()


class TestResgateConfirmation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = f"test_confirmation_{uuid.uuid4().hex}"
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.pool = create_async_engine(
            settings.DATABASE_URL, pool_size=4, max_overflow=0, pool_timeout=2,
            connect_args={"server_settings": {"search_path": self.schema}},
        )
        self.sessions = sessionmaker(self.pool, class_=AsyncSession, expire_on_commit=False)
        self.photos = tempfile.TemporaryDirectory(prefix="confirmation_photos_")
        async with self.pool.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            await conn.execute(text("""
                CREATE UNIQUE INDEX uq_confirmation_usuario_ativo
                ON solicitacoes_validacao (usuario_id)
                WHERE status IN ('pendente_analise', 'aprovado')
            """))
            await conn.execute(text("""
                CREATE TABLE email_queue (
                    id BIGSERIAL PRIMARY KEY, recipient VARCHAR NOT NULL,
                    subject VARCHAR NOT NULL, html_body TEXT NOT NULL,
                    sender_type VARCHAR NOT NULL DEFAULT 'ticket',
                    qr_image BYTEA, ticket_image BYTEA,
                    status VARCHAR NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    sent_at TIMESTAMPTZ, last_error TEXT
                )
            """))
            await conn.execute(text(RESGATE_JOBS_DDL))
            await conn.execute(text(RESGATE_JOBS_INDEX_DDL))
        async with self.sessions() as session:
            session.add(Secretaria(id=1, nome="Secretaria isolada", sigla="TESTE"))
            session.add(Lote(id=1, nome="Confirmação isolada", quantidade_total=50, ativo=True))
            await session.commit()
        self.provider = AsyncMock(side_effect=AssertionError("API externa executada durante confirmação"))
        self.batch_service = ReservaBatchService(self.sessions)
        await self.batch_service.start()
        self.patches = [
            patch.object(resgate, "async_session", self.sessions),
            patch.object(resgate, "reserva_batch_service", self.batch_service),
            patch.object(resgate, "FOTOS_DIR", self.photos.name),
            patch.object(resgate, "_ultima_varredura_expiracao", time.monotonic() + 600),
            patch.object(resgate.secrets, "randbelow", return_value=1),
            patch.object(resgate.lote_event_hub, "broadcast", AsyncMock()),
            patch.object(resgate, "_publicar_mudanca_reserva", return_value=None),
            patch.object(resgate.ServidorValidationService, "verificar_servidor", self.provider),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        await self.batch_service.stop()
        for item in reversed(self.patches):
            item.stop()
        self.photos.cleanup()
        await self.pool.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await engine.dispose()

    def request(self, path="/api/lote/1/resgatar", cookie=""):
        headers = [(b"cookie", cookie.encode())] if cookie else []
        return Request({
            "type": "http", "method": "POST", "scheme": "http", "path": path,
            "headers": headers, "query_string": b"", "server": ("localhost", 8000),
            "client": ("192.0.2.11", 12345),
        })

    async def reserve(self):
        fingerprint = "confirmation_" + uuid.uuid4().hex
        async with self.sessions() as session:
            response = await resgate.pagina_resgate(
                self.request("/api/lote/1/reservar"), 1, device_fingerprint=fingerprint,
                device_id=fingerprint, cpf=None, session=session,
            )
        self.assertEqual(response.status_code, 200)
        parsed = SimpleCookie()
        for key, value in response.raw_headers:
            if key.lower() == b"set-cookie":
                parsed.load(value.decode())
        cookie = "; ".join(f"{key}={morsel.value}" for key, morsel in parsed.items())
        self.assertIn(resgate.COOKIE_BROWSER_ID, parsed)
        return json.loads(response.body)["token_reserva"], cookie

    async def confirm(self, token, cookie, cpf=CPF_A, photo=PHOTO):
        async with self.sessions() as session:
            response = await resgate.processar_resgate(
                self.request(cookie=cookie), 1, token_reserva=token, cpf=cpf,
                nome="Participante de teste", data_nascimento="1990-01-01", setor="Teste",
                secretaria_id=1, vinculo="Efetivo", telefone="81999990000",
                email="teste@example.invalid", foto_base64=photo, session=session,
            )
        if response.status_code >= 400:
            raise HTTPException(response.status_code, detail=json.loads(response.body))
        return response

    async def quit(self, token, cookie):
        async with self.sessions() as session:
            return await resgate.desistir_reserva(
                self.request("/api/resgate/desistir", cookie), token_reserva=token, session=session,
            )

    async def scalar(self, sql, parameters=None):
        async with self.sessions() as session:
            return await session.scalar(text(sql), parameters or {})

    async def execute(self, sql, parameters=None):
        async with self.sessions() as session:
            await session.execute(text(sql), parameters or {})
            await session.commit()

    async def assert_one_confirmation(self):
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM solicitacoes_validacao"), 1)
        self.assertEqual(await self.scalar("SELECT quantidade_resgatada FROM lotes WHERE id = 1"), 1)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 1)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM resgate_jobs"), 1)

    async def test_confirma_grava_foto_email_job_sem_chamar_api_externa(self):
        token, cookie = await self.reserve()
        response = await self.confirm(token, cookie)
        payload = json.loads(response.body)
        self.assertTrue(payload["sucesso"])
        self.assertEqual(payload["status"], "pendente_analise")
        await self.assert_one_confirmation()
        self.assertEqual(await self.scalar("SELECT status FROM reservas_ingressos WHERE token = :token", {"token": token}), "concluida")
        self.assertFalse(await self.scalar("SELECT validado FROM usuarios"))
        self.assertFalse(await self.scalar("SELECT identificado_api FROM solicitacoes_validacao"))
        photo_url = await self.scalar("SELECT foto_rosto_url FROM usuarios")
        self.assertTrue((Path(self.photos.name) / Path(photo_url).name).is_file())
        self.assertEqual(len(list(Path(self.photos.name).iterdir())), 1)
        self.provider.assert_not_awaited()

    async def test_retry_recupera_mesma_confirmacao_apos_expiracao_sem_outra_foto(self):
        token, cookie = await self.reserve()
        original = json.loads((await self.confirm(token, cookie)).body)
        await self.execute("UPDATE reservas_ingressos SET expira_em = NOW() - INTERVAL '1 hour' WHERE token = :token", {"token": token})
        retried = json.loads((await self.confirm(token, cookie, photo="")).body)
        self.assertEqual(retried["solicitacao_id"], original["solicitacao_id"])
        self.assertEqual(retried["token"], original["token"])
        await self.assert_one_confirmation()
        self.assertEqual(len(list(Path(self.photos.name).iterdir())), 1)

    async def test_envios_concorrentes_mesmo_token_retornam_mesmo_resultado(self):
        token, cookie = await self.reserve()
        responses = await asyncio.wait_for(asyncio.gather(*(self.confirm(token, cookie) for _ in range(8))), 10)
        ids = {json.loads(response.body)["solicitacao_id"] for response in responses}
        self.assertEqual(len(ids), 1)
        await self.assert_one_confirmation()
        self.assertEqual(len(list(Path(self.photos.name).iterdir())), 1)

    async def test_mesmo_token_nao_confirma_dois_cpfs(self):
        token, cookie = await self.reserve()
        results = await asyncio.wait_for(asyncio.gather(
            self.confirm(token, cookie, CPF_A), self.confirm(token, cookie, CPF_B), return_exceptions=True,
        ), 10)
        success = [item for item in results if not isinstance(item, Exception)]
        failure = [item for item in results if isinstance(item, HTTPException)]
        self.assertEqual(len(success), 1, results)
        self.assertEqual(len(failure), 1, results)
        self.assertIn(failure[0].status_code, (400, 403, 409))
        await self.assert_one_confirmation()

    async def test_duas_reservas_mesmo_cpf_nao_duplicam_cadastro(self):
        first, first_cookie = await self.reserve()
        second, second_cookie = await self.reserve()
        results = await asyncio.wait_for(asyncio.gather(
            self.confirm(first, first_cookie), self.confirm(second, second_cookie), return_exceptions=True,
        ), 10)
        self.assertEqual(sum(not isinstance(item, Exception) for item in results), 1, results)
        self.assertEqual(sum(isinstance(item, HTTPException) for item in results), 1, results)
        await self.assert_one_confirmation()
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM usuarios"), 1)

    async def test_cookie_diferente_nao_recupera_confirmacao(self):
        token, cookie = await self.reserve()
        await self.confirm(token, cookie)
        with self.assertRaises(HTTPException) as caught:
            await self.confirm(token, "", photo="")
        self.assertEqual(caught.exception.status_code, 403)
        await self.assert_one_confirmation()

    async def test_recupera_recibo_por_get_sem_foto_ou_novo_envio(self):
        token, cookie = await self.reserve()
        original = json.loads((await self.confirm(token, cookie)).body)
        async with self.sessions() as session:
            response = await resgate.recuperar_confirmacao_resgate(
                self.request(cookie=cookie), 1, token_reserva=token, cpf=CPF_A, session=session,
            )
        self.assertEqual(json.loads(response.body)["solicitacao_id"], original["solicitacao_id"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        await self.assert_one_confirmation()
        self.assertEqual(len(list(Path(self.photos.name).iterdir())), 1)

    async def test_recuperacao_get_pendente_nao_modifica_reserva(self):
        token, cookie = await self.reserve()
        async with self.sessions() as session:
            response = await resgate.recuperar_confirmacao_resgate(
                self.request(cookie=cookie), 1, token_reserva=token, cpf=CPF_A, session=session,
            )
        self.assertEqual(json.loads(response.body), {"sucesso": False, "status": "nao_confirmado"})
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM solicitacoes_validacao"), 0)
        self.assertEqual(await self.scalar("SELECT status FROM reservas_ingressos WHERE token=:token", {"token": token}), "ativa")

    async def test_recuperacao_get_exige_cookie_assinado_do_dono(self):
        token, cookie = await self.reserve()
        await self.confirm(token, cookie)
        for wrong_cookie in ("", resgate.COOKIE_BROWSER_ID + "=forjado.assinatura"):
            async with self.sessions() as session:
                with self.assertRaises(HTTPException) as caught:
                    await resgate.recuperar_confirmacao_resgate(
                        self.request(cookie=wrong_cookie), 1, token_reserva=token, cpf=CPF_A, session=session,
                    )
                self.assertEqual(caught.exception.status_code, 403)

    async def test_falha_ao_enfileirar_email_reverte_confirmacao_e_foto(self):
        token, cookie = await self.reserve()
        with patch.object(resgate, "send_validation_pending_email_async", AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as caught:
                await self.confirm(token, cookie)
        self.assertGreaterEqual(caught.exception.status_code, 500)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM solicitacoes_validacao"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM usuarios"), 0)
        self.assertEqual(await self.scalar("SELECT quantidade_resgatada FROM lotes WHERE id = 1"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM resgate_jobs"), 0)
        self.assertEqual(await self.scalar("SELECT status FROM reservas_ingressos WHERE token = :token", {"token": token}), "ativa")
        self.assertEqual(list(Path(self.photos.name).iterdir()), [])
        self.assertEqual((await self.confirm(token, cookie)).status_code, 200)

    async def test_falha_job_reverte_tambem_email_da_mesma_transacao(self):
        token, cookie = await self.reserve()
        with patch.object(resgate, "enqueue_external_validation", AsyncMock(side_effect=RuntimeError("falha de fila controlada"))):
            with self.assertRaises(Exception):
                await self.confirm(token, cookie)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM solicitacoes_validacao"), 0)
        self.assertEqual(await self.scalar("SELECT quantidade_resgatada FROM lotes WHERE id = 1"), 0)
        self.assertEqual(list(Path(self.photos.name).iterdir()), [])

    async def test_expiracao_aguardando_lock_impede_confirmacao(self):
        token, cookie = await self.reserve()
        await self.execute("UPDATE reservas_ingressos SET expira_em = NOW() + INTERVAL '0.3 seconds' WHERE token = :token", {"token": token})
        waiting = asyncio.Event()

        def observe(conn, cursor, statement, parameters, context, executemany):
            if "FROM lotes" in statement and "FOR UPDATE" in statement:
                waiting.set()

        async with self.sessions() as locker:
            await locker.execute(text("SELECT id FROM lotes WHERE id = 1 FOR UPDATE"))
            event.listen(self.pool.sync_engine, "before_cursor_execute", observe)
            task = asyncio.create_task(self.confirm(token, cookie))
            try:
                await asyncio.wait_for(waiting.wait(), 2)
                await asyncio.sleep(0.35)
                await locker.commit()
                with self.assertRaises(HTTPException) as caught:
                    await asyncio.wait_for(task, 5)
                self.assertEqual(caught.exception.status_code, 400)
            finally:
                event.remove(self.pool.sync_engine, "before_cursor_execute", observe)
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM solicitacoes_validacao"), 0)
        self.assertEqual(await self.scalar("SELECT quantidade_resgatada FROM lotes WHERE id = 1"), 0)
        self.assertEqual(list(Path(self.photos.name).iterdir()), [])

    async def test_desistencia_concorrente_nao_desfaz_confirmacao_gravada(self):
        token, cookie = await self.reserve()
        results = await asyncio.wait_for(asyncio.gather(
            self.confirm(token, cookie), self.quit(token, cookie), return_exceptions=True,
        ), 10)
        confirmation, cancellation = results
        self.assertFalse(isinstance(cancellation, Exception), results)
        state = await self.scalar("SELECT status FROM reservas_ingressos WHERE token = :token", {"token": token})
        if isinstance(confirmation, HTTPException):
            self.assertEqual(state, "cancelada")
            self.assertEqual(await self.scalar("SELECT COUNT(*) FROM solicitacoes_validacao"), 0)
            self.assertEqual(await self.scalar("SELECT quantidade_resgatada FROM lotes WHERE id = 1"), 0)
        else:
            self.assertFalse(isinstance(confirmation, Exception), results)
            self.assertEqual(state, "concluida")
            await self.assert_one_confirmation()

    async def test_foto_preparada_sem_conexao_ou_lock_no_lote(self):
        token, cookie = await self.reserve()
        preparing = asyncio.Event()
        release = asyncio.Event()
        original = resgate._preparar_foto_resgate

        async def photo(photo_base64):
            self.assertEqual(self.pool.pool.checkedout(), 0)
            preparing.set()
            await release.wait()
            return await original(photo_base64)

        with patch.object(resgate, "_preparar_foto_resgate", photo):
            task = asyncio.create_task(self.confirm(token, cookie))
            try:
                await asyncio.wait_for(preparing.wait(), 2)
                async with self.pool.begin() as conn:
                    await conn.execute(text("SELECT id FROM lotes WHERE id = 1 FOR UPDATE NOWAIT"))
                release.set()
                self.assertEqual((await asyncio.wait_for(task, 5)).status_code, 200)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_resposta_perdida_apos_commit_recupera_cadastro_e_preserva_foto(self):
        token, cookie = await self.reserve()
        class CommitResponseLost(AsyncSession):
            async def commit(self):
                await super().commit()
                raise ConnectionError("confirmação do commit interrompida")

        uncertain_sessions = sessionmaker(self.pool, class_=CommitResponseLost, expire_on_commit=False)
        with patch.object(self, "sessions", uncertain_sessions):
            with self.assertRaises(Exception):
                await self.confirm(token, cookie)
        await self.assert_one_confirmation()
        self.assertEqual(len(list(Path(self.photos.name).iterdir())), 1)
        response = await self.confirm(token, cookie, photo="")
        self.assertTrue(json.loads(response.body)["sucesso"])
        await self.assert_one_confirmation()
        self.assertEqual(len(list(Path(self.photos.name).iterdir())), 1)
