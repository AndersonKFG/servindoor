import asyncio
import time
from datetime import datetime
from typing import Optional, List, Dict
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, or_, and_, desc
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.all_models import Lote, Usuario, Ingresso, ReservaIngresso, UserRole

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

DATA_FESTA_ISO = "2026-10-30T14:00:00"
DATA_FESTA_OBJ = datetime.fromisoformat(DATA_FESTA_ISO)
VUE_INDEX_PATH = "app/static/dist/index.html"

_live_status_cache: Dict[str, dict] = {}
_CACHE_TTL = 1.0

def extrair_ip_cliente(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    x_fwd = request.headers.get("x-forwarded-for")
    if x_fwd:
        return x_fwd.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"

def calcular_status_publico(lote: Optional[Lote], vagas_disponiveis: int, agora: datetime) -> dict:
    if not lote:
        dist_festa = int((DATA_FESTA_OBJ - agora).total_seconds())
        return {
            "status_slug": "contagem_festa",
            "status_label": "CONTAGEM REGRESSIVA",
            "badge_class": "bg-primary",
            "pode_resgatar": False,
            "segundos_para_abrir": max(0, dist_festa)
        }

    if not lote.ativo:
        return {
            "status_slug": "pausado",
            "status_label": "LOTE PAUSADO",
            "badge_class": "bg-secondary",
            "pode_resgatar": False,
            "segundos_para_abrir": 0
        }

    if lote.data_abertura and agora < lote.data_abertura:
        seg_restantes = int((lote.data_abertura - agora).total_seconds())
        return {
            "status_slug": "agendado",
            "status_label": "ABERTURA EM BREVE",
            "badge_class": "bg-warning",
            "pode_resgatar": False,
            "segundos_para_abrir": max(0, seg_restantes)
        }

    if lote.data_fechamento and agora > lote.data_fechamento:
        return {
            "status_slug": "encerrado",
            "status_label": "LOTE ENCERRADO",
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

async def obter_lote_relevante(session: AsyncSession, agora: datetime, lote_id: Optional[int] = None) -> Optional[Lote]:
    if lote_id:
        stmt = (
            select(Lote)
            .options(selectinload(Lote.secretaria))
            .where(Lote.id == lote_id)
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    stmt_aberto = (
        select(Lote)
        .options(selectinload(Lote.secretaria))
        .where(
            Lote.ativo == True,
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
            Lote.data_abertura > agora
        )
        .order_by(Lote.data_abertura.asc())
    )
    res_agendado = await session.execute(stmt_agendado)
    lote = res_agendado.scalars().first()
    if lote:
        return lote

    stmt_qualquer = (
        select(Lote)
        .options(selectinload(Lote.secretaria))
        .where(Lote.ativo == True)
        .order_by(Lote.id.desc())
    )
    res_qualquer = await session.execute(stmt_qualquer)
    return res_qualquer.scalars().first()


@router.get("/")
async def home(request: Request, session: AsyncSession = Depends(get_session)):
    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)

    agora = datetime.now()
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
                "data_festa_formatada": "30/10/2026 às 14:00",
                "status_info": status_info,
                "lote": None,
                "reservas_ativas": 0,
                "vagas_disponiveis": 0,
                "minha_reserva_segundos": None,
                "minha_reserva_expira_em_ms": None,
                "server_time_ms": int(agora.timestamp() * 1000)
            }
        )

    stmt_reservas = (
        select(func.count(ReservaIngresso.id))
        .where(
            ReservaIngresso.lote_id == lote.id,
            ReservaIngresso.utilizada == False,
            ReservaIngresso.expira_em > agora
        )
    )
    res_count = await session.execute(stmt_reservas)
    reservas_ativas = res_count.scalar() or 0

    vagas_disponiveis = max(0, lote.quantidade_total - (lote.quantidade_resgatada + reservas_ativas))
    status_info = calcular_status_publico(lote, vagas_disponiveis, agora)

    minha_reserva_segundos = None
    minha_reserva_expira_em_ms = None
    minha_reserva_token = None

    if device_id:
        stmt_minha = (
            select(ReservaIngresso)
            .where(
                ReservaIngresso.lote_id == lote.id,
                ReservaIngresso.utilizada == False,
                ReservaIngresso.expira_em > agora,
                ReservaIngresso.device_id == device_id
            )
            .order_by(desc(ReservaIngresso.expira_em))
        )
        res_minha = await session.execute(stmt_minha)
        minha_res = res_minha.scalars().first()
        if minha_res:
            minha_reserva_segundos = max(1, int((minha_res.expira_em - agora).total_seconds()))
            minha_reserva_expira_em_ms = int(minha_res.expira_em.timestamp() * 1000)
            minha_reserva_token = minha_res.token

    response = templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "modo_festa": False,
            "lote": lote,
            "status_info": status_info,
            "reservas_ativas": reservas_ativas,
            "vagas_disponiveis": vagas_disponiveis,
            "minha_reserva_segundos": minha_reserva_segundos,
            "minha_reserva_expira_em_ms": minha_reserva_expira_em_ms,
            "minha_reserva_token": minha_reserva_token,
            "server_time_ms": int(agora.timestamp() * 1000)
        }
    )

    return response


@router.get("/api/lote/live-status")
async def live_status(
    request: Request,
    lote_id: Optional[int] = None,
    device_fingerprint: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """API de alta performance para sincronização em tempo real (1-2s) com timestamp oficial do servidor"""
    agora = datetime.now()
    client_ip = extrair_ip_cliente(request)
    device_id = device_fingerprint or request.headers.get("x-device-fingerprint") or request.cookies.get("festa_device_id")

    server_time_ms = int(agora.timestamp() * 1000)
    lote = await obter_lote_relevante(session, agora, lote_id=lote_id)

    if not lote:
        status_festa = calcular_status_publico(None, 0, agora)
        return JSONResponse(
            content={
                "has_lote": False,
                "modo_festa": True,
                "server_time_ms": server_time_ms,
                "server_time_iso": agora.isoformat(),
                "data_festa_iso": DATA_FESTA_ISO,
                "data_festa_formatada": "30/10/2026 às 14:00",
                "status_slug": "contagem_festa",
                "status_label": "CONTAGEM REGRESSIVA",
                "badge_class": "bg-primary",
                "segundos_para_abrir": status_festa["segundos_para_abrir"],
                "minha_reserva_segundos": None,
                "minha_reserva_expira_em_ms": None,
                "minha_reserva_token": None
            },
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )

    cache_key = f"lote_{lote.id}"
    cache_entry = _live_status_cache.get(cache_key)
    agora_mono = time.monotonic()

    if cache_entry and (agora_mono - cache_entry["time"] < _CACHE_TTL):
        reservas_ativas = cache_entry["reservas_ativas"]
        vagas_disponiveis = cache_entry["vagas_disponiveis"]
        status_info = cache_entry["status_info"]
    else:
        stmt_reservas = (
            select(func.count(ReservaIngresso.id))
            .where(
                ReservaIngresso.lote_id == lote.id,
                ReservaIngresso.utilizada == False,
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

    minha_reserva_segundos = None
    minha_reserva_expira_em_ms = None
    minha_reserva_token = None

    if device_id:
        stmt_minha = (
            select(ReservaIngresso)
            .where(
                ReservaIngresso.lote_id == lote.id,
                ReservaIngresso.utilizada == False,
                ReservaIngresso.expira_em > agora,
                or_(
                    ReservaIngresso.device_id == device_id,
                    ReservaIngresso.device_id == request.cookies.get("festa_device_id")
                )
            )
            .order_by(desc(ReservaIngresso.expira_em))
        )
        res_minha = await session.execute(stmt_minha)
        minha_res = res_minha.scalars().first()
        if minha_res:
            minha_reserva_segundos = max(1, int((minha_res.expira_em - agora).total_seconds()))
            minha_reserva_expira_em_ms = int(minha_res.expira_em.timestamp() * 1000)
            minha_reserva_token = minha_res.token

    return JSONResponse(
        content={
            "has_lote": True,
            "modo_festa": False,
            "id": lote.id,
            "nome": lote.nome,
            "secretaria_nome": lote.secretaria.nome if lote.secretaria else None,
            "quantidade_total": lote.quantidade_total,
            "quantidade_resgatada": lote.quantidade_resgatada,
            "reservas_ativas": reservas_ativas,
            "vagas_disponiveis": vagas_disponiveis,
            "data_abertura_iso": lote.data_abertura.isoformat() if lote.data_abertura else None,
            "data_fechamento_iso": lote.data_fechamento.isoformat() if lote.data_fechamento else None,
            "data_fechamento_formatada": lote.data_fechamento.strftime("%d/%m/%Y às %H:%M") if lote.data_fechamento else None,
            "status_slug": status_info["status_slug"],
            "status_label": status_info["status_label"],
            "badge_class": status_info["badge_class"],
            "pode_resgatar": status_info["pode_resgatar"],
            "segundos_para_abrir": status_info["segundos_para_abrir"],
            "server_time_ms": server_time_ms,
            "server_time_iso": agora.isoformat(),
            "minha_reserva_segundos": minha_reserva_segundos,
            "minha_reserva_expira_em_ms": minha_reserva_expira_em_ms,
            "minha_reserva_token": minha_reserva_token
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )
