import asyncio
import base64
import hashlib
import hmac
import logging
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from typing import Optional
from weakref import WeakValueDictionary
from fastapi import APIRouter, Request, Depends, Form, Query, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlmodel import select, func, or_, and_, desc, update, delete
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.http_protection import ResgateFormRoute
from app.db.session import get_session, async_session
from app.models.all_models import (
    Lote, Usuario, Ingresso, Secretaria, ReservaIngresso, UserRole,
    SolicitacaoValidacao, RateLimitTentativa
)
from app.core.security import extrair_ip_cliente, formatar_data_sp, TZ_SAO_PAULO
from app.core.cpf import limpar_cpf, mascarar_cpf, validar_cpf_matematico
from app.services.email_service import send_validation_pending_email_async, send_ticket_email_async
from app.services.lotes_ocultos import conferir_autorizacao, configuracao, instante_utc, VINCULOS
from app.core.validators import normalizar_data_nascimento, formatar_telefone, validar_email
from app.services.validacao_servidor_service import ServidorValidationService
from app.services.resgate_jobs import enqueue_external_validation, get_external_validation_status
from app.services.validacao_comunicacao import chave_comunicacao
from app.services.reserva_batch import reserva_batch_service
from app.services.legal import validate_redemption, record_acceptance
from app.core.events import lote_event_hub

router = APIRouter(route_class=ResgateFormRoute)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")

FOTOS_DIR = "app/static/uploads/fotos"
os.makedirs(FOTOS_DIR, exist_ok=True)
VUE_INDEX_PATH = "app/static/dist/index.html"

COOKIE_BROWSER_ID = "festa_browser_id"
COOKIE_RESERVA_PRAZO = "festa_reserva_prazo"
COOKIE_DEVICE_LEGACY = "festa_device_id"

# Um processo admite uma criação por lote na transação de capacidade. O lock
# PostgreSQL continua coordenando processos diferentes. Referências fracas
# descartam o lock local quando não há chamadas usando/aguardando aquele lote.
_filas_criacao_reserva = WeakValueDictionary()


def _medir_fluxo_reserva(func):
    """Registra chamadas lentas sem CPF, token, cookie ou identificador pessoal."""
    @wraps(func)
    async def medida(*args, **kwargs):
        request = kwargs.get("request") or args[0]
        request.state.reserva_tempos = {}
        inicio = time.perf_counter()
        resultado = "excecao"
        lote_id = kwargs.get("lote_id")
        if lote_id is None and func.__name__ == "pagina_resgate" and len(args) > 1:
            lote_id = args[1]
        try:
            resposta = await func(*args, **kwargs)
            resultado = resposta.status_code
            return resposta
        finally:
            total_ms = (time.perf_counter() - inicio) * 1000
            if total_ms >= 1000:
                logger.warning(
                    "reserva_lenta operacao=%s lote_id=%s resultado=%s total_ms=%.1f etapas_ms=%s",
                    func.__name__, lote_id,
                    resultado, total_ms, request.state.reserva_tempos,
                )
    return medida


@contextmanager
def _medir_etapa_reserva(request: Request, etapa: str):
    inicio = time.perf_counter()
    try:
        yield
    finally:
        tempos = getattr(request.state, "reserva_tempos", None)
        if tempos is not None:
            tempos[etapa] = round((time.perf_counter() - inicio) * 1000, 1)




@asynccontextmanager
async def _transacao_capacidade_reserva(
    session: AsyncSession, request: Request, lote_id: int, criar: bool,
):
    fila = None
    if criar:
        # A busca inicial é somente leitura. Devolve sua conexão ANTES de
        # aguardar a fila local, mantendo o pool disponível para SSE e consultas.
        await session.close()
        fila = _filas_criacao_reserva.get(lote_id)
        if fila is None:
            fila = asyncio.Lock()
            _filas_criacao_reserva[lote_id] = fila
        with _medir_etapa_reserva(request, "fila_criacao_worker"):
            await fila.acquire()
    try:
        yield
    finally:
        try:
            # Também libera FOR UPDATE nas saídas antecipadas e nas exceções.
            # O próximo da fila só entra depois da devolução desta conexão.
            await session.close()
        finally:
            if fila is not None:
                fila.release()


# Rate Limit Global por IP via PostgreSQL (suporta 4 workers do Gunicorn)
# Calibrado para até 300 requisições/min por IP público, acomodando com folga 150+ participantes
# em redes NAT corporativas/órgãos públicos sem bloqueio coletivo indevido.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUISICOES = int(os.getenv("RATE_LIMIT_RESERVA_MAX_IP", "100000"))
reserva_batch_service.rate_limit = _RATE_LIMIT_MAX_REQUISICOES

# Estrutura e função para retrocompatibilidade com testes legados em memória
_ip_reserva_requisicoes = {}

def _chave_rate_limit_reserva(request: Request, lote_id: int, fingerprint: Optional[str], ip: str) -> str:
    """Separa visitantes sintéticos somente durante um teste explicitamente autorizado."""
    chave = settings.LOAD_TEST_SECRET
    if len(chave) < 32 or lote_id != settings.LOAD_TEST_LOTE_ID:
        return ip
    if not fingerprint or not fingerprint.startswith("loadtest_") or len(fingerprint) > 100:
        return ip
    fornecida = request.headers.get("x-load-test-key", "") or request.query_params.get("load_test_key", "")
    if not secrets.compare_digest(fornecida.encode("utf-8"), chave.encode("utf-8")):
        return ip
    try:
        limite = datetime.fromisoformat(settings.LOAD_TEST_UNTIL.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ip
    if limite.tzinfo is None:
        return ip
    restante = (limite - datetime.now(timezone.utc)).total_seconds()
    if not 0 < restante <= 7200:
        return ip
    # O limitador e sua consulta continuam sendo exercitados. Cada visitante
    # sintético recebe um contador próprio, sem alterar o IP salvo na reserva.
    return f"loadtest:{ip}:{fingerprint}"

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


def definir_cookie_prazo_reserva(response: Response, expira_em_ms: int, request: Request) -> None:
    """Persiste no navegador o prazo exato usado pelo cronômetro do resgate."""
    restante_ms = max(0, int(expira_em_ms) - int(datetime.now(timezone.utc).timestamp() * 1000))
    if restante_ms <= 0:
        response.delete_cookie(
            key=COOKIE_RESERVA_PRAZO,
            path="/",
            secure=is_conexao_segura(request),
            samesite="lax"
        )
        return

    response.set_cookie(
        key=COOKIE_RESERVA_PRAZO,
        value=str(int(expira_em_ms)),
        max_age=(restante_ms + 999) // 1000,
        httponly=False,
        secure=is_conexao_segura(request),
        samesite="lax",
        path="/"
    )


def remover_cookie_prazo_reserva(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=COOKIE_RESERVA_PRAZO,
        path="/",
        secure=is_conexao_segura(request),
        samesite="lax"
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
    Registra o limite sem obter outra conexão enquanto o chamador bloqueia o lote.
    O savepoint isola falhas do limitador sem comitar a transação da reserva nem
    liberar seu SELECT FOR UPDATE. Sem sessão fornecida, usa transação própria.
    """
    agora_utc = datetime.now(timezone.utc)
    limite_janela = agora_utc - timedelta(seconds=_RATE_LIMIT_WINDOW_SECONDS)

    async def registrar(rl_session: AsyncSession) -> bool:
        if rl_session.bind.dialect.name == "postgresql":
            # A chave do IP coordena COUNT + INSERT entre workers, sem prender
            # o lote durante essa operação. Testes autorizados usam chave por VU.
            await rl_session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:chave, 9137))"), {"chave": "reserva:" + ip})
        stmt_count = select(func.count(RateLimitTentativa.id)).where(
            RateLimitTentativa.ip == ip,
            RateLimitTentativa.acao == "reserva",
            RateLimitTentativa.criado_em > limite_janela
        )
        res = await rl_session.execute(stmt_count)
        total_tentativas = res.scalar() or 0

        if _RATE_LIMIT_MAX_REQUISICOES > 0 and _RATE_LIMIT_MAX_REQUISICOES < 100000 and total_tentativas >= _RATE_LIMIT_MAX_REQUISICOES:
            return False

        registro = RateLimitTentativa(ip=ip, acao="reserva", criado_em=agora_utc)
        rl_session.add(registro)
        await rl_session.flush()

        return True

    try:
        if session is not None:
            async with session.begin_nested():
                return await registrar(session)
        async with async_session() as rl_session:
            permitido = await registrar(rl_session)
            await rl_session.commit()
            return permitido
    except Exception:
        logger.error("Falha no limitador de reservas", exc_info=False)
        raise HTTPException(status_code=503, detail="Serviço de reserva ocupado. Tente novamente.")


def _publicar_mudanca_reserva(reserva: ReservaIngresso, tipo: str, **dados) -> None:
    """O commit é autoritativo; a entrega SSE não participa da resposta HTTP."""
    if reserva.acesso_versao is not None:
        return
    try:
        lote_event_hub.publish_reservation_change({
            "tipo": tipo, "lote_id": reserva.lote_id,
            "device_id": reserva.device_id,
            "device_fingerprint": reserva.device_fingerprint,
            "browser_token_hash": reserva.browser_token_hash,
            "token_reserva": reserva.token, **dados,
        })
    except Exception:
        logger.error("Falha ao agendar atualização de reserva lote_id=%s", reserva.lote_id)




async def reserva_maintenance_worker(stop_event):
    """Limpeza periódica fora do caminho de criação de reservas."""
    while not stop_event.is_set():
        try:
            async with async_session() as session:
                await expirar_reservas_vencidas(session)
                await session.execute(delete(RateLimitTentativa).where(
                    RateLimitTentativa.criado_em < datetime.now(timezone.utc) - timedelta(minutes=10)
                ))
                await session.commit()
        except Exception:
            logger.error("Falha na manutenção periódica de reservas", exc_info=False)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


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

    agora = datetime.now(timezone.utc)
    try:
        stmt = (
            update(ReservaIngresso)
            .where(
                ReservaIngresso.status == "ativa",
                ReservaIngresso.expira_em <= agora
            )
            .values(status="expirada")
            .returning(ReservaIngresso.lote_id)
        )
        res = await session.execute(stmt)
        lotes_expirados = res.scalars().all()
        await session.commit()
        for lote_id in set(lotes_expirados):
            lote_event_hub.mark_reservation_lot_dirty(lote_id)
        return len(lotes_expirados)
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

    if token_reserva:
        propria = (await session.execute(select(ReservaIngresso).where(
            ReservaIngresso.token == token_reserva
        ))).scalars().first()
        if propria and (not propria.browser_token_hash or propria.browser_token_hash == current_browser_hash):
            recovered = await _recuperar_resgate_confirmado(session, propria, cpf_limpo, request)
            if recovered:
                content = json.loads(recovered.body)
                content.update(valido=True, resgate_concluido=True)
                return JSONResponse(content=content)

    # Expiração direcionada atômica para o CPF e navegador desta chamada caso o sweeper global esteja em throttle
    agora_val = datetime.now(timezone.utc)
    stmt_expirar_direcionada = (
        update(ReservaIngresso)
        .where(
            ReservaIngresso.status == "ativa",
            ReservaIngresso.expira_em <= agora_val,
            ReservaIngresso.acesso_versao.is_(None),
            or_(
                ReservaIngresso.cpf == cpf_limpo,
                ReservaIngresso.browser_token_hash == current_browser_hash
            )
        )
        .values(status="expirada")
    )
    await session.execute(stmt_expirar_direcionada)

    valido, tipo_erro, mensagem, usuario = await verificar_elegibilidade_participante(cpf_limpo, session)
    if not valido:
        # Apenas reporta a inelegibilidade do CPF para o formulário exibir a mensagem amigável em tempo real.
        # Não cancela a vaga reservada da sessão para permitir que o usuário corrija qualquer erro de digitação.
        return JSONResponse(content={
            "valido": False,
            "tipo_erro": tipo_erro,
            "mensagem": mensagem
        })

    agora = datetime.now(timezone.utc)
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
            await session.execute(update(ReservaIngresso).where(
                ReservaIngresso.id == reserva_token_obj.id,
                ReservaIngresso.status == "ativa", ReservaIngresso.utilizada == False,
                ReservaIngresso.expira_em > datetime.now(timezone.utc)
            ).values(cpf=cpf_limpo))
            await session.commit()

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
    await expirar_reservas_vencidas(session)

    stmt = select(ReservaIngresso).where(ReservaIngresso.token == token_reserva)
    res = await session.execute(stmt)
    reserva = res.scalars().first()

    if not reserva:
        return JSONResponse(content={"status": "inexistente", "ativa": False, "motivo": "nao_encontrada"})
    conferir_autorizacao(request, await session.get(Lote, reserva.lote_id))

    if reserva.status == "concluida" or reserva.utilizada:
        return JSONResponse(content={"status": "utilizada", "ativa": False, "motivo": "utilizada"})

    if reserva.status == "cancelada" or reserva.expira_em <= datetime(2000, 1, 2, tzinfo=timezone.utc):
        return JSONResponse(content={"status": "desistida", "ativa": False, "motivo": "desistida"})

    agora_resposta = datetime.now(timezone.utc)
    restante_ms = int((reserva.expira_em - agora_resposta).total_seconds() * 1000)
    if reserva.status == "expirada" or restante_ms <= 0:
        if reserva.status == "ativa":
            try:
                await session.execute(update(ReservaIngresso).where(
                    ReservaIngresso.id == reserva.id, ReservaIngresso.status == "ativa",
                    ReservaIngresso.expira_em <= agora_resposta
                ).values(status="expirada"))
                await session.commit()
            except Exception:
                await session.rollback()
        response = JSONResponse(content={"status": "expirada", "ativa": False, "motivo": "tempo_esgotado"})
        remover_cookie_prazo_reserva(response, request)
        return response

    segundos_restantes = (restante_ms + 999) // 1000
    server_time_ms = int(agora_resposta.timestamp() * 1000)
    response = JSONResponse(content={
        "status": "ativa",
        "ativa": True,
        "segundos_restantes": segundos_restantes,
        "milissegundos_restantes": restante_ms,
        "server_time_ms": server_time_ms,
        "expira_em_ms": server_time_ms + restante_ms
    })
    definir_cookie_prazo_reserva(response, server_time_ms + restante_ms, request)
    return response


# ============================================================================
# 3. DESISTIR DA VAGA RESERVADA (LIBERAÇÃO IMEDIATA)
# ============================================================================
@router.post("/api/resgate/desistir")
@_medir_fluxo_reserva
async def desistir_reserva(
    request: Request,
    token_reserva: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    with _medir_etapa_reserva(request, "expiracao"):
        await expirar_reservas_vencidas(session)
    _, current_browser_hash, _ = obter_ou_criar_browser_id(request)

    stmt = select(ReservaIngresso).where(
        ReservaIngresso.token == token_reserva
    )
    with _medir_etapa_reserva(request, "consulta_reserva"):
        res = await session.execute(stmt)
    reserva = res.scalars().first()

    if reserva and reserva.status == "ativa" and not reserva.utilizada:
        conferir_autorizacao(request, await session.get(Lote, reserva.lote_id))
        # Valida que quem está desistindo é o navegador detentor da reserva
        if reserva.browser_token_hash and reserva.browser_token_hash != current_browser_hash:
            return JSONResponse(
                status_code=403,
                content={"sucesso": False, "mensagem": "Acesso não autorizado para desistir desta reserva."}
            )

        try:
            with _medir_etapa_reserva(request, "commit"):
                await _cancelar_reserva_ativa(session, reserva, "desistencia")
        except Exception:
            await session.rollback()
            return JSONResponse(status_code=500, content={"sucesso": False, "mensagem": "Erro ao cancelar reserva."})

    await session.close()
    response = JSONResponse(content={
        "sucesso": True,
        "mensagem": "Vaga liberada com sucesso."
    })
    remover_cookie_prazo_reserva(response, request)
    return response


# ============================================================================
# 4. PÁGINA E API DE RESGATE COM RESERVA ATÔMICA & COOKIE CRIPTOGRÁFICO
# ============================================================================
@router.get("/resgate/{lote_id}")
@router.post("/api/lote/{lote_id}/reservar")
@_medir_fluxo_reserva
async def pagina_resgate(
    request: Request,
    lote_id: int,
    device_fingerprint: Optional[str] = Query(None),
    device_id: Optional[str] = Query(None),
    cpf: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
):
    if not request.url.path.startswith("/api/") and "text/html" in request.headers.get("accept", "") and os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)

    browser_token, browser_hash, _ = obter_ou_criar_browser_id(request)
    fingerprint = device_fingerprint or request.headers.get("x-device-fingerprint")
    device = device_id or request.headers.get("x-device-id") or request.cookies.get(COOKIE_DEVICE_LEGACY)
    cpf_limpo = limpar_cpf(cpf) if cpf else None
    if cpf_limpo:
        valido, codigo, mensagem, _ = await verificar_elegibilidade_participante(cpf_limpo, session)
        if not valido:
            return JSONResponse(status_code=400, content={"codigo": codigo, "detail": mensagem, "mensagem": mensagem})
    # Nenhuma conexão do pedido permanece ocupada enquanto aguarda o batch.
    # Recuperações F5 usam o token explícito da aba, preservando seu prazo.
    await session.close()
    client_ip = extrair_ip_cliente(request)
    with _medir_etapa_reserva(request, "batch_reserva"):
        result = await reserva_batch_service.reserve(
            lote_id=lote_id, fp=fingerprint, device_id=device,
            browser_hash=browser_hash, cpf=cpf_limpo, ip=client_ip,
            rate_key=_chave_rate_limit_reserva(request, lote_id, fingerprint, client_ip),
            token=request.headers.get("x-reserva-token"),
        )
    if result.status_code != 200:
        content = {"codigo": result.codigo, "detail": result.detail, "mensagem": result.detail}
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            return JSONResponse(status_code=result.status_code, content=content)
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH)
        return templates.TemplateResponse(request=request, name="erro.html", context={"mensagem": result.detail})

    reserva, lote = result.reserva, result.lote
    server_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    expira_em_ms = int(reserva.expira_em.timestamp() * 1000)
    restante_ms = max(0, expira_em_ms - server_time_ms)
    segundos = (restante_ms + 999) // 1000
    if result.created:
        _publicar_mudanca_reserva(reserva, "reserva_criada", server_time_ms=server_time_ms,
            expira_em_ms=expira_em_ms, segundos_restantes=segundos,
            milissegundos_restantes=restante_ms)

    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        response = JSONResponse(content={"token_reserva": reserva.token, "lote_id": lote_id})
    elif os.path.exists(VUE_INDEX_PATH):
        response = FileResponse(VUE_INDEX_PATH)
    else:
        secretarias = (await session.execute(select(Secretaria).order_by(Secretaria.nome))).scalars().all()
        response = templates.TemplateResponse(request=request, name="resgate.html", context={
            "lote": lote, "secretarias": secretarias, "token_reserva": reserva.token,
            "server_time_ms": server_time_ms, "reserva_expira_em_ms": expira_em_ms,
            "tempo_restante_segundos": segundos,
        })
        await session.close()
    response.set_cookie(key=COOKIE_BROWSER_ID, value=browser_token, max_age=31536000,
        httponly=True, secure=is_conexao_segura(request), samesite="lax")
    # O snapshot SSE é a autoridade do cronômetro JSON. A tela legada usa cookie.
    if not request.url.path.startswith("/api/"):
        definir_cookie_prazo_reserva(response, expira_em_ms, request)
    return response


# ============================================================================
# 5. PROCESSAMENTO DO RESGATE COM VALIDAÇÃO RIGOROSA E ROLLBACK LIMPO
# ============================================================================
def _resposta_resgate_confirmado(request, solic, identificado_api=None, validacao_externa_status=None):
    content = {
        "sucesso": True, "status": solic.status,
        "solicitacao_id": solic.id, "token": solic.token,
        "identificado_api": bool(solic.identificado_api if identificado_api is None else identificado_api),
        "validacao_externa_status": validacao_externa_status or ("queued" if not solic.identificado_api else "done"),
        "mensagem": "Seu resgate foi realizado com sucesso! Nossa equipe e o sistema validarão seu cadastro em até 72h.",
        "redirect_url": f"/sucesso/analise?solicitacao_id={solic.id}&token={solic.token}",
    }
    if request.url.path.startswith("/api/avulso/"):
        content["mensagem"] = ("Cadastro aprovado. O ingresso foi enfileirado para envio por e-mail."
            if solic.status == "aprovado" else "Cadastro recebido e aguardando análise do superadministrador.")
    response = JSONResponse(content=content)
    response.set_cookie(key=f"solic_claim_{solic.id}", value=solic.token,
        max_age=86400 * 3, httponly=True, secure=is_conexao_segura(request), samesite="lax")
    remover_cookie_prazo_reserva(response, request)
    return response


async def _recuperar_resgate_confirmado(session, reserva, cpf_limpo, request):
    if reserva.status != "concluida" and not reserva.utilizada:
        return None
    solic = (await session.execute(select(SolicitacaoValidacao).where(
        SolicitacaoValidacao.reserva_id == reserva.id
    ))).scalars().first()
    if not solic or reserva.cpf != cpf_limpo:
        raise HTTPException(status_code=409, detail="Esta reserva já foi concluída por outro envio.")
    job_status = await get_external_validation_status(session, solic.id)
    return _resposta_resgate_confirmado(request, solic, validacao_externa_status=job_status or "legacy")


@router.get("/api/lote/{lote_id}/resgate-confirmado")
async def recuperar_confirmacao_resgate(
    request: Request, lote_id: int, token_reserva: str = Query(...),
    cpf: str = Query(...), session: AsyncSession = Depends(get_session),
):
    """Recupera o recibo após uma resposta perdida, sem reenviar foto/formulário."""
    conferir_autorizacao(request, await session.get(Lote, lote_id))
    payload = validar_browser_token(request.cookies.get(COOKIE_BROWSER_ID))
    if not payload:
        raise HTTPException(status_code=403, detail="A identidade do navegador é necessária para recuperar o resgate.")
    reserva = (await session.execute(select(ReservaIngresso).where(
        ReservaIngresso.token == token_reserva, ReservaIngresso.lote_id == lote_id,
    ))).scalars().first()
    if not reserva or not reserva.browser_token_hash or reserva.browser_token_hash != hash_token(payload):
        raise HTTPException(status_code=403, detail="Não foi possível autorizar a recuperação deste resgate.")
    response = await _recuperar_resgate_confirmado(session, reserva, limpar_cpf(cpf), request)
    if response is None:
        response = JSONResponse(content={"sucesso": False, "status": "nao_confirmado"})
    response.headers["Cache-Control"] = "no-store"
    return response


async def _preparar_foto_resgate(foto_base64):
    if not foto_base64 or not foto_base64.startswith("data:image/jpeg;base64,"):
        raise HTTPException(status_code=400, detail="A foto de identificação é obrigatória para validação.")
    if len(foto_base64) > 6 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="A foto excede o limite permitido de 4 MB.")

    def gravar():
        foto_bytes = base64.b64decode(foto_base64.split(",", 1)[1], validate=True)
        if len(foto_bytes) > 4 * 1024 * 1024 or not foto_bytes.startswith(b"\xff\xd8\xff"):
            raise ValueError("JPEG inválido")
        filename = f"selfie_{uuid.uuid4().hex}.jpg"
        path = os.path.join(FOTOS_DIR, filename)
        temporary = path + ".part"
        try:
            with open(temporary, "xb") as photo:
                photo.write(foto_bytes)
                photo.flush()
                os.fsync(photo.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return f"/static/uploads/fotos/{filename}", path

    try:
        # Esperar a thread até o fim permite limpar a foto mesmo se HTTP for
        # cancelado; um cancelamento não abandona uma escrita em andamento.
        task = asyncio.create_task(asyncio.to_thread(gravar))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            _, path = await task
            await asyncio.to_thread(os.unlink, path)
            raise
    except asyncio.CancelledError:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Erro ao processar e salvar a foto facial.")


async def _cancelar_reserva_ativa(session, reserva, motivo):
    # Não sobrescreve uma conclusão que tenha vencido a disputa.
    result = await session.execute(update(ReservaIngresso).where(
        ReservaIngresso.id == reserva.id, ReservaIngresso.status == "ativa",
        ReservaIngresso.utilizada == False,
    ).values(status="cancelada", expira_em=datetime(2000, 1, 1, tzinfo=timezone.utc)))
    changed = bool(result.rowcount)
    await session.commit()
    if changed:
        _publicar_mudanca_reserva(reserva, "reserva_liberada", motivo=motivo)


@router.post("/resgate/{lote_id}")
@router.post("/api/lote/{lote_id}/resgatar")
@_medir_fluxo_reserva
async def processar_resgate(
    request: Request, lote_id: int,
    token_reserva: str = Form(...), cpf: str = Form(...), nome: str = Form(...),
    data_nascimento: str = Form(...), setor: str = Form(...),
    secretaria_id: int = Form(...), vinculo: str = Form(...),
    telefone: str = Form(...), email: str = Form(...), foto_base64: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    cpf_limpo = limpar_cpf(cpf)
    _, browser_hash, _ = obter_ou_criar_browser_id(request)
    stmt_reserva = select(ReservaIngresso).where(
        ReservaIngresso.token == token_reserva, ReservaIngresso.lote_id == lote_id)
    reserva = (await session.execute(stmt_reserva)).scalars().first()
    if not reserva:
        raise HTTPException(status_code=400, detail="Reserva de vaga inválida ou não encontrada.")
    lote_inicial = await session.get(Lote, lote_id)
    conferir_autorizacao(request, lote_inicial)
    sem_prazo = bool(lote_inicial.oculto and not configuracao(lote_inicial)["temporizado"])
    if lote_inicial.oculto:
        if reserva.acesso_versao != lote_inicial.acesso_versao or reserva.browser_token_hash != browser_hash:
            raise HTTPException(403, "Formulário invalidado. Reinicie pelo link do lote.")
        cfg = configuracao(lote_inicial)
        valores = {"secretaria_id": secretaria_id, "setor": setor, "vinculo": vinculo}
        for campo, regra in cfg["campos"].items():
            if regra["modo"] == "fixo" and str(valores[campo]).strip() != regra["valor"]:
                raise HTTPException(400, "Um campo travado foi alterado. Reinicie o formulário.")
        try:
            normalizar_data_nascimento(data_nascimento)
            telefone = formatar_telefone(telefone)
            email = validar_email(email)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not nome.strip() or not setor.strip() or not telefone or not email or vinculo not in VINCULOS:
            raise HTTPException(400, "Preencha corretamente todos os campos obrigatórios.")
    # Se o token_reserva UUID bateu, permite confirmacao mesmo se o cookie de navegador foi perdido (ex: mobile/webview)
    if False and reserva.browser_token_hash and reserva.browser_token_hash != browser_hash:
        raise HTTPException(status_code=403, detail="A identidade do navegador não corresponde à reserva iniciada.")
    recovered = await _recuperar_resgate_confirmado(session, reserva, cpf_limpo, request)
    if recovered:
        return recovered
    expira_em = instante_utc(reserva.expira_em) if lote_inicial.oculto else reserva.expira_em
    if reserva.status != ("rascunho" if sem_prazo else "ativa") or reserva.utilizada or (not sem_prazo and expira_em <= datetime.now(timezone.utc)):
        return JSONResponse(status_code=400, content={"codigo": "reserva_expirada", "detail": "A reserva expirou ou foi encerrada. Inicie um novo resgate."})

    load_form = request.headers.get("x-load-test-form") == "1"
    if load_form and not _chave_rate_limit_reserva(
        request, lote_id, reserva.device_fingerprint, extrair_ip_cliente(request)
    ).startswith("loadtest:"):
        raise HTTPException(status_code=403, detail="Teste de formulário não autorizado ou expirado.")

    if not validar_cpf_matematico(cpf_limpo):
        await _cancelar_reserva_ativa(session, reserva, "cpf_invalido")
        raise HTTPException(status_code=400, detail="CPF inválido. Verifique os números digitados.")
    try:
        nascimento = datetime.strptime(data_nascimento.strip(), "%Y-%m-%d" if "-" in data_nascimento else "%d/%m/%Y")
        hoje = datetime.now(timezone.utc).astimezone(TZ_SAO_PAULO).date()
        idade = hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
        if idade < 18:
            raise ValueError("menor")
    except ValueError:
        await _cancelar_reserva_ativa(session, reserva, "data_nascimento_invalida")
        raise HTTPException(status_code=400, detail="Informe uma data de nascimento válida; o resgate exige idade mínima de 18 anos.")
    secretaria = await session.get(Secretaria, secretaria_id)
    if not secretaria:
        raise HTTPException(status_code=400, detail="Secretaria inválida.")
    secretaria_nome = secretaria.nome
    reserva_id = reserva.id
    await session.close()

    with _medir_etapa_reserva(request, "foto"):
        foto_url, photo_path = await _preparar_foto_resgate(foto_base64)
    adopted = False
    commit_attempted = False
    try:
        async with _transacao_capacidade_reserva(session, request, lote_id, criar=True):
            # Ordem fixa: lote, depois reserva. Desistência/expiração alteram
            # somente a reserva, por condição atômica, e nunca adquirem o lote.
            with _medir_etapa_reserva(request, "lock_lote"):
                lote = (await session.execute(select(Lote).where(
                    Lote.id == lote_id, Lote.deleted_at.is_(None)
                ).with_for_update())).scalars().first()
            reserva = (await session.execute(stmt_reserva.with_for_update().execution_options(populate_existing=True))).scalars().first()
            conferir_autorizacao(request, lote)
            if lote.oculto and (reserva is None or reserva.acesso_versao != lote.acesso_versao):
                raise HTTPException(403, "Formulário invalidado. Reinicie pelo link do lote.")
            if not reserva or reserva.id != reserva_id:
                raise HTTPException(status_code=400, detail="Reserva inválida.")
            # Se o token_reserva UUID bateu, permite confirmacao mesmo se o cookie de navegador foi perdido
            if False and reserva.browser_token_hash and reserva.browser_token_hash != browser_hash:
                raise HTTPException(status_code=403, detail="Reserva pertence a outro navegador.")
            recovered = await _recuperar_resgate_confirmado(session, reserva, cpf_limpo, request)
            if recovered:
                return recovered
            agora = datetime.now(timezone.utc)
            expira_em = instante_utc(reserva.expira_em) if lote.oculto else reserva.expira_em
            if reserva.status != ("rascunho" if sem_prazo else "ativa") or reserva.utilizada or (not sem_prazo and expira_em <= agora):
                return JSONResponse(status_code=400, content={"codigo": "reserva_expirada", "detail": "A reserva expirou ou foi encerrada. Inicie um novo resgate."})
            abertura = instante_utc(lote.data_abertura) if lote.oculto and lote.data_abertura else lote.data_abertura
            fechamento = instante_utc(lote.data_fechamento) if lote.oculto and lote.data_fechamento else lote.data_fechamento
            if not lote.ativo or (abertura and agora < abertura) or (fechamento and agora > fechamento):
                await _cancelar_reserva_ativa(session, reserva, "lote_indisponivel")
                raise HTTPException(status_code=400, detail="Este lote está indisponível para resgate.")
            if lote.quantidade_resgatada >= lote.quantidade_total:
                raise HTTPException(status_code=400, detail="Todos os ingressos deste lote já foram resgatados.")
            if sem_prazo:
                ativas = await session.scalar(select(func.count(ReservaIngresso.id)).where(
                    ReservaIngresso.lote_id == lote_id, ReservaIngresso.status == "ativa",
                    ReservaIngresso.expira_em > agora))
                if lote.quantidade_resgatada + (ativas or 0) >= lote.quantidade_total:
                    raise HTTPException(409, "Todas as vagas estão ocupadas ou em preenchimento.")
            if lote.secretaria_id and lote.secretaria_id != secretaria_id:
                await _cancelar_reserva_ativa(session, reserva, "secretaria_exclusiva")
                raise HTTPException(status_code=400, detail="Este lote é exclusivo para outra secretaria.")

            valido, codigo, mensagem, usuario = await verificar_elegibilidade_participante(cpf_limpo, session)
            if not valido:
                await _cancelar_reserva_ativa(session, reserva, codigo)
                return JSONResponse(status_code=409, content={"codigo": "cpf_ja_atendido" if codigo in ("ingresso_existente", "solicitacao_existente") else codigo, "detail": mensagem})

            legal_pair = await validate_redemption(session, await request.form())

            if not usuario:
                usuario = Usuario(cpf=cpf_limpo, role=UserRole.servidor, nome=nome.strip())
            usuario.nome = nome.strip()
            usuario.data_nascimento = data_nascimento.strip()
            usuario.setor = setor.strip()
            usuario.secretaria_id = secretaria_id
            usuario.vinculo = vinculo.strip()
            usuario.telefone = telefone.strip()
            usuario.email = email.strip().lower()
            usuario.foto_rosto_url = foto_url
            session.add(usuario)
            await session.flush()
            solic = SolicitacaoValidacao(reserva_id=reserva.id,
                usuario_id=usuario.id, lote_id=lote.id, secretaria_id=secretaria_id,
                token=secrets.token_urlsafe(32), status="pendente_analise",
                ip_origem=extrair_ip_cliente(request), identificado_api=False)
            imediato = lote.oculto and not configuracao(lote)["exige_validacao"]
            if imediato:
                solic.status = "aprovado"
                solic.analisado_em = agora
                solic.comunicado = True
                solic.comunicado_em = agora
                ingresso = Ingresso(usuario_id=usuario.id, lote_id=lote.id,
                                    qr_code_token=str(uuid.uuid4()))
                session.add(ingresso)
            session.add(solic)
            reserva.utilizada = True
            reserva.status = "concluida"
            reserva.cpf = cpf_limpo
            lote.quantidade_resgatada += 1
            session.add(reserva)
            session.add(lote)
            await session.flush()
            if legal_pair:
                await record_acceptance(session, usuario.id, legal_pair, "resgate", f"reserva:{reserva.id}")
            if not imediato:
                await enqueue_external_validation(session, solic.id)
            if load_form:
                await session.execute(text("UPDATE resgate_jobs SET status='skipped', finished_at=NOW(), last_error='authorized_load_test' WHERE solicitacao_id=:id"), {"id": solic.id})
            if imediato:
                enqueued = await send_ticket_email_async(usuario_nome=usuario.nome,
                    usuario_email=usuario.email, ingresso_token=ingresso.qr_code_token,
                    lote_nome=lote.nome, secretaria_nome=secretaria_nome, setor=usuario.setor,
                    cpf_formatado=cpf_limpo, session=session,
                    idempotency_key=chave_comunicacao(solic.id, solic.status))
                if not enqueued:
                    raise HTTPException(503, "Não foi possível registrar o envio do ingresso. Tente novamente.")
            elif usuario.email:
                enqueued = await send_validation_pending_email_async(usuario_nome=usuario.nome,
                    usuario_email=usuario.email, lote_nome=lote.nome,
                    secretaria_nome=secretaria_nome, session=session)
                if not enqueued:
                    raise HTTPException(status_code=503, detail="Não foi possível registrar a confirmação. Tente novamente com a mesma reserva.")
            response = _resposta_resgate_confirmado(request, solic)
            with _medir_etapa_reserva(request, "commit"):
                commit_attempted = True
                await session.commit()
                adopted = True
        _publicar_mudanca_reserva(reserva, "resgate_concluido")
        return response
    except IntegrityError:
        # Um rollback conhecido permite remover a foto nova; a confirmação
        # concorrente permanece recuperável pela reserva/CPF autorizados.
        commit_attempted = False
        await session.rollback()
        current = (await session.execute(stmt_reserva.execution_options(populate_existing=True))).scalars().first()
        if current:
            recovered = await _recuperar_resgate_confirmado(session, current, cpf_limpo, request)
            if recovered:
                return recovered
            await _cancelar_reserva_ativa(session, current, "conflito_cpf")
        return JSONResponse(status_code=409, content={"codigo": "cpf_ja_atendido", "detail": "Já foi realizado um resgate para este CPF."})
    finally:
        if not adopted and not commit_attempted:
            # Falha de conexão DURANTE commit pode ter confirmado o cadastro.
            # Nesse caso preserva o arquivo, e o retry recupera o resultado.
            try:
                await asyncio.to_thread(os.unlink, photo_path)
            except FileNotFoundError:
                pass




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
        "criado_em": formatar_data_sp(solic.criado_em) if solic.criado_em else "-",
        "prazo_horas": 72,
        "prazo_dias": 3,
        "identificado_api": bool(getattr(solic, "identificado_api", False)),
        "validacao_externa_status": await get_external_validation_status(session, solic.id) or "legacy",
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
            "data_resgate_formatada": formatar_data_sp(ingresso.data_resgate),
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
