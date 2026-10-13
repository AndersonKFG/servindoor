"""Proteção ASGI direta, sem criar tarefas adicionais por chunk SSE."""
import asyncio

from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.routers.gatekeeper import validar_token_gatekeeper


class ResgateFormRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            if request.method == "POST" and (
                request.url.path.endswith("/resgatar") or request.url.path.startswith("/resgate/")
            ):
                # A selfie é um campo textual base64. O parser multipart padrão
                # limita cada campo a 1 MB; o middleware já limita o corpo a 6 MB.
                await request.form(max_files=1, max_fields=16, max_part_size=6 * 1024 * 1024)
            return await original(request)
        return handler


class HttpProtectionMiddleware:
    def __init__(self, app, max_body_bytes=6 * 1024 * 1024, max_uploads=16):
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.upload_slots = asyncio.Semaphore(max_uploads)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        public_api = (
            path.startswith(("/api/gatekeeper/", "/api/meu-ingresso/", "/api/lote/live-status", "/api/lote/stream", "/api/faq", "/api/sponsor-logos"))
            or path.startswith("/api/correcao-foto/")
            or path in ("/api/sorteios/meus-premios", "/api/time")
        )
        if settings.GATEKEEPER_ENABLED and path.startswith("/api/") and not public_api:
            request = Request(scope)
            token = request.cookies.get(settings.SITE_ACCESS_COOKIE_NAME) or request.headers.get("x-gatekeeper-token")
            if not validar_token_gatekeeper(token) and not request.cookies.get("access_token"):
                return await JSONResponse(status_code=403, content={
                    "detail": "Acesso não autorizado. Código de liberação necessário.", "gatekeeper_required": True,
                })(scope, receive, send)
        form_post = scope.get("method") == "POST" and (
            (path.startswith("/api/lote/") and path.endswith("/resgatar"))
            or path.startswith("/resgate/")
            or path.startswith("/api/correcao-foto/")
        )
        if not form_post:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            content_length = int(headers.get(b"content-length", b"0"))
            if content_length < 0:
                raise ValueError()
        except ValueError:
            return await JSONResponse(status_code=400, content={"detail": "Tamanho da requisição inválido."})(scope, receive, send)
        if content_length > self.max_body_bytes:
            return await self._too_large(scope, receive, send)
        # Limita memória do parsing multipart/foto por worker; quem espera aqui
        # não segura nenhuma conexão do banco.
        async with self.upload_slots:
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > self.max_body_bytes:
                    return await self._too_large(scope, receive, send)
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)

    async def _too_large(self, scope, receive, send):
        return await JSONResponse(status_code=413, content={"detail": "A imagem excede o limite de 4 MB."})(scope, receive, send)
