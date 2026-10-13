"""Regressões do login com senha provisória, sem banco ou envio de e-mail."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse

from app.core import security
from app.models.all_models import Usuario, UserRole
from app.routers import auth


class TestSenhaObrigatoria(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.usuario = Usuario(
            id=1, cpf="52998224725", nome="Equipe de teste",
            role=UserRole.portaria, senha_hash="hash-provisorio",
            deve_trocar_senha=True,
        )
        result = MagicMock()
        result.scalars.return_value.first.return_value = self.usuario
        self.session = MagicMock()
        self.session.execute = AsyncMock(return_value=result)
        self.session.commit = AsyncMock()

    def request(self, accept="application/json", token=None):
        headers = [(b"accept", accept.encode())]
        if token:
            headers.append((b"cookie", f"access_token=Bearer {token}".encode()))
        return Request({
            "type": "http", "method": "POST", "path": "/login",
            "headers": headers, "client": ("127.0.0.1", 1234),
        })

    async def login(self, accept="application/json"):
        with (
            patch.object(auth, "verificar_rate_limit_login", AsyncMock(return_value=(True, None, 0))),
            patch.object(auth, "limpar_rate_limit_login", AsyncMock()),
            patch.object(security, "verify_password", return_value=True),
        ):
            return await auth.login_action(
                self.request(accept), username=self.usuario.cpf,
                password="Fest@Teste", forcar_login=False, session=self.session,
            )

    async def test_login_informa_troca_obrigatoria_e_preserva_cookie(self):
        response = await self.login()
        data = json.loads(response.body)
        self.assertTrue(data["deve_trocar_senha"])
        self.assertTrue(data["usuario"]["deve_trocar_senha"])
        self.assertEqual(data["redirect_url"], "/login")
        self.assertIn("access_token=", response.headers["set-cookie"])

    async def test_conta_criada_na_equipe_exige_troca_no_primeiro_login(self):
        from app.routers import admin as admin_routes

        empty_result = MagicMock()
        empty_result.scalars.return_value.first.return_value = None
        self.session.execute.return_value = empty_result
        self.session.refresh = AsyncMock()
        admin = Usuario(cpf="11144477735", nome="Administrador", role=UserRole.admin_geral)
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "cpf": "529.982.247-25", "nome": "Nova conta da equipe",
            "email": "equipe@example.invalid", "roles": ["portaria", "validador"],
        })

        with (
            patch.object(admin_routes, "send_team_credentials_email_async", AsyncMock()) as email,
            patch.object(security, "get_password_hash", return_value="hash-inicial") as hash_password,
        ):
            created = await admin_routes.criar_usuario_admin(request, self.session, admin)
            await asyncio.sleep(0)
            email.assert_awaited_once()
            credentials = email.call_args.kwargs

        self.assertTrue(json.loads(created.body)["sucesso"])
        self.usuario = self.session.add.call_args.args[0]
        self.assertTrue(self.usuario.deve_trocar_senha)
        self.assertFalse(credentials["is_reset"])
        senha_provisoria = credentials["senha_provisoria"]
        hash_password.assert_called_once_with(senha_provisoria)
        self.assertEqual(self.usuario.senha_hash, "hash-inicial")

        result = MagicMock()
        result.scalars.return_value.first.return_value = self.usuario
        self.session.execute.return_value = result
        with (
            patch.object(auth, "verificar_rate_limit_login", AsyncMock(return_value=(True, None, 0))),
            patch.object(auth, "limpar_rate_limit_login", AsyncMock()),
            patch.object(security, "verify_password", return_value=True) as verify_password,
        ):
            response = await auth.login_action(
                self.request(), username=self.usuario.cpf,
                password=senha_provisoria, forcar_login=False, session=self.session,
            )
        verify_password.assert_called_once_with(senha_provisoria, "hash-inicial")
        data = json.loads(response.body)
        self.assertTrue(data["sucesso"])
        self.assertTrue(data["deve_trocar_senha"])
        self.assertTrue(data["usuario"]["deve_trocar_senha"])
        self.assertEqual(data["redirect_url"], "/login")
        self.session.commit.assert_awaited()

    async def test_login_sem_pendencia_segue_para_painel(self):
        self.usuario.deve_trocar_senha = False
        data = json.loads((await self.login()).body)
        self.assertFalse(data["deve_trocar_senha"])
        self.assertEqual(data["redirect_url"], "/portaria")

    async def test_login_html_com_pendencia_permanece_no_login(self):
        response = await self.login("text/html")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    async def test_login_page_com_pendencia_entrega_interface(self):
        token = security.create_access_token({"sub": self.usuario.cpf})
        with patch.object(auth.os.path, "exists", return_value=True):
            response = await auth.login_page(self.request(token=token), self.session)
        self.assertIsInstance(response, FileResponse)

    async def test_nova_senha_persistida_remove_pendencia(self):
        token = security.create_access_token({"sub": self.usuario.cpf})
        req = auth.AlterarSenhaObrigatoriaRequest(
            nova_senha="MinhaNovaSenha", confirmacao_senha="MinhaNovaSenha",
        )
        with patch.object(security, "get_password_hash", return_value="hash-definitivo"):
            response = await auth.alterar_senha_obrigatoria(req, self.request(token=token), self.session)
        self.assertTrue(json.loads(response.body)["sucesso"])
        self.assertFalse(self.usuario.deve_trocar_senha)
        self.assertEqual(self.usuario.senha_hash, "hash-definitivo")
        self.session.commit.assert_awaited_once()

    async def test_senha_invalida_mantem_pendencia(self):
        token = security.create_access_token({"sub": self.usuario.cpf})
        for senha, confirmacao in [("123", "123"), ("NovaSenha", "Diferente")]:
            with self.subTest(senha=senha), self.assertRaises(HTTPException) as error:
                await auth.alterar_senha_obrigatoria(
                    auth.AlterarSenhaObrigatoriaRequest(nova_senha=senha, confirmacao_senha=confirmacao),
                    self.request(token=token), self.session,
                )
            self.assertEqual(error.exception.status_code, 400)
            self.assertTrue(self.usuario.deve_trocar_senha)
            self.assertEqual(self.usuario.senha_hash, "hash-provisorio")
        self.session.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
