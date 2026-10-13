import json
import unittest
from unittest.mock import patch

from fastapi import APIRouter, FastAPI, Form

from app.core.http_protection import HttpProtectionMiddleware, ResgateFormRoute, settings


class TestHttpProtection(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, path, chunks=(), headers=(), gatekeeper=False):
        messages = []
        incoming = iter([
            {"type": "http.request", "body": part, "more_body": i < len(chunks) - 1}
            for i, part in enumerate(chunks)
        ] or [{"type": "http.request", "body": b"", "more_body": False}])

        async def receive():
            return next(incoming, {"type": "http.disconnect"})

        async def send(message):
            messages.append(message)

        async def app(scope, receive, send):
            size = 0
            while True:
                message = await receive()
                size += len(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": str(size).encode()})

        scope = {"type": "http", "method": "POST", "path": path, "headers": headers}
        with patch.object(settings, "GATEKEEPER_ENABLED", gatekeeper):
            await HttpProtectionMiddleware(app, max_body_bytes=8)(scope, receive, send)
        return messages

    async def test_limita_rota_real_formulario_com_tamanho_declarado(self):
        messages = await self.invoke("/api/lote/1/resgatar", headers=[(b"content-length", b"9")])
        self.assertEqual(messages[0]["status"], 413)

    async def test_limita_rota_legada_sem_content_length(self):
        messages = await self.invoke("/resgate/1", chunks=[b"1234", b"56789"])
        self.assertEqual(messages[0]["status"], 413)

    async def test_repassa_corpo_sem_perder_chunks(self):
        messages = await self.invoke("/api/lote/1/resgatar", chunks=[b"12", b"34"])
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(messages[1]["body"], b"4")

    async def test_rejeita_content_length_invalido(self):
        messages = await self.invoke("/api/lote/1/resgatar", headers=[(b"content-length", b"-1")])
        self.assertEqual(messages[0]["status"], 400)

    async def test_sse_publico_passa_gatekeeper_sem_buffer(self):
        messages = await self.invoke("/api/lote/stream", chunks=[b"123456789"], gatekeeper=True)
        self.assertEqual(messages[0]["status"], 200)

    async def test_formulario_api_exige_gatekeeper(self):
        messages = await self.invoke("/api/lote/1/resgatar", gatekeeper=True)
        self.assertEqual(messages[0]["status"], 403)
        self.assertTrue(json.loads(messages[1]["body"])["gatekeeper_required"])

    async def test_multipart_aceita_selfie_base64_maior_que_um_mb(self):
        app = FastAPI()
        router = APIRouter(route_class=ResgateFormRoute)

        @router.post("/api/lote/1/resgatar")
        async def submit(foto_base64: str = Form(...)):
            return {"bytes": len(foto_base64)}

        app.include_router(router)
        payload = b"a" * (2 * 1024 * 1024)
        body = b'--test-boundary\r\nContent-Disposition: form-data; name="foto_base64"\r\n\r\n' + payload + b'\r\n--test-boundary--\r\n'
        scope = {"type": "http", "method": "POST", "path": "/api/lote/1/resgatar",
            "scheme": "http", "query_string": b"", "server": ("localhost", 8000),
            "headers": [(b"content-type", b"multipart/form-data; boundary=test-boundary"),
                        (b"content-length", str(len(body)).encode())]}
        incoming = iter([{"type": "http.request", "body": body, "more_body": False}])
        messages = []

        async def receive():
            return next(incoming, {"type": "http.disconnect"})

        async def send(message):
            messages.append(message)

        with patch.object(settings, "GATEKEEPER_ENABLED", False):
            await HttpProtectionMiddleware(app)(scope, receive, send)
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(json.loads(messages[1]["body"])["bytes"], len(payload))
