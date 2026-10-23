"""Servidor de ensaio HTTP real, opt-in, com schema/fotos/chave descartáveis.

Usa o frontend compilado e as rotas oficiais, sem workers SMTP ou de API externa.
Nunca iniciar fora do Docker local; encerrar por SIGTERM para remover o schema.
"""
import json
import os
import secrets
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import select

from app.core.config import settings
from app.core.http_protection import HttpProtectionMiddleware
from app.db import session as db
from app.models.all_models import Lote, Secretaria
from app.routers import avulsos, faq, gatekeeper, public, resgate, sponsor_logos, sorteios
from app.services.lotes_ocultos import senha_hash
from app.services.reserva_batch import ReservaBatchService

DIST = '/workspace/app/static/dist'
public.VUE_INDEX_PATH = resgate.VUE_INDEX_PATH = DIST + '/index.html'
schema = 'test_browser_flow_' + uuid.uuid4().hex
tokens = {str(i): secrets.token_urlsafe(32) for i in (301, 302, 303)}
sessions = None


@asynccontextmanager
async def lifespan(app):
    global sessions
    if os.environ.get('RUN_FLOW_E2E') != '1' or db.engine.url.host != 'db' or db.engine.url.database != 'festa_db':
        raise RuntimeError('Servidor permitido somente no Docker local db/festa_db com RUN_FLOW_E2E=1.')
    async with db.engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    pool = create_async_engine(db.engine.url, connect_args={**db.connect_args, 'server_settings': {'search_path': schema}})
    sessions = sessionmaker(pool, class_=AsyncSession, expire_on_commit=False)
    photos = tempfile.TemporaryDirectory(prefix='browser_flow_photos_')
    batch = ReservaBatchService(sessions)
    with patch.object(db, 'engine', pool), patch.object(resgate, 'async_session', sessions), \
         patch.object(public, 'async_session', sessions), patch.object(resgate, 'reserva_batch_service', batch), \
         patch.object(resgate, 'FOTOS_DIR', photos.name), \
         patch.object(settings, 'SECRET_KEY', secrets.token_urlsafe(48)), \
         patch.object(settings, 'GATEKEEPER_ENABLED', True), patch.object(settings, 'SITE_ACCESS_PIN', 'Gt#123'):
        try:
            await db.init_db()
            async with sessions() as s:
                s.add_all([Secretaria(id=1, nome='Secretaria do ensaio', sigla='E2E'),
                           Secretaria(id=2, nome='Outra secretaria', sigla='OUTRA')])
                abertura = datetime.now(timezone.utc) - timedelta(minutes=1)
                for lote_id, temporizado, validacao in ((301, False, True), (302, True, False), (303, False, True)):
                    config = {'temporizado': temporizado, 'exige_validacao': validacao, 'campos': {
                        'secretaria_id': {'modo': 'fixo', 'valor': '1'},
                        'setor': {'modo': 'fixo', 'valor': 'Laboratorio local'},
                        'vinculo': {'modo': 'fixo', 'valor': 'Efetivo'}}}
                    s.add(Lote(id=lote_id, nome=f'Oculto E2E {lote_id}', ativo=True, oculto=True,
                        quantidade_total=2, data_abertura=abertura, acesso_token=tokens[str(lote_id)],
                        acesso_senha_hash=senha_hash('Ab#123') if lote_id != 303 else None,
                        avulso_config=json.dumps(config)))
                s.add(Lote(id=201, nome='Publico E2E 201', ativo=True, quantidade_total=10, data_abertura=abertura))
                await s.commit()
            await batch.start()
            yield
        finally:
            await batch.stop()
            await pool.dispose()
            photos.cleanup()
            # db.engine está substituído no bloco; use outra conexão sem search_path.
            cleanup = create_async_engine(pool.url, connect_args=db.connect_args)
            try:
                async with cleanup.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            finally:
                await cleanup.dispose()
    await db.engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(HttpProtectionMiddleware)


async def session():
    async with sessions() as s:
        yield s


app.dependency_overrides[db.get_session] = session
for router in (avulsos.router, public.router, resgate.router, gatekeeper.router, faq.router, sponsor_logos.router, sorteios.router):
    app.include_router(router)


@app.get('/api/auth/me')
async def anonymous():
    return {'autenticado': False, 'usuario': None}


@app.get('/__test/info')
async def info():
    return {'tokens': tokens, 'senha': 'Ab#123', 'gate_pin': 'Gt#123', 'schema': schema}


@app.get('/__test/stats')
async def stats():
    async with sessions() as s:
        lotes = (await s.execute(text('SELECT id, quantidade_resgatada, quantidade_total FROM lotes ORDER BY id'))).mappings().all()
        solicitacoes = (await s.execute(text('SELECT lote_id,status,count(*) AS total FROM solicitacoes_validacao GROUP BY lote_id,status ORDER BY lote_id,status'))).mappings().all()
        emails = (await s.execute(text('SELECT sender_type,status,count(*) AS total,min(octet_length(ticket_image)) AS imagem_bytes FROM email_queue GROUP BY sender_type,status'))).mappings().all()
        ingressos = await s.scalar(text('SELECT count(*) FROM ingressos'))
        jobs = await s.scalar(text('SELECT count(*) FROM resgate_jobs'))
    return {'lotes': [dict(r) for r in lotes], 'solicitacoes': [dict(r) for r in solicitacoes],
            'emails': [dict(r) for r in emails], 'ingressos': ingressos, 'jobs': jobs}


app.mount('/assets', StaticFiles(directory=DIST + '/assets'))
app.mount('/images', StaticFiles(directory=DIST + '/images'))


@app.get('/{path:path}')
async def frontend(path: str):
    if path.startswith(('api/', '__test/')):
        raise HTTPException(404)
    return FileResponse(DIST + '/index.html')
