import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, status, Response, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func
from jose import jwt, JWTError

from app.core.config import settings
from app.db.session import get_session
from app.models.all_models import GatekeeperTentativa

router = APIRouter(prefix="/api/gatekeeper", tags=["Gatekeeper"])

# Memória cache de tentativas locais (fallback de segurança)
_fallback_tentativas = {}


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


async def contar_tentativas_falhas(ip: str, session: Optional[AsyncSession] = None) -> int:
    """Conta tentativas incorretas nas últimas 24 horas para este IP"""
    limite_tempo = datetime.utcnow() - timedelta(hours=24)

    if session:
        try:
            stmt = select(func.count(GatekeeperTentativa.id)).where(
                GatekeeperTentativa.ip == ip,
                GatekeeperTentativa.sucesso == False,
                GatekeeperTentativa.data_tentativa >= limite_tempo
            )
            result = await session.execute(stmt)
            return result.scalar() or 0
        except Exception as e:
            print(f"⚠️ Aviso ao consultar banco para rate limit: {e}")

    # Fallback em memória
    agora = datetime.utcnow()
    historico = _fallback_tentativas.get(ip, [])
    historico = [t for t in historico if agora - t < timedelta(hours=24)]
    _fallback_tentativas[ip] = historico
    return len(historico)


async def registrar_tentativa(ip: str, sucesso: bool, session: Optional[AsyncSession] = None):
    """Registra tentativa no banco de dados"""
    if session:
        try:
            tentativa = GatekeeperTentativa(
                ip=ip,
                sucesso=sucesso,
                data_tentativa=datetime.utcnow()
            )
            session.add(tentativa)
            await session.commit()
            return
        except Exception as e:
            print(f"⚠️ Aviso ao registrar tentativa no banco: {e}")

    if not sucesso:
        historico = _fallback_tentativas.setdefault(ip, [])
        historico.append(datetime.utcnow())


@router.get("/status")
async def gatekeeper_status(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    Retorna o status de autorização do dispositivo e quantas tentativas restam hoje.
    Regra única e igual para todos: 3 tentativas por dia.
    """
    if not settings.GATEKEEPER_ENABLED:
        return {"autorizado": True, "gatekeeper_enabled": False, "tentativas_restantes": 999}

    token = request.cookies.get(settings.SITE_ACCESS_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    autorizado = validar_token_gatekeeper(token)
    ip_cliente = extrair_ip_cliente(request)
    falhas = await contar_tentativas_falhas(ip_cliente, session)
    restantes = max(0, settings.GATEKEEPER_MAX_TENTATIVAS - falhas)

    return {
        "autorizado": autorizado,
        "gatekeeper_enabled": settings.GATEKEEPER_ENABLED,
        "tentativas_restantes": restantes,
        "expira_em_dias": settings.SITE_ACCESS_EXPIRE_DAYS
    }


@router.post("/verificar")
async def verificar_pin(
    data: GatekeeperPinRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session)
):
    """
    Verifica o código de 6 caracteres (letras, números e símbolos).
    Regra estrita e universal: todos os dispositivos têm no máximo 3 tentativas a cada 24 horas.
    """
    if not settings.GATEKEEPER_ENABLED:
        return {"sucesso": True, "mensagem": "Gatekeeper desativado.", "token": None}

    ip_cliente = extrair_ip_cliente(request)

    # 1. Rate Limit Estrito (3 tentativas por dia para todos)
    falhas_atuais = await contar_tentativas_falhas(ip_cliente, session)
    if falhas_atuais >= settings.GATEKEEPER_MAX_TENTATIVAS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Limite de 3 tentativas diárias atingido para este aparelho. Tente novamente em 24 horas."
        )

    pin_enviado = (data.pin or "").strip()
    pin_correto = (settings.SITE_ACCESS_PIN or "").strip()

    # Validação segura contra timing attack
    if not secrets.compare_digest(pin_enviado, pin_correto):
        await registrar_tentativa(ip_cliente, sucesso=False, session=session)
        falhas_atualizadas = await contar_tentativas_falhas(ip_cliente, session)
        restantes = max(0, settings.GATEKEEPER_MAX_TENTATIVAS - falhas_atualizadas)

        if restantes > 0:
            msg_erro = f"Código incorreto. Você tem mais {restantes} tentativa(s) hoje."
        else:
            msg_erro = "Limite de 3 tentativas atingido. O acesso deste aparelho foi bloqueado por 24 horas."

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg_erro
        )

    # Sucesso: registra liberação e emite token de 7 dias
    await registrar_tentativa(ip_cliente, sucesso=True, session=session)
    token = criar_token_gatekeeper(ip_cliente)

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
        "expira_em_dias": settings.SITE_ACCESS_EXPIRE_DAYS,
        "mensagem": "Aparelho liberado com sucesso!"
    }
