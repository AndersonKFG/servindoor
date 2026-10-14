"""Permissões HTTP do painel de lotes, sem banco real ou efeitos externos."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from app.core.deps import get_current_user
from app.db.session import get_session
from app.models.all_models import Usuario, UserRole
from app.routers import admin


class TestAdminLotesPermissoes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(admin.router)
        self.usuario = Usuario(cpf="11144477735", nome="Administrador", role=UserRole.admin)
        self.session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        self.session.execute.return_value = result

        async def usuario_atual():
            return self.usuario

        async def sessao():
            yield self.session

        self.app.dependency_overrides[get_current_user] = usuario_atual
        self.app.dependency_overrides[get_session] = sessao
        self.dashboard = patch.object(admin, "obter_dados_dashboard", AsyncMock(return_value=(
            {"total_vagas": 100, "total_resgatados": 25}, [], [],
        ))).start()
        self.addCleanup(patch.stopall)

    async def request(self, method, path):
        messages = []
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": method, "scheme": "http", "path": path,
            "raw_path": path.encode(), "query_string": b"",
            "root_path": "", "client": ("127.0.0.1", 1234), "server": ("test", 80),
            "headers": [(b"accept", b"application/json"), (b"content-type", b"application/json")],
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message):
            messages.append(message)

        await self.app(scope, receive, send)
        status = next(message["status"] for message in messages if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return status, json.loads(body) if body else None

    async def test_admin_e_admin_geral_consultam_painel_metricas_e_historico(self):
        for role, roles in [(UserRole.admin, None), (UserRole.admin_geral, None),
                            (UserRole.validador, "validador,admin")]:
            self.usuario.role = role
            self.usuario.roles = roles
            for path in ("/admin", "/api/lotes-admin", "/api/admin/lotes/backups"):
                with self.subTest(role=role, roles=roles, path=path):
                    status, data = await self.request("GET", path)
                    self.assertEqual(status, 200)
                    if path != "/api/admin/lotes/backups":
                        self.assertEqual(data["metricas"]["total_vagas"], 100)
                    else:
                        self.assertEqual(data["backups"], [])

    async def test_admin_nao_gerencia_lotes_ou_backups_nem_por_requisicao_direta(self):
        operations = [
            ("POST", "/admin/lote"),
            ("POST", "/admin/lote/1/editar"),
            ("POST", "/admin/lote/1/toggle"),
            ("POST", "/admin/lote/1/encerrar"),
            ("GET", "/api/admin/lote/1/verificar-exclusao"),
            ("POST", "/api/admin/lote/1/solicitar-codigo-exclusao"),
            ("POST", "/api/admin/lote/1/confirmar-exclusao"),
            ("POST", "/admin/lote/1/excluir"),
            ("POST", "/api/admin/lotes/backups/1/restaurar"),
            ("GET", "/api/admin/lotes/backups/1/exportar"),
            ("POST", "/api/admin/lotes/importar-backup"),
            ("DELETE", "/api/admin/lotes/backups/1"),
        ]
        for roles in (None, "admin,validador"):
            self.usuario.roles = roles
            for method, path in operations:
                with self.subTest(method=method, path=path, roles=roles):
                    status, data = await self.request(method, path)
                    self.assertEqual(status, 403)
                    self.assertIn("Administrador Geral", data["detail"])
        self.session.get.assert_not_awaited()
        self.session.execute.assert_not_awaited()
        self.session.commit.assert_not_awaited()

    async def test_outros_papeis_nao_acessam_consultas(self):
        for role in (UserRole.servidor, UserRole.validador, UserRole.portaria, UserRole.entregador):
            self.usuario.role = role
            for path in ("/admin", "/api/lotes-admin", "/api/admin/lotes/backups"):
                with self.subTest(role=role, path=path):
                    self.assertEqual((await self.request("GET", path))[0], 403)
        self.dashboard.assert_not_awaited()
        self.session.execute.assert_not_awaited()

    async def test_admin_geral_mantem_acesso_a_operacoes_e_retencao_obrigatoria(self):
        self.usuario.role = UserRole.admin_geral
        self.session.get.return_value = None
        for method, path in [
            ("POST", "/admin/lote/1/toggle"), ("POST", "/admin/lote/1/encerrar"),
            ("GET", "/api/admin/lote/1/verificar-exclusao"),
            ("GET", "/api/admin/lotes/backups/1/exportar"),
        ]:
            with self.subTest(path=path):
                self.assertEqual((await self.request(method, path))[0], 404)
        status, data = await self.request("DELETE", "/api/admin/lotes/backups/1")
        self.assertEqual(status, 403)
        self.assertIn("retenção", data["detail"])


if __name__ == "__main__":
    unittest.main()
