import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from app.core.config import settings
from app.db.session import init_db

# Importando as rotas separadas
from app.routers import public, resgate, admin, portaria, auth, sorteios

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

# Compressão GZip para respostas rápidas e menor tráfego de rede
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Configurar pasta de Arquivos Estáticos garantindo que o diretório exista
os.makedirs("app/static", exist_ok=True)
os.makedirs("app/static/uploads/fotos", exist_ok=True)
os.makedirs("app/static/uploads/premios", exist_ok=True)
os.makedirs("app/static/uploads/entregas", exist_ok=True)
os.makedirs("app/static/dist/assets", exist_ok=True)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/assets", StaticFiles(directory="app/static/dist/assets"), name="assets")

# --- LIGANDO OS FIOS (Incluindo os roteadores) ---
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
    if full_path.startswith('api/') or full_path.startswith('static/') or full_path.startswith('assets/'):
        raise HTTPException(status_code=404, detail='Recurso não encontrado.')
    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)
    raise HTTPException(status_code=404, detail='Página não encontrada.')
