"""Envio de validações: fila real isolada, sem SMTP ou acesso à produção."""

import json
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import event, text
from sqlmodel import SQLModel, Session, create_engine

from app.models.all_models import Ingresso, Lote, Secretaria, SolicitacaoValidacao, Usuario, UserRole
from app.routers import validacoes as routes


class AsyncSQLiteSession:
    def __init__(self, session):
        self.session = session
        self.fail_commit = False

    async def execute(self, statement, params=None):
        return self.session.execute(statement, params or {})

    def add(self, instance):
        self.session.add(instance)

    @asynccontextmanager
    async def begin_nested(self):
        with self.session.begin_nested():
            yield

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("Falha simulada antes do commit")
        self.session.commit()


class TestValidacoesComunicacao(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")

        # Garante que SAVEPOINT participe da transação externa também no SQLite.
        @event.listens_for(self.engine, "connect")
        def connect(connection, _):
            connection.isolation_level = None

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            connection.exec_driver_sql("BEGIN")

        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.db.execute(text("""CREATE TABLE email_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, recipient TEXT, subject TEXT,
            html_body TEXT, sender_type TEXT, qr_image BLOB, ticket_image BLOB,
            idempotency_key TEXT UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""))
        self.admin = Usuario(id=10000, cpf="11144477735", nome="Admin", role=UserRole.admin_geral)
        self.db.add_all([self.admin, Lote(id=1, nome="Lote"), Secretaria(id=1, nome="Secretaria")])
        self.db.commit()
        self.session = AsyncSQLiteSession(self.db)
        self.png = patch("app.services.ticket_generator.generate_ticket_png_bytes", return_value=b"png-teste").start()
        patch("app.services.email_queue.async_session", side_effect=AssertionError("Fila fora da transação")).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def criar(self, identifier, *, status="aprovado", email="pessoa@example.invalid", ingresso=True):
        self.db.add(Usuario(id=identifier, cpf=str(identifier).zfill(11), nome=f"Pessoa {identifier}",
                            email=email, secretaria_id=1))
        self.db.add(SolicitacaoValidacao(id=identifier, usuario_id=identifier, lote_id=1, status=status))
        if ingresso and status == "aprovado":
            self.db.add(Ingresso(usuario_id=identifier, lote_id=1, qr_code_token=f"token-{identifier}"))

    def salvar(self):
        self.db.commit()
        self.db.expunge_all()

    async def lote(self, *, after_id=0, limit=25, tipo="todos"):
        response = await routes.comunicar_em_lote_admin(
            tipo_filtro=tipo, session=self.session, admin=self.admin, limit=limit, after_id=after_id,
        )
        return json.loads(response.body)

    async def individual(self, identifier):
        response = await routes.comunicar_solicitacao_validacao(identifier, self.session, self.admin)
        return json.loads(response.body)

    def emails(self):
        return self.db.execute(text("SELECT COUNT(*) FROM email_queue")).scalar_one()

    def pendentes(self):
        return self.db.execute(text("SELECT COUNT(*) FROM solicitacoes_validacao WHERE comunicado = false")).scalar_one()

    async def test_1200_aprovados_em_paginas_sem_reenviar_e_kpi_zerado(self):
        for i in range(1, 1201):
            self.criar(i)
        self.salvar()
        cursor = total = paginas = 0
        while True:
            data = await self.lote(after_id=cursor)
            paginas += 1
            self.assertEqual(data["total_enfileirados"], 25)
            self.assertEqual(data["falhas"], 0)
            self.assertGreater(data["proximo_id"], cursor)
            total += data["total_enfileirados"]
            cursor = data["proximo_id"]
            if not data["tem_mais"]:
                break
        self.assertEqual((total, paginas, self.emails(), self.pendentes()), (1200, 48, 1200, 0))
        self.assertEqual((await self.lote())["total_enfileirados"], 0)
        await self.individual(1)
        self.assertEqual(self.emails(), 1200)
        self.assertEqual(self.png.call_args.kwargs["secretaria_nome"], "Secretaria")
        self.db.execute(text("CREATE TABLE resgate_jobs (solicitacao_id INTEGER, status TEXT, job_type TEXT)"))
        listing = await routes.listar_solicitacoes_validacao(
            status_filtro="todos", secretaria_id=None, session=self.session,
            validador=self.admin, page=1, limit=25, busca="",
        )
        self.assertEqual(json.loads(listing.body)["kpis"]["total_comunicacao_pendente"], 0)

    async def test_falhas_contadas_e_cursor_avanca_sem_repetir_caso_invalido(self):
        self.criar(1, email=None)
        self.criar(2, ingresso=False)
        self.criar(3, email="email-invalido")
        self.criar(4, status="rejeitado")
        self.criar(5)
        self.salvar()
        primeira = await self.lote(limit=4)
        self.assertEqual(primeira["falhas_por_motivo"], {"sem_email": 1, "sem_ingresso": 1, "fila": 1})
        self.assertEqual((primeira["falhas"], primeira["total_enfileirados"]), (3, 1))
        self.assertTrue(primeira["tem_mais"])
        segunda = await self.lote(after_id=primeira["proximo_id"], limit=4)
        self.assertEqual(segunda["total_enfileirados"], 1)
        self.assertFalse(segunda["tem_mais"])
        self.assertEqual((self.emails(), self.pendentes()), (2, 3))

    async def test_falha_no_commit_nao_deixa_email_sem_marcacao_e_preserva_pagina_anterior(self):
        self.criar(1)
        self.criar(2)
        self.salvar()
        await self.lote(limit=1)
        self.session.fail_commit = True
        with self.assertRaises(RuntimeError):
            await self.lote(after_id=1, limit=1)
        self.db.rollback()
        self.assertEqual((self.emails(), self.pendentes()), (1, 1))
        self.session.fail_commit = False
        self.assertEqual((await self.lote())["total_enfileirados"], 1)
        self.assertEqual((self.emails(), self.pendentes()), (2, 0))

    async def test_falha_sql_na_fila_isola_solicitacao_e_nao_anula_as_demais(self):
        self.criar(1)
        self.criar(2)
        self.salvar()
        self.db.execute(text("""CREATE TRIGGER falhar_primeiro BEFORE INSERT ON email_queue
            WHEN NEW.recipient = 'falhar@example.invalid'
            BEGIN SELECT RAISE(ABORT, 'falha simulada'); END"""))
        self.db.get(Usuario, 1).email = "falhar@example.invalid"
        self.db.commit()
        data = await self.lote()
        self.assertEqual((data["falhas"], data["total_enfileirados"]), (1, 1))
        self.assertEqual((self.emails(), self.pendentes()), (1, 1))

    async def test_individual_atomico_idempotente_e_nao_recria_ingresso(self):
        self.criar(1)
        self.salvar()
        self.session.fail_commit = True
        with self.assertRaises(RuntimeError):
            await self.individual(1)
        self.db.rollback()
        self.assertEqual((self.emails(), self.pendentes()), (0, 1))
        self.session.fail_commit = False
        self.assertTrue((await self.individual(1))["comunicado"])
        await self.individual(1)
        self.assertEqual((self.emails(), self.pendentes()), (1, 0))
        self.assertEqual(self.db.execute(text("SELECT COUNT(*) FROM ingressos")).scalar_one(), 1)

    async def test_filtros_respeitam_aprovados_rejeitados_e_pendentes(self):
        self.criar(1)
        self.criar(2, status="rejeitado")
        self.criar(3, status="pendente_analise")
        self.salvar()
        self.assertEqual((await self.lote(tipo="aprovados"))["total_enfileirados"], 1)
        self.assertFalse(self.db.get(SolicitacaoValidacao, 2).comunicado)
        self.assertEqual((await self.lote(tipo="rejeitados"))["total_enfileirados"], 1)
        self.assertFalse(self.db.get(SolicitacaoValidacao, 3).comunicado)
        with self.assertRaises(HTTPException) as error:
            await self.individual(3)
        self.assertEqual(error.exception.status_code, 400)

    async def test_marcacao_perdida_nao_reenvia_e_kpi_consulta_registro_duravel(self):
        self.criar(1)
        self.criar(2, status="rejeitado")
        self.salvar()
        await self.lote()
        self.db.execute(text("UPDATE solicitacoes_validacao SET comunicado = false, comunicado_em = NULL"))
        self.db.commit()
        self.db.expunge_all()
        self.png.reset_mock()
        self.assertEqual((await self.lote())["total_enfileirados"], 0)
        self.db.execute(text("CREATE TABLE resgate_jobs (solicitacao_id INTEGER, status TEXT, job_type TEXT)"))
        listing = await routes.listar_solicitacoes_validacao(
            status_filtro="todos", secretaria_id=None, session=self.session,
            validador=self.admin, page=1, limit=25, busca="",
        )
        data = json.loads(listing.body)
        self.assertEqual(data["kpis"]["total_comunicacao_pendente"], 0)
        self.assertTrue(all(s["comunicado"] and s["comunicado_em"] for s in data["solicitacoes"]))
        await self.individual(1)
        await self.individual(2)
        self.assertEqual((self.emails(), self.pendentes()), (2, 0))
        self.png.assert_not_called()

    async def test_fila_deduplica_mesmo_se_chamador_repetir_mesma_chave(self):
        from app.services.email_queue import enqueue_email

        for _ in range(2):
            self.assertTrue(await enqueue_email(
                "pessoa@example.invalid", "Ingresso", "html", "ticket",
                session=self.session, idempotency_key="validacao:1:aprovado",
            ))
        self.assertEqual(self.emails(), 1)

    async def test_somente_admin_geral_pode_enfileirar(self):
        self.admin = Usuario(cpf="52998224725", nome="Validador", role=UserRole.validador)
        for operation in (self.lote(), self.individual(1)):
            with self.assertRaises(HTTPException) as error:
                await operation
            self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.emails(), 0)


if __name__ == "__main__":
    unittest.main()
