"""Fluxo de correção com persistência SQLite isolada, sem SMTP ou banco real."""

import base64
import io
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException, Response
from PIL import Image
from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine, select

from app.models.all_models import Ingresso, Lote, SolicitacaoCorrecaoFoto, Usuario, UserRole
from app.routers import correcao_foto as routes


class AsyncSQLiteSession:
    """Adapta a interface assíncrona para transações reais em SQLite de teste."""

    def __init__(self, session):
        self.session = session

    async def execute(self, statement, params=None):
        return self.session.execute(statement, params or {})

    async def get(self, model, identifier):
        return self.session.get(model, identifier)

    def add(self, instance):
        self.session.add(instance)

    async def commit(self):
        self.session.commit()

    async def rollback(self):
        self.session.rollback()


class TestCorrecaoFoto(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.db.execute(text("""CREATE TABLE email_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, recipient TEXT, subject TEXT,
            html_body TEXT, sender_type TEXT, qr_image BLOB, ticket_image BLOB
        )"""))
        self.admin = Usuario(id=1, cpf="11144477735", nome="Admin", role=UserRole.admin_geral)
        self.usuario = Usuario(id=2, cpf="52998224725", nome="Participante <Teste>",
                               email="pessoa@example.invalid", foto_rosto_url="/static/foto-anterior.jpg")
        self.db.add(self.admin)
        self.db.add(self.usuario)
        self.db.add(Lote(id=1, nome="Lote teste", quantidade_total=1, quantidade_resgatada=1))
        self.db.add(Ingresso(id=1, usuario_id=2, lote_id=1, qr_code_token="ingresso-original"))
        self.db.commit()
        self.session = AsyncSQLiteSession(self.db)
        self.tempdir = tempfile.TemporaryDirectory()
        self.photo_dir = Path(self.tempdir.name)
        self.photo_patch = patch.object(routes, "FOTOS_DIR", self.photo_dir)
        self.photo_patch.start()

    def tearDown(self):
        self.photo_patch.stop()
        self.db.close()
        self.engine.dispose()
        self.tempdir.cleanup()

    async def solicitar(self, motivo="Foto escura.\nEnvie outra, por favor."):
        return await routes.solicitar_correcao_foto(
            self.usuario.id, routes.SolicitarCorrecaoFotoRequest(motivo=motivo),
            self.session, self.admin,
        )

    def ultimo_email(self):
        return self.db.execute(text("SELECT html_body FROM email_queue ORDER BY id DESC LIMIT 1")).scalar_one()

    def token(self):
        return re.search(r"/corrigir-foto#([A-Za-z0-9_-]{43})", self.ultimo_email()).group(1)

    def foto(self):
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), "white").save(buffer, format="JPEG")
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()

    async def enviar_foto(self, token=None, foto=None):
        return await routes.corrigir_foto(
            token or self.token(), routes.CorrigirFotoRequest(foto_base64=foto or self.foto()),
            Response(), self.session,
        )

    async def test_fluxo_completo_atualiza_so_foto_e_consumo_e_persistente(self):
        result = await self.solicitar()
        self.assertTrue(result["enfileirado"])
        token = self.token()
        request = self.db.exec(select(SolicitacaoCorrecaoFoto)).one()
        self.assertNotEqual(request.token_hash, token)
        self.assertEqual(request.solicitado_por_id, self.admin.id)
        self.assertEqual(request.email_destino, self.usuario.email)
        response = Response()
        info = await routes.consultar_correcao_foto(token, response, self.session)
        self.assertEqual(info["motivo"], "Foto escura.\nEnvie outra, por favor.")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue((await self.enviar_foto(token))["sucesso"])
        self.db.expire_all()
        request = self.db.get(SolicitacaoCorrecaoFoto, request.id)
        self.assertEqual(request.status, "concluida")
        self.assertIsNotNone(request.concluido_em)
        usuario = self.db.get(Usuario, 2)
        self.assertTrue(usuario.foto_rosto_url.startswith("/static/uploads/fotos/correcao_"))
        self.assertTrue((self.photo_dir / usuario.foto_rosto_url.split("/")[-1]).is_file())
        self.assertEqual(usuario.email, "pessoa@example.invalid")
        ingresso = self.db.get(Ingresso, 1)
        self.assertEqual(ingresso.qr_code_token, "ingresso-original")
        self.assertIsNone(ingresso.deleted_at)
        with self.assertRaises(HTTPException) as error:
            await self.enviar_foto(token)
        self.assertEqual(error.exception.status_code, 410)
        self.assertEqual(len(list(self.photo_dir.glob("*.jpg"))), 1)

    async def test_reenvio_invalida_link_anterior(self):
        await self.solicitar()
        antigo = self.token()
        await self.solicitar("Envie uma foto de frente.")
        novo = self.token()
        self.assertNotEqual(antigo, novo)
        with self.assertRaises(HTTPException) as error:
            await self.enviar_foto(antigo)
        self.assertEqual(error.exception.status_code, 410)
        self.assertTrue((await self.enviar_foto(novo))["sucesso"])

    async def test_falha_na_fila_reverte_nova_solicitacao_e_preserva_link_anterior(self):
        await self.solicitar()
        antigo = self.token()
        with patch.object(routes, "send_photo_correction_email_async", AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as error:
                await self.solicitar("Nova solicitação")
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(len(self.db.exec(select(SolicitacaoCorrecaoFoto)).all()), 1)
        self.assertTrue((await self.enviar_foto(antigo))["sucesso"])

    async def test_link_expirado_nao_altera_foto(self):
        await self.solicitar()
        request = self.db.exec(select(SolicitacaoCorrecaoFoto)).one()
        request.expira_em = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.add(request)
        self.db.commit()
        for operation in [self.enviar_foto, lambda token: routes.consultar_correcao_foto(token, Response(), self.session)]:
            with self.assertRaises(HTTPException) as error:
                await operation(self.token())
            self.assertEqual(error.exception.status_code, 410)
        self.assertEqual(self.usuario.foto_rosto_url, "/static/foto-anterior.jpg")

    async def test_foto_invalida_nao_consume_link(self):
        await self.solicitar()
        for foto in ["data:image/jpeg;base64,bmFvLWUtdW1hLWZvdG8=", "data:image/png;base64,AAAA"]:
            with self.assertRaises(HTTPException) as error:
                await self.enviar_foto(foto=foto)
            self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.usuario.foto_rosto_url, "/static/foto-anterior.jpg")
        self.assertTrue((await self.enviar_foto())["sucesso"])

    async def test_sem_email_nao_cria_solicitacao_ou_email(self):
        self.usuario.email = None
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            await self.solicitar()
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.exec(select(SolicitacaoCorrecaoFoto)).all(), [])
        self.assertEqual(self.db.execute(text("SELECT COUNT(*) FROM email_queue")).scalar(), 0)

    async def test_link_desconhecido_nao_altera_cadastro(self):
        for token in ["invalido", "a" * 43]:
            with self.assertRaises(HTTPException) as error:
                await self.enviar_foto(token)
            self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(self.usuario.foto_rosto_url, "/static/foto-anterior.jpg")

    async def test_email_escapa_nome_e_motivo_e_motivo_e_opcional(self):
        await self.solicitar('<script>alert("x")</script>\nRosto desfocado.')
        html = self.ultimo_email()
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Participante &lt;Teste&gt;", html)
        self.assertIn("<br>Rosto desfocado.", html)
        await self.solicitar("")
        self.assertNotIn("Mensagem da organização:", self.ultimo_email())

    async def test_link_revogado_quando_conta_inativa_ou_email_mudou(self):
        await self.solicitar()
        token = self.token()
        self.usuario.ativo = False
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            await self.enviar_foto(token)
        self.assertEqual(error.exception.status_code, 404)
        self.usuario.ativo = True
        self.usuario.email = "outro@example.invalid"
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            await self.enviar_foto(token)
        self.assertEqual(error.exception.status_code, 410)

    async def test_administrador_comum_nao_solicita_a_outro_administrador(self):
        self.admin.role = UserRole.admin
        self.usuario.role = UserRole.admin
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            await self.solicitar()
        self.assertEqual(error.exception.status_code, 403)

    async def test_endpoint_administrativo_exige_autenticacao(self):
        app = FastAPI()
        app.include_router(routes.router)
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message):
            messages.append(message)

        # Não abre conexão: get_current_user rejeita a ausência do cookie antes de consultar o banco.
        await app({"type": "http", "method": "POST", "path": "/api/admin/participantes/2/solicitar-correcao-foto",
                   "scheme": "http", "query_string": b"", "headers": [(b"content-type", b"application/json")],
                   "server": ("test", 80)}, receive, send)
        self.assertEqual(messages[0]["status"], 303)


if __name__ == "__main__":
    unittest.main()
