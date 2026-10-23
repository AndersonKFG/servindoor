"""Ensaio opt-in sobre um lote de teste persistente no banco Docker local.

--criar cria somente o lote e registra os dados em .venv/lote-oculto-teste.json.
Os testes usam savepoints dentro de uma transação externa, inclusive as filas
reais de e-mail/validação: workers não enxergam os envios, que são desfeitos.
Nenhuma senha ou sessão de um usuário real é alterada.
"""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.deps import get_current_user
from app.core.http_protection import HttpProtectionMiddleware
from app.core.security import get_password_hash
from app.db.session import engine, async_session, get_session
from app.models.all_models import Lote, Usuario, Secretaria, ReservaIngresso, SolicitacaoValidacao, Ingresso, UserRole
from app.routers import admin, avulsos, public, resgate, validacoes
from app.services.lotes_ocultos import configuracao

ARQUIVO = Path('.venv/lote-oculto-teste.json')


def conferir_banco_local():
    if os.environ.get('RUN_EXISTING_DB_TESTS') != '1' or engine.url.host != 'db' or engine.url.database != 'festa_db':
        raise RuntimeError('Requer RUN_EXISTING_DB_TESTS=1 e o banco Docker local db/festa_db.')


def aplicacao(sessao, usuario):
    app = FastAPI()
    for router in (admin.router, avulsos.router, public.router, resgate.router, validacoes.router):
        app.include_router(router)
    app.add_middleware(HttpProtectionMiddleware)
    app.dependency_overrides[get_session] = sessao
    app.dependency_overrides[get_current_user] = usuario
    return app


async def criar():
    conferir_banco_local()
    if ARQUIVO.exists():
        raise RuntimeError('Já existe um lote registrado no arquivo de teste; não criar duplicado.')
    async with async_session() as s:
        gestor = (await s.execute(select(Usuario).where(Usuario.role == UserRole.admin_geral,
            Usuario.deleted_at.is_(None), Usuario.ativo == True))).scalars().first()
        secretaria = (await s.execute(select(Secretaria).order_by(Secretaria.id))).scalars().first()
        if not gestor or not secretaria:
            raise RuntimeError('Superadministrador e secretaria cadastrada são necessários.')
        gestor_id, secretaria_id, secretaria_nome = gestor.id, secretaria.id, secretaria.nome
        portaria = (await s.execute(text('SELECT row_to_json(c) FROM controle_presenca c ORDER BY id'))).scalars().all()
    async def sessao():
        async with async_session() as s:
            yield s
    async def usuario():
        return Usuario(id=gestor_id, cpf='fixture-local', nome='Ensaio local', role=UserRole.admin_geral)
    config = {'temporizado': True, 'exige_validacao': True, 'campos': {
        'secretaria_id': {'modo': 'fixo', 'valor': str(secretaria_id)},
        'setor': {'modo': 'fixo', 'valor': 'TESTE LOCAL - LOTE OCULTO'},
        'vinculo': {'modo': 'fixo', 'valor': 'Efetivo'}}}
    senha = 'Ts#' + ''.join(secrets.choice('0123456789') for _ in range(3))
    nome = 'TESTE LOCAL - LOTE OCULTO - ' + datetime.now(timezone.utc).astimezone(admin.security.TZ_SAO_PAULO).strftime('%d/%m/%Y %H:%M')
    async with AsyncClient(transport=ASGITransport(app=aplicacao(sessao, usuario)), base_url='http://teste-local',
                           cookies={'access_token': 'ensaio-interno'}) as client:
        r = await client.post('/api/admin/lotes', data={'nome': nome, 'quantidade_total': '2',
            'data_abertura': (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            'ativo': 'on', 'oculto': 'true', 'avulso_config': json.dumps(config), 'acesso_senha': senha})
        if r.status_code != 201 or not r.json().get('oculto'):
            raise RuntimeError(f'Criação não confirmada: {r.status_code} {r.text}')
        lote_id = r.json()['id']
    async with async_session() as s:
        lote = await s.get(Lote, lote_id)
        dados = {'id': lote.id, 'nome': lote.nome, 'token': lote.acesso_token, 'senha': senha,
                 'gestor_id': gestor_id, 'secretaria_id': secretaria_id, 'secretaria_nome': secretaria_nome,
                 'portaria_antes': portaria, 'config': configuracao(lote)}
        ARQUIVO.parent.mkdir(exist_ok=True)
        ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'id': lote.id, 'nome': lote.nome, 'oculto': lote.oculto, 'limite': lote.quantidade_total,
                          'secretaria': secretaria_nome, 'arquivo': str(ARQUIVO)}, ensure_ascii=False))
    await engine.dispose()


async def regenerar():
    """Regenera só o lote marcado; a credencial de teste existe apenas em memória."""
    conferir_banco_local()
    dados = json.loads(ARQUIVO.read_text(encoding='utf-8'))
    senha = secrets.token_urlsafe(24)
    async def sessao():
        async with async_session() as s:
            yield s
    async def usuario():
        return Usuario(id=dados['gestor_id'], cpf='fixture-local', nome='Ensaio local',
                       role=UserRole.admin_geral, senha_hash=get_password_hash(senha))
    async with async_session() as s:
        lote = await s.get(Lote, dados['id'])
        if not lote or not lote.oculto or not lote.nome.startswith('TESTE LOCAL - LOTE OCULTO - '):
            raise RuntimeError('O lote não corresponde ao teste local.')
    async with AsyncClient(transport=ASGITransport(app=aplicacao(sessao, usuario)), base_url='http://teste-local',
                           cookies={'access_token': 'ensaio-interno'}) as client:
        r = await client.post(f"/api/admin/lote/{dados['id']}/regenerar-link", json={'senha': senha})
        if r.status_code != 200:
            raise RuntimeError(f'Regeneração não confirmada: {r.status_code} {r.text}')
        dados['token_anterior'] = dados['token']
        dados['token'] = r.json()['link'].lstrip('/')
        ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"Link do lote local #{dados['id']} regenerado; nenhuma senha real alterada.")
    await engine.dispose()


@unittest.skipUnless(os.environ.get('RUN_EXISTING_DB_TESTS') == '1' and ARQUIVO.exists(), 'Requer lote local criado explicitamente')
class TestLoteOcultoLocalCompleto(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        conferir_banco_local()
        self.dados = json.loads(ARQUIVO.read_text(encoding='utf-8'))
        self.id = self.dados['id']
        self.token = self.dados['token']
        self.conn = await engine.connect()
        self.outer = await self.conn.begin()
        self.antes = (await self.conn.execute(text('SELECT row_to_json(l) FROM lotes l ORDER BY id'))).scalars().all()
        self.portaria_antes = (await self.conn.execute(text('SELECT row_to_json(c) FROM controle_presenca c ORDER BY id'))).scalars().all()
        await self.conn.execute(text('SELECT id FROM lotes WHERE id=:id FOR UPDATE'), {'id': self.id})
        self.session = AsyncSession(bind=self.conn, expire_on_commit=False, join_transaction_mode='create_savepoint')
        self.proximo_id = -1_500_000_000 - secrets.randbelow(100_000_000)
        def ids_de_teste(session, flush_context, instances):
            for objeto in session.new:
                if hasattr(objeto, 'id') and objeto.id is None:
                    objeto.id = self.proximo_id
                    self.proximo_id -= 1
        event.listen(self.session.sync_session, 'before_flush', ids_de_teste)
        async def sessao():
            yield self.session
        self.senha_admin = secrets.token_urlsafe(20)
        self.superadmin = Usuario(id=self.dados['gestor_id'], cpf='fixture-local', nome='Ensaio local',
                                 role=UserRole.admin_geral, senha_hash=get_password_hash(self.senha_admin))
        self.usuario = self.superadmin
        async def usuario():
            return self.usuario
        self.app = aplicacao(sessao, usuario)
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url='http://teste-local')
        self.pasta = tempfile.TemporaryDirectory()
        self.fotos = patch.object(resgate, 'FOTOS_DIR', self.pasta.name)
        self.fotos.start()
        image = io.BytesIO()
        Image.new('RGB', (32, 32), 'white').save(image, format='JPEG')
        self.foto = 'data:image/jpeg;base64,' + base64.b64encode(image.getvalue()).decode()
        public.invalidar_cache_live_status()

    async def asyncTearDown(self):
        try:
            await self.client.aclose()
            await self.session.close()
            await self.outer.rollback()
            depois = (await self.conn.execute(text('SELECT row_to_json(l) FROM lotes l ORDER BY id'))).scalars().all()
            portaria = (await self.conn.execute(text('SELECT row_to_json(c) FROM controle_presenca c ORDER BY id'))).scalars().all()
            self.assertEqual(self.antes, depois, 'Os lotes reais devem permanecer intactos')
            self.assertEqual(self.portaria_antes, portaria)
        finally:
            await self.conn.close()
            await engine.dispose()
            self.fotos.stop()
            self.pasta.cleanup()
            public.invalidar_cache_live_status()

    async def cpf(self):
        while True:
            nums = [secrets.randbelow(10) for _ in range(9)]
            for tamanho in (9, 10):
                resto = sum(n * (tamanho + 1 - i) for i, n in enumerate(nums)) * 10 % 11
                nums.append(0 if resto == 10 else resto)
            cpf = ''.join(map(str, nums))
            if not await self.session.scalar(select(Usuario.id).where(Usuario.cpf == cpf)):
                return cpf

    async def autorizar(self, senha=None):
        r = await self.client.post(f'/api/avulso/{self.token}/acesso', json={'senha': senha or self.dados['senha']})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.headers['X-Lote-Acesso'] = r.json()['autorizacao']
        return r

    async def iniciar(self):
        r = await self.client.post(f'/api/avulso/{self.token}/iniciar')
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def enviar(self, reserva, cpf=None, **mudancas):
        dados = dict(token_reserva=reserva['token_reserva'], cpf=cpf or await self.cpf(), nome='PARTICIPANTE FICTICIO - TRANSACAO LOCAL',
            data_nascimento='1990-01-01', secretaria_id=str(self.dados['secretaria_id']), setor='TESTE LOCAL - LOTE OCULTO',
            vinculo='Efetivo', telefone='81999990000', email='lote-oculto-teste@example.invalid', foto_base64=self.foto)
        dados.update(mudancas)
        return await self.client.post(f'/api/avulso/{self.token}/resgatar', data=dados)

    async def editar(self, **mudancas):
        lote = await self.session.get(Lote, self.id)
        dados = dict(nome=lote.nome, quantidade_total=str(lote.quantidade_total),
            data_abertura=lote.data_abertura.isoformat(), ativo='on', secretaria_id='0')
        dados.update(mudancas)
        self.client.cookies.set('access_token', 'ensaio-interno')
        try:
            return await self.client.post(f'/admin/lote/{self.id}/editar', data=dados)
        finally:
            self.client.cookies.delete('access_token')

    async def configurar(self, **mudancas):
        lote = await self.session.get(Lote, self.id)
        cfg = configuracao(lote)
        cfg.update(mudancas)
        r = await self.editar(avulso_config=json.dumps(cfg))
        self.assertEqual(r.status_code, 303, r.text)

    async def test_01_senha_pin_global_e_ocultacao_publica(self):
        base = f'/api/avulso/{self.token}'
        for senha in ('', 'errada', '12345', '1234567'):
            r = await self.client.post(base + '/acesso', json={'senha': senha})
            self.assertEqual(r.status_code, 403)
        self.assertEqual((await self.client.get(base + '/status')).status_code, 403)
        with patch('app.core.http_protection.settings.GATEKEEPER_ENABLED', True):
            r = await self.autorizar()
            self.assertEqual(r.headers['cache-control'], 'no-store')
            self.assertEqual((await self.client.get('/api/lotes-admin')).status_code, 403)
            self.assertEqual((await self.client.get(base + '/secretarias')).status_code, 200)
        self.assertIsNone(await public.obter_lote_relevante(self.session, datetime.now(timezone.utc), self.id))
        self.assertEqual(await public.coletar_status_lote_para_sse(self.session, self.id), {'oculto': True})
        r = await self.client.get(f'/api/lote/live-status?lote_id={self.id}')
        self.assertNotEqual(r.json().get('id'), self.id)
        self.assertNotIn(self.dados['nome'], r.text)

    async def test_02_campos_travados_e_demais_obrigatorios(self):
        await self.autorizar()
        reserva = await self.iniciar()
        for campo, valor in [('secretaria_id', '99999999'), ('setor', 'ADULTERADO'), ('vinculo', 'Comissionado')]:
            r = await self.enviar(reserva, **{campo: valor})
            self.assertEqual(r.status_code, 400, r.text)
            self.assertIn('travado', r.text)
        for campo in ('cpf', 'nome', 'data_nascimento', 'secretaria_id', 'setor', 'vinculo', 'telefone', 'email', 'foto_base64'):
            r = await self.enviar(reserva, **{campo: ' '})
            self.assertEqual(r.status_code, 400, (campo, r.text))
        for campo, valor in [('email', 'invalido'), ('telefone', '1'), ('foto_base64', 'nao-imagem')]:
            self.assertEqual((await self.enviar(reserva, **{campo: valor})).status_code, 400)
        self.assertEqual((await self.session.get(Lote, self.id)).quantidade_resgatada, 0)

    async def test_03_cinco_minutos_reserva_limite_expiracao(self):
        await self.autorizar()
        primeira, segunda = await self.iniciar(), await self.iniciar()
        for reserva in (primeira, segunda):
            prazo = (reserva['expira_em_ms'] - reserva['server_time_ms']) / 1000
            self.assertTrue(299 <= prazo <= 301, prazo)
        self.assertEqual((await self.client.post(f'/api/avulso/{self.token}/iniciar')).status_code, 409)
        await self.session.execute(text("UPDATE reservas_ingressos SET expira_em=NOW()-INTERVAL '1 second' WHERE token=:token"), {'token': primeira['token_reserva']})
        await self.session.commit()
        self.session.expire_all()
        r = await self.enviar(primeira)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()['codigo'], 'reserva_expirada')
        await self.iniciar()  # A vaga expirada volta a estar disponível.

    async def test_04_sem_prazo_aprovacao_automatica_email_limite_e_cpf(self):
        await self.configurar(temporizado=False, exige_validacao=False)
        await self.autorizar()
        reservas = [await self.iniciar() for _ in range(4)]
        self.assertTrue(all(r['expira_em_ms'] is None for r in reservas))
        self.assertEqual((await self.session.get(Lote, self.id)).quantidade_resgatada, 0)
        await self.session.execute(text("UPDATE reservas_ingressos SET expira_em=NOW()-INTERVAL '1 day' WHERE lote_id=:id"), {'id': self.id})
        await self.session.commit()
        self.session.expire_all()
        cpf = await self.cpf()
        r = await self.enviar(reservas[0], cpf=cpf)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['status'], 'aprovado')
        self.assertEqual((await self.enviar(reservas[0], cpf=cpf)).status_code, 200)  # Reenvio idempotente.
        self.assertEqual((await self.enviar(reservas[1], cpf=cpf)).status_code, 409)
        r = await self.enviar(reservas[2])
        self.assertEqual(r.status_code, 200, r.text)
        r = await self.enviar(reservas[3])
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual((await self.session.get(Lote, self.id)).quantidade_resgatada, 2)
        self.assertEqual(await self.session.scalar(text('SELECT count(*) FROM ingressos WHERE lote_id=:id'), {'id': self.id}), 2)
        emails = (await self.session.execute(text("SELECT sender_type, status, octet_length(ticket_image) FROM email_queue WHERE recipient='lote-oculto-teste@example.invalid'"))).all()
        self.assertEqual(len(emails), 2)
        self.assertTrue(all(tipo == 'ticket' and status == 'queued' and tamanho > 0 for tipo, status, tamanho in emails))
        self.assertEqual(await self.session.scalar(text('SELECT count(*) FROM resgate_jobs j JOIN solicitacoes_validacao s ON s.id=j.solicitacao_id WHERE s.lote_id=:id'), {'id': self.id}), 0)

    async def test_05_validacao_so_superadmin_e_mudanca_apenas_novos(self):
        await self.configurar(temporizado=False, exige_validacao=True)
        await self.autorizar()
        cpf = await self.cpf()
        r = await self.enviar(await self.iniciar(), cpf=cpf)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['status'], 'pendente_analise')
        solic = (await self.session.execute(select(SolicitacaoValidacao).where(SolicitacaoValidacao.lote_id == self.id))).scalars().one()
        solic_id = solic.id
        await self.configurar(exige_validacao=False)
        self.assertEqual((await self.session.get(SolicitacaoValidacao, solic_id)).status, 'pendente_analise')
        self.assertEqual(await self.session.scalar(text('SELECT count(*) FROM ingressos WHERE lote_id=:id'), {'id': self.id}), 0)
        self.client.cookies.set('access_token', 'ensaio-interno')
        self.usuario = Usuario(id=self.dados['gestor_id'], cpf='fixture', nome='Admin comum', role=UserRole.admin)
        r = await self.client.get('/api/admin/validacoes', params={'busca': cpf})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()['solicitacoes'][0]['pode_gerenciar'])
        for acao in ('aprovar', 'rejeitar', 'comunicar'):
            self.assertEqual((await self.client.post(f'/api/admin/validacoes/{solic_id}/{acao}', json={})).status_code, 403)
        self.usuario = self.superadmin
        r = await self.client.post(f'/api/admin/validacoes/{solic_id}/aprovar', json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.session.get(SolicitacaoValidacao, solic_id)).status, 'aprovado')

    async def test_06_rotacao_exige_senha_admin_e_invalida_link_e_formulario(self):
        await self.autorizar()
        reserva = await self.iniciar()
        grant = self.client.headers['X-Lote-Acesso']
        antigo = self.token
        self.client.cookies.set('access_token', 'ensaio-interno')
        endpoint = f'/api/admin/lote/{self.id}/regenerar-link'
        self.usuario = Usuario(id=self.dados['gestor_id'], cpf='fixture', nome='Admin comum', role=UserRole.admin)
        self.assertEqual((await self.client.post(endpoint, json={'senha': self.senha_admin})).status_code, 403)
        self.usuario = self.superadmin
        self.assertEqual((await self.client.post(endpoint, json={'senha': 'errada'})).status_code, 401)
        r = await self.client.post(endpoint, json={'senha': self.senha_admin})
        self.assertEqual(r.status_code, 200, r.text)
        self.token = r.json()['link'].lstrip('/')
        self.assertNotEqual(self.token, antigo)
        for acao in ('acesso', 'iniciar', 'resgatar'):
            self.assertEqual((await self.client.post(f'/api/avulso/{antigo}/{acao}', json={})).status_code, 404)
        self.assertEqual((await self.client.get(f'/api/avulso/{self.token}/status')).status_code, 403)
        await self.autorizar()
        self.assertEqual((await self.enviar(reserva)).status_code, 403)
        self.assertEqual(await self.session.scalar(select(ReservaIngresso.status).where(ReservaIngresso.token == reserva['token_reserva'])), 'cancelada')
        self.assertNotEqual(self.client.headers['X-Lote-Acesso'], grant)
        await self.iniciar()

    async def test_07_trocar_senha_ou_config_exige_reinicio(self):
        await self.autorizar()
        reserva = await self.iniciar()
        self.assertEqual((await self.editar(acesso_senha='N0v@12')).status_code, 303)
        self.assertEqual((await self.enviar(reserva)).status_code, 403)
        self.assertEqual((await self.client.post(f'/api/avulso/{self.token}/acesso', json={'senha': self.dados['senha']})).status_code, 403)
        await self.autorizar('N0v@12')
        self.assertEqual((await self.enviar(reserva)).status_code, 403)
        nova = await self.iniciar()
        await self.configurar(temporizado=False)
        self.assertEqual((await self.enviar(nova)).status_code, 403)

    async def test_08_imutavel_tres_modos_e_configuracoes_invalidas(self):
        self.assertEqual((await self.editar(oculto='false')).status_code, 400)
        for senha in ('12345', '1234567'):
            self.assertEqual((await self.editar(acesso_senha=senha)).status_code, 400)
        for campo, valor in [('secretaria_id', '99999999'), ('vinculo', 'INEXISTENTE')]:
            r = await self.editar(avulso_config=json.dumps({'campos': {campo: {'modo': 'fixo', 'valor': valor}}}))
            self.assertEqual(r.status_code, 400, r.text)
        for modo in ('livre', 'preenchido', 'fixo'):
            campos = {nome: {'modo': modo, 'valor': regra['valor']} for nome, regra in self.dados['config']['campos'].items()}
            await self.configurar(campos=campos, temporizado=False)
            r = await self.autorizar()
            self.assertTrue(all(regra['modo'] == modo for regra in r.json()['config']['campos'].values()))
        await self.configurar(campos={'secretaria_id': {'modo': 'preenchido', 'valor': str(self.dados['secretaria_id'])},
            'setor': {'modo': 'preenchido', 'valor': 'Sugestao'}, 'vinculo': {'modo': 'livre', 'valor': ''}})
        await self.autorizar()
        r = await self.enviar(await self.iniciar(), setor='Valor editado', vinculo='Comissionado')
        self.assertEqual(r.status_code, 200, r.text)

    async def test_09_senha_opcional_e_pausa_invalidam_acesso(self):
        await self.autorizar()
        reserva = await self.iniciar()
        self.assertEqual((await self.editar(remover_senha='true')).status_code, 303)
        self.assertEqual((await self.enviar(reserva)).status_code, 403)
        r = await self.client.post(f'/api/avulso/{self.token}/acesso', json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()['tem_senha'])
        self.client.headers['X-Lote-Acesso'] = r.json()['autorizacao']
        reserva = await self.iniciar()
        self.client.cookies.set('access_token', 'ensaio-interno')
        r = await self.client.post(f'/admin/lote/{self.id}/toggle')
        self.assertEqual(r.status_code, 303, r.text)
        self.assertEqual((await self.enviar(reserva)).status_code, 403)


if __name__ == '__main__':
    if '--criar' in sys.argv:
        asyncio.run(criar())
    elif '--regenerar' in sys.argv:
        asyncio.run(regenerar())
    else:
        unittest.main()
