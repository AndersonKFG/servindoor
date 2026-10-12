import os
import uuid
from datetime import timedelta, datetime, timezone
from typing import Optional, Tuple
from fastapi import APIRouter, Request, Depends, Form, status, HTTPException
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from jose import jwt, JWTError

from app.db.session import get_session, async_session
from app.models.all_models import Usuario, UserRole, LoginRateLimit
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
    if user.session_id and token_sid and not user.is_session_valid(token_sid):
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                'autenticado': False,
                'sessao_substituida': True,
                'mensagem': 'Sua sessão foi encerrada porque o limite de 3 dispositivos conectados foi atingido ou sua sessão foi revogada.'
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
            'deve_trocar_senha': bool(getattr(user, 'deve_trocar_senha', False)),
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



PROGRESSIVE_LOGIN_TIERS = [
    {"tentativas": 4, "bloqueio_segundos": 60, "label": "1 minuto"},
    {"tentativas": 3, "bloqueio_segundos": 600, "label": "10 minutos"},
    {"tentativas": 2, "bloqueio_segundos": 1800, "label": "30 minutos"},
]

_fallback_login_ratelimit = {}


async def verificar_rate_limit_login(ip: str) -> Tuple[bool, Optional[str], int]:
    """
    Verifica se o IP está sob bloqueio temporário devido a excesso de tentativas falhas.
    Retorna (permitido, mensagem_bloqueio, segundos_restantes).
    """
    agora = datetime.now(timezone.utc)

    try:
        async with async_session() as db:
            stmt = select(LoginRateLimit).where(LoginRateLimit.ip == ip)
            res = await db.execute(stmt)
            registro = res.scalars().first()
            if registro and registro.bloqueado_ate:
                if registro.bloqueado_ate > agora:
                    segundos_restantes = max(1, int((registro.bloqueado_ate - agora).total_seconds()))
                    minutos = (segundos_restantes + 59) // 60
                    tempo_str = f"{minutos} minuto{'s' if minutos > 1 else ''}" if segundos_restantes > 60 else f"{segundos_restantes} segundo{'s' if segundos_restantes > 1 else ''}"
                    return False, f"Limite de tentativas excedido. Aguarde {tempo_str} antes de tentar novamente.", segundos_restantes
                registro.bloqueado_ate = None
                db.add(registro)
                await db.commit()
    except Exception:
        mem = _fallback_login_ratelimit.get(ip)
        if mem and mem.get("bloqueado_ate") and mem["bloqueado_ate"] > agora:
            segundos_restantes = max(1, int((mem["bloqueado_ate"] - agora).total_seconds()))
            return False, f"Limite de tentativas excedido. Aguarde {segundos_restantes} segundo(s) antes de tentar novamente.", segundos_restantes

    return True, None, 0


async def registrar_falha_login(ip: str) -> Tuple[bool, str, int]:
    """
    Registra tentativa inválida e aplica bloqueio progressivo caso atinja o limite do estágio.
    Retorna (bloqueado_agora, mensagem, segundos_bloqueio).
    """
    agora = datetime.now(timezone.utc)

    try:
        async with async_session() as db:
            stmt = select(LoginRateLimit).where(LoginRateLimit.ip == ip)
            res = await db.execute(stmt)
            registro = res.scalars().first()

            if not registro:
                registro = LoginRateLimit(
                    ip=ip,
                    tentativas_atuais=0,
                    estagio_bloqueio=0,
                    ultima_tentativa=agora
                )
                db.add(registro)

            # Inatividade por mais de 1 hora sem bloqueio reseta o ciclo para o estágio inicial
            if not registro.bloqueado_ate and (agora - registro.ultima_tentativa) > timedelta(hours=1):
                registro.tentativas_atuais = 0
                registro.estagio_bloqueio = 0

            registro.tentativas_atuais += 1
            registro.ultima_tentativa = agora

            estagio = min(registro.estagio_bloqueio, len(PROGRESSIVE_LOGIN_TIERS) - 1)
            tier = PROGRESSIVE_LOGIN_TIERS[estagio]

            if registro.tentativas_atuais >= tier["tentativas"]:
                segundos = tier["bloqueio_segundos"]
                registro.bloqueado_ate = agora + timedelta(seconds=segundos)
                registro.estagio_bloqueio = min(registro.estagio_bloqueio + 1, len(PROGRESSIVE_LOGIN_TIERS) - 1)
                registro.tentativas_atuais = 0
                db.add(registro)
                await db.commit()

                _fallback_login_ratelimit[ip] = {
                    "bloqueado_ate": registro.bloqueado_ate,
                    "estagio": registro.estagio_bloqueio,
                    "tentativas": 0
                }

                msg = f"Limite de tentativas excedido. Aguarde {tier['label']} antes de tentar novamente."
                return True, msg, segundos

            db.add(registro)
            await db.commit()

            _fallback_login_ratelimit[ip] = {
                "bloqueado_ate": None,
                "estagio": registro.estagio_bloqueio,
                "tentativas": registro.tentativas_atuais
            }

            return False, "CPF ou senha inválidos.", 0

    except Exception:
        mem = _fallback_login_ratelimit.setdefault(ip, {"bloqueado_ate": None, "estagio": 0, "tentativas": 0})
        mem["tentativas"] += 1
        estagio = min(mem["estagio"], len(PROGRESSIVE_LOGIN_TIERS) - 1)
        tier = PROGRESSIVE_LOGIN_TIERS[estagio]
        if mem["tentativas"] >= tier["tentativas"]:
            segundos = tier["bloqueio_segundos"]
            mem["bloqueado_ate"] = agora + timedelta(seconds=segundos)
            mem["estagio"] = min(mem["estagio"] + 1, len(PROGRESSIVE_LOGIN_TIERS) - 1)
            mem["tentativas"] = 0
            return True, f"Limite de tentativas excedido. Aguarde {tier['label']} antes de tentar novamente.", segundos
        return False, "CPF ou senha inválidos.", 0


async def limpar_rate_limit_login(ip: str) -> None:
    """Limpa tentativas e bloqueios para o IP após login bem-sucedido."""
    _fallback_login_ratelimit.pop(ip, None)
    try:
        async with async_session() as db:
            stmt = select(LoginRateLimit).where(LoginRateLimit.ip == ip)
            res = await db.execute(stmt)
            registro = res.scalars().first()
            if registro:
                registro.tentativas_atuais = 0
                registro.estagio_bloqueio = 0
                registro.bloqueado_ate = None
                db.add(registro)
                await db.commit()
    except Exception:
        pass


@router.post('/login')

async def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    forcar_login: bool = Form(False),
    session: AsyncSession = Depends(get_session)
):
    ip_cliente = security.extrair_ip_cliente(request)

    # 1. Verificação prévia de bloqueio por tentativas excessivas
    permitido, msg_bloqueio, seg_restantes = await verificar_rate_limit_login(ip_cliente)
    if not permitido:
        if request.url.path.startswith('/api/') or 'application/json' in request.headers.get('accept', ''):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    'erro': msg_bloqueio,
                    'bloqueado': True,
                    'segundos_restantes': seg_restantes
                }
            )
        return templates.TemplateResponse(
            request=request,
            name='login.html',
            context={'erro': msg_bloqueio},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS
        )

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
        bloqueado, msg_erro, seg_restantes = await registrar_falha_login(ip_cliente)
        status_code = status.HTTP_429_TOO_MANY_REQUESTS if bloqueado else status.HTTP_401_UNAUTHORIZED
        content = {
            'erro': msg_erro,
            'bloqueado': bloqueado,
            'segundos_restantes': seg_restantes
        }
        if request.url.path.startswith('/api/') or 'application/json' in request.headers.get('accept', ''):
            return JSONResponse(status_code=status_code, content=content)
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH, status_code=status_code)
        return templates.TemplateResponse(
            request=request,
            name='login.html',
            context={'erro': msg_erro},
            status_code=status_code
        )

    # Login bem-sucedido: limpa o contador de tentativas para este IP
    await limpar_rate_limit_login(ip_cliente)

    # Verificação de Sessão Única por Conta (Single Device Enforcement)
    agora = datetime.now(timezone.utc)
    cookie_token = request.cookies.get('access_token')
    sid_atual = None
    if cookie_token:
        try:
            _, _, p = cookie_token.partition(' ')
            pay = jwt.decode(p, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            sid_atual = pay.get('sid')
        except Exception:
            pass

    sessions = usuario.get_active_sessions()
    mesmo_dispositivo = bool(sid_atual and any(s.get("sid") == sid_atual for s in sessions))

    # Limite estrito de 3 dispositivos conectados simultaneamente:
    if len(sessions) >= 3 and not mesmo_dispositivo and not forcar_login:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                'sucesso': False,
                'sessao_ativa_outro_dispositivo': True,
                'mensagem': 'Você já possui o limite máximo de 3 dispositivos conectados simultaneamente à sua conta.',
                'dispositivo_anterior': f'{len(sessions)} dispositivos conectados',
                'dispositivos_ativos': len(sessions),
                'limite_maximo': 3,
                'ultimo_acesso': security.formatar_data_sp(usuario.ultimo_acesso) if usuario.ultimo_acesso else 'Recentemente'
            }
        )

    # Criação da nova sessão (mantém no máximo 3)
    novo_session_id = str(uuid.uuid4())
    info_disp = extrair_info_dispositivo(request.headers.get('user-agent', ''))

    usuario.add_active_session(novo_session_id, info_disp, max_sessions=3)
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
@router.post('/logout')
@router.post('/api/auth/logout')
async def logout(request: Request, session: AsyncSession = Depends(get_session)):
    token = request.cookies.get('access_token')
    if token:
        try:
            _, _, param = token.partition(' ')
            payload = jwt.decode(param, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            cpf = payload.get('sub')
            sid = payload.get('sid')
            if cpf:
                stmt = select(Usuario).where(Usuario.cpf == cpf)
                res = await session.execute(stmt)
                usr = res.scalars().first()
                if usr:
                    usr.remove_active_session(sid)
                    usr.session_device_info = None
                    session.add(usr)
                    await session.commit()
        except Exception:
            pass

    if request.url.path.startswith('/api/') or 'application/json' in request.headers.get('accept', ''):
        response = JSONResponse(content={'sucesso': True, 'mensagem': 'Sess?o encerrada com sucesso.'})
    else:
        response = RedirectResponse(url='/login', status_code=status.HTTP_303_SEE_OTHER)

    response.delete_cookie('access_token', path='/')
    return response


class AlterarSenhaObrigatoriaRequest(BaseModel):
    nova_senha: str
    confirmacao_senha: str

@router.post("/api/auth/alterar-senha-obrigatoria")
async def alterar_senha_obrigatoria(
    req: AlterarSenhaObrigatoriaRequest,
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Permite ao membro da equipe definir sua senha pessoal definitiva no primeiro login"""
    cookie_token = request.cookies.get('access_token')
    if not cookie_token:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    try:
        _, _, p = cookie_token.partition(' ')
        payload = jwt.decode(p, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        cpf = payload.get('sub')
    except Exception:
        raise HTTPException(status_code=401, detail="Sessão inválida.")

    res = await session.execute(select(Usuario).where(Usuario.cpf == cpf, Usuario.deleted_at.is_(None)))
    usuario = res.scalars().first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    if len(req.nova_senha) < 6:
        raise HTTPException(status_code=400, detail="A nova senha deve possuir pelo menos 6 caracteres.")

    if req.nova_senha != req.confirmacao_senha:
        raise HTTPException(status_code=400, detail="A confirmação de senha não confere.")

    usuario.senha_hash = security.get_password_hash(req.nova_senha)
    usuario.deve_trocar_senha = False
    session.add(usuario)
    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": "Nova senha cadastrada com sucesso!"
    })
