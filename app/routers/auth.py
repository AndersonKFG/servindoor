import os
from datetime import timedelta, datetime
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from jose import jwt, JWTError

from app.db.session import get_session
from app.models.all_models import Usuario, UserRole
from app.core import security
from app.core.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
VUE_INDEX_PATH = "app/static/dist/index.html"

@router.get("/api/auth/me")
async def get_me(request: Request, session: AsyncSession = Depends(get_session)):
    """Retorna os dados do usuário autenticado e todas as suas roles atribuídas"""
    token = request.cookies.get("access_token")
    if not token:
        return JSONResponse(content={"autenticado": False, "usuario": None})

    scheme, _, param = token.partition(" ")
    if not scheme or not param:
        return JSONResponse(content={"autenticado": False, "usuario": None})

    try:
        payload = jwt.decode(param, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        cpf: str = payload.get("sub")
        if not cpf:
            return JSONResponse(content={"autenticado": False, "usuario": None})
    except JWTError:
        return JSONResponse(content={"autenticado": False, "usuario": None})

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
        return JSONResponse(content={"autenticado": False, "usuario": None})

    roles_list = user.get_roles_list()
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    cpf_raw = user.cpf or ""
    cpf_fmt = f"{cpf_raw[:3]}.{cpf_raw[3:6]}.{cpf_raw[6:9]}-{cpf_raw[9:]}" if len(cpf_raw) == 11 else cpf_raw

    return JSONResponse(content={
        "autenticado": True,
        "usuario": {
            "id": user.id,
            "cpf": user.cpf,
            "cpf_formatado": cpf_fmt,
            "nome": user.nome,
            "role": role_str,
            "roles": roles_list,
            "is_admin_geral": "admin_geral" in roles_list,
            "email": user.email,
            "setor": user.setor
        }
    })

@router.get("/login")
async def login_page(request: Request, session: AsyncSession = Depends(get_session)):
    token = request.cookies.get("access_token")
    if token:
        scheme, _, param = token.partition(" ")
        if scheme and param:
            try:
                payload = jwt.decode(param, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                cpf: str = payload.get("sub")
                if cpf:
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
                    if user:
                        roles_list = user.get_roles_list()
                        if "admin_geral" in roles_list:
                            return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
                        elif "admin" in roles_list:
                            return RedirectResponse(url="/admin/participantes", status_code=status.HTTP_303_SEE_OTHER)
                        elif "portaria" in roles_list:
                            return RedirectResponse(url="/portaria", status_code=status.HTTP_303_SEE_OTHER)
                        elif "entregador" in roles_list:
                            return RedirectResponse(url="/admin/entregas", status_code=status.HTTP_303_SEE_OTHER)
            except Exception:
                pass

    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)
    return templates.TemplateResponse(request=request, name="login.html")

@router.post("/login")
async def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    # 1. Limpar CPF
    cpf_limpo = "".join([c for c in username if c.isdigit()]).zfill(11)

    # 2. Buscar Usuario (ativo e não excluído)
    statement = (
        select(Usuario)
        .where(
            Usuario.cpf == cpf_limpo,
            Usuario.deleted_at.is_(None),
            Usuario.ativo == True
        )
    )
    result = await session.execute(statement)
    usuario = result.scalars().first()

    # 3. Validar Credenciais
    senha_ok = bool(
        usuario
        and usuario.senha_hash
        and (
            security.verify_password(password, usuario.senha_hash)
            or security.verify_password(password.strip(), usuario.senha_hash)
        )
    )
    if not usuario or not senha_ok:
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH, status_code=status.HTTP_401_UNAUTHORIZED)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"erro": "CPF ou Senha incorretos."}
        )

    # 4. Atualiza último acesso
    usuario.ultimo_acesso = datetime.now()
    session.add(usuario)
    await session.commit()

    # 5. Sucesso! Gerar Token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    roles_list = usuario.get_roles_list()
    role_str = usuario.role.value if hasattr(usuario.role, "value") else str(usuario.role)
    access_token = security.create_access_token(
        data={"sub": usuario.cpf, "role": role_str, "roles": ",".join(roles_list)},
        expires_delta=access_token_expires
    )

    # 6. Redirecionar conforme prioridade de permissão
    if "admin_geral" in roles_list:
        destino = "/admin"
    elif "admin" in roles_list:
        destino = "/admin/participantes"
    elif "portaria" in roles_list:
        destino = "/portaria"
    elif "entregador" in roles_list:
        destino = "/admin/entregas"
    else:
        destino = "/"
    
    response = RedirectResponse(url=destino, status_code=status.HTTP_303_SEE_OTHER)
    
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        path="/"
    )
    
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token", path="/")
    return response
