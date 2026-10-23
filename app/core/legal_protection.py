"""Cabeçalhos e redação de tokens no access log ASGI (Uvicorn/Gunicorn)."""


class LegalProtectionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token_page = scope.get("path", "").startswith("/confirmar_termos/")
        protected = token_page or scope.get("path", "").startswith(("/api/legal/", "/api/admin/legal/"))
        if not protected:
            return await self.app(scope, receive, send)

        async def protected_send(message):
            if message["type"] == "http.response.start":
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() not in {b"referrer-policy", b"cache-control", b"x-robots-tag"}]
                headers.extend([(b"referrer-policy", b"no-referrer"), (b"cache-control", b"no-store"),
                                (b"x-robots-tag", b"noindex, nofollow"), (b"x-content-type-options", b"nosniff")])
                message = {**message, "headers": headers}
                if token_page:
                    headers.append((b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"))
                    # Uvicorn emite o access log durante response.start. A rota já foi resolvida.
                    original = {key: scope.get(key) for key in ("path", "raw_path", "query_string")}
                    scope.update(path="/confirmar_termos/[redacted]", raw_path=b"/confirmar_termos/[redacted]", query_string=b"")
                    try:
                        return await send(message)
                    finally:
                        scope.update(original)
            return await send(message)

        await self.app(scope, receive, protected_send)
