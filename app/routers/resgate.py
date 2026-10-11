import asyncio
import base64
import collections
import hashlib
import hmac
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, Query, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, or_, and_, desc, update, delete
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import get_session, async_session
from app.models.all_models import (
    Lote, Usuario, Ingresso, Secretaria, ReservaIngresso, UserRole,
    SolicitacaoValidacao, RateLimitTentativa
)
from app.core.security import extrair_ip_cliente
from app.core.cpf import limpar_cpf, formatar_cpf, mascarar_cpf, validar_cpf_matematico
from app.services.email_service import send_ticket_email_async, send_validation_pending_email_async
from app.services.validacao_servidor_service import ServidorValidationService
from app.core.events import lote_event_hub
from app.routers.public import invalidar_cache_live_status

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

FOTOS_DIR = "app/static/uploads/fotos"
os.makedirs(FOTOS_DIR, exist_ok=True)
VUE_INDEX_PATH = "app/static/dist/index.html"

COOKIE_BROWSER_ID = "festa_browser_id"
COOKIE_DEVICE_LEGACY = "festa_device_id"

# Rate Limit Global por IP via PostgreSQL (suporta 4 workers do Gunicorn)
# Calibrado para até 300 requisições/min por IP público, acomodando com folga 150+ participantes
# em redes NAT corporativas/órgãos públicos sem bloqueio coletivo indevido.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUISICOES = int(os.getenv("RATE_LIMIT_RESERVA_MAX_IP", "300"))

# Estrutura e função para retrocompatibilidade com testes legados em memória
_ip_reserva_requisicoes = {}

def verificar_rate_limit_ip_reserva(ip: str, max_requisicoes: int = 60, janela_segundos: int = 60) -> bool:
    """Implementação em memória para retrocompatibilidade com testes unitários locais."""
    agora = time.time()
    limite = agora - janela_segundos
    if ip not in _ip_reserva_requisicoes:
        _ip_reserva_requisicoes[ip] = []
    _ip_reserva_requisicoes[ip] = [ts for ts in _ip_reserva_requisicoes[ip] if ts > limite]
    if len(_ip_reserva_requisicoes[ip]) >= max_requisicoes:
        return False
    _ip_reserva_requisicoes[ip].append(agora)
    return True

# Throttle da varredura de expiração para evitar contenção de locks no PostgreSQL
_ultima_varredura_expiracao = 0.0
_EXPIRACAO_THROTTLE_SEGUNDOS = 3.0


def is_conexao_segura(request: Request) -> bool:
    """Detecta se a requisição é HTTPS (direta ou através de reverse proxy)"""
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
        or getattr(settings, "ENVIRONMENT", "") == "production"
    )


def assinar_browser_token(payload: str) -> str:
    """Gera assinatura criptográfica HMAC-SHA256 para o identificador opaco do navegador."""
    chave = settings.SECRET_KEY.encode("utf-8")
    sig = hmac.new(chave, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def validar_browser_token(token_completo: Optional[str]) -> Optional[str]:
    """
    Valida a autenticidade do token emitido pelo servidor via HMAC-SHA256.
    Retorna o payload original se a assinatura for autêntica; caso contrário, None.
    """
    if not token_completo or "." not in token_completo:
        return None
    partes = token_completo.split(".", 1)
    if len(partes) != 2:
        return None
    payload, sig = partes
    if len(payload) < 16 or len(sig) != 32:
        return None
    chave = settings.SECRET_KEY.encode("utf-8")
    expected_sig = hmac.new(chave, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    if hmac.compare_digest(sig, expected_sig):
        return payload
    return None


def hash_token(token: str) -> str:
    """Gera hash SHA-256 seguro do payload do identificador de navegador para persistência"""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def obter_ou_criar_browser_id(request: Request) -> tuple[str, str, bool]:
    """
    Extrai e valida a assinatura criptográfica do cookie emitido pelo servidor.
    Se o cookie for arbitrário, forjado, adulterado ou ausente:
    Descarta imediatamente e emite um novo identificador assinado com HMAC-SHA256.
    Retorna: (signed_token, hash_sha256, is_novo)
    """
    cookie_raw = request.cookies.get(COOKIE_BROWSER_ID)
    valid_payload = validar_browser_token(cookie_raw)
    if valid_payload:
        return cookie_raw, hash_token(valid_payload), False

    novo_payload = secrets.token_urlsafe(32)
    novo_signed = assinar_browser_token(novo_payload)
    return novo_signed, hash_token(novo_payload), True


async def verificar_e_registrar_rate_limit_db(ip: str, session: Optional[AsyncSession] = None) -> bool:
    """
    Rate limiter atômico compartilhado via banco de dados entre múltiplos workers do Gunicorn.
    Utiliza sessão dedicada independente para NUNCA comitar ou liberar prematuramente
    o lock de transação ('SELECT ... FOR UPDATE') da sessão principal do chamador.
    """
    agora_utc = datetime.utcnow()
    limite_janela = agora_utc - timedelta(seconds=_RATE_LIMIT_WINDOW_SECONDS)

    try:
        async with async_session() as rl_session:
            stmt_count = select(func.count(RateLimitTentativa.id)).where(
                RateLimitTentativa.ip == ip,
                RateLimitTentativa.acao == "reserva",
                RateLimitTentativa.criado_em > limite_janela
            )
            res = await rl_session.execute(stmt_count)
            total_tentativas = res.scalar() or 0

            if total_tentativas >= _RATE_LIMIT_MAX_REQUISICOES:
                return False

            registro = RateLimitTentativa(ip=ip, acao="reserva", criado_em=agora_utc)
            rl_session.add(registro)
            await rl_session.commit()

            # Limpeza periódica leve (2% das chamadas) de registros com mais de 10 minutos
            if secrets.randbelow(50) == 0:
                corte_antigo = agora_utc - timedelta(minutes=10)
                stmt_del = delete(RateLimitTentativa).where(RateLimitTentativa.criado_em < corte_antigo)
                await rl_session.execute(stmt_del)
                await rl_session.commit()

            return True
    except Exception:
        return True


async def expirar_reservas_vencidas(session: AsyncSession) -> int:
    """
    Atualiza atomicamente para 'expirada' as reservas vencidas com throttle de 3 segundos
    para evitar contenção excessiva de escrita e table-scan lock no PostgreSQL durante picos de abertura.
    """
    global _ultima_varredura_expiracao
    agora_mono = time.monotonic()
    if agora_mono - _ultima_varredura_expiracao < _EXPIRACAO_THROTTLE_SEGUNDOS:
        return 0
    _ultima_varredura_expiracao = agora_mono

    agora = datetime.now()
    try:
        stmt = (
            update(ReservaIngresso)
            .where(
                ReservaIngresso.status == "ativa",
                ReservaIngresso.expira_em <= agora
            )
            .values(status="expirada")
        )
        res = await session.execute(stmt)
        await session.commit()
        return res.rowcount or 0
    except Exception:
        await session.rollback()
        return 0


async def verificar_elegibilidade_participante(cpf_limpo: str, session: AsyncSession) -> tuple[bool, str, str, Optional[Usuario]]:
    """
    Valida a elegibilidade do participante (CPF) antes de conceder ou confirmar vaga.
    Retorna (valido, tipo_erro, mensagem, usuario).
    """
    if len(cpf_limpo) != 11:
        return False, "formato_invalido", "CPF incompleto. Digite os 11 dígitos.", None
    if not validar_cpf_matematico(cpf_limpo):
        return False, "cpf_invalido", "CPF inválido. Verifique os números digitados.", None

    stmt_usuario = select(Usuario).where(
        Usuario.cpf == cpf_limpo,
        Usuario.deleted_at.is_(None)
    )
    res_usuario = await session.execute(stmt_usuario)
    usuario = res_usuario.scalars().first()

    if usuario:
        if usuario.role != UserRole.servidor:
            return False, "equipe", "Não é possível resgatar para esse CPF.", usuario
        if getattr(usuario, "bloqueado_resgate", False):
            return False, "bloqueado", "Não é possível resgatar para esse CPF. Resgate bloqueado pela administração.", usuario

        stmt_ing = select(Ingresso).where(
            Ingresso.usuario_id == usuario.id,
            Ingresso.deleted_at.is_(None)
        )
        res_ing = await session.execute(stmt_ing)
        if res_ing.scalars().first():
            return False, "ingresso_existente", "Já foi realizado um resgate para este CPF", usuario

        stmt_solic = select(SolicitacaoValidacao).where(
            SolicitacaoValidacao.usuario_id == usuario.id,
            SolicitacaoValidacao.status.in_(["pendente_analise", "aprovado"])
        )
        res_solic = await session.execute(stmt_solic)
        if res_solic.scalars().first():
            return False, "solicitacao_existente", "Já foi realizado um resgate para este CPF", usuario

    return True, "", "", usuario


# ============================================================================
# 1. VALIDAÇÃO DE CPF EM SEGUNDO PLANO COM LIBERAÇÃO DE RESERVA SECUNDÁRIA
# ============================================================================
@router.get("/api/resgate/validar-cpf")
async def validar_cpf_resgate(
    request: Request,
    cpf: str = Query(..., description="CPF com ou sem pontuação"),
    token_reserva: Optional[str] = Query(None, description="Token da reserva ativa atual"),
    session: AsyncSession = Depends(get_session)
):
    cpf_limpo = "".join([ch for ch in cpf if ch.isdigit()]).zfill(11)
    await expirar_reservas_vencidas(session)

    _, current_browser_hash, _ = obter_ou_criar_browser_id(request)

    # Expiração direcionada atômica para o CPF e navegador desta chamada caso o sweeper global esteja em throttle
    agora_val = datetime.now()
    stmt_expirar_direcionada = (
        update(ReservaIngresso)
        .where(
            ReservaIngresso.status == "ativa",
            ReservaIngresso.expira_em <= agora_val,
            or_(
                ReservaIngresso.cpf == cpf_limpo,
                ReservaIngresso.browser_token_hash == current_browser_hash
            )
        )
        .values(status="expirada")
    )
    await session.execute(stmt_expirar_direcionada)

    # Helper seguro: Libera a reserva secundária desta chamada em caso de erro definitivo
    async def _cancelar_reserva_secundaria_se_pertencer():
        if not token_reserva:
            return
        stmt_sec = select(ReservaIngresso).where(
            ReservaIngresso.token == token_reserva,
            ReservaIngresso.status == "ativa"
        )
        r_sec = await session.execute(stmt_sec)
        res_sec = r_sec.scalars().first()
        # Cancela SOMENTE se a reserva secundária pertencer a este navegador ou não tiver hash
        if res_sec and (res_sec.browser_token_hash == current_browser_hash or not res_sec.browser_token_hash):
            res_sec.status = "cancelada"
            res_sec.expira_em = datetime(2000, 1, 1)
            session.add(res_sec)
            try:
                await session.commit()
                invalidar_cache_live_status()

                stmt_cnt = select(func.count(ReservaIngresso.id)).where(
                    ReservaIngresso.lote_id == res_sec.lote_id,
                    ReservaIngresso.status == "ativa",
                    ReservaIngresso.expira_em > datetime.now()
                )
                cnt = (await session.execute(stmt_cnt)).scalar() or 0
                st_lote = select(Lote).where(Lote.id == res_sec.lote_id)
                l_obj = (await session.execute(st_lote)).scalars().first()
                v_disp = max(0, l_obj.quantidade_total - (l_obj.quantidade_resgatada + cnt)) if l_obj else 0

                await lote_event_hub.broadcast(
                    "LOTE_ATUALIZADO",
                    {
                        "tipo": "reserva_liberada",
                        "lote_id": res_sec.lote_id,
                        "device_id": res_sec.device_id,
                        "token_reserva": res_sec.token,
                        "motivo": "reserva_duplicada"
                    }
                )
            except Exception:
                await session.rollback()

    valido, tipo_erro, mensagem, usuario = await verificar_elegibilidade_participante(cpf_limpo, session)
    if not valido:
        # Apenas reporta a inelegibilidade do CPF para o formulário exibir a mensagem amigável em tempo real.
        # Não cancela a vaga reservada da sessão para permitir que o usuário corrija qualquer erro de digitação.
        return JSONResponse(content={
            "valido": False,
            "tipo_erro": tipo_erro,
            "mensagem": mensagem
        })

    agora = datetime.now()
    # Verifica se este CPF já possui outra reserva ativa R1 em andamento em QUALQUER lote
    stmt_res_ativa = select(ReservaIngresso).where(
        ReservaIngresso.cpf == cpf_limpo,
        ReservaIngresso.status == "ativa",
        ReservaIngresso.expira_em > agora
    )
    res_ativa = await session.execute(stmt_res_ativa)
    reserva_ativa_cpf = res_ativa.scalars().first()

    if reserva_ativa_cpf and (not token_reserva or reserva_ativa_cpf.token != token_reserva):
        # O CPF já possui outra reserva ativa R1!
        # A reserva secundária R2 deste navegador é cancelada para liberar a vaga para outros servidores.
        # A reserva R1 original permanece intacta!
        await _cancelar_reserva_secundaria_se_pertencer()
        return JSONResponse(content={
            "valido": False,
            "tipo_erro": "reserva_existente",
            "mensagem": "Este CPF já possui uma reserva ativa em andamento."
        })

    # Se token_reserva foi fornecido, associa com segurança o CPF à reserva existente desta sessão
    if token_reserva:
        stmt_res_token = select(ReservaIngresso).where(
            ReservaIngresso.token == token_reserva,
            ReservaIngresso.status == "ativa",
            ReservaIngresso.expira_em > agora
        )
        res_token = await session.execute(stmt_res_token)
        reserva_token_obj = res_token.scalars().first()
        if reserva_token_obj and (reserva_token_obj.browser_token_hash == current_browser_hash or not reserva_token_obj.browser_token_hash):
            reserva_token_obj.cpf = cpf_limpo
            session.add(reserva_token_obj)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await _cancelar_reserva_secundaria_se_pertencer()
                return JSONResponse(content={
                    "valido": False,
                    "tipo_erro": "reserva_existente",
                    "mensagem": "Este CPF já possui uma reserva ativa em andamento."
                })

    if usuario:
        partes = usuario.nome.strip().split()
        if len(partes) > 1:
            nome_ofuscado = f"{partes[0]} " + " ".join([f"{p[0]}***" for p in partes[1:]])
        else:
            nome_ofuscado = partes[0] if partes else "Servidor"

        return JSONResponse(content={
            "valido": True,
            "usuario_existente": True,
            "nome_preview": nome_ofuscado,
            "mensagem": f"CPF localizado ({nome_ofuscado}). Prossiga com o preenchimento."
        })

    return JSONResponse(content={
        "valido": True,
        "usuario_existente": False
    })


# ============================================================================
# 2. STATUS DA RESERVA EM TEMPO REAL
# ============================================================================
@router.get("/api/resgate/status-reserva")
async def status_reserva(
    request: Request,
    token_reserva: str = Query(...),
    session: AsyncSession = Depends(get_session)
):
    agora = datetime.now()
    await expirar_reservas_vencidas(session)

    stmt = select(ReservaIngresso).where(ReservaIngresso.token == token_reserva)
    res = await session.execute(stmt)
    reserva = res.scalars().first()

    if not reserva:
        return JSONResponse(content={"status": "inexistente", "ativa": False, "motivo": "nao_encontrada"})

    if reserva.status == "concluida" or reserva.utilizada:
        return JSONResponse(content={"status": "utilizada", "ativa": False, "motivo": "utilizada"})

    if reserva.status == "cancelada" or reserva.expira_em <= datetime(2000, 1, 2):
        return JSONResponse(content={"status": "desistida", "ativa": False, "motivo": "desistida"})

    if reserva.status == "expirada" or agora > reserva.expira_em:
        if reserva.status == "ativa":
            reserva.status = "expirada"
            session.add(reserva)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
        return JSONResponse(content={"status": "expirada", "ativa": False, "motivo": "tempo_esgotado"})

    segundos_restantes = max(1, int((reserva.expira_em - agora).total_seconds()))
    return JSONResponse(content={
        "status": "ativa",
        "ativa": True,
        "segundos_restantes": segundos_restantes,
        "expira_em_ms": int(reserva.expira_em.timestamp() * 1000)
    })


# ============================================================================
# 3. DESISTIR DA VAGA RESERVADA (LIBERAÇÃO IMEDIATA)
# ============================================================================
@router.post("/api/resgate/desistir")
async def desistir_reserva(
    request: Request,
    token_reserva: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    await expirar_reservas_vencidas(session)
    _, current_browser_hash, _ = obter_ou_criar_browser_id(request)

    stmt = select(ReservaIngresso).where(
        ReservaIngresso.token == token_reserva
    )
    res = await session.execute(stmt)
    reserva = res.scalars().first()

    if reserva and reserva.status == "ativa" and not reserva.utilizada:
        # Valida que quem está desistindo é o navegador detentor da reserva
        if reserva.browser_token_hash and reserva.browser_token_hash != current_browser_hash:
            return JSONResponse(
                status_code=403,
                content={"sucesso": False, "mensagem": "Acesso não autorizado para desistir desta reserva."}
            )

        reserva.status = "cancelada"
        reserva.expira_em = datetime(2000, 1, 1)
        session.add(reserva)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            return JSONResponse(status_code=500, content={"sucesso": False, "mensagem": "Erro ao cancelar reserva."})

        # Recalcula contadores consistentes no banco apos commit
        stmt_count = select(func.count(ReservaIngresso.id)).where(
            ReservaIngresso.lote_id == reserva.lote_id,
            ReservaIngresso.status == "ativa",
            ReservaIngresso.expira_em > datetime.now()
        )
        res_count = await session.execute(stmt_count)
        reservas_ativas = res_count.scalar() or 0

        stmt_lote = select(Lote).where(Lote.id == reserva.lote_id)
        res_lote = await session.execute(stmt_lote)
        lote_obj = res_lote.scalars().first()
        vagas_disp = max(0, lote_obj.quantidade_total - (lote_obj.quantidade_resgatada + reservas_ativas)) if lote_obj else 0

        invalidar_cache_live_status()
        await lote_event_hub.broadcast(
            "LOTE_ATUALIZADO",
            {
                "tipo": "reserva_liberada",
                "lote_id": reserva.lote_id,
                "device_id": reserva.device_id,
                "token_reserva": token_reserva,
                "motivo": "desistencia"
            }
        )

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": "Vaga liberada com sucesso."
    })


# ============================================================================
# 4. PÁGINA E API DE RESGATE COM RESERVA ATÔMICA & COOKIE CRIPTOGRÁFICO
# ============================================================================
@router.get("/resgate/{lote_id}")
@router.get("/api/resgate/{lote_id}")
async def pagina_resgate(
    request: Request, 
    lote_id: int, 
    device_fingerprint: Optional[str] = Query(None),
    cpf: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session)
):
    if not request.url.path.startswith("/api/") and "text/html" in request.headers.get("accept", "") and os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)

    agora = datetime.now()
    server_time_ms = int(agora.timestamp() * 1000)
    client_ip = extrair_ip_cliente(request)
    
    # Expirar reservas vencidas com throttle
    await expirar_reservas_vencidas(session)

    # Identidade autenticada do navegador via Cookie com assinatura criptográfica HMAC-SHA256
    browser_token, browser_token_hash, is_new_browser_cookie = obter_ou_criar_browser_id(request)
    header_fp = request.headers.get("x-device-fingerprint")

    # CPF opcional passado no inicio do resgate
    cpf_limpo = "".join([ch for ch in cpf if ch.isdigit()]).zfill(11) if cpf else None
    if cpf_limpo:
        valido, tipo_erro, msg, _ = await verificar_elegibilidade_participante(cpf_limpo, session)
        if not valido:
            if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                return JSONResponse(status_code=400, content={"codigo": tipo_erro, "detail": msg, "mensagem": msg})
            raise HTTPException(status_code=400, detail=msg)

    # 1. Busca o Lote com bloqueio atômico para controle de concorrência
    stmt_lote = select(Lote).where(Lote.id == lote_id).with_for_update()
    res_lote = await session.execute(stmt_lote)
    lote = res_lote.scalars().first()
    if not lote or not lote.ativo:
        msg = "Este lote está temporariamente pausado ou inativo pela organização."
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            return JSONResponse(status_code=400, content={"codigo": "lote_inativo", "detail": msg, "mensagem": msg})
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH)
        return templates.TemplateResponse(request=request, name="erro.html", context={"mensagem": msg})

    # 2. Regra Soberana de Horário
    if lote.data_abertura and agora < lote.data_abertura:
        msg = f"O período de resgate deste lote ainda não iniciou. Abertura prevista para {lote.data_abertura.strftime('%d/%m/%Y às %H:%M')}."
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            return JSONResponse(status_code=400, content={"codigo": "nao_iniciado", "detail": msg, "mensagem": msg})
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH)
        return templates.TemplateResponse(request=request, name="erro.html", context={"mensagem": msg})

    if lote.data_fechamento and agora > lote.data_fechamento:
        msg = "O período de resgate deste lote já foi encerrado."
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            return JSONResponse(status_code=400, content={"codigo": "encerrado", "detail": msg, "mensagem": msg})
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH)
        return templates.TemplateResponse(request=request, name="erro.html", context={"mensagem": msg})

    # 2.5 Expiração direcionada atômica para o CPF e navegador desta requisição
    # Garante que reservas vencidas (expira_em <= agora) deste participante/navegador não gerem
    # falso conflito no índice único uq_reserva_*_ativa enquanto o sweeper global estiver em throttle.
    if cpf_limpo or browser_token_hash:
        conds_expirar = []
        if cpf_limpo:
            conds_expirar.append(ReservaIngresso.cpf == cpf_limpo)
        if browser_token_hash:
            conds_expirar.append(ReservaIngresso.browser_token_hash == browser_token_hash)
        
        stmt_expirar_alvo = (
            update(ReservaIngresso)
            .where(
                ReservaIngresso.status == "ativa",
                ReservaIngresso.expira_em <= agora,
                or_(*conds_expirar)
            )
            .values(status="expirada")
        )
        await session.execute(stmt_expirar_alvo)

    # 3. VERIFICA SE JÁ EXISTE RESERVA ATIVA GLOBAL (RESTRIÇÃO CROSS-LOTE)
    reserva_existente = None

    # 3.1 Checa pelo CPF (se fornecido) em TODOS os lotes
    if cpf_limpo:
        stmt_cpf = select(ReservaIngresso).where(
            ReservaIngresso.cpf == cpf_limpo,
            ReservaIngresso.status == "ativa",
            ReservaIngresso.expira_em > agora
        ).order_by(desc(ReservaIngresso.expira_em))
        res_cpf = await session.execute(stmt_cpf)
        res_cpf_obj = res_cpf.scalars().first()
        if res_cpf_obj:
            if res_cpf_obj.lote_id != lote.id:
                msg = "Você já possui uma reserva ativa em outro lote. Conclua ou desista dela para resgatar neste lote."
                if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                    return JSONResponse(status_code=400, content={"codigo": "reserva_outro_lote", "detail": msg, "mensagem": msg})
                raise HTTPException(status_code=400, detail=msg)
            if res_cpf_obj.browser_token_hash and res_cpf_obj.browser_token_hash != browser_token_hash:
                msg = "Este CPF já possui uma reserva ativa em andamento em outro navegador/dispositivo."
                if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                    return JSONResponse(status_code=409, content={"codigo": "reserva_existente", "detail": msg, "mensagem": msg})
                raise HTTPException(status_code=409, detail=msg)
            reserva_existente = res_cpf_obj

    # 3.2 Checa pelo Navegador autenticado em TODOS os lotes
    if not reserva_existente:
        stmt_browser = select(ReservaIngresso).where(
            ReservaIngresso.browser_token_hash == browser_token_hash,
            ReservaIngresso.status == "ativa",
            ReservaIngresso.expira_em > agora
        ).order_by(desc(ReservaIngresso.expira_em))
        res_browser = await session.execute(stmt_browser)
        res_browser_obj = res_browser.scalars().first()
        if res_browser_obj:
            if res_browser_obj.lote_id != lote.id:
                msg = "Este navegador já possui uma reserva ativa em outro lote. Conclua ou desista dela antes de tentar outro lote."
                if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                    return JSONResponse(status_code=400, content={"codigo": "reserva_outro_lote", "detail": msg, "mensagem": msg})
                raise HTTPException(status_code=400, detail=msg)
            reserva_existente = res_browser_obj

    if reserva_existente:
        # Re-atacha à reserva ativa existente
        if cpf_limpo and not reserva_existente.cpf:
            reserva_existente.cpf = cpf_limpo
            session.add(reserva_existente)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()

        token_reserva = reserva_existente.token
        reserva_expira_em_ms = int(reserva_existente.expira_em.timestamp() * 1000)
        tempo_restante_segundos = max(1, int((reserva_existente.expira_em - agora).total_seconds()))
    else:
        # 4. Verifica vagas disponíveis no lote
        stmt_reservas = (
            select(func.count(ReservaIngresso.id))
            .where(
                ReservaIngresso.lote_id == lote.id,
                ReservaIngresso.status == "ativa",
                ReservaIngresso.expira_em > agora
            )
        )
        res_count = await session.execute(stmt_reservas)
        reservas_ativas = res_count.scalar() or 0

        vagas_disponiveis = lote.quantidade_total - (lote.quantidade_resgatada + reservas_ativas)
        if vagas_disponiveis <= 0:
            if lote.quantidade_resgatada >= lote.quantidade_total:
                msg = "Todos os ingressos deste lote já foram resgatados por outros servidores."
                codigo = "esgotado"
            else:
                msg = "Todas as vagas restantes estão temporariamente em processo de preenchimento por outros servidores. Aguarde alguns instantes na tela inicial para tentar caso alguma vaga seja liberada!"
                codigo = "em_preenchimento"

            if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                return JSONResponse(status_code=400, content={"codigo": codigo, "detail": msg, "mensagem": msg})
            if os.path.exists(VUE_INDEX_PATH):
                return FileResponse(VUE_INDEX_PATH)
            return templates.TemplateResponse(request=request, name="erro.html", context={"mensagem": msg})

        # 5. Rate limit atômico por IP compartilhado via PostgreSQL
        if not await verificar_e_registrar_rate_limit_db(client_ip, session):
            msg_ratelimit = "Muitas tentativas de reserva a partir deste IP. Aguarde um instante e tente novamente."
            if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                return JSONResponse(status_code=429, content={"codigo": "rate_limit", "detail": msg_ratelimit, "mensagem": msg_ratelimit})
            raise HTTPException(status_code=429, detail=msg_ratelimit)

        # 6. Cria uma nova Reserva Ativa de 5 minutos
        token_reserva = str(uuid.uuid4())
        expira_em = agora + timedelta(minutes=5)

        nova_reserva = ReservaIngresso(
            token=token_reserva,
            lote_id=lote.id,
            criada_em=agora,
            expira_em=expira_em,
            utilizada=False,
            status="ativa",
            cpf=cpf_limpo,
            browser_token_hash=browser_token_hash,
            device_fingerprint=device_fingerprint or header_fp,
            ip_origem=client_ip,
            device_id=browser_token
        )
        session.add(nova_reserva)
        try:
            await session.commit()
        except IntegrityError:
            # Proteção contra corrida concorrente no PostgreSQL (rollback limpo sem 500)
            await session.rollback()
            agora_atual = datetime.now()
            # Se a colisão ocorreu com reserva que acabou de expirar, expira-a pontualmente e retenta
            conds_limpa = []
            if cpf_limpo:
                conds_limpa.append(ReservaIngresso.cpf == cpf_limpo)
            if browser_token_hash:
                conds_limpa.append(ReservaIngresso.browser_token_hash == browser_token_hash)
            
            stmt_limpa = (
                update(ReservaIngresso)
                .where(
                    ReservaIngresso.status == "ativa",
                    ReservaIngresso.expira_em <= agora_atual,
                    or_(*conds_limpa)
                )
                .values(status="expirada")
            )
            res_limpa = await session.execute(stmt_limpa)
            if res_limpa.rowcount and res_limpa.rowcount > 0:
                await session.commit()
                session.add(nova_reserva)
                try:
                    await session.commit()
                    tempo_rest = max(1, int((expira_em - datetime.now()).total_seconds()))
                    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                        return JSONResponse(content={
                            "token_reserva": token_reserva,
                            "tempo_restante_segundos": tempo_rest,
                            "reserva_expira_em_ms": int(expira_em.timestamp() * 1000),
                            "lote_id": lote.id
                        })
                except IntegrityError:
                    await session.rollback()

            if cpf_limpo:
                stmt_c = select(ReservaIngresso).where(
                    ReservaIngresso.cpf == cpf_limpo,
                    ReservaIngresso.status == "ativa",
                    ReservaIngresso.expira_em > datetime.now()
                )
                r_c = (await session.execute(stmt_c)).scalars().first()
                if r_c and r_c.browser_token_hash == browser_token_hash and r_c.lote_id == lote.id:
                    token_reserva = r_c.token
                    reserva_expira_em_ms = int(r_c.expira_em.timestamp() * 1000)
                    tempo_restante_segundos = max(1, int((r_c.expira_em - datetime.now()).total_seconds()))
                    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                        return JSONResponse(content={
                            "token_reserva": token_reserva,
                            "tempo_restante_segundos": tempo_restante_segundos,
                            "reserva_expira_em_ms": reserva_expira_em_ms,
                            "lote_id": lote.id
                        })
                else:
                    return JSONResponse(status_code=409, content={
                        "codigo": "reserva_concorrente",
                        "detail": "Este participante já possui uma reserva ativa em andamento.",
                        "mensagem": "Este participante já possui uma reserva ativa em andamento."
                    })
            else:
                stmt_b = select(ReservaIngresso).where(
                    ReservaIngresso.browser_token_hash == browser_token_hash,
                    ReservaIngresso.status == "ativa",
                    ReservaIngresso.expira_em > datetime.now()
                )
                r_b = (await session.execute(stmt_b)).scalars().first()
                if r_b and r_b.lote_id == lote.id:
                    token_reserva = r_b.token
                    reserva_expira_em_ms = int(r_b.expira_em.timestamp() * 1000)
                    tempo_restante_segundos = max(1, int((r_b.expira_em - datetime.now()).total_seconds()))
                    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                        return JSONResponse(content={
                            "token_reserva": token_reserva,
                            "tempo_restante_segundos": tempo_restante_segundos,
                            "reserva_expira_em_ms": reserva_expira_em_ms,
                            "lote_id": lote.id
                        })
                else:
                    return JSONResponse(status_code=409, content={
                        "codigo": "conflito_concorrencia",
                        "detail": "Conflito durante a reserva simultânea. Tente novamente.",
                        "mensagem": "Conflito durante a reserva simultânea. Tente novamente."
                    })

        reserva_expira_em_ms = int(expira_em.timestamp() * 1000)
        tempo_restante_segundos = 300

        # Transmite via SSE com contadores consistentes pós-commit
        invalidar_cache_live_status()
        await lote_event_hub.broadcast(
            "LOTE_ATUALIZADO",
            {
                "tipo": "reserva_criada",
                "lote_id": lote.id,
                "device_id": nova_reserva.device_id,
                "token_reserva": token_reserva,
                "expira_em_ms": reserva_expira_em_ms,
                "segundos_restantes": tempo_restante_segundos
            }
        )

    secure_flag = is_conexao_segura(request)

    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        json_resp = JSONResponse(content={
            "token_reserva": token_reserva,
            "server_time_ms": server_time_ms,
            "reserva_expira_em_ms": reserva_expira_em_ms,
            "tempo_restante_segundos": tempo_restante_segundos
        })
        json_resp.set_cookie(
            key=COOKIE_BROWSER_ID,
            value=browser_token,
            max_age=31536000,
            httponly=True,
            secure=secure_flag,
            samesite="lax"
        )
        return json_resp

    if os.path.exists(VUE_INDEX_PATH):
        response = FileResponse(VUE_INDEX_PATH)
    else:
        stmt_sec = select(Secretaria).order_by(Secretaria.nome)
        res_sec = await session.execute(stmt_sec)
        secretarias = res_sec.scalars().all()

        response = templates.TemplateResponse(
            request=request,
            name="resgate.html",
            context={
                "lote": lote,
                "secretarias": secretarias,
                "token_reserva": token_reserva,
                "server_time_ms": server_time_ms,
                "reserva_expira_em_ms": reserva_expira_em_ms,
                "tempo_restante_segundos": tempo_restante_segundos
            }
        )

    response.set_cookie(
        key=COOKIE_BROWSER_ID,
        value=browser_token,
        max_age=31536000,
        httponly=True,
        secure=secure_flag,
        samesite="lax"
    )
    return response


# ============================================================================
# 5. PROCESSAMENTO DO RESGATE COM VALIDAÇÃO RIGOROSA E ROLLBACK LIMPO
# ============================================================================
@router.post("/resgate/{lote_id}")
@router.post("/api/resgate/{lote_id}")
async def processar_resgate(
    request: Request, 
    lote_id: int,
    token_reserva: str = Form(...),
    cpf: str = Form(...),
    nome: str = Form(...),
    data_nascimento: str = Form(...),
    setor: str = Form(...),
    secretaria_id: int = Form(...),
    vinculo: str = Form(...),
    telefone: str = Form(...),
    email: str = Form(...),
    foto_base64: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    agora = datetime.now()
    cpf_limpo = "".join([ch for ch in cpf if ch.isdigit()]).zfill(11)
    _, current_browser_hash, _ = obter_ou_criar_browser_id(request)

    # 1. Validação da Reserva
    stmt_reserva = select(ReservaIngresso).where(
        ReservaIngresso.token == token_reserva,
        ReservaIngresso.lote_id == lote_id
    )
    res_reserva = await session.execute(stmt_reserva)
    reserva = res_reserva.scalars().first()

    if not reserva:
        raise HTTPException(status_code=400, detail="Reserva de vaga inválida ou não encontrada.")

    # Validação de titularidade do navegador sobre a reserva
    if reserva.browser_token_hash and reserva.browser_token_hash != current_browser_hash:
        raise HTTPException(
            status_code=403,
            detail="Acesso não autorizado: a identidade do navegador não corresponde à reserva iniciada."
        )

    if reserva.status == "concluida" or reserva.utilizada:
        raise HTTPException(status_code=400, detail="Esta reserva já foi utilizada para emitir um ingresso.")

    if reserva.status == "cancelada" or reserva.expira_em <= datetime(2000, 1, 2):
        raise HTTPException(status_code=400, detail="Você desistiu desta vaga por outro navegador.")

    if reserva.status == "expirada" or agora > reserva.expira_em:
        if reserva.status == "ativa":
            reserva.status = "expirada"
            session.add(reserva)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
        raise HTTPException(
            status_code=400, 
            detail="O seu tempo de 5 minutos para preenchimento expirou. Por favor, inicie um novo resgate na página inicial."
        )

    # Cancelamento imediato da reserva em falhas definitivas
    async def _cancelar_reserva_definitiva(detalhe_erro: str):
        reserva.status = "cancelada"
        reserva.expira_em = datetime(2000, 1, 1)
        session.add(reserva)
        try:
            await session.commit()
            invalidar_cache_live_status()

            stmt_count = select(func.count(ReservaIngresso.id)).where(
                ReservaIngresso.lote_id == lote_id,
                ReservaIngresso.status == "ativa",
                ReservaIngresso.expira_em > datetime.now()
            )
            res_cnt = await session.execute(stmt_count)
            res_ativas = res_cnt.scalar() or 0

            st_lote = select(Lote).where(Lote.id == lote_id)
            r_lote = await session.execute(st_lote)
            l_obj = r_lote.scalars().first()
            v_disp = max(0, l_obj.quantidade_total - (l_obj.quantidade_resgatada + res_ativas)) if l_obj else 0

            await lote_event_hub.broadcast(
                "LOTE_ATUALIZADO",
                {
                    "tipo": "reserva_liberada",
                    "lote_id": lote_id,
                    "device_id": reserva.device_id,
                    "token_reserva": token_reserva
                }
            )
        except Exception:
            await session.rollback()
        raise HTTPException(status_code=400, detail=detalhe_erro)

    # 2. Validação Matemática do CPF (rejeição definitiva se inválido)
    if not validar_cpf_matematico(cpf_limpo):
        await _cancelar_reserva_definitiva("CPF inválido. Verifique os números digitados.")

    # 3. Validação de Maioridade (18+ Anos) (rejeição definitiva se menor)
    try:
        data_nasc_limpa = data_nascimento.strip()
        if "-" in data_nasc_limpa:
            dt_nasc = datetime.strptime(data_nasc_limpa, "%Y-%m-%d")
        elif "/" in data_nasc_limpa:
            dt_nasc = datetime.strptime(data_nasc_limpa, "%d/%m/%Y")
        else:
            raise ValueError()

        idade = agora.year - dt_nasc.year - ((agora.month, agora.day) < (dt_nasc.month, dt_nasc.day))
        if idade < 18:
            await _cancelar_reserva_definitiva("O resgate de ingressos é permitido exclusivamente para maiores de 18 anos.")
    except HTTPException:
        raise
    except Exception:
        await _cancelar_reserva_definitiva("Data de nascimento inválida.")

    # 4. Validação do Lote
    stmt_lote = select(Lote).where(Lote.id == lote_id).with_for_update()
    res_lote = await session.execute(stmt_lote)
    lote = res_lote.scalars().first()
    if not lote or not lote.ativo:
        await _cancelar_reserva_definitiva("Este lote foi pausado ou desativado pela organização.")

    if lote.data_abertura and agora < lote.data_abertura:
        await _cancelar_reserva_definitiva("O lote ainda não está aberto para resgates.")

    if lote.data_fechamento and agora > lote.data_fechamento:
        await _cancelar_reserva_definitiva("O período de resgate deste lote já foi encerrado.")

    if lote.secretaria_id and lote.secretaria_id != secretaria_id:
        await _cancelar_reserva_definitiva("Este lote é exclusivo para servidores da secretaria selecionada.")

    # 5. Validação de Elegibilidade do Participante
    valido_eleg, tipo_erro_eleg, msg_eleg, usuario = await verificar_elegibilidade_participante(cpf_limpo, session)
    if not valido_eleg:
        await _cancelar_reserva_definitiva(msg_eleg)

    # 6. Validação com a Base Integrada Externa da Escola de Governo (falha recuperável)
    try:
        validacao_externa = await ServidorValidationService.verificar_servidor(cpf_limpo)
        is_servidor_confirmado = bool(validacao_externa.get("is_servidor", False))
    except Exception:
        is_servidor_confirmado = False

    # 7. Processamento da Foto Facial Obrigatória (falha recuperável)
    if not foto_base64 or not foto_base64.startswith("data:image/jpeg;base64,"):
        raise HTTPException(status_code=400, detail="A foto facial ao vivo é obrigatória para validação.")
    if len(foto_base64) > 6 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="A selfie excede o limite permitido de 4 MB.")

    try:
        header, encoded = foto_base64.split(",", 1)
        foto_bytes = base64.b64decode(encoded, validate=True)
        if len(foto_bytes) > 4 * 1024 * 1024 or not foto_bytes.startswith(b"\xff\xd8\xff"):
            raise ValueError("Imagem JPEG inválida ou acima do limite")
        nome_arquivo_foto = f"selfie_{uuid.uuid4().hex}.jpg"
        caminho_foto = os.path.join(FOTOS_DIR, nome_arquivo_foto)
        with open(caminho_foto, "wb") as f:
            f.write(foto_bytes)
        foto_url = f"/static/uploads/fotos/{nome_arquivo_foto}"
    except Exception:
        raise HTTPException(status_code=400, detail="Erro ao processar e salvar a foto facial.")

    # 8. Criação ou Atualização do Usuário
    if not usuario:
        usuario = Usuario(
            cpf=cpf_limpo,
            nome=nome.strip(),
            data_nascimento=data_nascimento.strip(),
            setor=setor.strip(),
            secretaria_id=secretaria_id,
            vinculo=vinculo.strip(),
            telefone=telefone.strip(),
            email=email.strip().lower(),
            foto_rosto_url=foto_url,
            role=UserRole.servidor
        )
        session.add(usuario)
        await session.flush()
    else:
        usuario.nome = nome.strip()
        usuario.data_nascimento = data_nascimento.strip()
        usuario.setor = setor.strip()
        usuario.secretaria_id = secretaria_id
        usuario.vinculo = vinculo.strip()
        usuario.telefone = telefone.strip()
        usuario.email = email.strip().lower()
        usuario.foto_rosto_url = foto_url
        session.add(usuario)

    client_ip = extrair_ip_cliente(request)
    if is_servidor_confirmado:
        usuario.validado = True
        session.add(usuario)

    # 9. Criação da Solicitação de Validação
    token_solic = secrets.token_urlsafe(32)
    solic_val = SolicitacaoValidacao(
        usuario_id=usuario.id,
        lote_id=lote.id,
        secretaria_id=secretaria_id,
        token=token_solic,
        status="pendente_analise",
        ip_origem=client_ip,
        identificado_api=is_servidor_confirmado
    )
    session.add(solic_val)

    # 10. Atualiza o Lote e Conclui a Reserva
    lote.quantidade_resgatada += 1
    session.add(lote)

    reserva.utilizada = True
    reserva.status = "concluida"
    reserva.cpf = cpf_limpo
    session.add(reserva)

    # Invalida quaisquer outras reservas deste participante ou dispositivo em aberto
    limpar_conds = [ReservaIngresso.cpf == cpf_limpo]
    if reserva.browser_token_hash:
        limpar_conds.append(ReservaIngresso.browser_token_hash == reserva.browser_token_hash)

    stmt_limpar = select(ReservaIngresso).where(
        ReservaIngresso.id != reserva.id,
        ReservaIngresso.status == "ativa",
        or_(*limpar_conds)
    )
    res_limpar = await session.execute(stmt_limpar)
    for r_pendente in res_limpar.scalars().all():
        r_pendente.status = "concluida"
        r_pendente.utilizada = True
        session.add(r_pendente)

    try:
        await session.commit()
        await session.refresh(solic_val)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflito de concorrência: ingresso ou solicitação já emitida para este participante."
        )

    # 11. Broadcast SSE pós-commit com contadores consistentes
    invalidar_cache_live_status()
    await lote_event_hub.broadcast(
        "LOTE_ATUALIZADO",
        {
            "tipo": "resgate_concluido",
            "lote_id": lote.id,
            "device_id": reserva.device_id,
            "token_reserva": reserva.token
        }
    )

    if email_dest := (usuario.email or "").strip():
        sec_obj = await session.get(Secretaria, secretaria_id) if secretaria_id else None
        sec_nome = sec_obj.nome if sec_obj else None
        asyncio.create_task(
            send_validation_pending_email_async(
                usuario_nome=usuario.nome,
                usuario_email=email_dest,
                lote_nome=lote.nome,
                secretaria_nome=sec_nome
            )
        )

    resp_content = {
        "sucesso": True,
        "status": "pendente_analise",
        "solicitacao_id": solic_val.id,
        "token": token_solic,
        "identificado_api": is_servidor_confirmado,
        "mensagem": "Seu resgate foi realizado com sucesso! Nossa equipe e o sistema validarão seu cadastro em até 72h.",
        "redirect_url": f"/sucesso/analise?solicitacao_id={solic_val.id}&token={token_solic}"
    }
    response = JSONResponse(content=resp_content)
    response.set_cookie(
        key=f"solic_claim_{solic_val.id}",
        value=token_solic,
        max_age=86400 * 3,
        httponly=True,
        secure=is_conexao_segura(request),
        samesite="lax"
    )
    return response


@router.get("/api/sucesso/analise-status/{solicitacao_id}")
async def status_analise_solicitacao(
    request: Request,
    solicitacao_id: int,
    token: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session)
):
    """Retorna detalhes da solicitação de análise pendente para a tela de confirmação (protegido contra IDOR - SEC-02)"""
    stmt = (
        select(SolicitacaoValidacao)
        .options(
            selectinload(SolicitacaoValidacao.usuario).selectinload(Usuario.secretaria),
            selectinload(SolicitacaoValidacao.lote)
        )
        .where(SolicitacaoValidacao.id == solicitacao_id)
    )
    res = await session.execute(stmt)
    solic = res.scalars().first()
    if not solic:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")

    # Proteção estrita contra IDOR (SEC-02): Valida posse por cookie seguro, token explícito ou sessão autenticada
    tem_permissao = False
    claim_cookie = request.cookies.get(f"solic_claim_{solicitacao_id}")
    if solic.token and ((token and token == solic.token) or (claim_cookie and claim_cookie == solic.token)):
        tem_permissao = True
    else:
        access_tok = request.cookies.get("access_token")
        if access_tok:
            try:
                from jose import jwt
                from app.core.config import settings
                _, _, p = access_tok.partition(" ")
                pay = jwt.decode(p, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                sub_cpf = pay.get("sub")
                roles_str = pay.get("roles", "")
                u_cpf = solic.usuario.cpf if solic.usuario else ""
                if sub_cpf and (sub_cpf == u_cpf or any(r in roles_str for r in ["admin", "admin_geral", "validador", "portaria"])):
                    tem_permissao = True
            except Exception:
                pass

    if not tem_permissao:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso não autorizado aos dados desta solicitação."
        )

    u = solic.usuario
    sec = u.secretaria if u else None
    resp = JSONResponse(content={
        "sucesso": True,
        "id": solic.id,
        "status": solic.status,
        "criado_em": solic.criado_em.strftime("%d/%m/%Y às %H:%M") if solic.criado_em else "-",
        "prazo_horas": 72,
        "prazo_dias": 3,
        "identificado_api": bool(getattr(solic, "identificado_api", False)),
        "lote_nome": solic.lote.nome if solic.lote else "Lote Oficial",
        "secretaria_nome": sec.nome if sec else "Secretaria Municipal",
        "usuario": {
            "nome": u.nome if u else "Servidor",
            "cpf_mascarado": mascarar_cpf(u.cpf) if u else "",
            "email": u.email if u else "",
            "setor": u.setor if u else ""
        }
    })
    if token and solic.token and token == solic.token:
        resp.set_cookie(
            key=f"solic_claim_{solicitacao_id}",
            value=solic.token,
            max_age=86400 * 3,
            httponly=True,
            samesite="lax"
        )
    return resp


@router.get("/sucesso/analise")
async def pagina_sucesso_analise(request: Request):
    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)
    return RedirectResponse(url="/")


@router.get("/sucesso/{ingresso_id}")
@router.get("/api/sucesso/{ingresso_id}")
async def pagina_sucesso(
    request: Request, 
    ingresso_id: int, 
    token: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session)
):
    stmt = (
        select(Ingresso)
        .options(selectinload(Ingresso.usuario), selectinload(Ingresso.lote))
        .where(Ingresso.id == ingresso_id, Ingresso.deleted_at.is_(None))
    )
    res = await session.execute(stmt)
    ingresso = res.scalars().first()

    if not ingresso:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            raise HTTPException(status_code=404, detail="Ingresso não encontrado ou cancelado.")
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH)
        return templates.TemplateResponse(
            request=request, 
            name="erro.html", 
            context={"mensagem": "Ingresso não encontrado ou cancelado."}
        )

    # Proteção estrita contra IDOR: Valida posse por cookie seguro, token explícito ou sessão autenticada
    tem_permissao = False
    claim_cookie = request.cookies.get(f"ingresso_claim_{ingresso_id}")
    if claim_cookie and claim_cookie == ingresso.qr_code_token:
        tem_permissao = True
    elif token and token == ingresso.qr_code_token:
        tem_permissao = True
    else:
        # Checa se há usuário autenticado da equipe ou titular
        access_tok = request.cookies.get("access_token")
        if access_tok:
            try:
                from jose import jwt
                from app.core.config import settings
                _, _, p = access_tok.partition(" ")
                pay = jwt.decode(p, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                sub_cpf = pay.get("sub")
                roles_str = pay.get("roles", "")
                if sub_cpf and (sub_cpf == (ingresso.usuario.cpf if ingresso.usuario else "") or any(r in roles_str for r in ["admin", "admin_geral", "portaria", "validador"])):
                    tem_permissao = True
            except Exception:
                pass

    if not tem_permissao:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso não autorizado aos dados deste ingresso."
            )
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    secretaria = None
    if ingresso.usuario and ingresso.usuario.secretaria_id:
        stmt_sec = select(Secretaria).where(Secretaria.id == ingresso.usuario.secretaria_id)
        res_sec = await session.execute(stmt_sec)
        secretaria = res_sec.scalars().first()

    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        cpf_mascarado = f"{ingresso.usuario.cpf[:3]}.***.***-{ingresso.usuario.cpf[-2:]}" if ingresso.usuario and len(ingresso.usuario.cpf) == 11 else (ingresso.usuario.cpf if ingresso.usuario else "")
        sec_nome = secretaria.nome if secretaria else "Geral"
        lote_nome_val = ingresso.lote.nome if ingresso.lote else "Geral"
        resp_json = JSONResponse(content={
            "id": ingresso.id,
            "qr_code_token": ingresso.qr_code_token,
            "data_resgate": ingresso.data_resgate.isoformat() if ingresso.data_resgate else None,
            "data_resgate_formatada": ingresso.data_resgate.strftime("%d/%m/%Y às %H:%M") if ingresso.data_resgate else None,
            "lote_nome": lote_nome_val,
            "cpf": cpf_mascarado,
            "usuario": {
                "nome": ingresso.usuario.nome if ingresso.usuario else "Servidor",
                "cpf_formatado": cpf_mascarado,
                "setor": ingresso.usuario.setor if ingresso.usuario else "",
                "secretaria_nome": sec_nome,
                "vinculo": ingresso.usuario.vinculo if ingresso.usuario else "Servidor",
                "telefone": ingresso.usuario.telefone if ingresso.usuario else "",
                "foto_rosto_url": ingresso.usuario.foto_rosto_url if ingresso.usuario else None
            },
            "ingresso": {
                "id": ingresso.id,
                "qr_code_token": ingresso.qr_code_token,
                "data_resgate": ingresso.data_resgate.isoformat() if ingresso.data_resgate else None
            },
            "lote": {
                "id": ingresso.lote.id if ingresso.lote else None,
                "nome": lote_nome_val
            }
        })
        if token and token == ingresso.qr_code_token:
            resp_json.set_cookie(
                key=f"ingresso_claim_{ingresso_id}",
                value=ingresso.qr_code_token,
                max_age=86400 * 30,
                httponly=True,
                samesite="lax"
            )
        return resp_json

    if os.path.exists(VUE_INDEX_PATH):
        response = FileResponse(VUE_INDEX_PATH)
    else:
        response = templates.TemplateResponse(
            request=request,
            name="sucesso.html",
            context={
                "ingresso": ingresso,
                "secretaria": secretaria
            }
        )

    if token and token == ingresso.qr_code_token:
        response.set_cookie(
            key=f"ingresso_claim_{ingresso_id}",
            value=ingresso.qr_code_token,
            max_age=86400 * 30,
            httponly=True,
            samesite="lax"
        )

    return response
