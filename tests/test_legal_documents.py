"""HTTP, concorrência, migração e fila em schema descartável no PostgreSQL local.

RUN_LEGAL_POSTGRES_TESTS=1 habilita; não usa init_db, SMTP nem a API externa.
"""
import asyncio
import base64
import io
import os
import re
import secrets
import smtplib
import tempfile
import unittest
import uuid
import zipfile
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel, select

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.legal_protection import LegalProtectionMiddleware
from app.db.legal_migration import migrate_legal
from app.db.session import engine, get_session
from app.models.all_models import (Usuario, UserRole, Secretaria, Lote, Ingresso,
                                    ReservaIngresso)
from app.models.legal import LegalConfig, LegalDocument, LegalAcceptance, LegalInvitation, utcnow
from app.routers import legal, resgate
from app.services import email_queue
from app.services import email_service
from app.services.legal import prepare_legal_batch, digest, start_individual_communication
from app.services.legal_uploads import validate_document
from app.services.resgate_jobs import RESGATE_JOBS_DDL


def pdf(javascript=False):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    if javascript:
        writer.add_js("app.alert('unsafe')")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def docx(extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types><Override ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" /></Types>')
        archive.writestr("_rels/.rels", '<Relationships/>')
        archive.writestr("word/document.xml", '<document><body><p>Documentação</p></body></document>')
        if extra:
            archive.writestr(*extra)
    return output.getvalue()


class TestLegalUploads(unittest.TestCase):
    def test_pdf_docx_and_structural_rejections(self):
        self.assertEqual(validate_document(pdf(), "arquivo.pdf"), "pdf")
        self.assertEqual(validate_document(docx(), "arquivo.docx"), "docx")
        for content, name in [(pdf(True), "script.pdf"), (b"%PDF-fake", "fake.pdf"),
                              (pdf(), "documento.exe"), (docx(("word/vbaProject.bin", b"macro")), "macro.docx"),
                              (docx(("../escape.xml", b"<x/>")), "escape.docx"),
                              (docx(("word/_rels/document.xml.rels", b'<Relationship TargetMode="External" Target="file:///etc/passwd"/>')), "external.docx"),
                              (docx(("word/test.xml", b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><x>&y;</x>')), "entity.docx"),
                              (b"x" * (5 * 1024 * 1024 + 1), "grande.pdf")]:
            with self.subTest(name=name), self.assertRaises(Exception):
                validate_document(content, name)


@unittest.skipUnless(os.environ.get("RUN_LEGAL_POSTGRES_TESTS") == "1", "Requer PostgreSQL local opt-in")
class TestLegalDocuments(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if engine.url.host != "db":
            raise RuntimeError("Os testes legais exigem o banco Docker local db.")
        self.schema = "test_legal_" + uuid.uuid4().hex
        self.admin_pool = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        async with self.admin_pool.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.pool = create_async_engine(settings.DATABASE_URL, pool_size=6, max_overflow=0,
                                        connect_args={"server_settings": {"search_path": self.schema}})
        self.sessions = sessionmaker(self.pool, class_=AsyncSession, expire_on_commit=False)
        async with self.pool.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            await conn.execute(text("""
                CREATE TABLE email_queue (
                    id BIGSERIAL PRIMARY KEY, recipient VARCHAR NOT NULL, subject VARCHAR NOT NULL,
                    html_body TEXT NOT NULL, sender_type VARCHAR NOT NULL, qr_image BYTEA, ticket_image BYTEA,
                    status VARCHAR NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    sent_at TIMESTAMPTZ, last_error TEXT, idempotency_key VARCHAR UNIQUE
                )
            """))
            await conn.execute(text(RESGATE_JOBS_DDL))
            await migrate_legal(conn)
        async with self.sessions() as session:
            session.add(Secretaria(id=1, nome="Secretaria de teste"))
            session.add(Lote(id=1, nome="Lote de teste", quantidade_total=50, quantidade_resgatada=1))
            await session.flush()
            session.add_all([
                Usuario(id=1, cpf="super-fixture", nome="Super Administrador", role=UserRole.admin_geral, email="super@example.invalid"),
                Usuario(id=2, cpf="admin-fixture", nome="Administrador comum", role=UserRole.admin),
                Usuario(id=3, cpf="52998224725", nome="Ana Participante", email="ana@example.invalid"),
            ])
            await session.flush()
            session.add(Ingresso(id=1, usuario_id=3, lote_id=1, qr_code_token="ticket-fixture", data_resgate=utcnow() - timedelta(days=10)))
            await session.commit()
            for table in ("usuarios", "lotes", "secretarias", "ingressos"):
                await session.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}), TRUE)"))
            await session.commit()
        self.actor_id = 1
        self.application = FastAPI()
        self.application.include_router(legal.router)
        self.application.include_router(legal.admin_router)
        self.application.include_router(resgate.router)
        self.application.add_middleware(LegalProtectionMiddleware)

        async def session_dependency():
            async with self.sessions() as session:
                yield session

        async def actor_dependency():
            async with self.sessions() as session:
                return await session.get(Usuario, self.actor_id)

        self.application.dependency_overrides[get_session] = session_dependency
        self.application.dependency_overrides[get_current_user] = actor_dependency
        self.client = AsyncClient(transport=ASGITransport(app=self.application), base_url="https://test.local",
                                  headers={"X-Legal-Action": "1"})
        self.photos = tempfile.TemporaryDirectory(prefix="legal_photos_")
        self.patches = [patch.object(resgate, "FOTOS_DIR", self.photos.name),
                        patch.object(resgate, "_publicar_mudanca_reserva", return_value=None)]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.patches):
            item.stop()
        self.photos.cleanup()
        await self.pool.dispose()
        async with self.admin_pool.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin_pool.dispose()

    async def scalar(self, sql, params=None):
        async with self.sessions() as session:
            return await session.scalar(text(sql), params or {})

    async def execute(self, sql, params=None):
        async with self.sessions() as session:
            await session.execute(text(sql), params or {})
            await session.commit()

    async def upload(self, kind="terms", version="1", content=None, name="arquivo.pdf"):
        response = await self.client.post("/api/admin/legal/documents", data={"kind": kind, "title": "Documento de teste", "version": version},
                                           files={"file": (name, content or pdf())})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def publish_pair(self):
        terms = await self.upload()
        privacy = await self.upload("privacy")
        for doc in (terms, privacy):
            response = await self.client.post(f"/api/admin/legal/documents/{doc['id']}/publish")
            self.assertEqual(response.status_code, 200, response.text)
        return {"terms_id": terms["id"], "privacy_id": privacy["id"]}

    async def controls(self, **values):
        controls = dict(require_on_redemption=False, voluntary_enabled=False, communications_enabled=False, token_days=30)
        controls.update(values)
        response = await self.client.put("/api/admin/legal/settings", json=controls)
        self.assertEqual(response.status_code, 200, response.text)

    async def invitation(self):
        pair = await self.publish_pair()
        await self.controls(voluntary_enabled=True, communications_enabled=True)
        response = await self.client.post("/api/admin/legal/campaigns", json={**pair, "confirmation": "AUTORIZAR ENVIO"})
        self.assertEqual(response.status_code, 200, response.text)
        async with self.sessions() as session:
            self.assertEqual(await prepare_legal_batch(session), 1)
        body = await self.scalar("SELECT html_body FROM email_queue WHERE sender_type='legal'")
        token = re.search(r"/confirmar_termos/([A-Za-z0-9_-]{43})", body).group(1)
        return pair, token

    async def redemption(self, legal_data=None, token=None):
        token = token or secrets.token_urlsafe(32)
        async with self.sessions() as session:
            existing = await session.scalar(select(ReservaIngresso.id).where(ReservaIngresso.token == token))
            if not existing:
                session.add(ReservaIngresso(token=token, lote_id=1, expira_em=utcnow() + timedelta(minutes=5)))
                await session.commit()
        data = {"token_reserva": token, "cpf": "11144477735", "nome": "Participante Novo", "data_nascimento": "1990-01-01",
                "setor": "Teste", "secretaria_id": "1", "vinculo": "Efetivo", "telefone": "81999999999",
                "email": "novo@example.invalid", "foto_base64": "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xfffixture").decode()}
        data.update(legal_data or {})
        return await self.client.post("/api/lote/1/resgatar", data=data, headers={"Accept": "application/json"})

    async def test_defaults_and_public_unavailability(self):
        controls = (await self.client.get("/api/admin/legal/settings")).json()
        self.assertFalse(any(controls[key] for key in ("require_on_redemption", "voluntary_enabled", "communications_enabled")))
        self.assertEqual((await self.client.get("/api/legal/current")).json()["documents"], [])
        response = await self.client.put("/api/admin/legal/settings", json={"require_on_redemption": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 0)

    async def test_drafts_private_upload_download_and_duplicate_version(self):
        doc = await self.upload()
        response = await self.client.get(f"/api/legal/documents/{doc['id']}/file")
        self.assertEqual(response.status_code, 404)
        response = await self.client.get(doc["file_url"])
        self.assertEqual(response.content, pdf())
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("sandbox", response.headers["content-security-policy"])
        response = await self.client.post("/api/admin/legal/documents", data={"kind": "terms", "title": "Duplicado", "version": "1"}, files={"file": ("a.pdf", pdf())})
        self.assertEqual(response.status_code, 409)
        doc = await self.upload("privacy", content=docx(), name="documento.docx")
        response = await self.client.get(doc["file_url"])
        self.assertIn("attachment", response.headers["content-disposition"])

    async def test_reject_active_upload_and_csrf(self):
        response = await self.client.post("/api/admin/legal/documents", data={"kind": "terms", "title": "Inseguro", "version": "1"}, files={"file": ("script.pdf", pdf(True))})
        self.assertEqual(response.status_code, 400)
        response = await self.client.put("/api/admin/legal/settings", json={}, headers={"Origin": "https://evil.invalid"})
        self.assertEqual(response.status_code, 403)
        response = await self.client.put("/api/admin/legal/settings", json={}, headers={"X-Legal-Action": ""})
        self.assertEqual(response.status_code, 403)

    async def test_document_upload_from_browser_through_proxy(self):
        response = await self.client.post("/api/admin/legal/documents",
            headers={"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"},
            data={"kind": "terms", "title": "Termos de Uso v1", "version": "1.0", "notes": ""},
            files={"file": ("termos.pdf", pdf(), "application/pdf")})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["version"], "1.0")
        self.assertEqual(response.json()["status"], "draft")
        self.actor_id = 2
        response = await self.client.post("/api/admin/legal/documents",
            headers={"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"},
            data={"kind": "terms", "title": "Documento indevido", "version": "2.0"},
            files={"file": ("termos.pdf", pdf(), "application/pdf")})
        self.assertEqual(response.status_code, 403)

    async def test_only_superadmin_can_access_every_management_endpoint(self):
        self.actor_id = 2
        paths = [("GET", "documents"), ("GET", "settings"), ("GET", "dashboard"), ("GET", "history"),
                 ("GET", "acceptances"), ("GET", "communications"), ("GET", "documents/1/file"),
                 ("POST", "documents/1/publish"), ("POST", "documents/1/archive"),
                 ("POST", "documents"), ("POST", "email-preview"), ("POST", "email-test"),
                 ("POST", "campaigns"), ("POST", "communications/1/retry"), ("PUT", "settings")]
        for method, path in paths:
            response = await self.client.request(method, "/api/admin/legal/" + path)
            self.assertEqual(response.status_code, 403, path)
        for role in (UserRole.servidor, UserRole.validador, UserRole.portaria, UserRole.entregador):
            await self.execute("UPDATE usuarios SET role=:role WHERE id=2", {"role": role.value})
            self.assertEqual((await self.client.get("/api/admin/legal/documents")).status_code, 403)

    async def test_publication_versions_hashes_and_no_automatic_activation(self):
        pair = await self.publish_pair()
        before = await self.scalar("SELECT sha256 FROM legal_documents WHERE id=:id", {"id": pair["terms_id"]})
        doc = await self.upload(version="2")
        response = await self.client.post(f"/api/admin/legal/documents/{doc['id']}/publish")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(await self.scalar("SELECT status FROM legal_documents WHERE id=:id", {"id": pair["terms_id"]}), "archived")
        self.assertEqual(await self.scalar("SELECT sha256 FROM legal_documents WHERE id=:id", {"id": pair["terms_id"]}), before)
        self.assertEqual(before, digest(pdf()))
        self.assertEqual(await self.scalar("SELECT published_by FROM legal_documents WHERE id=:id", {"id": doc["id"]}), 1)
        self.assertIsNotNone(await self.scalar("SELECT legacy_cutoff FROM legal_config"))
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 0)
        self.assertFalse(await self.scalar("SELECT require_on_redemption OR voluntary_enabled OR communications_enabled FROM legal_config"))
        response = await self.client.post(f"/api/admin/legal/documents/{pair['terms_id']}/publish")
        self.assertEqual(response.status_code, 409)
        response = await self.client.get(f"/api/legal/documents/{pair['terms_id']}/file")
        self.assertEqual(response.status_code, 200)

    async def test_database_immutability_and_idempotent_migration(self):
        await self.publish_pair()
        async with self.pool.begin() as conn:
            await migrate_legal(conn)
            await migrate_legal(conn)
        for sql in ("UPDATE legal_documents SET title='alterado' WHERE id=1", "DELETE FROM legal_documents WHERE id=1",
                    "UPDATE legal_audit SET details='{}'", "DELETE FROM legal_audit"):
            with self.subTest(sql=sql), self.assertRaises(DBAPIError):
                await self.execute(sql)

    async def test_redemption_disabled_preserves_existing_flow(self):
        response = await self.redemption()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM solicitacoes_validacao"), 1)

    async def test_required_redemption_correct_version_and_idempotency(self):
        pair = await self.publish_pair()
        await self.controls(require_on_redemption=True)
        data = {"legal_accepted": "true", "legal_terms_id": str(pair["terms_id"]), "legal_privacy_id": str(pair["privacy_id"])}
        token = secrets.token_urlsafe(32)
        response = await self.redemption(data, token)
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.redemption(data, token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 1)
        self.assertEqual(await self.scalar("SELECT terms_id FROM legal_acceptances"), pair["terms_id"])
        self.assertEqual(await self.scalar("SELECT privacy_id FROM legal_acceptances"), pair["privacy_id"])
        self.assertEqual(await self.scalar("SELECT method FROM legal_acceptances"), "resgate")
        with self.assertRaises(DBAPIError):
            await self.execute("UPDATE legal_acceptances SET method='email_link'")

    async def test_required_redemption_rejects_missing_or_forged_versions(self):
        pair = await self.publish_pair()
        await self.controls(require_on_redemption=True)
        for data in ({}, {"legal_accepted": "true"}, {"legal_accepted": "true", "legal_terms_id": "999", "legal_privacy_id": str(pair["privacy_id"])}):
            response = await self.redemption(data)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM solicitacoes_validacao"), 0)
        self.assertEqual(await self.scalar("SELECT quantidade_resgatada FROM lotes WHERE id=1"), 1)

    async def test_redemption_failure_rolls_back_legal_evidence(self):
        pair = await self.publish_pair()
        await self.controls(require_on_redemption=True)
        with patch.object(resgate, "send_validation_pending_email_async", AsyncMock(return_value=False)):
            response = await self.redemption({"legal_accepted": "true", "legal_terms_id": str(pair["terms_id"]), "legal_privacy_id": str(pair["privacy_id"])})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM solicitacoes_validacao"), 0)

    async def test_confirmation_get_never_accepts_and_invalid_token(self):
        pair, token = await self.invitation()
        for _ in range(2):
            response = await self.client.get("/api/legal/confirmation", headers={"X-Legal-Token": token})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["first_name"], "Ana")
            self.assertNotIn("email", response.json())
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 0)
        for invalid in ("wrong", secrets.token_urlsafe(32)):
            response = await self.client.get("/api/legal/confirmation", headers={"X-Legal-Token": invalid})
            self.assertEqual(response.status_code, 404)
        self.assertEqual(await self.scalar("SELECT token_hash FROM legal_invitations"), digest(token))
        self.assertNotEqual(await self.scalar("SELECT token_hash FROM legal_invitations"), token)

    async def test_confirmation_post_idempotent_concurrent_and_ticket_unchanged(self):
        pair, token = await self.invitation()
        responses = await asyncio.gather(*[self.client.post("/api/legal/confirmation", headers={"X-Legal-Token": token}, json={**pair, "accepted": True}) for _ in range(2)])
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 1)
        response = await self.client.get("/api/legal/confirmation", headers={"X-Legal-Token": token})
        self.assertEqual(response.json()["status"], "confirmed")
        self.assertEqual(await self.scalar("SELECT qr_code_token FROM ingressos WHERE id=1"), "ticket-fixture")
        self.assertIsNone(await self.scalar("SELECT deleted_at FROM ingressos WHERE id=1"))

    async def test_expired_link_renewal_and_old_ticket_preserved_without_acceptance(self):
        pair, token = await self.invitation()
        await self.execute("UPDATE email_queue SET status='sent'")
        await self.execute("UPDATE legal_invitations SET expires_at=NOW()-INTERVAL '1 day'")
        response = await self.client.get("/api/legal/confirmation", headers={"X-Legal-Token": token})
        self.assertEqual(response.json()["status"], "expired")
        response = await self.client.post("/api/legal/confirmation", headers={"X-Legal-Token": token}, json={**pair, "accepted": True})
        self.assertEqual(response.status_code, 410)
        response = await self.client.post("/api/legal/confirmation/renew", headers={"X-Legal-Token": token})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.scalar("SELECT status FROM legal_invitations"), "pending")
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM ingressos WHERE deleted_at IS NULL"), 1)
        async with self.sessions() as session:
            self.assertEqual(await prepare_legal_batch(session), 1)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 2)
        response = await self.client.get("/api/legal/confirmation", headers={"X-Legal-Token": token})
        self.assertEqual(response.status_code, 404)

    async def test_confirmation_rejects_false_and_wrong_document(self):
        pair, token = await self.invitation()
        for data, status in [({**pair, "accepted": False}, 422), ({**pair, "terms_id": 999, "accepted": True}, 409)]:
            response = await self.client.post("/api/legal/confirmation", headers={"X-Legal-Token": token}, json=data)
            self.assertEqual(response.status_code, status)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 0)

    async def test_campaign_explicit_confirmation_idempotency_and_pause(self):
        pair = await self.publish_pair()
        response = await self.client.post("/api/admin/legal/campaigns", json={**pair, "confirmation": "AUTORIZAR ENVIO"})
        self.assertEqual(response.status_code, 409)
        await self.controls(voluntary_enabled=True, communications_enabled=True)
        response = await self.client.post("/api/admin/legal/campaigns", json={**pair, "confirmation": "sim"})
        self.assertEqual(response.status_code, 400)
        for _ in range(2):
            response = await self.client.post("/api/admin/legal/campaigns", json={**pair, "confirmation": "AUTORIZAR ENVIO"})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_campaigns"), 1)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_invitations"), 1)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 0)
        await self.controls(voluntary_enabled=True)
        async with self.sessions() as session:
            self.assertEqual(await prepare_legal_batch(session), 0)
        await self.controls(voluntary_enabled=True, communications_enabled=True)
        async with self.sessions() as session:
            self.assertEqual(await prepare_legal_batch(session), 1)
            self.assertEqual(await prepare_legal_batch(session), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 1)

    async def test_communication_statuses_failure_retry_and_no_token_exposure(self):
        pair, token = await self.invitation()
        response = await self.client.get("/api/admin/legal/communications")
        self.assertNotIn(token, response.text)
        self.assertNotIn(digest(token), response.text)
        self.assertEqual(response.json()["items"][0]["status"], "queued")
        response = await self.client.post("/api/admin/legal/communications/1/retry")
        self.assertEqual(response.status_code, 409)
        await self.execute("UPDATE email_queue SET status='failed', attempts=5, last_error='SMTP failure'")
        dashboard = (await self.client.get("/api/admin/legal/dashboard")).json()
        self.assertEqual(dashboard["failed"], 1)
        response = await self.client.post("/api/admin/legal/communications/1/retry")
        self.assertEqual(response.status_code, 200, response.text)
        async with self.sessions() as session:
            self.assertEqual(await prepare_legal_batch(session), 1)
            self.assertEqual(await prepare_legal_batch(session), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 2)

    async def test_individual_email_only_one_recipient_and_idempotent(self):
        await self.publish_pair()
        await self.controls(voluntary_enabled=True, communications_enabled=True)
        async with self.sessions() as session:
            actor = await session.get(Usuario, 1)
            invitation_id = await start_individual_communication(session, actor, 3,
                public_base_url="http://localhost:5173")
            repeated_id = await start_individual_communication(session, actor, 3,
                public_base_url="http://localhost:5173")
        self.assertEqual(invitation_id, repeated_id)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_invitations"), 1)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 1)
        self.assertEqual(await self.scalar("SELECT recipient FROM email_queue"), "ana@example.invalid")
        body = await self.scalar("SELECT html_body FROM email_queue")
        self.assertIn("http://localhost:5173/confirmar_termos/", body)
        self.assertIn("http://localhost:5173/termos-de-uso", body)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_audit WHERE action='campaign_authorized'"), 0)

    async def test_individual_group_only_expands_after_explicit_broadcast(self):
        pair = await self.publish_pair()
        await self.controls(voluntary_enabled=True, communications_enabled=True)
        async with self.sessions() as session:
            session.add(Usuario(id=4, cpf="fixture-four", nome="Outro participante", email="other@example.invalid"))
            await session.flush()
            session.add(Ingresso(usuario_id=4, lote_id=1, qr_code_token="ticket-four", data_resgate=utcnow()-timedelta(days=10)))
            await session.commit()
            actor = await session.get(Usuario, 1)
            await start_individual_communication(session, actor, 3)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_invitations"), 1)
        response = await self.client.post("/api/admin/legal/campaigns", json={**pair, "confirmation": "AUTORIZAR ENVIO"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_invitations"), 2)
        response = await self.client.post("/api/admin/legal/campaigns", json={**pair, "confirmation": "AUTORIZAR ENVIO"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_invitations"), 2)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 1)

    async def test_individual_email_preserves_disabled_controls_and_permissions(self):
        await self.publish_pair()
        async with self.sessions() as session:
            actor = await session.get(Usuario, 1)
            with self.assertRaises(HTTPException) as error:
                await start_individual_communication(session, actor, 3)
            self.assertEqual(error.exception.status_code, 409)
        await self.controls(voluntary_enabled=True, communications_enabled=True)
        async with self.sessions() as session:
            actor = await session.get(Usuario, 2)
            with self.assertRaises(HTTPException) as error:
                await start_individual_communication(session, actor, 3)
            self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 0)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_campaigns"), 0)

    async def test_email_preview_and_test_recipient_are_restricted(self):
        pair = await self.publish_pair()
        response = await self.client.post("/api/admin/legal/email-preview", json=pair)
        self.assertEqual(response.status_code, 200)
        self.assertIn("#confirmacao-de-exemplo", response.json()["html"])
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 0)
        await self.controls(communications_enabled=True)
        response = await self.client.post("/api/admin/legal/email-test", json={**pair, "email": "attacker@example.invalid"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.scalar("SELECT recipient FROM email_queue"), "super@example.invalid")
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_invitations"), 0)

    async def test_archive_requires_disabling_controls(self):
        pair = await self.publish_pair()
        await self.controls(require_on_redemption=True)
        response = await self.client.post(f"/api/admin/legal/documents/{pair['terms_id']}/archive")
        self.assertEqual(response.status_code, 409)

    async def run_email_worker(self, sender, max_idle=100):
        stop = asyncio.Event()
        idle = 0

        async def fast_wait(event, seconds):
            nonlocal idle
            idle += 1
            # Avança somente o relógio das próximas tentativas do schema de teste.
            await self.execute("UPDATE email_queue SET next_attempt_at=NOW() WHERE status='queued'")
            if idle >= max_idle:
                stop.set()
            await asyncio.sleep(0.005)

        def fake_smtp(*args, **kwargs):
            return sender(stop, *args, **kwargs)

        with patch.object(email_queue, "engine", self.pool), patch.object(email_queue, "async_session", self.sessions), \
             patch.object(email_queue, "_LEADER_LOCK_ID", int(uuid.uuid4().hex[:12], 16)), \
             patch.object(email_queue, "_wait_or_stop", fast_wait), \
             patch.object(email_service, "_send_smtp_email_sync", fake_smtp):
            await asyncio.wait_for(email_queue.email_queue_worker(stop), timeout=15)

    async def test_worker_retries_known_failure_without_duplicate_message(self):
        await self.invitation()
        calls = []

        def sender(stop, *args, **kwargs):
            calls.append(kwargs["queue_id"])
            if len(calls) == 1:
                raise smtplib.SMTPDataError(451, b"retry later")
            stop.set()
            return True

        await self.run_email_worker(sender)
        self.assertEqual(calls, [1, 1])
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM email_queue"), 1)
        self.assertEqual(await self.scalar("SELECT status FROM email_queue"), "sent")
        self.assertEqual(await self.scalar("SELECT attempts FROM email_queue"), 2)
        self.assertNotIn("confirmar_termos", await self.scalar("SELECT html_body FROM email_queue"))
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM legal_acceptances"), 0)

    async def test_worker_records_terminal_failure_after_five_attempts(self):
        await self.invitation()
        calls = []

        def sender(stop, *args, **kwargs):
            calls.append(kwargs["queue_id"])
            if len(calls) >= 5:
                stop.set()
            raise smtplib.SMTPDataError(451, b"temporary provider failure")

        await self.run_email_worker(sender)
        self.assertEqual(len(calls), 5)
        self.assertEqual(await self.scalar("SELECT status FROM email_queue"), "failed")
        self.assertEqual(await self.scalar("SELECT attempts FROM email_queue"), 5)

    async def test_worker_pauses_legal_email_when_control_disabled(self):
        await self.invitation()
        await self.controls(voluntary_enabled=True)
        sender = unittest.mock.Mock(side_effect=AssertionError("SMTP não deveria ser chamado"))
        await self.run_email_worker(sender, max_idle=1)
        sender.assert_not_called()
        self.assertEqual(await self.scalar("SELECT status FROM email_queue"), "queued")

    async def test_worker_holds_ambiguous_delivery_and_never_retries_automatically(self):
        await self.invitation()

        def sender(stop, *args, **kwargs):
            stop.set()
            raise smtplib.SMTPServerDisconnected("connection lost after DATA")

        await self.run_email_worker(sender)
        self.assertEqual(await self.scalar("SELECT status FROM email_queue"), "uncertain")
        sender = unittest.mock.Mock(side_effect=AssertionError("Envio incerto não pode ser repetido"))
        await self.run_email_worker(sender, max_idle=1)
        sender.assert_not_called()
        response = await self.client.post("/api/admin/legal/communications/1/retry")
        self.assertEqual(response.status_code, 409)

    async def test_worker_does_not_send_an_expired_link(self):
        await self.invitation()
        await self.execute("UPDATE legal_invitations SET expires_at=NOW()-INTERVAL '1 day'")
        sender = unittest.mock.Mock(side_effect=AssertionError("Link expirado não deve ser enviado"))
        await self.run_email_worker(sender, max_idle=1)
        sender.assert_not_called()
        self.assertEqual(await self.scalar("SELECT status FROM email_queue"), "failed")

    async def test_token_page_headers_block_external_resources_and_redact_access_log(self):
        scope = {"type": "http", "path": "/confirmar_termos/" + "x" * 43,
                 "raw_path": b"/confirmar_termos/" + b"x" * 43, "query_string": b"", "headers": []}
        captured = []

        async def application(scope, receive, send):
            self.assertIn("x" * 43, scope["path"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def send(message):
            if message["type"] == "http.response.start":
                captured.append((scope["path"], dict(message["headers"])))

        await LegalProtectionMiddleware(application)(scope, None, send)
        self.assertEqual(captured[0][0], "/confirmar_termos/[redacted]")
        self.assertEqual(captured[0][1][b"referrer-policy"], b"no-referrer")
        self.assertIn(b"connect-src 'self'", captured[0][1][b"content-security-policy"])

    async def test_rate_limit_persists_invalid_attempts(self):
        for _ in range(30):
            response = await self.client.get("/api/legal/confirmation", headers={"X-Legal-Token": "wrong"})
            self.assertEqual(response.status_code, 404)
        response = await self.client.get("/api/legal/confirmation", headers={"X-Legal-Token": "wrong"})
        self.assertEqual(response.status_code, 429)


if __name__ == "__main__":
    unittest.main()
