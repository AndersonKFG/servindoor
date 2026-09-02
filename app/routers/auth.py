import os
import uuid
from datetime import timedelta, datetime
from typing import Optional
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
templates = Jinja2Templates(directory='app/templates')
VUE_INDEX_PATH = 'app/static/dist/index.html'


def extrair_info_dispositivo(ua: str) -> str:
    if not ua:
        return 'Dispositivo desconhecido'
    os_name = 'Dispositivo'
    if 'iPhone' in ua:
        os_name = 'iPhone'
    elif 'iPad' in ua:
        os_name = 'iPad'
    elif 'Android' in ua:
        os_name = 'Android'
    elif 'Windows' in ua:
        os_name = 'Windows'
    elif 'Macintosh' in ua or 'Mac OS' in ua:
        os_name = 'Mac'
    elif 'Linux' in ua:
        os_name = 'Linux'

    nav_name = 'Navegador'
    if 'Edg/' in ua or 'Edge/' in ua:
        nav_name = 'Microsoft Edge'
    elif 'Chrome/' in ua and 'Chromium' not in ua:
        nav_name = 'Google Chrome'
    elif 'Safari/' in ua and 'Chrome' not in ua:
        nav_name = 'Safari'
    elif 'Firefox/' in ua:
        nav_name = 'Firefox'
    elif 'Opera' in ua or 'OPR/' in ua:
        nav_name = 'Opera'

    return f'{nav_name} ({os_name})'


@router.get('/api/auth/me')
async def get_me(request: Request, session: AsyncSession = Depends(get_session)):
    token = request.cookies.get('access_token')
    if not token:
        return JSONResponse(content={'autenticado': False, 'usuario': None})

    scheme, _, param = token.partition(' ')
    if not scheme or not param:
        return JSONResponse(content={'autenticado': False, 'usuario': None})

    try:
        payload = jwt.decode(param, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        cpf: str = payload.get('sub')
        token_sid: Optional[str] = payload.get('sid')
        if not cpf:
            return JSONResponse(content={'autenticado': False, 'usuario': None})
    except JWTError:
        return JSONResponse(content={'autenticado': False, 'usuario': None})

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
        return JSONResponse(content={'autenticado': False, 'usuario': None})

    # Validação de Sessão Única: se outro dispositivo assumiu a conta
    if user.session_id and token_sid and user.session_id != token_sid:
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                'autenticado': False,
                'sessao_substituida': True,
                'mensagem': 'Sua sessão foi encerrada porque sua conta foi conectada em outro dispositivo.'
            }
        )
        response.delete_cookie('access_token', path='/')
        return response

    roles_list = user.get_roles_list()
    role_str = user.role.value if hasattr(user.role, 'value') else str(user.role)
    cpf_raw = user.cpf or ''
    cpf_fmt = f'{cpf_raw[:3]}.{cpf_raw[3:6]}.{cpf_raw[6:9]}-{cpf_raw[9:]}' if len(cpf_raw) == 11 else cpf_raw

    return JSONResponse(content={
        'autenticado': True,
        'usuario': {
            'id': user.id,
            'cpf': user.cpf,
            'cpf_formatado': cpf_fmt,
            'nome': user.nome,
            'role': role_str,
            'roles': roles_list,
            'is_admin_geral': 'admin_geral' in roles_list,
            'email': user.email,
            'setor': user.setor
        }
    })


@router.get('/login')
async def login_page(request: Request, session: AsyncSession = Depends(get_session)):
    token = request.cookies.get('access_token')
    if token:
        scheme, _, param = token.partition(' ')
        if scheme and param:
            try:
                payload = jwt.decode(param, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                cpf: str = payload.get('sub')
                token_sid: Optional[str] = payload.get('sid')
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
                    if user and (not user.session_id or not token_sid or user.session_id == token_sid):
                        roles_list = user.get_roles_list()
                        if 'admin_geral' in roles_list:
                            return RedirectResponse(url='/admin', status_code=status.HTTP_303_SEE_OTHER)
                        elif 'admin' in roles_list:
                            return RedirectResponse(url='/admin/participantes', status_code=status.HTTP_303_SEE_OTHER)
                        elif 'portaria' in roles_list:
                            return RedirectResponse(url='/portaria', status_code=status.HTTP_303_SEE_OTHER)
                        elif 'entregador' in roles_list:
                            return RedirectResponse(url='/admin/entregas', status_code=status.HTTP_303_SEE_OTHER)
            except Exception:
                pass

    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)
    return templates.TemplateResponse(request=request, name='login.html')


@router.post('/login')
async def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    forcar_login: bool = Form(False),
    session: AsyncSession = Depends(get_session)
):
    cpf_limpo = ''.join([c for c in username if c.isdigit()]).zfill(11)

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

    senha_ok = bool(
        usuario
        and usuario.senha_hash
        and (
            security.verify_password(password, usuario.senha_hash)
            or security.verify_password(password.strip(), usuario.senha_hash)
        )
    )
    if not usuario or not senha_ok:
        if request.url.path.startswith('/api/') or 'application/json' in request.headers.get('accept', ''):
            return JSONResponse(status_code=401, content={'erro': 'CPF ou Senha incorretos.'})
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH, status_code=status.HTTP_401_UNAUTHORIZED)
        return templates.TemplateResponse(
            request=request,
            name='login.html',
            context={'erro': 'CPF ou Senha incorretos.'}
        )

    # Verificação de Sessão Única por Conta (Single Device Enforcement)
    agora = datetime.now()
    cookie_token = request.cookies.get('access_token')
    sid_atual = None
    if cookie_token:
        try:
            _, _, p = cookie_token.partition(' ')
            pay = jwt.decode(p, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            sid_atual = pay.get('sid')
        except Exception:
            pass

    mesmo_dispositivo = bool(sid_atual and usuario.session_id and sid_atual == usuario.session_id)

    sessao_ativa = False
    if usuario.session_id and usuario.ultimo_acesso:
        tempo_decorrido = (agora - usuario.ultimo_acesso).total_seconds()
        if tempo_decorrido < (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60):
            sessao_ativa = True

    # Se já estiver conectado em outro aparelho e NÃO pediu para forçar/desconectar o outro:
    if sessao_ativa and not mesmo_dispositivo and not forcar_login:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                'sucesso': False,
                'sessao_ativa_outro_dispositivo': True,
                'mensagem': 'Você já possui uma sessão ativa em outro dispositivo ou navegador.',
                'dispositivo_anterior': usuario.session_device_info or 'Outro dispositivo',
                'ultimo_acesso': usuario.ultimo_acesso.strftime('%d/%m/%Y às %H:%M') if usuario.ultimo_acesso else 'Recentemente'
            }
        )

    # Criação da nova sessão
    novo_session_id = str(uuid.uuid4())
    info_disp = extrair_info_dispositivo(request.headers.get('user-agent', ''))

    usuario.session_id = novo_session_id
    usuario.session_device_info = info_disp
    usuario.ultimo_acesso = agora
    session.add(usuario)
    await session.commit()

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    roles_list = usuario.get_roles_list()
    role_str = usuario.role.value if hasattr(usuario.role, 'value') else str(usuario.role)
    access_token = security.create_access_token(
        data={
            'sub': usuario.cpf,
            'role': role_str,
            'roles': ','.join(roles_list),
            'sid': novo_session_id
        },
        expires_delta=access_token_expires
    )

    if 'admin_geral' in roles_list:
        destino = '/admin'
    elif 'admin' in roles_list:
        destino = '/admin/participantes'
    elif 'portaria' in roles_list:
        destino = '/portaria'
    elif 'entregador' in roles_list:
        destino = '/admin/entregas'
    else:
        destino = '/'

    if 'application/json' in request.headers.get('accept', ''):
        response = JSONResponse(content={
            'sucesso': True,
            'redirect_url': destino,
            'usuario': {
                'id': usuario.id,
                'cpf': usuario.cpf,
                'nome': usuario.nome,
                'role': role_str,
                'roles': roles_list
            }
        })
    else:
        response = RedirectResponse(url=destino, status_code=status.HTTP_303_SEE_OTHER)

    response.set_cookie(
        key='access_token',
        value=f'Bearer {access_token}',
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite='lax',
        path='/'
    )

    return response


@router.get('/logout')
async def logout(request: Request, session: AsyncSession = Depends(get_session)):
    token = request.cookies.get('access_token')
    if token:
        try:
            _, _, param = token.partition(' ')
            payload = jwt.decode(param, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            cpf = payload.get('sub')
            if cpf:
                stmt = select(Usuario).where(Usuario.cpf == cpf)
                res = await session.execute(stmt)
                usr = res.scalars().first()
                if usr:
                    usr.session_id = None
                    usr.session_device_info = None
                    session.add(usr)
                    await session.commit()
        except Exception:
            pass

    response = RedirectResponse(url='/login', status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie('access_token', path='/')
    return response
