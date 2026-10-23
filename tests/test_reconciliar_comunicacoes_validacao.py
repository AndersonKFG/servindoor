"""Reconciliação isolada: comprovação pelo QR, histórico preservado e zero SMTP."""

import io
import json
import unittest
from unittest.mock import patch

import qrcode
from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from app.models.all_models import Ingresso, Lote, SolicitacaoValidacao, Usuario, UserRole
from app.routers import validacoes as routes
from tools.reconciliar_comunicacoes_validacao import aplicar, decodificar_tokens, diagnosticar


class AsyncSQLiteSession:
    def __init__(self, db):
        self.db = db

    async def execute(self, statement, params=None):
        return self.db.execute(statement, params or {})

    async def commit(self):
        self.db.commit()


class TestReconciliarComunicacoes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.db.execute(text("""CREATE TABLE email_queue (
            id INTEGER PRIMARY KEY, recipient TEXT, sender_type TEXT, status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP, idempotency_key TEXT UNIQUE, ticket_image BLOB,
            qr_image BLOB, last_error TEXT
        )"""))
        self.db.execute(text("CREATE TABLE resgate_jobs (solicitacao_id INTEGER, status TEXT, job_type TEXT)"))
        self.admin = Usuario(id=10000, cpf="11144477735", nome="Admin", role=UserRole.admin_geral)
        self.db.add_all([self.admin, Lote(id=1, nome="Lote")])
        self.db.commit()
        self.session = AsyncSQLiteSession(self.db)
        patch.object(routes, "send_ticket_email_async", side_effect=AssertionError("Não deve reenviar")).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def criar(self, identifier, *, email=None, status="aprovado", cancelado=False):
        self.db.add(Usuario(id=identifier, cpf=str(identifier).zfill(11), nome=f"Pessoa {identifier}",
                            email=email or f"pessoa{identifier}@example.invalid"))
        self.db.add(SolicitacaoValidacao(id=identifier, usuario_id=identifier, lote_id=1, status=status))
        if status == "aprovado":
            from datetime import datetime
            self.db.add(Ingresso(usuario_id=identifier, lote_id=1, qr_code_token=f"token-{identifier}",
                                deleted_at=datetime(2026, 1, 1) if cancelado else None))
        self.db.commit()

    def email(self, identifier, usuario_id, *, token=None, status="sent", remetente="ticket", imagem=None):
        token = token or f"token-{usuario_id}"
        if imagem is None:
            buffer = io.BytesIO()
            qrcode.make(token).save(buffer, format="PNG")
            imagem = buffer.getvalue()
        self.db.execute(text("""
            INSERT INTO email_queue (id, recipient, sender_type, status, sent_at, ticket_image)
            VALUES (:id, :email, :tipo, :status, :enviado, :imagem)
        """), {"id": identifier, "email": self.db.get(Usuario, usuario_id).email,
               "tipo": remetente, "status": status, "imagem": imagem,
               "enviado": "2026-10-23 12:00:00" if status == "sent" else None})
        self.db.commit()

    async def test_929_enviados_recuperados_novos_continuam_pendentes_sem_smtp(self):
        # A regra de associação usa o mesmo decoder; este teste grande evita gerar 929 PNGs.
        for i in range(1, 931):
            self.criar(i)
            if i <= 929:
                self.email(i, i, imagem=f"token-{i}".encode())
        decoder = lambda imagem, _: {imagem.decode()}
        diagnostico = await diagnosticar(self.session, decoder)
        self.assertEqual((diagnostico["pendentes_antes"], diagnostico["recuperaveis"]), (930, 929))
        self.assertEqual(self.db.execute(text("SELECT COUNT(*) FROM solicitacoes_validacao WHERE comunicado = true")).scalar(), 0)
        await aplicar(self.session, diagnostico)
        self.db.commit()
        self.db.expunge_all()
        novo = await diagnosticar(self.session, decoder)
        self.assertEqual((novo["pendentes_antes"], novo["recuperaveis"], novo["sem_comprovacao"]), (1, 0, 1))
        listing = await routes.listar_solicitacoes_validacao(
            status_filtro="todos", secretaria_id=None, session=self.session,
            validador=self.admin, page=1, limit=25, busca="",
        )
        self.assertEqual(json.loads(listing.body)["kpis"]["total_comunicacao_pendente"], 1)
        self.assertEqual(self.db.execute(text("SELECT COUNT(*) FROM email_queue")).scalar(), 929)

    async def test_qr_real_distingue_pessoas_com_mesmo_email_e_cancela_so_duplicatas(self):
        self.criar(1, email="compartilhado@example.invalid")
        self.criar(2, email="compartilhado@example.invalid")
        self.email(1, 1)
        self.email(2, 1, status="queued")
        self.email(3, 2, status="queued")
        self.email(4, 1, token="outro-ingresso", status="queued")
        diagnostico = await diagnosticar(self.session)
        self.assertEqual(diagnostico["recuperaveis"], 1)
        self.assertEqual(diagnostico["registros"][0]["duplicatas_na_fila"], [2])
        await aplicar(self.session, diagnostico)
        self.db.commit()
        self.assertEqual(self.db.execute(text("SELECT id, status FROM email_queue ORDER BY id")).all(),
                         [(1, "sent"), (2, "cancelled"), (3, "queued"), (4, "queued")])
        self.assertFalse(self.db.get(SolicitacaoValidacao, 2).comunicado)

    async def test_nao_recupera_falhas_pendentes_mensagem_generica_qr_errado_ou_cancelado(self):
        for i in range(1, 8):
            self.criar(i, cancelado=i == 7)
        self.email(1, 1, status="failed")
        self.email(2, 2, status="queued")
        self.email(3, 3, remetente="communications")
        self.email(4, 4, token="token-errado")
        self.email(5, 5, imagem=b"png-invalido")
        self.email(6, 6, status="sending")
        self.email(7, 7)
        self.assertEqual((await diagnosticar(self.session))["recuperaveis"], 0)

    async def test_falha_na_aplicacao_reverte_marcacoes_e_chaves(self):
        self.criar(1)
        self.email(1, 1)
        diagnostico = await diagnosticar(self.session)
        self.db.execute(text("UPDATE solicitacoes_validacao SET status = 'rejeitado' WHERE id = 1"))
        self.db.commit()
        with self.assertRaises(ValueError):
            await aplicar(self.session, diagnostico)
        self.db.rollback()
        self.assertIsNone(self.db.execute(text("SELECT idempotency_key FROM email_queue")).scalar())
        self.assertFalse(self.db.get(SolicitacaoValidacao, 1).comunicado)

    def test_decoder_le_qr_de_ingresso_em_anexo_png(self):
        from app.services.ticket_generator import generate_ticket_png_bytes

        token = "476d8c07-9ca4-4cb3-8c80-b3a89663e29d"
        imagem = generate_ticket_png_bytes(
            nome="Pessoa Teste", cpf="***.***.***-**", ingresso_token=token,
            lote_nome="Lote Teste", secretaria_nome="Secretaria Teste",
        )
        self.assertTrue(imagem)
        self.assertEqual(decodificar_tokens(imagem, None), {token})


if __name__ == "__main__":
    unittest.main()
