import asyncio
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import unquote, urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from sqlmodel import select

from app.core.config import settings
from app.core.events import lote_event_hub
from app.core.http_protection import HttpProtectionMiddleware
from app.db.session import async_session, init_db
from app.models.all_models import Ingresso, SolicitacaoCancelamento, SolicitacaoValidacao, Usuario

# Importando as rotas separadas
from app.routers import public, resgate, admin, portaria, auth, sorteios, gatekeeper, cancelamento, validacoes, faq, sponsor_logos, correcao_foto, avulsos

_MAX_RESGATE_BODY_BYTES = 6 * 1024 * 1024

# Os loggers do Gunicorn não configuram automaticamente os módulos de app.*.
# Envia os eventos da aplicação ao stderr capturado por docker compose logs.
app_logger = logging.getLogger("app")
app_logger.setLevel(logging.INFO)
app_logger.propagate = False
if not app_logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(name)s: %(message)s"
    ))
    app_logger.addHandler(console_handler)


def validar_configuracao_producao() -> None:
    if settings.ENVIRONMENT.strip().lower() != "production":
        return

    problemas = []
    if len(settings.SECRET_KEY) < 32 or settings.SECRET_KEY == "festa-servidor-super-secret-key-ultra-fast-2026":
        problemas.append("SECRET_KEY precisa ser exclusiva e ter pelo menos 32 caracteres")
    if len(settings.SITE_ACCESS_PIN.strip()) != 6 or settings.SITE_ACCESS_PIN.strip() == "123456":
        problemas.append("SITE_ACCESS_PIN precisa ser exclusivo e ter exatamente 6 caracteres")

    banco = urlsplit(settings.DATABASE_URL)
    senha_banco = unquote(banco.password or "")
    if len(senha_banco) < 16 or senha_banco == "postgres":
        problemas.append("a senha do banco precisa ter pelo menos 16 caracteres e não pode ser padrão")

    if problemas:
        raise RuntimeError("Configuração de produção insegura: " + "; ".join(problemas))

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"🚀 Iniciando {settings.PROJECT_NAME} com alta performance...")
    validar_configuracao_producao()
    try:
        await init_db()
        print("✅ Banco de dados sincronizado e tabelas verificadas com sucesso!")
    except Exception as e:
        print(f"❌ Falha ao inicializar o banco: {e}")
        raise

    # Barramento de eventos inter-worker via PostgreSQL LISTEN / NOTIFY (Gunicorn multi-worker)
    listen_task = None
    if "asyncpg" in settings.DATABASE_URL:
        try:
            import asyncpg
            from sqlalchemy import text
            from app.db.session import engine

            async def _send_pg_notify(payload_str: str):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT pg_notify('lote_events', :payload)"), {"payload": payload_str})
                    await conn.commit()

            lote_event_hub.register_pg_sender(_send_pg_notify)

            async def _pg_listener_worker():
                db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
                if "?sslmode=require" in db_url:
                    db_url = db_url.replace("?sslmode=require", "")
                while True:
                    conn = None
                    try:
                        conn = await asyncpg.connect(db_url)
                        def _on_notify(c, pid, channel, payload):
                            lote_event_hub.on_bus_notification(payload)
                        await conn.add_listener("lote_events", _on_notify)
                        while True:
                            await asyncio.sleep(60)
                            await conn.execute("SELECT 1;")
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        await asyncio.sleep(5)
                    finally:
                        if conn is not None:
                            await conn.close()

            listen_task = asyncio.create_task(_pg_listener_worker())
        except Exception:
            pass

    email_worker_stop = asyncio.Event()
    from app.services.email_queue import email_queue_worker
    email_worker_task = asyncio.create_task(email_queue_worker(email_worker_stop))
    from app.services.resgate_jobs import resgate_jobs_worker
    external_worker_task = asyncio.create_task(resgate_jobs_worker(email_worker_stop))
    maintenance_task = asyncio.create_task(resgate.reserva_maintenance_worker(email_worker_stop))

    async def _public_snapshot(lote_id):
        async with async_session() as session:
            return await public.coletar_status_lote_para_sse(session, lote_id)

    lote_event_hub.start_reservation_publisher(_public_snapshot)
    await resgate.reserva_batch_service.start()
    try:
        yield
    finally:
        email_worker_stop.set()
        await resgate.reserva_batch_service.stop()
        await lote_event_hub.stop_reservation_publisher()
        tasks = [email_worker_task, external_worker_task, maintenance_task]
        if listen_task:
            tasks.append(listen_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    print("🛑 Desligando sistema...")

app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.add_middleware(HttpProtectionMiddleware, max_body_bytes=_MAX_RESGATE_BODY_BYTES)


# Compressão GZip para respostas rápidas e menor tráfego de rede
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Configurar pasta de Arquivos Estáticos garantindo que o diretório exista
os.makedirs("app/static", exist_ok=True)
os.makedirs("app/static/uploads/fotos", exist_ok=True)
os.makedirs("app/static/uploads/premios", exist_ok=True)
os.makedirs("app/static/uploads/entregas", exist_ok=True)
os.makedirs("app/static/dist/assets", exist_ok=True)
os.makedirs("app/static/dist/images", exist_ok=True)

# SEC-04: Proteção de dados biométricos sensíveis (LGPD) contra download público não autorizado
@app.get("/static/uploads/fotos/{filename}")
async def obter_foto_biometrica_protegida(filename: str, request: Request):
    if not filename or os.path.basename(filename) != filename:
        raise HTTPException(status_code=404, detail="Foto não encontrada.")

    caminho = os.path.join("app/static/uploads/fotos", filename)
    foto_url = f"/static/uploads/fotos/{filename}"
    autorizado = False
    usuario_foto = None

    async with async_session() as session:
        result = await session.execute(
            select(Usuario).where(Usuario.foto_rosto_url == foto_url)
        )
        usuario_foto = result.scalars().first()

        result_cancelamento = await session.execute(
            select(SolicitacaoCancelamento.id).where(
                SolicitacaoCancelamento.foto_ao_vivo_url == foto_url
            ).limit(1)
        )
        foto_de_cancelamento = result_cancelamento.scalar_one_or_none() is not None

    if not usuario_foto and not foto_de_cancelamento:
        raise HTTPException(status_code=404, detail="Foto não encontrada.")

    # 1. Permite acesso para membros da equipe autenticados
    access_tok = request.cookies.get("access_token")
    if access_tok:
        try:
            from jose import jwt
            _, _, p = access_tok.partition(" ")
            pay = jwt.decode(p, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            roles_claim = pay.get("roles", "")
            if isinstance(roles_claim, str):
                roles = {role.strip() for role in roles_claim.split(",") if role.strip()}
            elif isinstance(roles_claim, list):
                roles = {str(role).strip() for role in roles_claim if str(role).strip()}
            else:
                roles = set()

            if pay.get("sub") and roles.intersection(
                {"admin", "admin_geral", "portaria", "validador", "entregador"}
            ):
                autorizado = True
            elif usuario_foto and pay.get("sub") == usuario_foto.cpf:
                autorizado = True
        except Exception:
            pass

    # 2. Permite acesso ao titular somente com token de posse vinculado ao próprio cadastro.
    if not autorizado:
        claim_tokens = [
            value for name, value in request.cookies.items()
            if name.startswith("ingresso_claim_") or name.startswith("solic_claim_")
        ]
        if usuario_foto and claim_tokens:
            async with async_session() as session:
                result_solicitacao = await session.execute(
                    select(SolicitacaoValidacao.id).where(
                        SolicitacaoValidacao.usuario_id == usuario_foto.id,
                        SolicitacaoValidacao.token.in_(claim_tokens)
                    ).limit(1)
                )
                result_ingresso = await session.execute(
                    select(Ingresso.id).where(
                        Ingresso.usuario_id == usuario_foto.id,
                        Ingresso.qr_code_token.in_(claim_tokens)
                    ).limit(1)
                )
                autorizado = (
                    result_solicitacao.scalar_one_or_none() is not None
                    or result_ingresso.scalar_one_or_none() is not None
                )

    # Bloqueia qualquer acesso n?o autorizado imediatamente sem revelar se o arquivo existe (previne oráculo LGPD)
    if not autorizado:
        raise HTTPException(status_code=403, detail="Acesso não autorizado a dados biométricos.")

    if not os.path.exists(caminho):
        raise HTTPException(status_code=404, detail="Foto não encontrada.")

    return FileResponse(caminho, media_type="image/jpeg")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/assets", StaticFiles(directory="app/static/dist/assets"), name="assets")
app.mount("/images", StaticFiles(directory="app/static/dist/images"), name="images")

# --- LIGANDO OS FIOS (Incluindo os roteadores) ---
app.include_router(gatekeeper.router)
app.include_router(avulsos.router)
app.include_router(public.router)
app.include_router(auth.router)
app.include_router(resgate.router)
app.include_router(admin.router)
app.include_router(portaria.router)
app.include_router(sorteios.router)
app.include_router(cancelamento.router)
app.include_router(validacoes.router)
app.include_router(faq.router)
app.include_router(sponsor_logos.router)
app.include_router(correcao_foto.router)

# Fallback Catch-all para SPA Vue Router (Evita 404 em recarregamento F5)
VUE_INDEX_PATH = 'app/static/dist/index.html'

@app.get('/{full_path:path}')
async def catch_all_spa(full_path: str):
    if (
        full_path.startswith('api/')
        or full_path.startswith('static/')
        or full_path.startswith('assets/')
        or full_path.startswith('images/')
    ):
        raise HTTPException(status_code=404, detail='Recurso não encontrado.')
    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH, headers={
            "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex",
            "Cache-Control": "no-store",
        })
    raise HTTPException(status_code=404, detail='Página não encontrada.')
