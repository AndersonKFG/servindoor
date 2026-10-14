"""Edição administrativa de participantes com persistência SQLite isolada."""

import json
import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine

from app.core.deps import get_current_admin
from app.models.all_models import Ingresso, Lote, Usuario, UserRole
from app.routers.admin import editar_participante_admin


class AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    async def get(self, model, identifier):
        return self.session.get(model, identifier)

    def add(self, instance):
        self.session.add(instance)

    async def commit(self):
        self.session.commit()

    async def refresh(self, instance):
        self.session.refresh(instance)


class TestEdicaoParticipante(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(Usuario(id=1, cpf="52998224725", nome="Nome original",
                            vinculo="Efetivo", email="pessoa@example.invalid"))
        self.db.add(Lote(id=1, nome="Lote teste"))
        self.db.add(Ingresso(id=1, usuario_id=1, lote_id=1, qr_code_token="token-original"))
        self.db.commit()
        self.session = AsyncSessionAdapter(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def editar(self, data, role=UserRole.admin):
        admin = Usuario(cpf="11144477735", nome="Administrador", role=role)
        response = await editar_participante_admin(
            1, AsyncMock(json=AsyncMock(return_value=data)), self.session, admin,
        )
        return json.loads(response.body)

    async def test_admin_e_admin_geral_editam_nome_e_vinculo_sem_afetar_ingresso(self):
        for role in (UserRole.admin, UserRole.admin_geral):
            with self.subTest(role=role):
                data = await self.editar({"nome": "  Maria da Conceição  ", "vinculo": "  Comissionado  "}, role)
                self.assertEqual(data["participante"]["nome"], "Maria da Conceição")
                self.assertEqual(data["participante"]["vinculo"], "Comissionado")
                self.db.expire_all()
                usuario = self.db.get(Usuario, 1)
                self.assertEqual(usuario.nome, "Maria da Conceição")
                self.assertEqual(usuario.vinculo, "Comissionado")
                self.assertEqual(usuario.cpf, "52998224725")
                self.assertEqual(usuario.email, "pessoa@example.invalid")
                self.assertEqual(usuario.role, UserRole.servidor)
                self.assertEqual(self.db.get(Ingresso, 1).qr_code_token, "token-original")

    async def test_nome_obrigatorio_e_textual(self):
        for nome in (None, "", "   ", 123, []):
            with self.subTest(nome=nome):
                with self.assertRaises(HTTPException) as error:
                    await self.editar({"nome": nome, "vinculo": "Aposentado"})
                self.assertEqual(error.exception.status_code, 400)
                self.db.rollback()
                self.assertEqual(self.db.get(Usuario, 1).nome, "Nome original")
                self.assertEqual(self.db.get(Usuario, 1).vinculo, "Efetivo")

    async def test_campos_omitidos_preservam_nome_e_vinculo(self):
        data = await self.editar({"setor": "Novo setor"})
        self.assertEqual(data["participante"]["nome"], "Nome original")
        self.assertEqual(data["participante"]["vinculo"], "Efetivo")
        self.assertEqual(data["participante"]["setor"], "Novo setor")

    async def test_vinculo_pode_ser_removido(self):
        for vinculo in (None, "", "   "):
            with self.subTest(vinculo=vinculo):
                data = await self.editar({"vinculo": vinculo})
                self.assertIsNone(data["participante"]["vinculo"])
                self.db.expire_all()
                self.assertIsNone(self.db.get(Usuario, 1).vinculo)

    async def test_vinculo_rejeita_valor_nao_textual(self):
        with self.assertRaises(HTTPException) as error:
            await self.editar({"vinculo": ["Efetivo"]})
        self.assertEqual(error.exception.status_code, 400)

    async def test_admin_comum_nao_edita_outro_administrador(self):
        usuario = self.db.get(Usuario, 1)
        usuario.role = UserRole.admin
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            await self.editar({"nome": "Outro nome", "vinculo": "Staff"})
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(usuario.nome, "Nome original")

    async def test_edicao_continua_restrita_a_administradores(self):
        for role in (UserRole.servidor, UserRole.validador, UserRole.portaria):
            with self.subTest(role=role):
                with self.assertRaises(HTTPException) as error:
                    await get_current_admin(Usuario(cpf="11144477735", nome="Sem acesso", role=role))
                self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
