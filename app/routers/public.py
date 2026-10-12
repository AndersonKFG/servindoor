import math
import os
import json
import asyncio
import time
import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Dict
from fastapi import APIRouter, Request, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, or_, and_, desc
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.all_models import Lote, Usuario, Ingresso, ReservaIngresso, UserRole
from app.core.security import extrair_ip_cliente, formatar_iso_sp, para_epoch_ms_sp, TZ_SAO_PAULO
from app.core.events import lote_event_hub

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

DATA_FESTA_ISO = "2026-10-30T12:00:00-03:00"
DATA_FESTA_OBJ = datetime.fromisoformat(DATA_FESTA_ISO)
VUE_INDEX_PATH = "app/static/dist/index.html"

_live_status_cache: Dict[str, dict] = {}
_CACHE_TTL = 1.5

def invalidar_cache_live_status():
    """Invalida o cache de live-status para refletir novas reservas, desistências e alterações de lote imediatamente"""
    _live_status_cache.clear()

lote_event_hub.register_cache_invalidator(invalidar_cache_live_status)


def calcular_status_publico(lote: Optional[Lote], vagas_disponiveis: int, agora: datetime) -> dict:
    if not lote:
        agora_sp = agora.replace(tzinfo=TZ_SAO_PAULO) if agora.tzinfo is None else agora.astimezone(TZ_SAO_PAULO)
        dist_festa = int((DATA_FESTA_OBJ - agora_sp).total_seconds())
        return {
            "status_slug": "contagem_festa",
            "status_label": "CONTAGEM REGRESSIVA",
            "badge_class": "bg-primary",
            "pode_resgatar": False,
            "segundos_para_abrir": max(0, dist_festa)
        }

    if lote.data_abertura and agora < lote.data_abertura:
        seg_restantes = (lote.data_abertura - agora).total_seconds()
        if seg_restantes > 0.05:
            return {
                "status_slug": "agendado",
                "status_label": "ABERTURA EM BREVE",
                "badge_class": "bg-warning",
                "pode_resgatar": False,
                "segundos_para_abrir": max(1, int(math.ceil(seg_restantes)))
            }

    if lote.data_fechamento and agora > lote.data_fechamento:
        return {
            "status_slug": "encerrado",
            "status_label": "LOTE ENCERRADO",
            "badge_class": "bg-secondary",
            "pode_resgatar": False,
            "segundos_para_abrir": 0
        }

    if not lote.ativo:
        return {
            "status_slug": "pausado",
            "status_label": "LOTE PAUSADO",
            "badge_class": "bg-secondary",
            "pode_resgatar": False,
            "segundos_para_abrir": 0
        }

    if lote.quantidade_resgatada >= lote.quantidade_total:
        return {
            "status_slug": "esgotado",
            "status_label": "ESGOTADO",
            "badge_class": "bg-danger",
            "pode_resgatar": False,
            "segundos_para_abrir": 0
        }

    if vagas_disponiveis <= 0:
        return {
            "status_slug": "reservado",
            "status_label": "EM LIBERAÇÃO",
            "badge_class": "bg-warning",
            "pode_resgatar": True,
            "segundos_para_abrir": 0
        }

    return {
        "status_slug": "aberto",
        "status_label": "RESGATE LIBERADO",
        "badge_class": "bg-success",
        "pode_resgatar": True,
        "segundos_para_abrir": 0
    }


async def coletar_status_lote_para_sse(session: AsyncSession, lote_id: int) -> dict:
    """Calcula o status público atualizado para anexar aos eventos de reserva SSE."""
    agora = datetime.now(timezone.utc)
    lote = (await session.execute(
        select(Lote).where(Lote.id == lote_id, Lote.deleted_at.is_(None))
    )).scalars().first()
    if not lote:
        return {}

    reservas_ativas = (await session.execute(
        select(func.count(ReservaIngresso.id)).where(
            ReservaIngresso.lote_id == lote_id,
            ReservaIngresso.status == "ativa",
            ReservaIngresso.expira_em > agora
        )
    )).scalar() or 0
    vagas_disponiveis = max(0, lote.quantidade_total - (lote.quantidade_resgatada + reservas_ativas))
    return calcular_status_publico(lote, vagas_disponiveis, agora)

async def obter_lote_relevante(session: AsyncSession, agora: datetime, lote_id: Optional[int] = None) -> Optional[Lote]:
    if lote_id:
        stmt = (
            select(Lote)
            .options(selectinload(Lote.secretaria))
            .where(Lote.id == lote_id, Lote.deleted_at.is_(None))
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    stmt_aberto = (
        select(Lote)
        .options(selectinload(Lote.secretaria))
        .where(
            Lote.ativo == True,
            Lote.deleted_at.is_(None),
            or_(Lote.data_abertura.is_(None), Lote.data_abertura <= agora),
            or_(Lote.data_fechamento.is_(None), Lote.data_fechamento >= agora),
            Lote.quantidade_resgatada < Lote.quantidade_total
        )
        .order_by(Lote.id.asc())
    )
    res_aberto = await session.execute(stmt_aberto)
    lote = res_aberto.scalars().first()
    if lote:
        return lote

    stmt_agendado = (
        select(Lote)
        .options(selectinload(Lote.secretaria))
        .where(
            Lote.ativo == True,
            Lote.deleted_at.is_(None),
            Lote.data_abertura > agora
        )
        .order_by(Lote.data_abertura.asc())
    )
    res_agendado = await session.execute(stmt_agendado)
    lote = res_agendado.scalars().first()
    if lote:
        return lote

    stmt_pausado = (
        select(Lote)
        .options(selectinload(Lote.secretaria))
        .where(
            Lote.ativo == False,
            Lote.deleted_at.is_(None),
            or_(Lote.data_abertura.is_(None), Lote.data_abertura <= agora),
            or_(Lote.data_fechamento.is_(None), Lote.data_fechamento >= agora)
        )
        .order_by(Lote.id.desc())
    )
    res_pausado = await session.execute(stmt_pausado)
    lote = res_pausado.scalars().first()
    if lote:
        return lote

    stmt_qualquer = (
        select(Lote)
        .options(selectinload(Lote.secretaria))
        .where(Lote.deleted_at.is_(None))
        .order_by(Lote.id.desc())
    )
    res_qualquer = await session.execute(stmt_qualquer)
    return res_qualquer.scalars().first()


@router.get("/")
async def home(request: Request, session: AsyncSession = Depends(get_session)):
    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)

    agora = datetime.now(timezone.utc)
    client_ip = extrair_ip_cliente(request)
    device_id = request.cookies.get("festa_device_id")

    lote = await obter_lote_relevante(session, agora)

    if not lote:
        status_info = calcular_status_publico(None, 0, agora)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "modo_festa": True,
                "data_festa_iso": DATA_FESTA_ISO,
                "data_festa_formatada": "30/10/2026 às 12:00",
                "status_info": status_info,
                "lote": None,
                "minha_reserva_segundos": None,
                "minha_reserva_expira_em_ms": None,
                "server_time_ms": int(agora.timestamp() * 1000)
            }
        )

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

    vagas_disponiveis = max(0, lote.quantidade_total - (lote.quantidade_resgatada + reservas_ativas))
    status_info = calcular_status_publico(lote, vagas_disponiveis, agora)

    minha_reserva_segundos = None
    minha_reserva_milissegundos = None
    minha_reserva_expira_em_ms = None
    minha_reserva_token = None

    browser_hash_home = _obter_browser_token_hash_public(request)
    conds_home = []
    if browser_hash_home:
        conds_home.append(ReservaIngresso.browser_token_hash == browser_hash_home)
    if device_id:
        conds_home.append(ReservaIngresso.device_id == device_id)
    if request.cookies.get("festa_device_id"):
        conds_home.append(ReservaIngresso.device_id == request.cookies.get("festa_device_id"))

    if conds_home:
        stmt_minha = (
            select(ReservaIngresso)
            .where(
                ReservaIngresso.lote_id == lote.id,
                ReservaIngresso.status == "ativa",
                ReservaIngresso.expira_em > agora,
                or_(*conds_home)
            )
            .order_by(desc(ReservaIngresso.expira_em))
        )
        res_minha = await session.execute(stmt_minha)
        minha_res = res_minha.scalars().first()
        if minha_res:
            restante_ms = max(0, int((minha_res.expira_em - agora).total_seconds() * 1000))
            if restante_ms > 0:
                minha_reserva_milissegundos = restante_ms
                minha_reserva_segundos = (restante_ms + 999) // 1000
                minha_reserva_expira_em_ms = int(agora.timestamp() * 1000) + restante_ms
                minha_reserva_token = minha_res.token

    response = templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "modo_festa": False,
            "lote": lote,
            "status_info": status_info,
            "minha_reserva_segundos": minha_reserva_segundos,
            "minha_reserva_milissegundos": minha_reserva_milissegundos,
            "minha_reserva_expira_em_ms": minha_reserva_expira_em_ms,
            "minha_reserva_token": minha_reserva_token,
            "server_time_ms": int(agora.timestamp() * 1000)
        }
    )

    return response


@router.get("/api/time")
async def get_server_time(t: Optional[str] = None):
    """Endpoint de altíssima precisão NTP para sincronização de relógios dos clientes"""
    agora = datetime.now(timezone.utc)
    now_ms = int(agora.timestamp() * 1000)
    return JSONResponse(
        content={
            "server_time_ms": now_ms,
            "server_time_iso": agora.isoformat()
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )


def _obter_browser_token_hash_public(request: Request) -> Optional[str]:
    from app.routers.resgate import validar_browser_token, hash_token
    tok = request.cookies.get("festa_browser_id")
    valid_payload = validar_browser_token(tok)
    if valid_payload:
        return hash_token(valid_payload)
    legacy = request.cookies.get("festa_device_id")
    if legacy and len(legacy.strip()) >= 16:
        return hashlib.sha256(legacy.strip().encode("utf-8")).hexdigest()
    return None


def _reserva_datetime_utc(valor: Optional[datetime]) -> Optional[datetime]:
    """Interpreta timestamps sem fuso como horário local de São Paulo e normaliza para UTC."""
    if valor is None:
        return None
    if valor.tzinfo is None:
        return valor.replace(tzinfo=TZ_SAO_PAULO).astimezone(timezone.utc)
    return valor.astimezone(timezone.utc)


async def _obter_prazo_reserva_sse(
    session: AsyncSession,
    request: Request,
    lote_id: Optional[int],
    device_id: Optional[str],
    agora_utc: datetime,
) -> dict:
    """Resolve a reserva deste navegador e calcula o prazo uma única vez para o SSE."""
    resultado = {
        "minha_reserva_segundos": None,
        "minha_reserva_milissegundos": None,
        "minha_reserva_expira_em_ms": None,
        "minha_reserva_token": None,
    }
    if not lote_id:
        return resultado

    browser_hash = _obter_browser_token_hash_public(request)
    legacy_device_id = request.cookies.get("festa_device_id")
    condicoes = []
    if browser_hash:
        condicoes.append(ReservaIngresso.browser_token_hash == browser_hash)
    if device_id:
        condicoes.extend((
            ReservaIngresso.device_id == device_id,
            ReservaIngresso.device_fingerprint == device_id,
        ))
    if legacy_device_id:
        condicoes.append(ReservaIngresso.device_id == legacy_device_id)
    if not condicoes:
        return resultado

    stmt = (
        select(ReservaIngresso)
        .where(
            ReservaIngresso.lote_id == lote_id,
            ReservaIngresso.status == "ativa",
            ReservaIngresso.utilizada == False,
            or_(*condicoes),
        )
    )
    encontrados = (await session.execute(stmt)).scalars().all()

    # Filtra em UTC depois de normalizar os valores retornados pelo banco. Isso
    # evita comparar um timestamp local sem fuso com o relógio UTC do servidor.
    reservas_validas = []
    for reserva in encontrados:
        criada_em_utc = _reserva_datetime_utc(reserva.criada_em)
        expira_em_utc = _reserva_datetime_utc(reserva.expira_em)
        if criada_em_utc and expira_em_utc and criada_em_utc <= agora_utc < expira_em_utc:
            reservas_validas.append((reserva, criada_em_utc, expira_em_utc))

    if not reservas_validas:
        return resultado

    reserva_forte = next((item for item in reservas_validas if (
        (browser_hash and item[0].browser_token_hash == browser_hash) or
        (legacy_device_id and item[0].device_id == legacy_device_id)
    )), None)
    reserva, _criada_em_utc, expira_em_utc = reserva_forte or max(
        reservas_validas,
        key=lambda item: item[2],
    )

    restante_ms = max(0, int((expira_em_utc - agora_utc).total_seconds() * 1000))
    if restante_ms <= 0:
        return resultado

    resultado.update({
        "minha_reserva_segundos": (restante_ms + 999) // 1000,
        "minha_reserva_milissegundos": restante_ms,
        "minha_reserva_expira_em_ms": int(expira_em_utc.timestamp() * 1000),
    })
    if reserva_forte:
        resultado["minha_reserva_token"] = reserva.token
    return resultado


async def coletar_dados_live_status(
    session: AsyncSession,
    request: Request,
    lote_id: Optional[int] = None,
    device_id: Optional[str] = None
) -> dict:
    """Coleta o estado completo consolidado de lote, contagem e reserva ativa deste dispositivo"""
    agora = datetime.now(timezone.utc)
    dev_id = device_id or request.headers.get("x-device-fingerprint") or request.cookies.get("festa_device_id")

    server_time_ms = int(agora.timestamp() * 1000)
    cache_global_key = f"base_status_{lote_id or 0}"
    cache_entry = _live_status_cache.get(cache_global_key)
    agora_mono = time.monotonic()

    if cache_entry and (agora_mono - cache_entry["time"] < _CACHE_TTL):
        base_content = dict(cache_entry["content"])
        base_content["server_time_ms"] = server_time_ms
        base_content["server_time_iso"] = agora.isoformat()

        target_lote_id = base_content.get("id")
        prazo_reserva = await _obter_prazo_reserva_sse(
            session, request, target_lote_id, dev_id, agora
        )
        base_content.update(prazo_reserva)
        base_content["state_version"] = lote_event_hub.state_version

        return base_content

    lote = await obter_lote_relevante(session, agora, lote_id=lote_id)

    # 1. Verifica se ha lote com previsao de abertura futura (agendado)
    stmt_ag = (
        select(Lote)
        .where(
            Lote.ativo == True,
            Lote.deleted_at.is_(None),
            Lote.data_abertura.is_not(None),
            Lote.data_abertura > agora
        )
        .order_by(Lote.data_abertura.asc())
    )
    res_ag = await session.execute(stmt_ag)
    lote_com_previsao_obj = res_ag.scalars().first()
    tem_lote_com_previsao = lote_com_previsao_obj is not None

    # 2. Busca o lote mais recente aberto que ja encerrou
    stmt_enc = (
        select(Lote)
        .where(
            Lote.ativo == True,
            Lote.deleted_at.is_(None),
            or_(
                and_(Lote.data_fechamento.is_not(None), Lote.data_fechamento <= agora),
                Lote.quantidade_resgatada >= Lote.quantidade_total
            )
        )
        .order_by(desc(func.coalesce(Lote.data_fechamento, Lote.data_abertura)), desc(Lote.id))
    )
    res_enc = await session.execute(stmt_enc)
    lote_encerrado_recente_obj = res_enc.scalars().first()
    lote_encerrado_info = None

    if lote_encerrado_recente_obj:
        momento_fechamento = lote_encerrado_recente_obj.data_fechamento
        if lote_encerrado_recente_obj.quantidade_resgatada >= lote_encerrado_recente_obj.quantidade_total:
            stmt_last_ing = select(func.max(Ingresso.data_resgate)).where(Ingresso.lote_id == lote_encerrado_recente_obj.id)
            res_last = await session.execute(stmt_last_ing)
            ultimo_resgate = res_last.scalar()
            if ultimo_resgate:
                if momento_fechamento:
                    momento_fechamento = min(momento_fechamento, ultimo_resgate)
                else:
                    momento_fechamento = ultimo_resgate
        if not momento_fechamento:
            momento_fechamento = agora

        segundos_decorridos = max(0, int((agora - momento_fechamento).total_seconds()))
        lote_encerrado_info = {
            "id": lote_encerrado_recente_obj.id,
            "nome": lote_encerrado_recente_obj.nome,
            "data_encerramento_iso": momento_fechamento.isoformat(),
            "segundos_desde_encerramento": segundos_decorridos
        }

    if not lote:
        status_festa = calcular_status_publico(None, 0, agora)
        return {
            "has_lote": False,
            "modo_festa": True,
            "server_time_ms": server_time_ms,
            "server_time_iso": agora.isoformat(),
            "state_version": lote_event_hub.state_version,
            "data_festa_iso": DATA_FESTA_ISO,
            "data_festa_formatada": "30/10/2026 às 12:00",
            "status_slug": "contagem_festa",
            "status_label": "CONTAGEM REGRESSIVA",
            "badge_class": "bg-primary",
            "segundos_para_abrir": status_festa["segundos_para_abrir"],
            "tem_lote_com_previsao": tem_lote_com_previsao,
            "lote_previsao_id": lote_com_previsao_obj.id if (lote_com_previsao_obj and lote_com_previsao_obj.data_abertura) else None,
            "lote_previsao_abertura_iso": formatar_iso_sp(lote_com_previsao_obj.data_abertura) if (lote_com_previsao_obj and lote_com_previsao_obj.data_abertura) else None,
            "lote_previsao_abertura_ms": para_epoch_ms_sp(lote_com_previsao_obj.data_abertura) if (lote_com_previsao_obj and lote_com_previsao_obj.data_abertura) else None,
            "server_timezone": "America/Sao_Paulo",
            "lote_encerrado_recente": lote_encerrado_info,
            "minha_reserva_segundos": None,
            "minha_reserva_expira_em_ms": None,
            "minha_reserva_token": None
        }

    cache_key = f"lote_{lote.id}"
    cache_entry = _live_status_cache.get(cache_key)
    agora_mono = time.monotonic()

    cache_valido = False
    if cache_entry and (agora_mono - cache_entry["time"] < _CACHE_TTL):
        status_slug_cached = cache_entry.get("status_info", {}).get("status_slug")
        if status_slug_cached == "agendado" and lote.data_abertura and agora >= lote.data_abertura:
            cache_valido = False
        elif status_slug_cached == "aberto" and lote.data_fechamento and agora > lote.data_fechamento:
            cache_valido = False
        else:
            cache_valido = True

    if cache_valido:
        reservas_ativas = cache_entry["reservas_ativas"]
        vagas_disponiveis = cache_entry["vagas_disponiveis"]
        status_info = cache_entry["status_info"]
    else:
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

        vagas_disponiveis = max(0, lote.quantidade_total - (lote.quantidade_resgatada + reservas_ativas))
        status_info = calcular_status_publico(lote, vagas_disponiveis, agora)

        _live_status_cache[cache_key] = {
            "time": agora_mono,
            "reservas_ativas": reservas_ativas,
            "vagas_disponiveis": vagas_disponiveis,
            "status_info": status_info
        }

    prazo_reserva = await _obter_prazo_reserva_sse(
        session, request, lote.id, dev_id, agora
    )

    final_content = {
        "has_lote": True,
        "modo_festa": False,
        "id": lote.id,
        "nome": lote.nome,
        "secretaria_nome": lote.secretaria.nome if lote.secretaria else None,
        "data_abertura_iso": formatar_iso_sp(lote.data_abertura),
        "data_abertura_ms": para_epoch_ms_sp(lote.data_abertura),
        "data_fechamento_iso": formatar_iso_sp(lote.data_fechamento),
        "data_fechamento_ms": para_epoch_ms_sp(lote.data_fechamento),
        "data_fechamento_formatada": lote.data_fechamento.strftime("%d/%m/%Y às %H:%M") if lote.data_fechamento else None,
        "status_slug": status_info["status_slug"],
        "status_label": status_info["status_label"],
        "badge_class": status_info["badge_class"],
        "pode_resgatar": status_info["pode_resgatar"],
        "segundos_para_abrir": status_info["segundos_para_abrir"],
        "server_time_ms": server_time_ms,
        "server_time_iso": formatar_iso_sp(agora),
        "server_timezone": "America/Sao_Paulo",
        "state_version": lote_event_hub.state_version,
        "tem_lote_com_previsao": tem_lote_com_previsao,
        "lote_previsao_id": lote_com_previsao_obj.id if (lote_com_previsao_obj and lote_com_previsao_obj.data_abertura) else lote.id,
        "lote_previsao_abertura_iso": formatar_iso_sp(lote_com_previsao_obj.data_abertura) if (lote_com_previsao_obj and lote_com_previsao_obj.data_abertura) else None,
        "lote_previsao_abertura_ms": para_epoch_ms_sp(lote_com_previsao_obj.data_abertura) if (lote_com_previsao_obj and lote_com_previsao_obj.data_abertura) else None,
        "lote_encerrado_recente": lote_encerrado_info,
        "data_festa_iso": DATA_FESTA_ISO,
        "data_festa_formatada": "30/10/2026 às 12:00",
        **prazo_reserva
    }

    # Salva no cache global
    base_cached = dict(final_content)
    base_cached["minha_reserva_segundos"] = None
    base_cached["minha_reserva_milissegundos"] = None
    base_cached["minha_reserva_expira_em_ms"] = None
    base_cached["minha_reserva_token"] = None
    _live_status_cache[cache_global_key] = {
        "time": agora_mono,
        "content": base_cached
    }

    return final_content


@router.get("/api/lote/stream")
async def stream_lote_eventos(
    request: Request,
    last_version: Optional[int] = Query(None),
    device_fingerprint: Optional[str] = Query(None),
    lote_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_session)
):
    """
    Canal Server-Sent Events (SSE) oficial em tempo real (<50ms).
    Notifica instantaneamente todos os clientes conectados sobre alterações de lotes,
    reservas criadas/liberadas/concluídas, adiamentos, antecipações, ativações, pausas e encerramentos.
    Garante consistência absoluta e linearizabilidade:
    1. Registra a fila de eventos ANTES de ler o snapshot (zero window of vulnerability).
    2. Envia replay de quaisquer eventos ocorridos entre a requisição inicial (last_version) e a abertura do SSE.
    3. Envia o ESTADO_CONSOLIDADO atômico lido no exato momento da conexão.
    4. Continua entregando todos os eventos futuros em tempo real.
    """
    # 1. Registra na fila ANTES do snapshot para não perder nenhum evento que ocorra durante a leitura
    queue = await lote_event_hub.subscribe()
    dev_id = device_fingerprint or request.headers.get("x-device-fingerprint") or request.cookies.get("festa_device_id")

    # Extrai last_version (prioriza Query param, depois header oficial Last-Event-ID)
    header_last_id = request.headers.get("last-event-id")
    eff_version = last_version
    if not eff_version and header_last_id and header_last_id.isdigit():
        eff_version = int(header_last_id)

    # 2. Busca eventos perdidos no buffer caso o cliente tenha recebido versão anterior no fetch inicial
    missed_events = lote_event_hub.get_events_since(eff_version)

    # 3. Coleta estado atômico mais recente do banco de dados no momento exato desta conexão
    estado_atual = await coletar_dados_live_status(session, request, lote_id=lote_id, device_id=dev_id)
    version_snap = estado_atual.get("state_version", lote_event_hub.state_version)

    async def event_generator():
        try:
            # Handshake inicial informando conexão estabelecida
            yield f'id: {version_snap}\nevent: conectado\ndata: {{"status": "conectado", "state_version": {version_snap}}}\n\n'

            # Replay de eventos perdidos entre a requisição inicial e a abertura do SSE
            for ev in missed_events:
                yield ev

            # Snapshot do estado consolidado atual para garantir sincronização perfeita de dados e reserva
            yield f'id: {version_snap}\nevent: ESTADO_CONSOLIDADO\ndata: {json.dumps(estado_atual, ensure_ascii=False)}\n\n'

            while True:
                try:
                    # Aguarda mensagens de transmissão com timeout de 20s para keep-alive ping
                    msg = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await lote_event_hub.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/api/lote/live-status")
async def live_status(
    request: Request,
    lote_id: Optional[int] = None,
    device_fingerprint: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """API de consulta com timestamp oficial do servidor (utilizada como fallback ou carga inicial)"""
    dev_id = device_fingerprint or request.headers.get("x-device-fingerprint") or request.cookies.get("festa_device_id")
    final_content = await coletar_dados_live_status(session, request, lote_id=lote_id, device_id=dev_id)
    return JSONResponse(
        content=final_content,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )
