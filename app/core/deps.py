from typing import Optional
from fastapi import Request, HTTPException, status, Depends
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.db.session import get_session
from app.models.all_models import Usuario, UserRole

async def get_current_user(
    request: Request, 
    session: AsyncSession = Depends(get_session)
) -> Usuario:
    """
    Busca o token no cookie, decodifica e retorna o usuário ativo (não excluído).
    Se der errado, lança exceção e força o login.
    """
    token = request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )

    scheme, _, param = token.partition(" ")
    if not scheme or not param:
         raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )

    try:
        payload = jwt.decode(
            param, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        cpf: str = payload.get("sub")
        token_sid: Optional[str] = payload.get("sid")
        if not cpf:
            raise HTTPException(status_code=401, detail="Token inválido")
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )

    # Busca o usuário no banco garantindo que NÃO foi soft-deleted
    statement = (
        select(Usuario)
        .where(
            Usuario.cpf == cpf,
            Usuario.deleted_at.is_(None),
            Usuario.ativo == True
        )
    )
    result = await session.execute(statement)
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado ou inativo.")

    # Validação de Sessão Única por Conta (Single Device Enforcement)
    # Se o usuário possui um session_id ativo no banco e o token deste request tem um sid diferente,
    # significa que a conta foi conectada em outro dispositivo e esta sessão foi revogada!
    if user.session_id and token_sid and user.session_id != token_sid:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão encerrada: sua conta foi conectada em outro dispositivo."
            )
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login?motivo=sessao_substituida"}
        )

    # Atualiza o timestamp de último acesso
    from datetime import datetime
    user.ultimo_acesso = datetime.now()
    session.add(user)
    await session.commit()

    return user


async def get_current_admin_geral(
    current_user: Usuario = Depends(get_current_user)
) -> Usuario:
    """Verifica se possui privilégios de Administrador Geral (Superadmin)"""
    user_roles = current_user.get_roles_list()
    if "admin_geral" not in user_roles and current_user.role != UserRole.admin_geral:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Acesso negado. Ação restrita exclusivamente ao Administrador Geral."
        )
    return current_user


async def get_current_admin(
    current_user: Usuario = Depends(get_current_user)
) -> Usuario:
    """Verifica se é Administrador (Geral ou Comum)"""
    if not current_user.has_role("admin", "admin_geral"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Acesso negado. Requer privilégios de Administrador."
        )
    return current_user


async def get_current_portaria(
    current_user: Usuario = Depends(get_current_user)
) -> Usuario:
    """Permite Portaria, Administrador ou Administrador Geral"""
    if not current_user.has_role("portaria", "admin", "admin_geral"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Acesso negado. Requer permissão da equipe de Portaria."
        )
    return current_user


async def get_current_entregador(
    current_user: Usuario = Depends(get_current_user)
) -> Usuario:
    """Permite Entregador de Prêmios, Administrador ou Administrador Geral"""
    if not current_user.has_role("entregador", "admin", "admin_geral"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Acesso negado. Requer permissão da equipe de Entrega de Prêmios."
        )
    return current_user


async def get_current_staff(
    current_user: Usuario = Depends(get_current_user)
) -> Usuario:
    """Permite qualquer membro da equipe operacional"""
    user_roles = current_user.get_roles_list()
    allowed = ["admin_geral", "admin", "portaria", "entregador"]
    if not any(r in allowed for r in user_roles) and current_user.role not in [
        UserRole.admin_geral, UserRole.admin, UserRole.portaria, UserRole.entregador
    ]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Acesso restrito a membros da equipe."
        )
    return current_user
