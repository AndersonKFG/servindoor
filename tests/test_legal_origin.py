"""Validação CSRF com navegador, proxy de desenvolvimento e proxy HTTPS."""
import unittest

from fastapi import Depends, FastAPI, File, UploadFile
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.routers.legal import same_origin_action


class TestLegalOrigin(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        application = FastAPI()

        @application.post("/upload", dependencies=[Depends(same_origin_action)])
        async def upload(file: UploadFile = File(...)):
            return {"size": len(await file.read())}

        self.client = AsyncClient(transport=ASGITransport(app=application), base_url="http://127.0.0.1:8000")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def upload(self, **headers):
        return await self.client.post("/upload", files={"file": ("documento.pdf", b"conteudo de teste")},
                                      headers={"X-Legal-Action": "1", **headers})

    async def test_browser_same_origin_through_vite_proxy(self):
        response = await self.upload(**{"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["size"], 17)

    async def test_browser_same_origin_through_https_proxy(self):
        response = await self.upload(**{"Origin": "https://www.servindoor.com.br", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 200, response.text)

    async def test_vite_preserved_host_without_fetch_metadata(self):
        response = await self.upload(**{"Host": "localhost:5173", "Origin": "http://localhost:5173"})
        self.assertEqual(response.status_code, 200, response.text)

    async def test_canonical_origin_without_fetch_metadata(self):
        response = await self.upload(Origin=settings.PUBLIC_BASE_URL.rstrip("/"))
        self.assertEqual(response.status_code, 200, response.text)

    async def test_foreign_origin_without_fetch_metadata_is_rejected(self):
        response = await self.upload(Origin="https://evil.invalid")
        self.assertEqual(response.status_code, 403)

    async def test_cross_site_is_rejected_even_when_origin_matches(self):
        response = await self.upload(**{"Origin": settings.PUBLIC_BASE_URL.rstrip("/"), "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status_code, 403)

    async def test_sibling_subdomain_is_not_same_origin(self):
        response = await self.upload(**{"Origin": "https://untrusted.servindoor.com.br", "Sec-Fetch-Site": "same-site"})
        self.assertEqual(response.status_code, 403)

    async def test_same_origin_still_requires_action_header(self):
        response = await self.upload(**{"X-Legal-Action": "", "Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 403)

    async def test_untrusted_forwarding_headers_cannot_allow_foreign_origin(self):
        response = await self.upload(**{"Origin": "https://evil.invalid", "X-Forwarded-Host": "evil.invalid", "X-Forwarded-Proto": "https"})
        self.assertEqual(response.status_code, 403)

    async def test_null_origin_is_rejected(self):
        response = await self.upload(Origin="null")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
