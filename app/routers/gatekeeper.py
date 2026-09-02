import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, status, Response
from pydantic import BaseModel
from jose import jwt, JWTError

from app.core.config import settings

router = APIRouter(prefix="/api/gatekeeper", tags=["Gatekeeper"])


class GatekeeperPinRequest(BaseModel):
    pin: str


def extrair_ip_cliente(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    x_fwd = request.headers.get("x-forwarded-for")
    if x_fwd:
        return x_fwd.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def criar_token_gatekeeper(ip: str) -> str:
    expiracao = datetime.now(timezone.utc) + timedelta(days=settings.SITE_ACCESS_EXPIRE_DAYS)
    payload = {
        "sub": "dispositivo_autorizado",
        "tipo": "gatekeeper",
        "ip": ip,
        "exp": expiracao
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def validar_token_gatekeeper(token: Optional[str]) -> bool:
    if not token:
        return False
    if token.startswith("Bearer "):
        token = token[7:]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("tipo") != "gatekeeper":
            return False
        return True
    except JWTError:
        return False


@router.get("/status")
async def gatekeeper_status(request: Request):
    """
    Informa ao frontend se o gatekeeper está ativo e se o cliente atual já está autorizado.
    """
    if not settings.GATEKEEPER_ENABLED:
        return {"autorizado": True, "gatekeeper_enabled": False}

    token = request.cookies.get(settings.SITE_ACCESS_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    autorizado = validar_token_gatekeeper(token)
    return {
        "autorizado": autorizado,
        "gatekeeper_enabled": settings.GATEKEEPER_ENABLED
    }


@router.post("/verificar")
async def verificar_pin(data: GatekeeperPinRequest, request: Request, response: Response):
    """
    Verifica o código de 6 dígitos e libera o dispositivo com cookie seguro e token.
    """
    if not settings.GATEKEEPER_ENABLED:
        return {"sucesso": True, "mensagem": "Gatekeeper desativado.", "token": None}

    pin_enviado = (data.pin or "").strip()
    pin_correto = (settings.SITE_ACCESS_PIN or "").strip()

    if not secrets.compare_digest(pin_enviado, pin_correto):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código de acesso incorreto. Verifique e tente novamente."
        )

    ip_cliente = extrair_ip_cliente(request)
    token = criar_token_gatekeeper(ip_cliente)

    # Define o cookie HTTP-Only persistente
    max_age_segundos = settings.SITE_ACCESS_EXPIRE_DAYS * 86400
    response.set_cookie(
        key=settings.SITE_ACCESS_COOKIE_NAME,
        value=token,
        max_age=max_age_segundos,
        httponly=True,
        samesite="lax",
        path="/"
    )

    return {
        "sucesso": True,
        "token": token,
        "expira_em_dias": settings.SITE_ACCESS_EXPIRE_DAYS
    }
