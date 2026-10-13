"""Auditoria em esquema PostgreSQL descartável e fotos em diretório temporário."""

import argparse
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db import session as app_db
from tools.carga import conferir_resgates as audit_tool

ADMIN_ENGINE = app_db.engine


class TestConferirArquivos(unittest.TestCase):
    def test_arquivo_ausente_formato_invalido_e_traversal(self):
        with tempfile.TemporaryDirectory(prefix="load_audit_photo_") as directory:
            root = Path(directory).resolve()
            (root / "photo.jpg").write_bytes(b"\xff\xd8\xffvalid-test")
            (root / "invalid.jpg").write_bytes(b"not-a-jpeg")
            self.assertEqual(audit_tool._photo_state("/static/uploads/fotos/photo.jpg", root), "presente_jpeg")
            self.assertEqual(audit_tool._photo_state("/static/uploads/fotos/missing.jpg", root), "ausente_ou_vazio")
            self.assertEqual(audit_tool._photo_state("/static/uploads/fotos/invalid.jpg", root), "formato_invalido")
            self.assertEqual(audit_tool._photo_state("/static/uploads/fotos/../../outside.jpg", root), "caminho_invalido")
            self.assertEqual(audit_tool._photo_state("https://example.invalid/photo.jpg", root), "caminho_invalido")

    def test_identificacao_rejeita_entrada_fora_do_escopo(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            audit_tool._run_id("run' OR 1=1")


class TestConferirResgates(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = f"test_load_audit_{uuid.uuid4().hex}"
        async with ADMIN_ENGINE.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.pool = create_async_engine(settings.DATABASE_URL, connect_args={"server_settings": {"search_path": self.schema}})
        self.sessions = sessionmaker(self.pool, class_=AsyncSession, expire_on_commit=False)
        self.directory = tempfile.TemporaryDirectory(prefix="load_audit_fixture_")
        self.root = Path(self.directory.name)
        photos = self.root / "app/static/uploads/fotos"
        photos.mkdir(parents=True)
        self.photo = photos / "fixture.jpg"
        self.photo.write_bytes(b"\xff\xd8\xfffixture-test")
        statements = [
            "CREATE TABLE lotes (id INTEGER PRIMARY KEY, quantidade_total INTEGER, quantidade_resgatada INTEGER)",
            "CREATE TABLE reservas_ingressos (id INTEGER PRIMARY KEY, lote_id INTEGER, status VARCHAR, utilizada BOOLEAN, expira_em TIMESTAMPTZ, criada_em TIMESTAMPTZ, device_fingerprint VARCHAR)",
            "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, cpf VARCHAR, foto_rosto_url VARCHAR, setor VARCHAR)",
            "CREATE TABLE solicitacoes_validacao (id INTEGER PRIMARY KEY, reserva_id INTEGER, usuario_id INTEGER, lote_id INTEGER, status VARCHAR)",
            "CREATE TABLE resgate_jobs (id INTEGER PRIMARY KEY, solicitacao_id INTEGER, status VARCHAR)",
            "CREATE TABLE email_queue (id INTEGER PRIMARY KEY, status VARCHAR, html_body VARCHAR)",
            "INSERT INTO lotes VALUES (1, 2, 1)",
            "INSERT INTO reservas_ingressos VALUES (1, 1, 'concluida', TRUE, NOW() + INTERVAL '1 minute', NOW() - INTERVAL '1 minute', 'loadtest_fixture_run_1')",
            "INSERT INTO usuarios VALUES (1, 'synthetic-cpf', '/static/uploads/fotos/fixture.jpg', 'TESTE_CARGA_fixture_run')",
            "INSERT INTO solicitacoes_validacao VALUES (1, 1, 1, 1, 'pendente_analise')",
            "INSERT INTO resgate_jobs VALUES (1, 1, 'skipped')",
            "INSERT INTO email_queue VALUES (1, 'queued', '<p>TESTE CARGA fixture_run VU 1</p>')",
        ]
        async with self.pool.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
        self.patches = [patch.object(app_db, "engine", self.pool), patch.object(app_db, "async_session", self.sessions),
                        patch.object(audit_tool, "PROJECT_ROOT", self.root)]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()
        await self.pool.dispose()
        async with ADMIN_ENGINE.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await ADMIN_ENGINE.dispose()
        self.directory.cleanup()

    async def test_snapshot_somente_leitura_e_contagens_conferem(self):
        queries = []
        def capture(connection, cursor, statement, parameters, context, executemany):
            queries.append(statement)
        event.listen(self.pool.sync_engine, "before_cursor_execute", capture)
        report = await audit_tool.audit("fixture_run", 1, 1)
        self.assertTrue(report["consistente"])
        self.assertEqual(report["solicitacoes_deste_teste"], 1)
        self.assertEqual(report["fotos"], {"presente_jpeg": 1})
        self.assertEqual(report["emails"], {"queued": 1})
        self.assertIn("READ ONLY", queries[0])
        self.assertTrue(all(query.lstrip().startswith(("SELECT", "SET")) for query in queries))
        self.assertNotIn("synthetic-cpf", str(report))
        self.assertNotIn("fixture.jpg", str(report))

    async def test_detecta_duplicacao_foto_ausente_e_lotacao_excedida(self):
        async with self.pool.begin() as connection:
            await connection.execute(text("INSERT INTO solicitacoes_validacao VALUES (2, 1, 1, 1, 'pendente_analise')"))
            await connection.execute(text("UPDATE lotes SET quantidade_resgatada=3 WHERE id=1"))
        self.photo.unlink()
        report = await audit_tool.audit("fixture_run", 1, 1)
        self.assertFalse(report["consistente"])
        for key in ["cpfs_unicos", "uma_solicitacao_por_reserva", "fotos_unicas", "fotos_presentes_jpeg",
                    "contador_nao_excede_lotacao", "um_email_por_cadastro", "cadastros_conferem_com_resumo_http"]:
            self.assertFalse(report["verificacoes"][key], key)

    async def test_outro_teste_nao_e_incluido(self):
        report = await audit_tool.audit("outro_teste", 1)
        self.assertEqual(report["solicitacoes_deste_teste"], 0)
        self.assertEqual(report["reservas_deste_teste"], {})
        self.assertEqual(report["emails"], {})
        self.assertFalse(report["consistente"])


if __name__ == "__main__":
    unittest.main()
