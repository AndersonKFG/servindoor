"""PostgreSQL real em schema descartável. Ative RUN_POSTGRES_TESTS=1.

O schema é criado pela própria suíte; init_db e dados da aplicação não são tocados.
"""
import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest import skipUnless
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select, func

from app.db.session import engine as application_engine, connect_args, migrar_lotes_ocultos
from app.models.all_models import BackupLote, Ingresso, Lote
from app.routers import resgate
from app.core.security import get_password_hash
import test_lotes_ocultos as fixtures


@skipUnless(os.environ.get('RUN_POSTGRES_TESTS') == '1', 'Ative RUN_POSTGRES_TESTS=1 para PostgreSQL isolado')
class TestLotesOcultosPostgres(fixtures.TestLotesOcultos):
    async def criar_engine(self):
        self.schema = 'test_avulso_' + uuid.uuid4().hex
        self.root = create_async_engine(application_engine.url, connect_args=connect_args)
        async with self.root.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.addAsyncCleanup(self.limpar_schema)
        return create_async_engine(application_engine.url, connect_args={
            **connect_args, 'server_settings': {'search_path': self.schema}})

    async def limpar_schema(self):
        async with self.root.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.root.dispose()

    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with self.engine.begin() as conn:
            await migrar_lotes_ocultos(conn)
            for tabela in ('usuarios', 'lotes', 'secretarias'):
                await conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), (SELECT MAX(id) FROM {tabela}), TRUE)"))
            await conn.execute(text("CREATE UNIQUE INDEX uq_avulso_usuario_ingresso ON ingressos (usuario_id) WHERE deleted_at IS NULL"))
            await conn.execute(text("CREATE UNIQUE INDEX uq_avulso_usuario_solicitacao ON solicitacoes_validacao (usuario_id) WHERE status IN ('pendente_analise', 'aprovado')"))

    async def test_ultima_vaga_concorrente_sem_fila_local(self):
        await self.configurar(temporizado=False, exige_validacao=False)
        async with self.sessions() as s:
            lote = await s.get(Lote, 1)
            lote.quantidade_total = 1
            await s.commit()
        await self.autorizar()
        a, b = await self.iniciar(), await self.iniciar()

        @asynccontextmanager
        async def apenas_banco(session, request, lote_id, criar):
            try:
                yield
            finally:
                await session.close()

        # Remove a fila do processo para testar a garantia FOR UPDATE entre workers.
        with patch.object(resgate, '_transacao_capacidade_reserva', apenas_banco):
            respostas = await asyncio.gather(self.enviar(a), self.enviar(b, cpf='12345678909'), return_exceptions=True)
        for resposta in respostas:
            if isinstance(resposta, BaseException):
                raise resposta
        self.assertEqual(sorted(r.status_code for r in respostas), [200, 400])
        async with self.sessions() as s:
            self.assertEqual((await s.get(Lote, 1)).quantidade_resgatada, 1)
            self.assertEqual(await s.scalar(select(func.count(Ingresso.id))), 1)
        self.ticket_email.assert_awaited_once()

    async def test_imutabilidade_no_banco_e_migracao_idempotente(self):
        async with self.engine.begin() as conn:
            await migrar_lotes_ocultos(conn)
            await migrar_lotes_ocultos(conn)
        with self.assertRaises(DBAPIError):
            async with self.engine.begin() as conn:
                await conn.execute(text('UPDATE lotes SET oculto=FALSE WHERE id=1'))
        async with self.sessions() as s:
            self.assertTrue((await s.get(Lote, 1)).oculto)

    async def test_restauracao_preserva_configuracao_e_troca_link(self):
        await self.configurar(temporizado=False, exige_validacao=False)
        await self.autorizar()
        await self.iniciar()
        self.superadmin.senha_hash = get_password_hash('senha-admin-teste')
        async with self.sessions() as s:
            lote = await s.get(Lote, 1)
            lote.deleted_at = datetime.now(timezone.utc)
            lote.ativo = False
            s.add(BackupLote(id=1, lote_id=1, lote_nome=lote.nome, dados_json=json.dumps({'ingressos': []}),
                            expira_em=datetime.now(timezone.utc)))
            await s.commit()
        with patch('app.core.http_protection.settings.GATEKEEPER_ENABLED', False):
            resposta = await self.client.post('/api/admin/lotes/backups/1/restaurar', json={'senha': 'senha-admin-teste'})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        async with self.sessions() as s:
            lote = await s.get(Lote, 1)
            self.assertTrue(lote.oculto)
            self.assertNotEqual(lote.acesso_token, 'x' * 43)
            self.assertFalse(json.loads(lote.avulso_config)['temporizado'])
            self.assertEqual(lote.acesso_versao, 2)
