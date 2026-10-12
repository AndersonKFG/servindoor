from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Any
import ipaddress
import secrets

try:
    from jose import jwt
except ImportError:
    jwt = None

try:
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
except ImportError:
    CryptContext = None
    pwd_context = None

try:
    from fastapi import Request
except ImportError:
    Request = Any

from app.core.config import settings
from app.core.cpf import validar_cpf_matematico, limpar_cpf, formatar_cpf, mascarar_cpf

# Configurações carregadas do .env (Seguro!)
def verify_password(plain_password, hashed_password):
    if pwd_context:
        return pwd_context.verify(plain_password, hashed_password)
    return False

def get_password_hash(password):
    if pwd_context:
        return pwd_context.hash(password)
    return password

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    # Aqui usamos a chave que está escondida no .env
    if jwt:
        return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return ""

def is_ip_privado_ou_local(ip_str: str) -> bool:
    if not ip_str:
        return False
    clean_ip = ip_str.strip()
    if clean_ip in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(clean_ip)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except Exception:
        return False

def is_valid_ip(ip_str: str) -> bool:
    if not ip_str:
        return False
    try:
        ipaddress.ip_address(ip_str.strip())
        return True
    except Exception:
        return False

def extrair_ip_cliente(request: Request) -> str:
    """
    Extrai IP real do cliente com proteção estrita contra IP spoofing em proxies reversos/Docker.
    - Se a conexão direta não for de proxy local/privado, ignora headers e usa request.client.host.
    - Se estiver atrás de proxy local/privado, prioriza CF-Connecting-IP, X-Real-IP e sanitiza X-Forwarded-For
      selecionando o IP confiável de borda e descartando headers forjados/malformados.
    """
    client_host = request.client.host if request.client else "127.0.0.1"
    if not is_ip_privado_ou_local(client_host):
        return client_host

    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and is_valid_ip(cf_ip):
        return cf_ip.strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip and is_valid_ip(real_ip):
        return real_ip.strip()

    x_fwd = request.headers.get("x-forwarded-for")
    if x_fwd and x_fwd.strip():
        partes = [p.strip() for p in x_fwd.split(",") if p.strip() and is_valid_ip(p)]
        if partes:
            candidatos_publicos = [p for p in partes if not is_ip_privado_ou_local(p)]
            if candidatos_publicos:
                return candidatos_publicos[-1]
            return partes[0]

    return client_host

def gerar_codigo_2fa_criptografico(digitos: int = 6) -> str:
    """Gera código numérico 2FA utilizando gerador criptograficamente seguro (CSPRNG)"""
    limite = 10 ** digitos
    base = 10 ** (digitos - 1)
    return str(secrets.randbelow(limite - base) + base)

TZ_SAO_PAULO = ZoneInfo("America/Sao_Paulo")

def para_datetime_sp(dt: Optional[datetime]) -> Optional[datetime]:
    """Converte instantes para São Paulo; datas locais legadas recebem esse fuso."""
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ_SAO_PAULO)
    return dt.astimezone(TZ_SAO_PAULO)


def formatar_iso_sp(dt: Optional[datetime]) -> Optional[str]:
    """Formata datetime com o offset de America/Sao_Paulo."""
    localizado = para_datetime_sp(dt)
    return localizado.isoformat() if localizado else None


def formatar_data_sp(
    dt: Optional[datetime], formato: str = "%d/%m/%Y às %H:%M"
) -> Optional[str]:
    """Formata horários para pessoas sem alterar o instante persistido em UTC."""
    localizado = para_datetime_sp(dt)
    return localizado.strftime(formato) if localizado else None

def para_epoch_ms_sp(dt: Optional[datetime]) -> Optional[int]:
    """Converte datetime para timestamp Unix epoch em milissegundos referenciado a America/Sao_Paulo"""
    localizado = para_datetime_sp(dt)
    return int(localizado.timestamp() * 1000) if localizado else None

def para_epoch_ms_utc(dt: Optional[datetime]) -> Optional[int]:
    """Converte datas persistidas em UTC para epoch sem depender do fuso do servidor."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp() * 1000)
