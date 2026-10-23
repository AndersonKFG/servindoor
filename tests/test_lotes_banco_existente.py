"""Testes no banco local existente, com rollback de todas as escritas de teste.

Ative RUN_EXISTING_DB_TESTS=1 explicitamente. Não chama init_db, não envia e-mails,
não altera sequências e preserva registros reais, inclusive o controle de portaria.
"""
import json
import os
import secrets
import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.deps import get_current_user
from app.db.session import engine, get_session, migrar_fuso_lotes
from app.models.all_models import Lote, RateLimitTentativa, Usuario, UserRole
from app.routers import admin, avulsos, portaria, public


@unittest.skipUnless(os.environ.get('RUN_EXISTING_DB_TESTS') == '1', 'Requer RUN_EXISTING_DB_TESTS=1')
class TestLotesBancoExistente(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await engine.connect()
        self.outer = await self.conn.begin()
        await self.conn.execute(text("SET LOCAL TIME ZONE 'America/Sao_Paulo'"))
        self.antes = (await self.conn.execute(text("SELECT id, nome, oculto, data_abertura::text, data_fechamento::text FROM lotes ORDER BY id"))).mappings().all()
        self.portaria_antes = (await self.conn.execute(text("SELECT id, liberada, alterado_por_id, alterado_em::text FROM controle_presenca ORDER BY id"))).mappings().all()
        self.tipo_antes = await self.conn.scalar(text("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='lotes' AND column_name='data_abertura'"))
        await migrar_fuso_lotes(self.conn)
        self.session = AsyncSession(bind=self.conn, expire_on_commit=False, join_transaction_mode='create_savepoint')
        self.proximo_id = -1_000_000_000 - secrets.randbelow(100_000_000)

        def ids_de_teste(session, flush_context, instances):
            # Evita nextval: sequências PostgreSQL não voltam com rollback.
            for objeto in session.new:
                if isinstance(objeto, (Lote, RateLimitTentativa)) and objeto.id is None:
                    objeto.id = self.proximo_id
                    self.proximo_id -= 1
        event.listen(self.session.sync_session, 'before_flush', ids_de_teste)

        async def sessao():
            yield self.session
        self.usuario = Usuario(id=46, cpf='fixture', nome='Operador de teste local', role=UserRole.admin_geral)
        async def usuario():
            return self.usuario
        self.app = FastAPI()
        for router in (admin.router, avulsos.router, portaria.router, public.router):
            self.app.include_router(router)
        self.app.dependency_overrides[get_session] = sessao
        self.app.dependency_overrides[get_current_user] = usuario
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url='https://teste-local')
        public.invalidar_cache_live_status()

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.session.close()
        await self.outer.rollback()
        # Confirma no banco real que os registros e a liberação foram preservados.
        depois = (await self.conn.execute(text("SELECT id, nome, oculto, data_abertura::text, data_fechamento::text FROM lotes ORDER BY id"))).mappings().all()
        portaria_depois = (await self.conn.execute(text("SELECT id, liberada, alterado_por_id, alterado_em::text FROM controle_presenca ORDER BY id"))).mappings().all()
        self.assertEqual(self.antes, depois)
        self.assertEqual(self.portaria_antes, portaria_depois)
        await self.conn.close()
        await engine.dispose()
        public.invalidar_cache_live_status()

    async def criar(self, oculto=True):
        config = {'temporizado': False, 'exige_validacao': False, 'campos': {
            'setor': {'modo': 'fixo', 'valor': 'Setor do teste com banco existente'}}}
        form = {'nome': 'TESTE TRANSACIONAL - NAO PERSISTIR', 'quantidade_total': '2',
                'data_abertura': '2026-10-22T19:30', 'data_fechamento': '2026-12-30T23:00',
                'secretaria_id': '0', 'ativo': 'on', 'oculto': str(oculto).lower()}
        if oculto:
            form.update(avulso_config=json.dumps(config), acesso_senha='Ab#123')
        return await self.client.post('/api/admin/lotes', data=form)

    async def test_migracao_preserva_horarios_locais_e_e_idempotente(self):
        tipos = (await self.conn.execute(text("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='lotes' AND column_name IN ('data_abertura','data_fechamento','deleted_at')"))).scalars().all()
        self.assertEqual(set(tipos), {'timestamp with time zone'})
        for antes in self.antes:
            lote = await self.session.get(Lote, antes['id'])
            if self.tipo_antes == 'timestamp without time zone' and antes['data_abertura']:
                self.assertEqual(admin._horarios_lote_para_formulario(lote)['data_abertura_input'],
                                 datetime.fromisoformat(antes['data_abertura']).strftime('%Y-%m-%dT%H:%M'))
        instantes = (await self.conn.execute(text('SELECT id, data_abertura, data_fechamento, deleted_at FROM lotes ORDER BY id'))).all()
        await migrar_fuso_lotes(self.conn)
        self.assertEqual(instantes, (await self.conn.execute(text('SELECT id, data_abertura, data_fechamento, deleted_at FROM lotes ORDER BY id'))).all())

    async def test_cadastro_oculto_persiste_opcoes_e_nao_vaza_na_home(self):
        response = await self.criar()
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertTrue(data['oculto'])
        self.assertEqual(data['data_abertura_input'], '2026-10-22T19:30')
        lote = await self.session.get(Lote, data['id'])
        self.assertTrue(lote.oculto)
        self.assertIsNotNone(lote.acesso_token)
        self.assertIsNotNone(lote.acesso_senha_hash)
        self.assertFalse(json.loads(lote.avulso_config)['temporizado'])
        self.assertEqual(json.loads(lote.avulso_config)['campos']['setor']['modo'], 'fixo')
        self.assertIsNone(await public.obter_lote_relevante(self.session, datetime.now(timezone.utc), lote.id))
        status = await self.client.get(f'/api/lote/live-status?lote_id={lote.id}')
        self.assertNotIn('TESTE TRANSACIONAL', status.text)
        denied = await self.client.post(f'/api/avulso/{lote.acesso_token}/acesso', json={})
        self.assertEqual(denied.status_code, 403)
        allowed = await self.client.post(f'/api/avulso/{lote.acesso_token}/acesso', json={'senha': 'Ab#123'})
        self.assertEqual(allowed.status_code, 200)

    async def test_cadastro_publico_tambem_preserva_fuso_apos_releitura(self):
        response = await self.criar(oculto=False)
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertFalse(data['oculto'])
        self.session.expunge_all()
        lote = await self.session.get(Lote, data['id'])
        self.assertEqual(lote.data_abertura.isoformat(), '2026-10-22T22:30:00+00:00')
        self.assertEqual(admin._horarios_lote_para_formulario(lote)['data_abertura_input'], '2026-10-22T19:30')
        self.assertEqual(admin._horarios_lote_para_formulario(lote)['data_fechamento_input'], '2026-12-30T23:00')

    async def test_botao_portaria_preserva_autorizacao_e_persistencia(self):
        response = await self.client.get('/api/portaria/liberacao-presenca')
        self.assertEqual(response.status_code, 200)
        estado = response.json()['liberada']
        response = await self.client.put('/api/portaria/liberacao-presenca', json={'liberada': not estado})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.client.get('/api/portaria/liberacao-presenca')).json()['liberada'], not estado)
        self.usuario = Usuario(id=46, cpf='fixture', nome='Admin teste', role=UserRole.admin)
        response = await self.client.put('/api/portaria/liberacao-presenca', json={'liberada': estado})
        self.assertEqual(response.status_code, 403)
