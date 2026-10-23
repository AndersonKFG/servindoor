"""Servidor opt-in para o browser, sempre sem workers e em schema descartável.

Executar com PYTHONPATH incluindo tests, RUN_LEGAL_POSTGRES_TESTS=1 e porta local 8137.
"""
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.deps import get_current_user
from app.core.legal_protection import LegalProtectionMiddleware
from app.models.all_models import Usuario
from app.routers import legal
from app.services.legal import prepare_legal_batch
from test_legal_documents import TestLegalDocuments, pdf

fixture = TestLegalDocuments()
DIST = "/workspace/app/static/dist"


@asynccontextmanager
async def lifespan(app):
    await fixture.asyncSetUp()
    app.dependency_overrides.update(fixture.application.dependency_overrides)

    async def user(request: Request):
        async with fixture.sessions() as session:
            return await session.get(Usuario, 2 if request.cookies.get("legal_e2e_role") == "admin" else 1)

    app.dependency_overrides[get_current_user] = user
    try:
        yield
    finally:
        await fixture.asyncTearDown()


app = FastAPI(lifespan=lifespan)
app.add_middleware(LegalProtectionMiddleware)
app.include_router(legal.admin_router)
app.include_router(legal.router)


@app.get("/api/auth/me")
async def me(request: Request):
    role = "admin" if request.cookies.get("legal_e2e_role") == "admin" else "admin_geral"
    return {"autenticado": True, "usuario": {"id": 2 if role == "admin" else 1,
            "nome": "Administrador de ensaio", "roles": [role], "role": role}}


@app.get("/api/gatekeeper/status")
async def gatekeeper():
    return {"gatekeeper_enabled": False, "autorizado": True}


@app.get("/__test/info")
async def info():
    return {"schema": fixture.schema}


@app.get("/__test/pdf")
async def document():
    return Response(pdf(), media_type="application/pdf")


@app.post("/__test/prepare")
async def prepare():
    async with fixture.sessions() as session:
        await prepare_legal_batch(session)
    body = await fixture.scalar("SELECT html_body FROM email_queue WHERE sender_type='legal' ORDER BY id DESC LIMIT 1")
    token = re.search(r"/confirmar_termos/([A-Za-z0-9_-]{43})", body).group(1)
    return {"token": token}


@app.get("/__test/stats")
async def stats():
    return {"acceptances": await fixture.scalar("SELECT COUNT(*) FROM legal_acceptances"),
            "tickets": await fixture.scalar("SELECT COUNT(*) FROM ingressos WHERE deleted_at IS NULL"),
            "emails": await fixture.scalar("SELECT COUNT(*) FROM email_queue"),
            "sent": await fixture.scalar("SELECT COUNT(*) FROM email_queue WHERE status='sent'")}


app.mount("/assets", StaticFiles(directory=DIST + "/assets"))
app.mount("/images", StaticFiles(directory=DIST + "/images"))


@app.get("/{path:path}")
async def frontend(path: str):
    if path.startswith(("api/", "__test/")):
        raise HTTPException(404)
    return FileResponse(DIST + "/index.html")
