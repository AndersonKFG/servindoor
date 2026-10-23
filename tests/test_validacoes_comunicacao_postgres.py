"""Testes opcionais em schema descartável de um PostgreSQL explicitamente local."""

import asyncio
import json
import os
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.db.session import migrar_idempotencia_emails
from app.models.all_models import Ingresso, Lote, SolicitacaoValidacao, Usuario, UserRole
from app.routers import validacoes as routes
from app.services.email_queue import enqueue_email
from tools.reconciliar_comunicacoes_validacao import aplicar, diagnosticar


@unittest.skipUnless(os.environ.get("COMUNICACAO_TEST_DATABASE_URL"), "PostgreSQL local não configurado")
class TestComunicacaoPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(os.environ["COMUNICACAO_TEST_DATABASE_URL"])
        if url.host not in {"localhost", "127.0.0.1", "db"}:
            raise ValueError("Use apenas PostgreSQL local descartável; db refere-se ao Docker Compose local.")
        self.schema = "comunicacao_test_" + uuid.uuid4().hex
        self.control = create_async_engine(url)
        async with self.control.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.pool = create_async_engine(url, connect_args={"server_settings": {"search_path": self.schema}})
        self.sessions = sessionmaker(self.pool, class_=AsyncSession, expire_on_commit=False)
        async with self.pool.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            await conn.execute(text("""CREATE TABLE email_queue (
                id BIGSERIAL PRIMARY KEY, recipient VARCHAR NOT NULL, subject VARCHAR NOT NULL,
                html_body TEXT NOT NULL, sender_type VARCHAR NOT NULL,
                qr_image BYTEA, ticket_image BYTEA, status VARCHAR NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), sent_at TIMESTAMPTZ, last_error TEXT
            )"""))
            await migrar_idempotencia_emails(conn)
            await migrar_idempotencia_emails(conn)
            await conn.execute(text("CREATE TABLE resgate_jobs (solicitacao_id INTEGER, status TEXT, job_type TEXT)"))
        self.admin = Usuario(id=10000, cpf="11144477735", nome="Admin", role=UserRole.admin_geral)
        async with self.sessions() as session:
            session.add_all([self.admin, Lote(id=1, nome="Lote")])
            await session.commit()
        patch("app.services.ticket_generator.generate_ticket_png_bytes", return_value=b"png").start()
        self.addCleanup(patch.stopall)

    async def asyncTearDown(self):
        await self.pool.dispose()
        async with self.control.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.control.dispose()

    async def criar(self, total):
        async with self.sessions() as session:
            for i in range(1, total + 1):
                session.add(Usuario(id=i, cpf=str(i).zfill(11), nome=f"Pessoa {i}", email=f"pessoa{i}@example.invalid"))
                session.add(SolicitacaoValidacao(id=i, usuario_id=i, lote_id=1, status="aprovado"))
                session.add(Ingresso(usuario_id=i, lote_id=1, qr_code_token=f"token-{i}"))
            await session.commit()

    async def lote(self):
        async with self.sessions() as session:
            return json.loads((await routes.comunicar_em_lote_admin(
                tipo_filtro="todos", session=session, admin=self.admin, limit=25, after_id=0,
            )).body)

    async def test_concorrencia_marcacao_perdida_e_contador(self):
        await self.criar(10)
        respostas = await asyncio.gather(self.lote(), self.lote())
        self.assertEqual(sum(r["total_enfileirados"] for r in respostas), 10)
        async with self.pool.begin() as conn:
            await conn.execute(text("UPDATE solicitacoes_validacao SET comunicado = FALSE, comunicado_em = NULL"))
        self.assertEqual((await self.lote())["total_enfileirados"], 0)
        async with self.sessions() as session:
            listing = await routes.listar_solicitacoes_validacao(
                status_filtro="todos", secretaria_id=None, session=session,
                validador=self.admin, page=1, limit=25, busca="",
            )
            self.assertEqual(json.loads(listing.body)["kpis"]["total_comunicacao_pendente"], 0)
            await routes.comunicar_solicitacao_validacao(1, session, self.admin)
        async with self.pool.connect() as conn:
            self.assertEqual(await conn.scalar(text("SELECT COUNT(*) FROM email_queue")), 10)
            self.assertTrue(await conn.scalar(text("SELECT comunicado FROM solicitacoes_validacao WHERE id = 1")))

    async def test_chave_unica_no_banco_e_rollback_atomico(self):
        async with self.sessions() as session:
            for _ in range(2):
                self.assertTrue(await enqueue_email("pessoa@example.invalid", "Ingresso", "html", "ticket",
                                                    session=session, idempotency_key="validacao:1:aprovado"))
            await session.commit()
        async with self.pool.connect() as conn:
            self.assertEqual(await conn.scalar(text("SELECT COUNT(*) FROM email_queue")), 1)
        async with self.sessions() as session:
            self.assertTrue(await enqueue_email("pessoa@example.invalid", "Ingresso", "html", "ticket",
                                                session=session, idempotency_key="validacao:2:aprovado"))
            await session.rollback()
        async with self.pool.connect() as conn:
            self.assertEqual(await conn.scalar(text("SELECT COUNT(*) FROM email_queue")), 1)
        await self.criar(1)
        async with self.sessions() as session:
            await routes.comunicar_solicitacao_validacao(1, session, self.admin)
        async with self.pool.connect() as conn:
            self.assertEqual(await conn.scalar(text("SELECT COUNT(*) FROM email_queue")), 1)

    async def test_migracao_preserva_historico_sem_chaves(self):
        async with self.pool.begin() as conn:
            await conn.execute(text("""
                INSERT INTO email_queue (recipient, subject, html_body, sender_type, status, sent_at)
                VALUES ('pessoa@example.invalid', 'Ingresso', 'html', 'ticket', 'sent', NOW()),
                       ('pessoa@example.invalid', 'Ingresso', 'html', 'ticket', 'sent', NOW())
            """))
            await migrar_idempotencia_emails(conn)
            self.assertEqual(await conn.scalar(text("SELECT COUNT(*) FROM email_queue WHERE status = 'sent' AND idempotency_key IS NULL")), 2)

    async def test_recuperacao_preserva_horario_original_e_cancela_duplicata(self):
        await self.criar(1)
        criado_em = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        async with self.pool.begin() as conn:
            await conn.execute(text("""
                INSERT INTO email_queue (recipient, subject, html_body, sender_type, ticket_image,
                                         status, created_at, sent_at)
                VALUES ('pessoa1@example.invalid', 'Ingresso', 'html', 'ticket', :imagem, 'sent', :criado, :criado),
                       ('pessoa1@example.invalid', 'Ingresso', 'html', 'ticket', :imagem, 'queued', :criado, NULL)
            """), {"imagem": b"token-1", "criado": criado_em})
            plano = await diagnosticar(conn, lambda imagem, _: {imagem.decode()})
            self.assertEqual((plano["recuperaveis"], plano["duplicatas_na_fila"]), (1, 1))
            await aplicar(conn, plano)
        async with self.sessions() as session:
            solic = await session.get(SolicitacaoValidacao, 1)
            self.assertTrue(solic.comunicado)
            self.assertEqual(solic.comunicado_em.replace(tzinfo=timezone.utc), criado_em)
        self.assertEqual((await self.lote())["total_enfileirados"], 0)
        async with self.pool.connect() as conn:
            self.assertEqual((await conn.execute(text("SELECT status FROM email_queue ORDER BY id"))).scalars().all(),
                             ["sent", "cancelled"])


if __name__ == "__main__":
    unittest.main()
