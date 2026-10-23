"""Contratos dos lotes ocultos em banco isolado; sem SMTP ou API externa."""
import json
import os
import tempfile
import uuid
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from sqlmodel import SQLModel, select, func

from app.core.deps import get_current_user
from app.core.http_protection import HttpProtectionMiddleware
from app.db.session import get_session
from app.models.all_models import Lote, Usuario, Secretaria, ReservaIngresso, SolicitacaoValidacao, Ingresso, UserRole
from app.routers import admin, avulsos, public, resgate, validacoes
from app.services.lotes_ocultos import configuracao, validar_configuracao, criar_autorizacao, revogar_acessos, senha_hash
from app.core.security import get_password_hash


class TestLotesOcultos(unittest.IsolatedAsyncioTestCase):
    async def criar_engine(self):
        return create_async_engine("sqlite+aiosqlite://")

    async def asyncSetUp(self):
        self.engine = await self.criar_engine()
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            await conn.execute(text("CREATE TABLE resgate_jobs (solicitacao_id INTEGER, job_type VARCHAR, status VARCHAR)"))
            await conn.execute(text("CREATE TABLE email_queue (id INTEGER PRIMARY KEY, idempotency_key VARCHAR UNIQUE, created_at TIMESTAMP)"))
        self.sessions = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.app = FastAPI()
        for router in (admin.router, avulsos.router, public.router, resgate.router, validacoes.router):
            self.app.include_router(router)
        self.app.add_middleware(HttpProtectionMiddleware)
        self.superadmin = Usuario(id=1, cpf="11144477735", nome="Super", role=UserRole.admin_geral)
        self.user = self.superadmin
        async def session():
            async with self.sessions() as s:
                yield s
        self.app.dependency_overrides[get_session] = session
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        async with self.sessions() as s:
            s.add_all([Secretaria(id=1, nome="Secretaria teste"),
                self.superadmin,
                Lote(id=1, nome="Oculto", quantidade_total=2, ativo=True,
                     oculto=True, acesso_token="x" * 43),
                Lote(id=2, nome="Público", quantidade_total=10, ativo=True)])
            await s.commit()
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="https://test")
        self.pending_email = patch.object(resgate, "send_validation_pending_email_async", AsyncMock(return_value=True)).start()
        self.ticket_email = patch.object(resgate, "send_ticket_email_async", AsyncMock(return_value=True)).start()
        self.jobs = patch.object(resgate, "enqueue_external_validation", AsyncMock()).start()
        patch.object(resgate, "get_external_validation_status", AsyncMock(return_value=None)).start()
        patch.object(resgate, "_preparar_foto_resgate", AsyncMock(return_value=(
            "/foto-teste", os.path.join(tempfile.gettempdir(), 'avulso-' + uuid.uuid4().hex)))).start()
        self.addCleanup(patch.stopall)

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()

    async def configurar(self, **config):
        async with self.sessions() as s:
            lote = await s.get(Lote, 1)
            lote.avulso_config = await validar_configuracao(config, s)
            await s.commit()

    async def autorizar(self):
        response = await self.client.post('/api/avulso/' + 'x' * 43 + '/acesso', json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.headers['X-Lote-Acesso'] = response.json()['autorizacao']

    async def iniciar(self):
        response = await self.client.post('/api/avulso/' + 'x' * 43 + '/iniciar')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['token_reserva']

    async def enviar(self, token, cpf="52998224725", **changes):
        form = dict(token_reserva=token, cpf=cpf, nome="Participante Teste", data_nascimento="1990-01-01",
                    setor="Setor teste", secretaria_id="1", vinculo="Efetivo",
                    telefone="81999990000", email="teste@example.invalid", foto_base64="foto-obrigatoria")
        form.update(changes)
        return await self.client.post('/api/avulso/' + 'x' * 43 + '/resgatar', data=form)

    async def test_home_nunca_seleciona_oculto_nem_por_id(self):
        async with self.sessions() as s:
            agora = datetime.now(timezone.utc)
            lote = await public.obter_lote_relevante(s, agora)
            self.assertEqual(lote.id, 2)
            self.assertIsNone(await public.obter_lote_relevante(s, agora, lote_id=1))
            self.assertEqual(await public.coletar_status_lote_para_sse(s, 1), {"oculto": True})
        for endpoint in ('live-status', 'stream'):
            response = await self.client.get(f'/api/lote/{endpoint}?lote_id=1') if endpoint != 'stream' else None
            if response:
                self.assertNotIn('Oculto', response.text)

    async def test_sem_cronometro_nao_reserva_e_envio_emite_uma_vez(self):
        await self.configurar(temporizado=False, exige_validacao=False)
        await self.autorizar()
        token = await self.iniciar()
        async with self.sessions() as s:
            reserva = (await s.execute(select(ReservaIngresso))).scalars().one()
            self.assertEqual(reserva.status, 'rascunho')
            self.assertEqual((await s.get(Lote, 1)).quantidade_resgatada, 0)
            reserva.expira_em = datetime.now(timezone.utc) - timedelta(days=1)
            await s.commit()  # Rascunho sem cronômetro não expira como reserva.
        response = await self.enviar(token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'aprovado')
        response = await self.enviar(token)
        self.assertEqual(response.status_code, 200, response.text)
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(select(func.count(Ingresso.id))), 1)
            self.assertEqual((await s.get(Lote, 1)).quantidade_resgatada, 1)
        self.ticket_email.assert_awaited_once()
        self.jobs.assert_not_awaited()

    async def test_rotacao_invalida_link_autorizacao_e_formulario(self):
        await self.autorizar()
        token = await self.iniciar()
        async with self.sessions() as s:
            lote = await s.get(Lote, 1)
            await revogar_acessos(lote, s, novo_link=True)
            await s.commit()
            novo = lote.acesso_token
        old = await self.enviar(token)
        self.assertEqual(old.status_code, 404)
        invalid = await self.client.get(f'/api/avulso/{novo}/status')
        self.assertEqual(invalid.status_code, 403)
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(select(ReservaIngresso.status)), 'cancelada')

    async def test_travados_e_obrigatoriedade_sao_validados_no_servidor(self):
        await self.configurar(temporizado=False, campos={"setor": {"modo": "fixo", "valor": "Gabinete"}})
        await self.autorizar()
        token = await self.iniciar()
        for changes in ({"setor": "Adulterado"}, {"setor": "Gabinete", "nome": " "},
                        {"setor": "Gabinete", "email": "inválido"}, {"setor": "Gabinete", "foto_base64": ""}):
            response = await self.enviar(token, **changes)
            self.assertEqual(response.status_code, 400, response.text)
        response = await self.enviar(token, setor="Gabinete")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'pendente_analise')
        self.pending_email.assert_awaited_once()

    async def test_senha_e_rate_limit_persistentes(self):
        async with self.sessions() as s:
            lote = await s.get(Lote, 1)
            lote.acesso_senha_hash = senha_hash("Ab#123")
            await s.commit()
        base = '/api/avulso/' + 'x' * 43 + '/acesso'
        for _ in range(10):
            response = await self.client.post(base, json={"senha": "errada"})
            self.assertEqual(response.status_code, 403)
        response = await self.client.post(base, json={"senha": "Ab#123"})
        self.assertEqual(response.status_code, 429)

    async def test_admin_comum_le_mas_nao_aprova_avulso(self):
        self.user = Usuario(id=9, cpf="123", nome="Admin", role=UserRole.admin, secretarias_validador="1")
        async with self.sessions() as s:
            s.add(Usuario(id=2, cpf="52998224725", nome="Participante"))
            s.add(SolicitacaoValidacao(id=1, usuario_id=2, lote_id=1, secretaria_id=1))
            await s.commit()
        # Middleware exige o PIN geral para a administração, mesmo com lote autorizado.
        with patch('app.core.http_protection.settings.GATEKEEPER_ENABLED', False):
            lista = await self.client.get('/api/admin/validacoes')
            self.assertEqual(lista.status_code, 200, lista.text)
            self.assertFalse(lista.json()['solicitacoes'][0]['pode_gerenciar'])
            for acao in ('aprovar', 'rejeitar'):
                response = await self.client.post(f'/api/admin/validacoes/1/{acao}', json={})
                self.assertEqual(response.status_code, 403)

    async def test_limite_cronometro_e_cpf_duplicado(self):
        await self.configurar(temporizado=True, exige_validacao=False)
        await self.autorizar()
        primeiro = await self.iniciar()
        segundo = await self.iniciar()
        response = await self.client.post('/api/avulso/' + 'x' * 43 + '/iniciar')
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.enviar(primeiro)).status_code, 200)
        response = await self.enviar(segundo)
        self.assertEqual(response.status_code, 409, response.text)
        self.ticket_email.assert_awaited_once()

    async def test_sem_prazo_nao_ultrapassa_capacidade(self):
        await self.configurar(temporizado=False, exige_validacao=False)
        await self.autorizar()
        tokens = [await self.iniciar() for _ in range(3)]
        for token, cpf in zip(tokens, ['52998224725', '12345678909', '93541134780']):
            response = await self.enviar(token, cpf=cpf)
        self.assertEqual(response.status_code, 400, response.text)
        async with self.sessions() as s:
            self.assertEqual((await s.get(Lote, 1)).quantidade_resgatada, 2)
            self.assertEqual(await s.scalar(select(func.count(Ingresso.id))), 2)

    async def test_edicao_preserva_pendencia_mas_invalida_formularios(self):
        await self.configurar(temporizado=False)
        await self.autorizar()
        enviado = await self.iniciar()
        self.assertEqual((await self.enviar(enviado)).status_code, 200)
        aberto = await self.iniciar()
        with patch('app.core.http_protection.settings.GATEKEEPER_ENABLED', False):
            response = await self.client.post('/admin/lote/1/editar', data={
                'nome': 'Oculto editado', 'quantidade_total': '2', 'data_abertura': '2026-01-01T00:00',
                'ativo': 'on', 'secretaria_id': '0',
                'avulso_config': json.dumps({'temporizado': False, 'exige_validacao': False})})
            self.assertEqual(response.status_code, 303, response.text)
            response = await self.client.post('/admin/lote/1/editar', data={
                'nome': 'Conversão proibida', 'quantidade_total': '2', 'data_abertura': '2026-01-01T00:00',
                'oculto': 'false'})
            self.assertEqual(response.status_code, 400)
        self.assertEqual((await self.enviar(aberto, cpf='12345678909')).status_code, 403)
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(select(SolicitacaoValidacao.status)), 'pendente_analise')
            self.assertEqual(await s.scalar(select(func.count(Ingresso.id))), 0)

    async def test_regenerar_exige_superadmin_e_senha_atual(self):
        self.superadmin.senha_hash = get_password_hash('senha-admin-teste')
        await self.autorizar()
        with patch('app.core.http_protection.settings.GATEKEEPER_ENABLED', False):
            self.user = Usuario(id=9, cpf='123', nome='Admin', role=UserRole.admin)
            response = await self.client.post('/api/admin/lote/1/regenerar-link', json={'senha': 'senha-admin-teste'})
            self.assertEqual(response.status_code, 403)
            lista = await self.client.get('/api/lotes-admin')
            oculto = next(l['model'] for l in lista.json()['lotes'] if l['model']['id'] == 1)
            self.assertIsNone(oculto['acesso_link'])
            self.assertIsNone(oculto['avulso_config'])
            self.user = self.superadmin
            response = await self.client.post('/api/admin/lote/1/regenerar-link', json={'senha': 'errada'})
            self.assertEqual(response.status_code, 401)
            response = await self.client.post('/api/admin/lote/1/regenerar-link', json={'senha': 'senha-admin-teste'})
            self.assertEqual(response.status_code, 200, response.text)
        antigo = await self.client.get('/api/avulso/' + 'x' * 43 + '/status')
        self.assertEqual(antigo.status_code, 404)

    async def test_trocar_senha_invalida_acesso_e_aceita_simbolos(self):
        await self.autorizar()
        token = await self.iniciar()
        with patch('app.core.http_protection.settings.GATEKEEPER_ENABLED', False):
            response = await self.client.post('/admin/lote/1/editar', data={
                'nome': 'Oculto', 'quantidade_total': '2', 'data_abertura': '2026-01-01T00:00',
                'ativo': 'on', 'secretaria_id': '0', 'acesso_senha': '#&Aa12'})
            self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual((await self.enviar(token)).status_code, 403)
        base = '/api/avulso/' + 'x' * 43 + '/acesso'
        response = await self.client.post(base, json={})
        self.assertEqual(response.status_code, 403)
        response = await self.client.post(base, json={'senha': '#&Aa12'})
        self.assertEqual(response.status_code, 200, response.text)


if __name__ == '__main__':
    unittest.main()
