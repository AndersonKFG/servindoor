"""Liberação de presença por HTTP, com persistência SQLite isolada."""

import json
import unittest

from fastapi import FastAPI
from sqlmodel import SQLModel, Session, create_engine, select

from app.core.deps import get_current_user
from app.db.session import get_session
from app.models.all_models import ControlePresenca, Ingresso, LogAcesso, Lote, Usuario, UserRole
from app.routers import portaria


class AsyncSessionAdapter:
    """Executa as operações reais do ORM sem exigir um driver assíncrono de teste."""

    def __init__(self, session):
        self.session = session

    async def get(self, *args):
        return self.session.get(*args)

    async def execute(self, statement):
        return self.session.execute(statement)

    def add(self, instance):
        self.session.add(instance)

    async def commit(self):
        self.session.commit()


class TestPortariaLiberacao(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        SQLModel.metadata.create_all(self.engine)
        self.usuario = Usuario(id=1, cpf="11144477735", nome="Operador", role=UserRole.admin_geral)
        with Session(self.engine, expire_on_commit=False) as session:
            session.add(self.usuario)
            session.add(Usuario(id=2, cpf="12345678909", nome="Participante"))
            session.add(Lote(id=1, nome="Lote Teste"))
            session.add(Ingresso(id=1, usuario_id=2, lote_id=1, qr_code_token="ingresso-teste"))
            session.commit()

        self.app = FastAPI()
        self.app.include_router(portaria.router)

        async def usuario_atual():
            return self.usuario

        async def sessao():
            with Session(self.engine, expire_on_commit=False) as session:
                yield AsyncSessionAdapter(session)

        self.app.dependency_overrides[get_current_user] = usuario_atual
        self.app.dependency_overrides[get_session] = sessao

    async def request(self, method, path="/api/portaria/liberacao-presenca", payload=None):
        messages = []
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": method, "scheme": "http", "path": path,
            "raw_path": path.encode(), "query_string": b"", "root_path": "",
            "client": ("127.0.0.1", 1234), "server": ("test", 80),
            "headers": [(b"accept", b"application/json"), (b"content-type", b"application/json")],
        }

        async def receive():
            return {"type": "http.request", "body": json.dumps(payload or {}).encode(), "more_body": False}

        async def send(message):
            messages.append(message)

        await self.app(scope, receive, send)
        response = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return response["status"], json.loads(body)

    async def test_inicialmente_bloqueada(self):
        status, data = await self.request("GET")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"liberada": False})
        self.assertFalse(ControlePresenca().liberada)

    async def test_somente_admin_geral_altera_inclusive_multiplos_papeis(self):
        for role in (UserRole.admin, UserRole.portaria, UserRole.entregador, UserRole.validador, UserRole.servidor):
            self.usuario.role = role
            with self.subTest(role=role):
                self.assertEqual((await self.request("PUT", payload={"liberada": True}))[0], 403)
        self.usuario.roles = "admin,portaria,admin_geral"
        self.assertEqual((await self.request("PUT", payload={"liberada": True}))[0], 200)

    async def test_equipe_consulta_e_demais_papeis_nao(self):
        for role in UserRole:
            self.usuario.role = role
            with self.subTest(role=role):
                expected = 403 if role in (UserRole.servidor, UserRole.validador) else 200
                self.assertEqual((await self.request("GET"))[0], expected)

    async def test_persiste_liberacao_bloqueio_e_responsavel_entre_sessoes(self):
        for liberada in (True, False, True):
            self.assertEqual((await self.request("PUT", payload={"liberada": liberada}))[0], 200)
            self.assertEqual((await self.request("GET"))[1]["liberada"], liberada)
            with Session(self.engine) as session:
                controle = session.get(ControlePresenca, 1)
                self.assertEqual(controle.liberada, liberada)
                self.assertEqual(controle.alterado_por_id, 1)
                self.assertIsNotNone(controle.alterado_em)

    async def test_exige_booleano_explicito(self):
        for payload in ({}, {"liberada": "false"}, {"liberada": 1}, {"liberada": None}):
            with self.subTest(payload=payload):
                self.assertEqual((await self.request("PUT", payload=payload))[0], 422)
        self.assertFalse((await self.request("GET"))[1]["liberada"])

    async def test_bloqueio_impede_entrada_e_saida_inclusive_admin_geral(self):
        for role in (UserRole.admin_geral, UserRole.admin, UserRole.portaria, UserRole.entregador):
            self.usuario.role = role
            for novo_status in ("entrada", "saida"):
                with self.subTest(role=role, novo_status=novo_status):
                    status, data = await self.request("POST", "/api/portaria/alterar-status", {
                        "usuario_id": 2, "novo_status": novo_status,
                    })
                    self.assertEqual(status, 403)
                    self.assertEqual(data["codigo"], "presenca_bloqueada")
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(LogAcesso)).all(), [])

    async def test_liberar_registrar_bloquear_e_liberar_novamente(self):
        await self.request("PUT", payload={"liberada": True})
        payload = {"usuario_id": 2, "novo_status": "entrada"}
        self.usuario.role = UserRole.portaria
        status, data = await self.request("POST", "/api/portaria/alterar-status", payload)
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "dentro")

        # Preserva a validação existente de movimentos duplicados.
        self.assertEqual((await self.request("POST", "/api/portaria/alterar-status", payload))[0], 400)
        self.usuario.role = UserRole.admin_geral
        await self.request("PUT", payload={"liberada": False})
        payload["novo_status"] = "saida"
        self.assertEqual((await self.request("POST", "/api/portaria/alterar-status", payload))[0], 403)
        await self.request("PUT", payload={"liberada": True})
        status, data = await self.request("POST", "/api/portaria/alterar-status", payload)
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "fora")
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(LogAcesso)).all()), 2)

    async def test_busca_continua_disponivel_com_presenca_bloqueada(self):
        status, data = await self.request("POST", "/api/portaria/buscar", {"identificador": "12345678909"})
        self.assertEqual(status, 200)
        self.assertTrue(data["sucesso"])
        self.assertEqual(data["usuario_id"], 2)


if __name__ == "__main__":
    unittest.main()
