import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from app.core.config import settings
from app.db.session import init_db

# Importando as rotas separadas
from app.routers import public, resgate, admin, portaria, auth, sorteios, gatekeeper
from app.routers.gatekeeper import validar_token_gatekeeper

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"🚀 Iniciando {settings.PROJECT_NAME} com alta performance...")
    try:
        await init_db()
        print("✅ Banco de dados sincronizado e tabelas verificadas com sucesso!")
    except Exception as e:
        print(f"⚠️ Aviso na inicialização do banco: {e}")
    yield
    print("🛑 Desligando sistema...")

app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

# Middleware de Proteção Gatekeeper (Intercepta chamadas /api/* não autorizadas)
from fastapi.responses import JSONResponse

@app.middleware("http")
async def gatekeeper_api_protection(request: Request, call_next):
    if not settings.GATEKEEPER_ENABLED:
        return await call_next(request)

    path = request.url.path

    # Permite arquivos estáticos, rotas do próprio gatekeeper e assets
    if (
        path.startswith("/api/gatekeeper/")
        or path.startswith("/static/")
        or path.startswith("/assets/")
        or path.startswith("/images/")
        or path in ["/favicon.ico", "/servindooricon.ico"]
    ):
        return await call_next(request)

    # Se for uma rota de API, verifica autorização do dispositivo
    if path.startswith("/api/"):
        token = request.cookies.get(settings.SITE_ACCESS_COOKIE_NAME)
        if not token:
            token = request.headers.get("x-gatekeeper-token")
        
        if not validar_token_gatekeeper(token):
            # Se não tem o token do gatekeeper, checa se há sessão de usuário autenticado
            user_cookie = request.cookies.get("access_token")
            if not user_cookie:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Acesso não autorizado. Código de liberação necessário.",
                        "gatekeeper_required": True
                    }
                )

    return await call_next(request)



# Compressão GZip para respostas rápidas e menor tráfego de rede
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Configurar pasta de Arquivos Estáticos garantindo que o diretório exista
os.makedirs("app/static", exist_ok=True)
os.makedirs("app/static/uploads/fotos", exist_ok=True)
os.makedirs("app/static/uploads/premios", exist_ok=True)
os.makedirs("app/static/uploads/entregas", exist_ok=True)
os.makedirs("app/static/dist/assets", exist_ok=True)
os.makedirs("app/static/dist/images", exist_ok=True)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/assets", StaticFiles(directory="app/static/dist/assets"), name="assets")
app.mount("/images", StaticFiles(directory="app/static/dist/images"), name="images")

# --- LIGANDO OS FIOS (Incluindo os roteadores) ---
app.include_router(gatekeeper.router)
app.include_router(public.router)
app.include_router(auth.router)
app.include_router(resgate.router)
app.include_router(admin.router)
app.include_router(portaria.router)
app.include_router(sorteios.router)

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
        return FileResponse(VUE_INDEX_PATH)
    raise HTTPException(status_code=404, detail='Página não encontrada.')
