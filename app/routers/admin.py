import math
from app.core import security
from app.core.security import gerar_codigo_2fa_criptografico
from app.services.email_service import send_custom_message_email_async, send_ticket_email_async, send_lote_deletion_code_email_async, send_team_credentials_email_async
import csv
import io
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse, FileResponse, Response
import json
import secrets
import asyncio
import re
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, or_
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.all_models import Lote, Usuario, Ingresso, Secretaria, LogAcesso, MovimentoTipo, UserRole, ReservaIngresso, BackupLote, TokenExclusaoLote, SolicitacaoValidacao, SolicitacaoCancelamento
from app.core.deps import get_current_admin, get_current_admin_geral
from app.core.validators import normalizar_data_nascimento, formatar_telefone, validar_email
from app.core.events import lote_event_hub
from app.routers.public import coletar_status_lote_para_sse

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _datetime_utc(value: str, fuso_sem_offset=timezone.utc) -> datetime:
    """Preserva offsets explícitos; o formulário de lotes informa o fuso local."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=fuso_sem_offset)
    return parsed.astimezone(timezone.utc)


def _horarios_lote_para_formulario(lote: Lote) -> dict:
    """Entrega ISO com fuso e valores locais prontos para os campos datetime-local."""
    return {
        "data_abertura": security.formatar_iso_sp(lote.data_abertura),
        "data_fechamento": security.formatar_iso_sp(lote.data_fechamento),
        "data_abertura_input": security.formatar_data_sp(lote.data_abertura, "%Y-%m-%dT%H:%M") or "",
        "data_fechamento_input": security.formatar_data_sp(lote.data_fechamento, "%Y-%m-%dT%H:%M") or "",
    }


VUE_INDEX_PATH = "app/static/dist/index.html"

def calcular_status_lote(lote: Lote) -> dict:
    """
    Calcula o status do lote com base na regra soberana do período de resgate:
    1. Se agora > data_fechamento -> Encerrado (não pode toggle)
    2. Se agora < data_abertura -> Agendado (não pode toggle; período soberano)
    3. Se data_abertura <= agora <= data_fechamento -> Período de resgate ativo (pode toggle pausar/despausar)
    """
    agora = datetime.now(timezone.utc)
    
    # 1. Encerrado pelo horário final
    if lote.data_fechamento and agora > lote.data_fechamento:
        return {
            "key": "encerrado",
            "label": "Encerrado",
            "badge_class": "bg-dark",
            "icon": "bi-clock-history",
            "pode_toggle": False,
            "motivo_bloqueio": "Prazo de fechamento expirado."
        }
    
    # 2. Agendado para o futuro (o período é soberano, aguardando abertura)
    if lote.data_abertura and agora < lote.data_abertura:
        return {
            "key": "agendado",
            "label": "Agendado",
            "badge_class": "bg-warning",
            "icon": "bi-calendar-event-fill",
            "pode_toggle": False,
            "motivo_bloqueio": "Lote aguardando o horário de abertura."
        }
        
    # 3. Dentro do período de resgate válido (data_abertura <= agora <= data_fechamento)
    if not lote.ativo:
        return {
            "key": "pausado",
            "label": "Pausado",
            "badge_class": "bg-secondary",
            "icon": "bi-pause-circle-fill",
            "pode_toggle": True,
            "motivo_bloqueio": None
        }
        
    if lote.quantidade_resgatada >= lote.quantidade_total:
        return {
            "key": "esgotado",
            "label": "Esgotado",
            "badge_class": "bg-danger",
            "icon": "bi-x-circle-fill",
            "pode_toggle": True,
            "motivo_bloqueio": None
        }
        
    return {
        "key": "aberto",
        "label": "Aberto",
        "badge_class": "bg-success",
        "icon": "bi-check-circle-fill",
        "pode_toggle": True,
        "motivo_bloqueio": None
    }


def dados_status_lote_sse(lote: Lote) -> dict:
    """Campos de status para clientes refletirem alterações administrativas sem esperar polling."""
    status_lote = calcular_status_lote(lote)
    return {
        "status_slug": status_lote["key"],
        "status_label": status_lote["label"],
        "badge_class": status_lote["badge_class"]
    }

async def obter_dados_dashboard(session: AsyncSession):
    agora = datetime.now(timezone.utc)
    stmt_lotes = (
        select(Lote)
        .where(Lote.deleted_at.is_(None))
        .options(selectinload(Lote.secretaria))
        .order_by(Lote.id.asc())
    )
    res_lotes = await session.execute(stmt_lotes)
    lotes_raw = res_lotes.scalars().all()

    stmt_vagas = select(func.sum(Lote.quantidade_total)).where(Lote.deleted_at.is_(None))
    res_vagas = await session.execute(stmt_vagas)
    total_vagas = res_vagas.scalar() or 0

    # A ocupação por lote usa este contador como fonte oficial. Reutilizá-lo
    # mantém o KPI geral coerente com as barras exibidas na tabela, sem contar
    # ingressos órfãos ou registros divergentes do lote.
    total_resgatados = sum(max(0, lote.quantidade_resgatada or 0) for lote in lotes_raw)

    # Usa o relógio do servidor: reservas vencidas deixam de contar mesmo antes
    # de a rotina de expiração atualizar seu status no banco.
    stmt_em_resgate = (
        select(func.count(ReservaIngresso.id))
        .join(Lote, Lote.id == ReservaIngresso.lote_id)
        .where(
            Lote.deleted_at.is_(None),
            ReservaIngresso.status == "ativa",
            ReservaIngresso.utilizada == False,
            ReservaIngresso.criada_em <= agora,
            ReservaIngresso.expira_em > agora,
        )
    )
    total_em_resgate = (await session.execute(stmt_em_resgate)).scalar() or 0

    stmt_checkins = select(func.count(LogAcesso.id)).where(LogAcesso.tipo == MovimentoTipo.entrada)
    res_checkins = await session.execute(stmt_checkins)
    total_checkins = res_checkins.scalar() or 0

    lotes_processados = []
    lotes_abertos_count = 0

    for l in lotes_raw:
        st = calcular_status_lote(l)
        if st["key"] == "aberto":
            lotes_abertos_count += 1
        
        vagas_rest = max(0, l.quantidade_total - l.quantidade_resgatada)
        pct = round((l.quantidade_resgatada / l.quantidade_total * 100), 1) if l.quantidade_total > 0 else 0

        bar_color = "bg-primary"
        if pct >= 100:
            bar_color = "bg-danger"
        elif pct >= 80:
            bar_color = "bg-warning"
        elif pct > 0:
            bar_color = "bg-success"

        lotes_processados.append({
            "model": l,
            "status": st,
            "vagas_restantes": vagas_rest,
            "pct": pct,
            "bar_color": bar_color
        })

    stmt_sec = select(Secretaria).order_by(Secretaria.nome)
    res_sec = await session.execute(stmt_sec)
    secretarias = res_sec.scalars().all()

    taxa_ocupacao = round((total_resgatados / total_vagas * 100), 1) if total_vagas > 0 else 0

    metricas = {
        "total_vagas": total_vagas,
        "total_resgatados": total_resgatados,
        "total_em_resgate": total_em_resgate,
        "total_checkins": total_checkins,
        "total_lotes": len(lotes_raw),
        "lotes_abertos": lotes_abertos_count,
        "taxa_ocupacao": taxa_ocupacao
    }

    return metricas, lotes_processados, secretarias

@router.get("/api/lotes-admin")
async def api_lotes_admin(
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    metricas, lotes_processados, secretarias = await obter_dados_dashboard(session)
    return JSONResponse({
        "metricas": metricas,
        "lotes": [
            {
                "model": {
                    "id": item["model"].id,
                    "nome": item["model"].nome,
                    "quantidade_total": item["model"].quantidade_total,
                    "quantidade_resgatada": item["model"].quantidade_resgatada,
                    **_horarios_lote_para_formulario(item["model"]),
                    "ativo": item["model"].ativo,
                    "secretaria_id": item["model"].secretaria_id,
                    "secretaria": {"id": item["model"].secretaria.id, "nome": item["model"].secretaria.nome} if item["model"].secretaria else None
                },
                "status": item["status"],
                "vagas_restantes": item["vagas_restantes"],
                "pct": item["pct"],
                "bar_color": item["bar_color"]
            } for item in lotes_processados
        ],
        "secretarias": [{"id": s.id, "nome": s.nome} for s in secretarias]
    })

@router.get("/admin")
async def painel_admin(
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    if "application/json" in request.headers.get("accept", ""):
        return await api_lotes_admin(session=session, current_user=current_user)

    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)

    metricas, lotes_processados, secretarias = await obter_dados_dashboard(session)
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "user": current_user,
            "metricas": metricas,
            "lotes": lotes_processados,
            "secretarias": secretarias
        }
    )

@router.post("/admin/lote")
async def criar_lote(
    nome: str = Form(...),
    quantidade_total: int = Form(...),
    data_abertura: str = Form(...),
    data_fechamento: Optional[str] = Form(None),
    secretaria_id: Optional[str] = Form(None),
    ativo: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    agora = datetime.now(timezone.utc)
    dt_abertura = _datetime_utc(data_abertura, security.TZ_SAO_PAULO)
    dt_fechamento = _datetime_utc(data_fechamento, security.TZ_SAO_PAULO) if data_fechamento and data_fechamento.strip() else None

    if dt_fechamento and dt_fechamento <= dt_abertura:
        raise HTTPException(
            status_code=400, 
            detail="A data de fechamento deve ser posterior à data de abertura."
        )

    sec_id = int(secretaria_id) if secretaria_id and secretaria_id.strip() and secretaria_id != "0" else None
    esta_ativo = True if dt_abertura > agora or ativo in ["on", "true", "1", True] else False

    novo_lote = Lote(
        nome=nome.strip(),
        quantidade_total=quantidade_total,
        quantidade_resgatada=0,
        data_abertura=dt_abertura,
        data_fechamento=dt_fechamento,
        secretaria_id=sec_id,
        ativo=esta_ativo
    )
    
    session.add(novo_lote)
    await session.commit()
    await session.refresh(novo_lote)

    await lote_event_hub.broadcast("LOTE_ATUALIZADO", {
        "tipo": "LOTE_ATUALIZADO",
        "lote_id": novo_lote.id,
        "nome": novo_lote.nome,
        "data_abertura_iso": novo_lote.data_abertura.isoformat() if novo_lote.data_abertura else None,
        "data_fechamento_iso": novo_lote.data_fechamento.isoformat() if novo_lote.data_fechamento else None,
        "ativo": novo_lote.ativo,
        **dados_status_lote_sse(novo_lote),
        **(await coletar_status_lote_para_sse(session, novo_lote.id))
    })

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/admin/lote/{lote_id}/editar")
async def editar_lote(
    lote_id: int,
    nome: str = Form(...),
    quantidade_total: int = Form(...),
    data_abertura: str = Form(...),
    data_fechamento: Optional[str] = Form(None),
    secretaria_id: Optional[str] = Form(None),
    ativo: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    lote = await session.get(Lote, lote_id)
    if not lote:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    agora = datetime.now(timezone.utc)
    dt_abertura = _datetime_utc(data_abertura, security.TZ_SAO_PAULO)
    dt_fechamento = _datetime_utc(data_fechamento, security.TZ_SAO_PAULO) if data_fechamento and data_fechamento.strip() else None

    if dt_fechamento and dt_fechamento <= dt_abertura:
        raise HTTPException(
            status_code=400, 
            detail="A data de fechamento deve ser posterior à data de abertura."
        )

    lote.nome = nome.strip()
    lote.quantidade_total = quantidade_total
    lote.data_abertura = dt_abertura
    lote.data_fechamento = dt_fechamento
    lote.secretaria_id = int(secretaria_id) if secretaria_id and secretaria_id.strip() and secretaria_id != "0" else None
    
    if dt_abertura > agora:
        lote.ativo = True
    else:
        lote.ativo = True if ativo in ["on", "true", "1", True] else False

    session.add(lote)
    await session.commit()
    await session.refresh(lote)

    # Transmissão SSE em tempo real (<50ms): notifica adiamento/alteração imediatamente aos navegadores
    await lote_event_hub.broadcast("LOTE_ATUALIZADO", {
        "tipo": "LOTE_ATUALIZADO",
        "lote_id": lote.id,
        "nome": lote.nome,
        "data_abertura_iso": lote.data_abertura.isoformat() if lote.data_abertura else None,
        "data_fechamento_iso": lote.data_fechamento.isoformat() if lote.data_fechamento else None,
        "ativo": lote.ativo,
        **dados_status_lote_sse(lote),
        **(await coletar_status_lote_para_sse(session, lote.id))
    })

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/admin/lote/{lote_id}/toggle")
async def toggle_lote(
    lote_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    lote = await session.get(Lote, lote_id)
    if not lote:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    st = calcular_status_lote(lote)
    if not st["pode_toggle"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Não é permitido pausar/despausar este lote. {st['motivo_bloqueio']}"
        )

    lote.ativo = not lote.ativo
    session.add(lote)
    await session.commit()
    await session.refresh(lote)

    await lote_event_hub.broadcast("LOTE_ATUALIZADO", {
        "tipo": "LOTE_ATUALIZADO",
        "lote_id": lote.id,
        "ativo": lote.ativo,
        **dados_status_lote_sse(lote),
        **(await coletar_status_lote_para_sse(session, lote.id))
    })

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/admin/lote/{lote_id}/encerrar")
async def encerrar_lote_agora(
    lote_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    lote = await session.get(Lote, lote_id)
    if not lote:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    lote.data_fechamento = datetime.now(timezone.utc)
    session.add(lote)
    await session.commit()
    await session.refresh(lote)

    await lote_event_hub.broadcast("LOTE_ATUALIZADO", {
        "tipo": "LOTE_ATUALIZADO",
        "lote_id": lote.id,
        "data_fechamento_iso": lote.data_fechamento.isoformat(),
        **dados_status_lote_sse(lote),
        **(await coletar_status_lote_para_sse(session, lote.id))
    })

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


def mascarar_email(email: str) -> str:
    if not email or "@" not in email:
        return "seu e-mail"
    user_part, domain_part = email.split("@", 1)
    if len(user_part) <= 2:
        masked_user = user_part[0] + "***"
    else:
        masked_user = user_part[:2] + "***" + user_part[-1]
    return f"{masked_user}@{domain_part}"

def normalizar_cpf(cpf: str) -> str:
    return "".join(c for c in (cpf or "") if c.isdigit()).zfill(11)


# ==============================================================================
# SISTEMA DE EXCLUSÃO CRÍTICA DE LOTE E BACKUPS COM RETENÇÃO DE 3 DIAS
# ==============================================================================

@router.get("/api/admin/lote/{lote_id}/verificar-exclusao")
async def verificar_exclusao_lote(
    lote_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Verifica se o lote possui participantes e se requer as etapas avançadas de confirmação:
    - Se participantes == 0: apenas confirmação da senha da conta
    - Se participantes > 0: texto obrigatório + senha + código 2FA no e-mail
    """
    lote = await session.get(Lote, lote_id)
    if not lote or lote.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Lote não encontrado ou já excluído.")

    stmt_count = select(func.count(Ingresso.id)).where(
        Ingresso.lote_id == lote_id,
        Ingresso.deleted_at.is_(None)
    )
    res_count = await session.execute(stmt_count)
    total_participantes = res_count.scalar() or 0

    return JSONResponse({
        "sucesso": True,
        "lote": {
            "id": lote.id,
            "nome": lote.nome,
            "quantidade_total": lote.quantidade_total,
            "quantidade_resgatada": lote.quantidade_resgatada
        },
        "tem_participantes": total_participantes > 0,
        "total_participantes": total_participantes,
        "admin_email": admin.email,
        "admin_email_mascarado": mascarar_email(admin.email) if admin.email else "sem e-mail cadastrado"
    })


@router.post("/api/admin/lote/{lote_id}/solicitar-codigo-exclusao")
async def solicitar_codigo_exclusao_lote(
    lote_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Envia código de segurança para o e-mail do administrador quando o lote tem participantes
    """
    lote = await session.get(Lote, lote_id)
    if not lote or lote.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Lote não encontrado.")

    if not admin.email or "@" not in admin.email:
        raise HTTPException(
            status_code=400,
            detail="Sua conta de administrador não possui um e-mail válido cadastrado para envio do código de autorização."
        )

    stmt_count = select(func.count(Ingresso.id)).where(
        Ingresso.lote_id == lote_id,
        Ingresso.deleted_at.is_(None)
    )
    res_count = await session.execute(stmt_count)
    total_participantes = res_count.scalar() or 0

    codigo = gerar_codigo_2fa_criptografico(6)
    token = secrets.token_hex(24)
    expira_em = datetime.now(timezone.utc) + timedelta(minutes=10)

    token_obj = TokenExclusaoLote(
        token=token,
        lote_id=lote_id,
        usuario_id=admin.id,
        codigo_verificacao=codigo,
        codigo_expira_em=expira_em
    )
    session.add(token_obj)
    await session.commit()

    # Dispara e-mail de segurança de alta prioridade
    asyncio.create_task(
        send_lote_deletion_code_email_async(
            admin_nome=admin.nome,
            admin_email=admin.email,
            lote_nome=lote.nome,
            total_ingressos=total_participantes,
            codigo=codigo
        )
    )

    return JSONResponse({
        "sucesso": True,
        "token": token,
        "email_mascarado": mascarar_email(admin.email),
        "mensagem": f"Código de segurança de 6 dígitos enviado para {mascarar_email(admin.email)}."
    })


@router.post("/api/admin/lote/{lote_id}/confirmar-exclusao")
@router.post("/admin/lote/{lote_id}/excluir")
async def confirmar_exclusao_lote(
    lote_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Processa a exclusão segura do lote aplicando as regras estritas:
    - Se participantes == 0: validação estrita da senha da conta
    - Se participantes > 0:
        1. Texto exato: 'Sim, eu realmente desejo excluir esse lote'
        2. Validação da senha da conta
        3. Código 2FA enviado por e-mail
    - Salva backup completo com retenção inegociável de 3 dias
    """
    lote = await session.get(Lote, lote_id)
    if not lote or lote.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Lote não encontrado ou já excluído.")

    # Extrai payload JSON ou Form
    dados = {}
    try:
        dados = await request.json()
    except Exception:
        form = await request.form()
        dados = dict(form)

    senha = dados.get("senha") or dados.get("senha_admin") or ""
    confirmacao_texto = str(dados.get("confirmacao_texto", "")).strip()
    token_codigo = dados.get("token_codigo") or dados.get("token") or ""
    codigo_email = str(dados.get("codigo_email") or dados.get("codigo") or "").strip()

    # 1. Validação da senha da conta do administrador
    if not senha:
        raise HTTPException(status_code=400, detail="A confirmação da senha da sua conta é obrigatória.")

    if not admin.senha_hash or not (
        security.verify_password(senha, admin.senha_hash) or
        security.verify_password(senha.strip(), admin.senha_hash)
    ):
        raise HTTPException(status_code=401, detail="Senha de administrador incorreta. Ação abortada.")

    # 2. Contagem de participantes ativos no lote
    stmt_count = select(func.count(Ingresso.id)).where(
        Ingresso.lote_id == lote_id,
        Ingresso.deleted_at.is_(None)
    )
    res_count = await session.execute(stmt_count)
    total_participantes = res_count.scalar() or 0

    # 3. Se tiver participantes: validações obrigatórias adicionais
    if total_participantes > 0:
        # 3.1. Texto obrigatório
        frase_esperada = "Sim, eu realmente desejo excluir esse lote"
        if confirmacao_texto != frase_esperada:
            raise HTTPException(
                status_code=400,
                detail=f'Texto de confirmação incorreto. Você deve digitar exatamente: "{frase_esperada}"'
            )

        # 3.2. Validação do código 2FA enviado ao e-mail
        if not token_codigo or not codigo_email:
            raise HTTPException(status_code=400, detail="O código de confirmação enviado por e-mail é obrigatório.")

        stmt_token = select(TokenExclusaoLote).where(
            TokenExclusaoLote.token == token_codigo,
            TokenExclusaoLote.lote_id == lote_id,
            TokenExclusaoLote.usuario_id == admin.id,
            TokenExclusaoLote.utilizado == False
        )
        res_token = await session.execute(stmt_token)
        token_obj = res_token.scalars().first()

        if not token_obj:
            raise HTTPException(status_code=400, detail="Sessão de autorização de código expirada ou já utilizada. Solicite um novo código.")

        if token_obj.tentativas >= 5:
            raise HTTPException(status_code=429, detail="Limite de tentativas excedido por segurança. Solicite um novo código.")

        if datetime.now(timezone.utc) > token_obj.codigo_expira_em:
            raise HTTPException(status_code=400, detail="O código de confirmação expirou. Solicite um novo código.")

        if token_obj.codigo_verificacao != codigo_email:
            token_obj.tentativas += 1
            session.add(token_obj)
            await session.commit()
            raise HTTPException(status_code=400, detail="Código de confirmação de e-mail incorreto.")

        token_obj.utilizado = True
        session.add(token_obj)

    # 4. Snapshot Completo de Backup com todos os Ingressos e Usuários
    stmt_ings = (
        select(Ingresso)
        .where(Ingresso.lote_id == lote_id)
        .options(selectinload(Ingresso.usuario).selectinload(Usuario.secretaria))
    )
    res_ings = await session.execute(stmt_ings)
    ingressos_lote = res_ings.scalars().all()

    snapshot_ingressos = []
    for ing in ingressos_lote:
        usr = ing.usuario
        snapshot_ingressos.append({
            "ingresso_id": ing.id,
            "qr_code_token": ing.qr_code_token,
            "data_resgate": ing.data_resgate.isoformat() if ing.data_resgate else None,
            "deleted_at": ing.deleted_at.isoformat() if ing.deleted_at else None,
            "usuario": {
                "id": usr.id if usr else None,
                "nome": usr.nome if usr else "Desconhecido",
                "cpf": usr.cpf if usr else "",
                "email": usr.email if usr else "",
                "telefone": usr.telefone if usr else "",
                "setor": usr.setor if usr else "",
                "secretaria_id": usr.secretaria_id if usr else None,
                "secretaria_nome": usr.secretaria.nome if usr and usr.secretaria else None
            }
        })

    snapshot_completo = {
        "versao_backup": "1.0",
        "criado_em": datetime.now(timezone.utc).isoformat(),
        "excluido_por": {
            "id": admin.id,
            "nome": admin.nome,
            "cpf": admin.cpf,
            "email": admin.email
        },
        "lote": {
            "id": lote.id,
            "nome": lote.nome,
            "quantidade_total": lote.quantidade_total,
            "quantidade_resgatada": lote.quantidade_resgatada,
            "data_abertura": lote.data_abertura.isoformat() if lote.data_abertura else None,
            "data_fechamento": lote.data_fechamento.isoformat() if lote.data_fechamento else None,
            "secretaria_id": lote.secretaria_id,
            "ativo": lote.ativo
        },
        "total_ingressos": len(snapshot_ingressos),
        "ingressos": snapshot_ingressos
    }

    agora = datetime.now(timezone.utc)
    expira_em = agora + timedelta(days=3)  # Retenção estrita de 3 dias

    backup = BackupLote(
        lote_id=lote.id,
        lote_nome=lote.nome,
        dados_json=json.dumps(snapshot_completo, ensure_ascii=False),
        total_ingressos=len(snapshot_ingressos),
        excluido_em=agora,
        expira_em=expira_em,
        excluido_por_id=admin.id,
        excluido_por_nome=admin.nome,
        ip_origem=request.client.host if request.client else None,
        restaurado=False
    )
    session.add(backup)

    # 5. Soft-delete do Lote
    lote.deleted_at = agora
    lote.ativo = False
    session.add(lote)

    # 6. Soft-delete seguro dos ingressos do lote
    for ing in ingressos_lote:
        if ing.deleted_at is None:
            ing.deleted_at = agora
            session.add(ing)

    # Limpa reservas transitórias não concluídas
    stmt_reservas = select(ReservaIngresso).where(ReservaIngresso.lote_id == lote_id)
    res_res = await session.execute(stmt_reservas)
    for r in res_res.scalars().all():
        await session.delete(r)

    await session.commit()
    await session.refresh(backup)

    await lote_event_hub.broadcast("LOTE_ATUALIZADO", {
        "tipo": "LOTE_ATUALIZADO",
        "lote_id": lote_id,
        "deletado": True,
        "ativo": False
    })

    if "application/json" in request.headers.get("accept", "") or request.url.path.startswith("/api/"):
        return JSONResponse({
            "sucesso": True,
            "mensagem": f"Lote '{lote.nome}' excluído com sucesso. Backup completo salvo com retenção garantida de 3 dias.",
            "backup_id": backup.id,
            "expira_em": security.formatar_data_sp(expira_em)
        })

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/api/admin/lotes/backups")
async def listar_backups_lotes(
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Lista todos os backups salvos dos lotes com histórico de retenção de 3 dias.
    """
    stmt = select(BackupLote).order_by(BackupLote.id.desc())
    res = await session.execute(stmt)
    backups = res.scalars().all()

    agora = datetime.now(timezone.utc)
    lista = []
    for b in backups:
        tempo_restante_seg = max(0, (b.expira_em - agora).total_seconds())
        horas_restantes = int(tempo_restante_seg // 3600)
        dias_restantes = round(horas_restantes / 24, 1)

        lista.append({
            "id": b.id,
            "lote_id": b.lote_id,
            "lote_nome": b.lote_nome,
            "total_ingressos": b.total_ingressos,
            "excluido_em": security.formatar_data_sp(b.excluido_em),
            "expira_em": security.formatar_data_sp(b.expira_em),
            "excluido_por_nome": b.excluido_por_nome or "Administrador",
            "restaurado": b.restaurado,
            "restaurado_em": security.formatar_data_sp(b.restaurado_em),
            "horas_restantes": horas_restantes,
            "dias_restantes": dias_restantes,
            "pode_restaurar": not b.restaurado,
            "pode_excluir": False,  # Regra de ouro: O backup NUNCA pode ser excluído manualmente
            "aviso_retencao": "Retenção Protegida de 3 Dias • Exclusão Proibida"
        })

    return JSONResponse({
        "sucesso": True,
        "backups": lista
    })


@router.post("/api/admin/lotes/backups/{backup_id}/restaurar")
async def restaurar_backup_lote(
    backup_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Restaura um lote e todos os seus ingressos a partir do backup protegido.
    Requer confirmação de senha do administrador por segurança.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    senha = body.get("senha", "")
    if not senha:
        raise HTTPException(status_code=400, detail="Digite sua senha de administrador para autorizar a restauração.")

    if not admin.senha_hash or not (
        security.verify_password(senha, admin.senha_hash) or
        security.verify_password(senha.strip(), admin.senha_hash)
    ):
        raise HTTPException(status_code=401, detail="Senha incorreta.")

    backup = await session.get(BackupLote, backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup não encontrado.")

    # 1. Recupera o lote no banco ou recria
    lote = await session.get(Lote, backup.lote_id)
    if lote:
        lote.deleted_at = None
        lote.ativo = True
        session.add(lote)

        # SEC-13: Reativa APENAS os ingressos que estavam ativos no snapshot e cujo usuário não possui outro ativo
        ingressos_ativos_ids = set()
        try:
            snapshot_dados = json.loads(backup.dados_json)
            for ing_d in snapshot_dados.get("ingressos", []):
                if ing_d.get("deleted_at") is None and ing_d.get("ingresso_id"):
                    ingressos_ativos_ids.add(ing_d["ingresso_id"])
        except Exception:
            pass

        stmt_ings = select(Ingresso).where(Ingresso.lote_id == lote.id)
        res_ings = await session.execute(stmt_ings)
        for ing in res_ings.scalars().all():
            if ing.id in ingressos_ativos_ids:
                stmt_outro = select(Ingresso).where(
                    Ingresso.usuario_id == ing.usuario_id,
                    Ingresso.deleted_at.is_(None),
                    Ingresso.id != ing.id
                )
                res_outro = await session.execute(stmt_outro)
                if not res_outro.scalars().first():
                    ing.deleted_at = None
                    session.add(ing)
    else:
        try:
            dados = json.loads(backup.dados_json)
            lote_data = dados.get("lote", {})
            novo_lote = Lote(
                nome=lote_data.get("nome", backup.lote_nome),
                quantidade_total=lote_data.get("quantidade_total", 100),
                quantidade_resgatada=lote_data.get("quantidade_resgatada", 0),
                data_abertura=_datetime_utc(lote_data["data_abertura"]) if lote_data.get("data_abertura") else None,
                data_fechamento=_datetime_utc(lote_data["data_fechamento"]) if lote_data.get("data_fechamento") else None,
                secretaria_id=lote_data.get("secretaria_id"),
                ativo=True
            )
            session.add(novo_lote)
            await session.flush()

            for ing_d in dados.get("ingressos", []):
                # SEC-13: Só recria ingressos que estavam ativos no snapshot
                if ing_d.get("deleted_at") is not None:
                    continue
                usr_d = ing_d.get("usuario", {})
                usr_id = usr_d.get("id")
                if usr_id:
                    stmt_outro = select(Ingresso).where(
                        Ingresso.usuario_id == usr_id,
                        Ingresso.deleted_at.is_(None)
                    )
                    res_outro = await session.execute(stmt_outro)
                    if not res_outro.scalars().first():
                        novo_ing = Ingresso(
                            usuario_id=usr_id,
                            lote_id=novo_lote.id,
                            qr_code_token=ing_d.get("qr_code_token") or secrets.token_hex(16),
                            data_resgate=_datetime_utc(ing_d["data_resgate"]) if ing_d.get("data_resgate") else datetime.now(timezone.utc),
                            deleted_at=None
                        )
                        session.add(novo_ing)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao reconstruir lote a partir do backup: {str(e)}")

    backup.restaurado = True
    backup.restaurado_em = datetime.now(timezone.utc)
    backup.restaurado_por_id = admin.id
    session.add(backup)
    await session.commit()

    await lote_event_hub.broadcast("LOTE_ATUALIZADO", {
        "tipo": "LOTE_ATUALIZADO",
        "lote_id": backup.lote_id,
        "restaurado": True
    })

    return JSONResponse({
        "sucesso": True,
        "mensagem": f"Lote '{backup.lote_nome}' e seus {backup.total_ingressos} ingressos foram restaurados com sucesso!"
    })


@router.get("/api/admin/lotes/backups/{backup_id}/exportar")
async def exportar_backup_lote_json(
    backup_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Exporta o arquivo JSON do backup do lote para download.
    """
    backup = await session.get(BackupLote, backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup não encontrado.")

    nome_seguro = re.sub(r'[^a-zA-Z0-9_\-]', '_', backup.lote_nome)
    data_str = security.formatar_data_sp(backup.excluido_em, "%Y%m%d_%H%M")
    filename = f"backup_lote_{backup.lote_id}_{nome_seguro}_{data_str}.json"

    return Response(
        content=backup.dados_json,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.post("/api/admin/lotes/importar-backup")
async def importar_backup_lote_json(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Importa um arquivo JSON de backup previamente exportado, restaurando o lote e os ingressos.
    """
    body = await request.json()
    senha = body.get("senha", "")
    dados_backup = body.get("backup_json", {})

    if not senha:
        raise HTTPException(status_code=400, detail="A confirmação de senha é obrigatória para importar backups.")

    if not admin.senha_hash or not (
        security.verify_password(senha, admin.senha_hash) or
        security.verify_password(senha.strip(), admin.senha_hash)
    ):
        raise HTTPException(status_code=401, detail="Senha de administrador incorreta.")

    if not dados_backup or "lote" not in dados_backup:
        raise HTTPException(status_code=400, detail="Arquivo de backup inválido ou formato incompatível.")

    lote_info = dados_backup.get("lote", {})
    ingressos_info = dados_backup.get("ingressos", [])

    nome_lote = lote_info.get("nome", "Lote Importado")
    novo_nome = f"{nome_lote} (Importado)"

    novo_lote = Lote(
        nome=novo_nome,
        quantidade_total=lote_info.get("quantidade_total", max(len(ingressos_info), 100)),
        quantidade_resgatada=len(ingressos_info),
        data_abertura=_datetime_utc(lote_info["data_abertura"]) if lote_info.get("data_abertura") else None,
        data_fechamento=_datetime_utc(lote_info["data_fechamento"]) if lote_info.get("data_fechamento") else None,
        secretaria_id=lote_info.get("secretaria_id"),
        ativo=True
    )
    session.add(novo_lote)
    await session.flush()

    total_recuperados = 0
    for ing_item in ingressos_info:
        usr_info = ing_item.get("usuario", {})
        cpf_usr = normalizar_cpf(usr_info.get("cpf", ""))

        if cpf_usr:
            stmt_u = select(Usuario).where(Usuario.cpf == cpf_usr)
            res_u = await session.execute(stmt_u)
            usuario_existente = res_u.scalars().first()

            if usuario_existente:
                # SEC-13: Ignora ingressos que estavam cancelados no momento do backup
                if ing_item.get("deleted_at") is not None:
                    continue

                # Não duplica se o usuário já possui ingresso ativo
                stmt_ativo = select(Ingresso).where(
                    Ingresso.usuario_id == usuario_existente.id,
                    Ingresso.deleted_at.is_(None)
                )
                res_ativo = await session.execute(stmt_ativo)
                if res_ativo.scalars().first():
                    continue

                token_qr = ing_item.get("qr_code_token") or secrets.token_hex(16)
                stmt_dup = select(Ingresso).where(Ingresso.qr_code_token == token_qr)
                res_dup = await session.execute(stmt_dup)
                if res_dup.scalars().first():
                    token_qr = f"{token_qr}_imp_{secrets.token_hex(4)}"

                dt_resgate = _datetime_utc(ing_item["data_resgate"]) if ing_item.get("data_resgate") else datetime.now(timezone.utc)

                ing_novo = Ingresso(
                    usuario_id=usuario_existente.id,
                    lote_id=novo_lote.id,
                    qr_code_token=token_qr,
                    data_resgate=dt_resgate,
                    deleted_at=None
                )
                session.add(ing_novo)
                total_recuperados += 1

    # Registra no histórico de backups
    backup_registro = BackupLote(
        lote_id=novo_lote.id,
        lote_nome=novo_lote.nome,
        dados_json=json.dumps(dados_backup, ensure_ascii=False),
        total_ingressos=total_recuperados,
        excluido_em=datetime.now(timezone.utc),
        expira_em=datetime.now(timezone.utc) + timedelta(days=3),
        excluido_por_id=admin.id,
        excluido_por_nome=admin.nome,
        ip_origem=request.client.host if request.client else None,
        restaurado=True,
        restaurado_em=datetime.now(timezone.utc),
        restaurado_por_id=admin.id
    )
    session.add(backup_registro)
    await session.commit()

    await lote_event_hub.broadcast("LOTE_ATUALIZADO", {
        "tipo": "LOTE_ATUALIZADO",
        "lote_id": novo_lote.id,
        "importado": True
    })

    return JSONResponse({
        "sucesso": True,
        "mensagem": f"Backup importado com sucesso! Lote '{novo_nome}' restaurado com {total_recuperados} ingressos."
    })


@router.delete("/api/admin/lotes/backups/{backup_id}")
async def proibir_exclusao_backup(
    backup_id: int,
    admin: Usuario = Depends(get_current_admin)
):
    """
    Regra inviolável: Os backups de lotes possuem retenção obrigatória de 3 dias e NÃO podem ser excluídos.
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Operação Bloqueada: Os backups de lotes possuem retenção inegociável de 3 dias e não podem ser excluídos sob nenhuma hipótese."
    )


@router.get("/admin/lote/{lote_id}/ingressos")
async def ver_ingressos_lote(
    request: Request,
    lote_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    lote = await session.get(Lote, lote_id)
    if not lote:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    stmt_ing = (
        select(Ingresso)
        .where(Ingresso.lote_id == lote_id, Ingresso.deleted_at.is_(None))
        .options(selectinload(Ingresso.usuario).selectinload(Usuario.secretaria))
        .order_by(Ingresso.data_resgate.desc())
    )
    resultado_ing = await session.execute(stmt_ing)
    ingressos_raw = resultado_ing.scalars().all()

    # Resgata também solicitações de validação para incluir rejeitados e pendentes
    from app.models.all_models import SolicitacaoValidacao
    stmt_solic = (
        select(SolicitacaoValidacao)
        .where(SolicitacaoValidacao.lote_id == lote_id)
        .options(
            selectinload(SolicitacaoValidacao.usuario).selectinload(Usuario.secretaria),
            selectinload(SolicitacaoValidacao.secretaria)
        )
        .order_by(SolicitacaoValidacao.criado_em.desc())
    )
    res_solic = await session.execute(stmt_solic)
    solicitacoes_raw = res_solic.scalars().all()

    stmt_logs = select(LogAcesso.usuario_id).where(LogAcesso.tipo == MovimentoTipo.entrada)
    res_logs = await session.execute(stmt_logs)
    usuarios_presentes = set(res_logs.scalars().all())

    ingressos_por_usuario = {ing.usuario_id: ing for ing in ingressos_raw}
    participantes_processados = []

    for ing in ingressos_raw:
        u = ing.usuario
        sec_nome = u.secretaria.nome if u and u.secretaria else "Geral / Não informada"
        ja_entrou = ing.usuario_id in usuarios_presentes
        participantes_processados.append({
            "model": {
                "id": ing.id,
                "data_resgate": ing.data_resgate.isoformat() if ing.data_resgate else None,
                "tipo": "ingresso"
            },
            "status": "aprovado",
            "motivo_rejeicao": None,
            "usuario": {
                "id": u.id,
                "nome": u.nome,
                "cpf": u.cpf,
                "setor": u.setor,
                "vinculo": u.vinculo,
                "telefone": u.telefone
            } if u else None,
            "secretaria_nome": sec_nome,
            "ja_entrou": ja_entrou
        })

    for s in solicitacoes_raw:
        if s.status in ("rejeitado", "pendente_analise") and s.usuario_id not in ingressos_por_usuario:
            u = s.usuario
            sec_nome = (s.secretaria.nome if s.secretaria else (u.secretaria.nome if u and u.secretaria else "Geral"))
            participantes_processados.append({
                "model": {
                    "id": s.id,
                    "data_resgate": s.criado_em.isoformat() if s.criado_em else None,
                    "tipo": "solicitacao"
                },
                "status": s.status,
                "motivo_rejeicao": s.motivo_rejeicao,
                "usuario": {
                    "id": u.id,
                    "nome": u.nome,
                    "cpf": u.cpf,
                    "setor": u.setor,
                    "vinculo": u.vinculo,
                    "telefone": u.telefone
                } if u else None,
                "secretaria_nome": sec_nome,
                "ja_entrou": False
            })

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({
            "lote": {
                "id": lote.id,
                "nome": lote.nome,
                "quantidade_total": lote.quantidade_total,
                "quantidade_resgatada": lote.quantidade_resgatada,
                **_horarios_lote_para_formulario(lote)
            },
            "total_ingressos": lote.quantidade_resgatada,
            "ingressos": participantes_processados
        })

    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)

    return templates.TemplateResponse(
        request=request,
        name="lote_ingressos.html",
        context={
            "user": current_user,
            "lote": lote,
            "ingressos": participantes_processados,
            "total_ingressos": lote.quantidade_resgatada
        }
    )

@router.post("/api/admin/ingressos/{ingresso_id}/cancelar")
@router.post("/admin/ingresso/{ingresso_id}/cancelar")
async def cancelar_ingresso(
    ingresso_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Realiza o cancelamento administrativo (extravio) do ingresso com motivo e senha do administrador"""
    stmt = (
        select(Ingresso)
        .where(
            Ingresso.id == ingresso_id,
            Ingresso.deleted_at.is_(None)
        )
        .options(selectinload(Ingresso.lote), selectinload(Ingresso.usuario))
    )
    res = await session.execute(stmt)
    ingresso = res.scalars().first()
    if not ingresso:
        raise HTTPException(status_code=404, detail="Ingresso não encontrado ou já cancelado.")

    data = {}
    try:
        data = await request.json()
    except Exception:
        form = await request.form()
        data = dict(form)

    motivo = (data.get("motivo") or "").strip()
    senha_admin = data.get("senha_admin") or data.get("senha") or ""

    if not motivo:
        raise HTTPException(status_code=400, detail="O motivo do cancelamento é obrigatório.")

    if not senha_admin:
        raise HTTPException(status_code=400, detail="A senha de administrador é obrigatória para autorizar o cancelamento.")

    if not admin.senha_hash or not (
        security.verify_password(senha_admin, admin.senha_hash) or
        security.verify_password(senha_admin.strip(), admin.senha_hash)
    ):
        raise HTTPException(status_code=401, detail="Senha de administrador incorreta. Ação não autorizada.")

    agora = datetime.now(timezone.utc)
    ingresso.deleted_at = agora
    ingresso.cancelado_por_id = admin.id
    ingresso.motivo_cancelamento = motivo
    session.add(ingresso)

    # Bloqueio estritamente obrigatório para qualquer novo resgate
    if ingresso.usuario:
        ingresso.usuario.bloqueado_resgate = True
        session.add(ingresso.usuario)

    if ingresso.lote and ingresso.lote.quantidade_resgatada > 0:
        ingresso.lote.quantidade_resgatada -= 1
        session.add(ingresso.lote)

    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": "Ingresso extraviado/cancelado com sucesso. Vaga devolvida ao lote e CPF bloqueado para novos resgates."
    })

@router.get("/admin/lote/{lote_id}/exportar-csv")
@router.get("/api/admin/lote/{lote_id}/exportar-csv")
async def exportar_ingressos_csv(
    lote_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    lote = await session.get(Lote, lote_id)
    if not lote:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    stmt = (
        select(Ingresso)
        .where(Ingresso.lote_id == lote_id)
        .options(selectinload(Ingresso.usuario).selectinload(Usuario.secretaria))
        .order_by(Ingresso.data_resgate.asc())
    )
    resultado = await session.execute(stmt)
    ingressos = resultado.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    writer.writerow([
        "ID Registro", 
        "Tipo",
        "Status no Lote",
        "CPF Servidor", 
        "Nome Completo", 
        "Data de Nascimento",
        "Setor / Local", 
        "Secretaria", 
        "Vínculo", 
        "Telefone", 
        "E-mail",
        "Data do Resgate",
        "Token QR Code",
        "Observação / Motivo Recusa"
    ])

    ingressos_user_ids = set()
    for ing in ingressos:
        u = ing.usuario
        if u:
            ingressos_user_ids.add(u.id)
        sec_nome = u.secretaria.nome if u and u.secretaria else "Geral / Não informada"
        writer.writerow([
            ing.id,
            "Ingresso Oficial",
            "Aprovado / Emitido",
            f"'{u.cpf}" if u else "",
            u.nome if u else "",
            u.data_nascimento if u else "",
            u.setor if u else "",
            sec_nome,
            u.vinculo if u else "",
            u.telefone if u else "",
            u.email if u else "",
            security.formatar_data_sp(ing.data_resgate, "%d/%m/%Y %H:%M:%S") if ing.data_resgate else "",
            ing.qr_code_token or "",
            ""
        ])

    from app.models.all_models import SolicitacaoValidacao
    stmt_solic_csv = (
        select(SolicitacaoValidacao)
        .where(SolicitacaoValidacao.lote_id == lote_id)
        .options(
            selectinload(SolicitacaoValidacao.usuario).selectinload(Usuario.secretaria),
            selectinload(SolicitacaoValidacao.secretaria)
        )
        .order_by(SolicitacaoValidacao.criado_em.asc())
    )
    res_solic_csv = await session.execute(stmt_solic_csv)
    solics_csv = res_solic_csv.scalars().all()

    for s in solics_csv:
        if s.usuario_id not in ingressos_user_ids:
            u = s.usuario
            sec_nome = s.secretaria.nome if s.secretaria else (u.secretaria.nome if u and u.secretaria else "Geral")
            status_desc = "Recusado / Vínculo Não Confirmado" if s.status == "rejeitado" else "Em Análise"
            writer.writerow([
                f"SOLIC-{s.id}",
                "Solicitação de Validação",
                status_desc,
                f"'{u.cpf}" if u else "",
                u.nome if u else "",
                u.data_nascimento if u else "",
                u.setor if u else "",
                sec_nome,
                u.vinculo if u else "",
                u.telefone if u else "",
                u.email if u else "",
                security.formatar_data_sp(s.criado_em, "%d/%m/%Y %H:%M:%S") if s.criado_em else "",
                "",
                s.motivo_rejeicao or ""
            ])

    output.seek(0)
    nome_arquivo = f"ingressos_lote_{lote.id}_{security.formatar_data_sp(datetime.now(timezone.utc), '%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue().encode('utf-8-sig')]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"}
    )

@router.get("/api/admin/ingressos/exportar-csv")
async def exportar_todos_ingressos_csv(
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Exporta todos os ingressos ativos de todos os lotes em formato CSV consolidado"""
    stmt = (
        select(Ingresso)
        .where(Ingresso.deleted_at.is_(None))
        .options(
            selectinload(Ingresso.usuario).selectinload(Usuario.secretaria),
            selectinload(Ingresso.lote)
        )
        .order_by(Ingresso.data_resgate.asc())
    )
    resultado = await session.execute(stmt)
    ingressos = resultado.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    writer.writerow([
        "ID Ingresso", 
        "Lote",
        "CPF Servidor", 
        "Nome Completo", 
        "Data de Nascimento",
        "Setor / Local", 
        "Secretaria", 
        "Vínculo", 
        "Telefone", 
        "E-mail",
        "Data do Resgate",
        "Token QR Code"
    ])

    for ing in ingressos:
        u = ing.usuario
        lote_nome = ing.lote.nome if ing.lote else "Lote Geral"
        sec_nome = u.secretaria.nome if u and u.secretaria else "Geral / Não informada"
        writer.writerow([
            ing.id,
            lote_nome,
            f"'{u.cpf}" if u else "",
            u.nome if u else "",
            u.data_nascimento if u else "",
            u.setor if u else "",
            sec_nome,
            u.vinculo if u else "",
            u.telefone if u else "",
            u.email if u else "",
            security.formatar_data_sp(ing.data_resgate, "%d/%m/%Y %H:%M:%S"),
            ing.qr_code_token or ""
        ])

    output.seek(0)
    nome_arquivo = f"ingressos_festa_servidor_{security.formatar_data_sp(datetime.now(timezone.utc), '%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue().encode('utf-8-sig')]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"}
    )


# ==========================================
# GESTÃO DE USUÁRIOS E PERMISSÕES (ADMIN)
# ==========================================

@router.get("/api/admin/participantes")
async def listar_participantes_admin(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=50),
    busca: Optional[str] = Query(None),
    secretaria_id: Optional[str] = Query(None),
    lote_id: Optional[str] = Query(None),
    status_presenca: Optional[str] = Query(None),
    secretarias: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Lista com paginação estrita no servidor (LIMIT 50 OFFSET ?) e filtros de busca, secretarias e status"""
    # 1. Carrega opções de lotes e secretarias para filtros rápidos
    res_lotes = await session.execute(
        select(Lote).where(Lote.deleted_at.is_(None)).order_by(Lote.id.asc())
    )
    lista_lotes = [{"id": l.id, "nome": l.nome} for l in res_lotes.scalars().all()]

    res_sec = await session.execute(
        select(Secretaria).order_by(Secretaria.nome.asc())
    )
    lista_secretarias = [{"id": s.id, "nome": s.nome} for s in res_sec.scalars().all()]

    stmt = (
        select(Usuario)
        .where(
            Usuario.deleted_at.is_(None),
            Usuario.ativo == True
        )
        .options(
            selectinload(Usuario.secretaria),
            selectinload(Usuario.ingressos).selectinload(Ingresso.lote),
            selectinload(Usuario.ingressos).selectinload(Ingresso.cancelado_por),
            selectinload(Usuario.logs_acesso).selectinload(LogAcesso.operador),
            selectinload(Usuario.solicitacoes_validacao).selectinload(SolicitacaoValidacao.analisado_por),
            selectinload(Usuario.solicitacoes_validacao).selectinload(SolicitacaoValidacao.secretaria),
            selectinload(Usuario.solicitacoes_cancelamento).selectinload(SolicitacaoCancelamento.analisado_por)
        )
        .order_by(Usuario.nome.asc())
    )
    res = await session.execute(stmt)
    todos = res.scalars().all()

    lista_participantes_todos = []
    total_ingressos_resgatados = 0
    total_presentes = 0

    for u in todos:
        tem_ingresso = bool(u.ingressos and len(u.ingressos) > 0)
        tem_validacao = bool(u.solicitacoes_validacao and len(u.solicitacoes_validacao) > 0)
        tem_cancelamento = bool(u.solicitacoes_cancelamento and len(u.solicitacoes_cancelamento) > 0)

        # Filtra apenas quem ? servidor ou possui registro no evento
        if not (u.role == UserRole.servidor or tem_ingresso or tem_validacao or tem_cancelamento):
            continue

        cpf_raw = u.cpf or ""
        cpf_fmt = f"{cpf_raw[:3]}.{cpf_raw[3:6]}.{cpf_raw[6:9]}-{cpf_raw[9:]}" if len(cpf_raw) == 11 else cpf_raw

        ingressos_ativos = [i for i in u.ingressos if i.deleted_at is None] if u.ingressos else []
        ingressos_cancelados = [i for i in u.ingressos if i.deleted_at is not None] if u.ingressos else []

        ing_info = None
        if ingressos_ativos:
            ultimo_ing = sorted(ingressos_ativos, key=lambda x: x.data_resgate, reverse=True)[0]
            ing_info = {
                "id": ultimo_ing.id,
                "lote_id": ultimo_ing.lote_id,
                "lote_nome": ultimo_ing.lote.nome if ultimo_ing.lote else f"Lote #{ultimo_ing.lote_id}",
                "qr_code_token": ultimo_ing.qr_code_token,
                "data_resgate": security.formatar_data_sp(ultimo_ing.data_resgate, "%d/%m/%Y %H:%M:%S"),
                "cancelado": False
            }
            total_ingressos_resgatados += 1
        elif ingressos_cancelados:
            ultimo_ing_canc = sorted(ingressos_cancelados, key=lambda x: x.deleted_at or x.data_resgate, reverse=True)[0]
            ing_info = {
                "id": ultimo_ing_canc.id,
                "lote_id": ultimo_ing_canc.lote_id,
                "lote_nome": ultimo_ing_canc.lote.nome if ultimo_ing_canc.lote else f"Lote #{ultimo_ing_canc.lote_id}",
                "qr_code_token": ultimo_ing_canc.qr_code_token,
                "data_resgate": security.formatar_data_sp(ultimo_ing_canc.data_resgate, "%d/%m/%Y %H:%M:%S"),
                "cancelado": True
            }

        # M?quina de 6 Estados do "STATUS NO EVENTO"
        ultima_validacao = sorted(u.solicitacoes_validacao, key=lambda x: x.criado_em, reverse=True)[0] if u.solicitacoes_validacao else None
        ultima_canc = sorted(u.solicitacoes_cancelamento, key=lambda x: x.criado_em, reverse=True)[0] if u.solicitacoes_cancelamento else None

        situacao_evento = None

        # 3 ou 4: Possui ingresso ativo -> Presente no Evento ou Fora do Evento
        if ingressos_ativos:
            ultimo_log = sorted(u.logs_acesso, key=lambda x: x.data_hora, reverse=True)[0] if u.logs_acesso else None
            tipo_str = (ultimo_log.tipo.value if hasattr(ultimo_log.tipo, "value") else str(ultimo_log.tipo)) if ultimo_log else None
            data_fmt = security.formatar_data_sp(ultimo_log.data_hora, "%d/%m às %H:%M:%S") if ultimo_log else None

            if tipo_str == "entrada":
                total_presentes += 1
                situacao_evento = {
                    "status_slug": "presente",
                    "label": "Presente no Evento",
                    "badge_class": "bg-success",
                    "icon_class": "bi bi-check-circle-fill",
                    "dentro": True,
                    "ultima_movimentacao": f"Entrada em {data_fmt}",
                    "detalhes": None
                }
            else:
                situacao_evento = {
                    "status_slug": "fora",
                    "label": "Fora do Evento",
                    "badge_class": "bg-warning",
                    "icon_class": "bi bi-geo-alt-fill",
                    "dentro": False,
                    "ultima_movimentacao": f"Saída em {data_fmt}" if data_fmt else "Sem acesso registrado",
                    "detalhes": None
                }

        # 6: Ingresso Extraviado (Cancelado por Administrador)
        elif ingressos_cancelados and any(i.cancelado_por_id is not None for i in ingressos_cancelados):
            ing_ext = sorted([i for i in ingressos_cancelados if i.cancelado_por_id is not None], key=lambda x: x.deleted_at or x.data_resgate, reverse=True)[0]
            data_ext = security.formatar_data_sp(ing_ext.deleted_at, "%d/%m/%Y às %H:%M:%S") if ing_ext.deleted_at else "Data não informada"
            por_ext = ing_ext.cancelado_por.nome if ing_ext.cancelado_por else "Administrador"
            situacao_evento = {
                "status_slug": "extraviado",
                "label": "Ingresso Extraviado",
                "badge_class": "bg-danger",
                "icon_class": "bi bi-slash-circle-fill",
                "dentro": False,
                "ultima_movimentacao": f"Extraviado em {data_ext}",
                "detalhes": {
                    "tipo": "extraviado",
                    "quando": data_ext,
                    "por_quem": por_ext,
                    "motivo": ing_ext.motivo_cancelamento or "Cancelamento administrativo realizado pelo painel."
                }
            }

        # 5: Ingresso Cancelado (Optou por cancelar o próprio ingresso)
        elif (ultima_canc and ultima_canc.status == "aprovado") or (ingressos_cancelados and any(i.cancelado_por_id is None for i in ingressos_cancelados)):
            data_canc = None
            if ultima_canc and ultima_canc.analisado_em:
                data_canc = security.formatar_data_sp(ultima_canc.analisado_em, "%d/%m/%Y às %H:%M:%S")
            elif ingressos_cancelados and ingressos_cancelados[0].deleted_at:
                data_canc = security.formatar_data_sp(ingressos_cancelados[0].deleted_at, "%d/%m/%Y às %H:%M:%S")
            else:
                data_canc = "Data não informada"

            motivo_canc = (ultima_canc.motivo if ultima_canc and ultima_canc.motivo else None) or "Desistência voluntária pelo servidor."
            situacao_evento = {
                "status_slug": "cancelado",
                "label": "Ingresso Cancelado",
                "badge_class": "bg-secondary",
                "icon_class": "bi bi-x-circle-fill",
                "dentro": False,
                "ultima_movimentacao": f"Cancelado em {data_canc}",
                "detalhes": {
                    "tipo": "cancelado",
                    "quando": data_canc,
                    "por_quem": "O próprio participante (servidor)",
                    "motivo": motivo_canc
                }
            }

        # 2: Validação Recusada (Validador informou que não é servidor)
        elif ultima_validacao and ultima_validacao.status == "rejeitado":
            data_rec = security.formatar_data_sp(ultima_validacao.analisado_em, "%d/%m/%Y às %H:%M:%S") if ultima_validacao.analisado_em else "Data não informada"
            por_rec = ultima_validacao.analisado_por.nome if ultima_validacao.analisado_por else "Comissão de Validação"
            sec_rec = ultima_validacao.secretaria.nome if ultima_validacao.secretaria else (u.secretaria.nome if u.secretaria else "Geral")
            situacao_evento = {
                "status_slug": "validacao_recusada",
                "label": "Validação Recusada",
                "badge_class": "bg-danger",
                "icon_class": "bi bi-shield-x",
                "dentro": False,
                "ultima_movimentacao": f"Recusado em {data_rec}",
                "detalhes": {
                    "tipo": "validacao_recusada",
                    "quando": data_rec,
                    "por_quem": por_rec,
                    "secretaria": sec_rec,
                    "motivo": ultima_validacao.motivo_rejeicao or "Vínculo de servidor público municipal não confirmado pela secretaria."
                }
            }

        # 1: Em validação (Resgate realizado, vínculo pendente de análise)
        elif ultima_validacao and ultima_validacao.status == "pendente_analise":
            data_val = security.formatar_data_sp(ultima_validacao.criado_em, "%d/%m/%Y às %H:%M:%S") if ultima_validacao.criado_em else "Recentemente"
            situacao_evento = {
                "status_slug": "em_validacao",
                "label": "Em validação",
                "badge_class": "bg-info",
                "icon_class": "bi bi-hourglass-split",
                "dentro": False,
                "ultima_movimentacao": f"Aguardando análise desde {data_val}",
                "detalhes": None
            }

        # Padrão: Sem Ingresso
        else:
            situacao_evento = {
                "status_slug": "sem_ingresso",
                "label": "Sem Ingresso",
                "badge_class": "bg-secondary",
                "icon_class": "bi bi-dash-circle",
                "dentro": False,
                "ultima_movimentacao": None,
                "detalhes": None
            }

        lista_participantes_todos.append({
            "id": u.id,
            "cpf": u.cpf,
            "cpf_formatado": cpf_fmt,
            "nome": u.nome,
            "email": u.email,
            "telefone": u.telefone,
            "data_nascimento": u.data_nascimento,
            "setor": u.setor,
            "vinculo": u.vinculo,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "validado": u.validado,
            "foto_url": u.foto_rosto_url,
            "bloqueado_resgate": bool(getattr(u, "bloqueado_resgate", False)),
            "secretaria": {
                "id": u.secretaria.id,
                "nome": u.secretaria.nome
            } if u.secretaria else None,
            "ingresso": ing_info,
            "situacao_evento": situacao_evento,
            "logs_acesso": [
                {
                    "id": log.id,
                    "tipo": log.tipo.value if hasattr(log.tipo, "value") else str(log.tipo),
                    "data_hora": security.formatar_data_sp(log.data_hora, "%d/%m/%Y %H:%M:%S"),
                    "operador_nome": log.operador.nome if log.operador else ("Portaria" if log.operador_id else "Sistema")
                }
                for log in sorted(u.logs_acesso, key=lambda x: x.data_hora, reverse=True)[:10]
            ] if u.logs_acesso else []
        })

    # Filtragem
    lista_filtrada = []
    selected_sec_ids = [s.strip() for s in secretarias.split(",") if s.strip()] if secretarias else []
    if secretaria_id and str(secretaria_id) not in selected_sec_ids:
        selected_sec_ids.append(str(secretaria_id))

    for p in lista_participantes_todos:
        if busca and busca.strip():
            q = busca.strip().lower()
            m_nome = q in (p["nome"] or "").lower()
            m_cpf = q in (p["cpf"] or "")
            m_email = q in (p["email"] or "").lower()
            m_setor = q in (p["setor"] or "").lower()
            m_sec = q in (p["secretaria"]["nome"] if p["secretaria"] else "").lower()
            m_token = q in (p["ingresso"]["qr_code_token"] if p["ingresso"] else "").lower()
            if not (m_nome or m_cpf or m_email or m_setor or m_sec or m_token):
                continue

        if lote_id and str(lote_id).strip():
            if not p["ingresso"] or str(p["ingresso"]["lote_id"]) != str(lote_id).strip():
                continue

        if selected_sec_ids:
            sec_p_id = str(p["secretaria"]["id"]) if p["secretaria"] else "sem_secretaria"
            if sec_p_id not in selected_sec_ids:
                continue

        if status_presenca:
            status_selecionados = {
                status.strip()
                for status in status_presenca.split(",")
                if status.strip() and status.strip() != "todos"
            }
            status_participante = p["situacao_evento"]["status_slug"]
            corresponde_a_algum_status = any(
                status_participante == status for status in status_selecionados
            )
            if status_selecionados and not corresponde_a_algum_status:
                continue

        lista_filtrada.append(p)

    total_filtrados = len(lista_filtrada)
    limit = min(max(1, limit), 50)
    total_pages = max(1, math.ceil(total_filtrados / limit))
    page = min(max(1, page), total_pages)
    offset = (page - 1) * limit
    paginados = lista_filtrada[offset : offset + limit]

    total_fora = max(0, total_ingressos_resgatados - total_presentes)

    return JSONResponse(content={
        "participantes": paginados,
        "kpis": {
            "total_ingressos_resgatados": total_ingressos_resgatados,
            "total_presentes": total_presentes,
            "total_fora": total_fora
        },
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_filtrados,
            "total_pages": total_pages
        },
        "lotes_disponiveis": lista_lotes,
        "secretarias_disponiveis": lista_secretarias
    })


@router.put("/api/admin/participantes/{participante_id}")
async def editar_participante_admin(
    participante_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Permite que Administradores (admin) e Administradores Gerais (admin_geral)
    atualizem nome completo, vínculo, secretaria, setor, telefone,
    data de nascimento e e-mail de um participante.
    """
    try:
        data = await request.json()
    except Exception:
        data = dict(await request.form())

    stmt = select(Usuario).where(
        Usuario.id == participante_id,
        Usuario.deleted_at.is_(None)
    )
    res = await session.execute(stmt)
    usuario = res.scalars().first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Participante não encontrado.")

    is_super = "admin_geral" in admin.get_roles_list()
    target_roles = usuario.get_roles_list()

    # Se o participante alvo for admin ou admin_geral, apenas o Administrador Geral pode editar
    if ("admin_geral" in target_roles or "admin" in target_roles) and not is_super:
        raise HTTPException(
            status_code=403,
            detail="Apenas o Administrador Geral pode editar dados de outros administradores."
        )

    if "nome" in data:
        nome = data.get("nome")
        if not isinstance(nome, str) or not nome.strip():
            raise HTTPException(status_code=400, detail="O nome completo do participante é obrigatório.")
        usuario.nome = nome.strip()

    if "vinculo" in data:
        vinculo = data.get("vinculo")
        if vinculo is not None and not isinstance(vinculo, str):
            raise HTTPException(status_code=400, detail="Vínculo inválido.")
        usuario.vinculo = (vinculo.strip() or None) if vinculo is not None else None

    # 1. Secretaria
    if "secretaria_id" in data:
        raw_sec = data.get("secretaria_id")
        if raw_sec is None or raw_sec == "" or raw_sec == 0 or raw_sec == "0":
            usuario.secretaria_id = None
        else:
            try:
                sec_id = int(raw_sec)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Identificador de secretaria inválido.")

            sec = await session.get(Secretaria, sec_id)
            if not sec:
                raise HTTPException(status_code=404, detail="Secretaria informada não encontrada.")
            usuario.secretaria_id = sec.id

            # Sincroniza solicitações de validação pendentes de análise deste participante
            stmt_solic = select(SolicitacaoValidacao).where(
                SolicitacaoValidacao.usuario_id == usuario.id,
                SolicitacaoValidacao.status == "pendente_analise"
            )
            res_solic = await session.execute(stmt_solic)
            for solic in res_solic.scalars().all():
                solic.secretaria_id = sec.id
                session.add(solic)

    # 2. Setor
    if "setor" in data:
        raw_setor = data.get("setor")
        usuario.setor = str(raw_setor).strip() if raw_setor and str(raw_setor).strip() else None

    # 3. Telefone
    if "telefone" in data:
        raw_tel = data.get("telefone")
        if raw_tel and str(raw_tel).strip():
            try:
                usuario.telefone = formatar_telefone(str(raw_tel))
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
        else:
            usuario.telefone = None

    # 4. Data de Nascimento
    if "data_nascimento" in data:
        raw_data = data.get("data_nascimento")
        if raw_data and str(raw_data).strip():
            try:
                usuario.data_nascimento = normalizar_data_nascimento(str(raw_data))
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
        else:
            usuario.data_nascimento = None

    # 5. E-mail
    if "email" in data:
        raw_email = data.get("email")
        if raw_email and str(raw_email).strip():
            try:
                email_clean = validar_email(str(raw_email))
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))

            # Verifica unicidade de e-mail entre participantes ativos
            stmt_email = select(Usuario).where(
                Usuario.email.ilike(email_clean),
                Usuario.id != usuario.id,
                Usuario.deleted_at.is_(None)
            )
            res_email = await session.execute(stmt_email)
            if res_email.scalars().first():
                raise HTTPException(status_code=400, detail=f"O e-mail '{email_clean}' já está em uso por outro participante.")
            usuario.email = email_clean
        else:
            usuario.email = None

    session.add(usuario)
    await session.commit()
    await session.refresh(usuario)

    sec_info = None
    if usuario.secretaria_id:
        sec_obj = await session.get(Secretaria, usuario.secretaria_id)
        if sec_obj:
            sec_info = {"id": sec_obj.id, "nome": sec_obj.nome}

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": f"Dados do participante {usuario.nome} atualizados com sucesso!",
        "participante": {
            "id": usuario.id,
            "nome": usuario.nome,
            "vinculo": usuario.vinculo,
            "cpf": usuario.cpf,
            "email": usuario.email,
            "telefone": usuario.telefone,
            "data_nascimento": usuario.data_nascimento,
            "setor": usuario.setor,
            "secretaria": sec_info
        }
    })


@router.get("/api/admin/usuarios-equipe")
async def listar_usuarios_equipe_admin(
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Lista exclusivamente a equipe administrativa (Admin Geral, Admin, Portaria, Entregadores) com multi-roles e status de login"""
    stmt = (
        select(Usuario)
        .where(
            Usuario.deleted_at.is_(None),
            Usuario.ativo == True
        )
        .order_by(Usuario.nome.asc())
    )
    res = await session.execute(stmt)
    todos = res.scalars().all()

    equipe = [u for u in todos if u.role != UserRole.servidor and "servidor" not in u.get_roles_list()]

    agora = datetime.now(timezone.utc)
    lista_equipe = []

    admin_geral_total, admin_geral_logados = 0, 0
    admin_total, admin_logados = 0, 0
    validador_total, validador_logados = 0, 0
    portaria_total, portaria_logados = 0, 0
    entregadores_total, entregadores_logados = 0, 0

    for u in equipe:
        roles_list = u.get_roles_list()
        
        is_logado = False
        ultimo_acesso_fmt = "Nunca acessou"
        if u.ultimo_acesso:
            delta_segundos = (agora - u.ultimo_acesso).total_seconds()
            if delta_segundos < 7200:  # 2 horas
                is_logado = True
            ultimo_acesso_fmt = security.formatar_data_sp(u.ultimo_acesso)

        if "admin_geral" in roles_list:
            admin_geral_total += 1
            if is_logado: admin_geral_logados += 1
        if "admin" in roles_list:
            admin_total += 1
            if is_logado: admin_logados += 1
        if "portaria" in roles_list:
            portaria_total += 1
            if is_logado: portaria_logados += 1
        if "validador" in roles_list:
            validador_total += 1
            if is_logado: validador_logados += 1
        if "entregador" in roles_list:
            entregadores_total += 1
            if is_logado: entregadores_logados += 1

        cpf_raw = u.cpf or ""
        cpf_fmt = f"{cpf_raw[:3]}.{cpf_raw[3:6]}.{cpf_raw[6:9]}-{cpf_raw[9:]}" if len(cpf_raw) == 11 else cpf_raw

        lista_equipe.append({
            "id": u.id,
            "cpf": u.cpf,
            "cpf_formatado": cpf_fmt,
            "nome": u.nome,
            "email": u.email,
            "telefone": u.telefone,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "roles": roles_list,
            "secretarias_validador": u.secretarias_validador,
            "is_validador": "validador" in roles_list,
            "is_admin_geral": "admin_geral" in roles_list,
            "is_admin": "admin" in roles_list,
            "has_senha": bool(u.senha_hash),
            "deve_trocar_senha": bool(u.deve_trocar_senha),
            "is_logado": is_logado,
            "ultimo_acesso": ultimo_acesso_fmt
        })

    stmt_sec = select(Secretaria).order_by(Secretaria.nome.asc())
    res_sec = await session.execute(stmt_sec)
    secretarias_todas = res_sec.scalars().all()

    return JSONResponse(content={
        "usuarios": lista_equipe,
        "secretarias": [{"id": s.id, "nome": s.nome} for s in secretarias_todas],
        "kpis": {
            "admin_geral_total": admin_geral_total,
            "admin_geral_logados": admin_geral_logados,
            "admin_total": admin_total,
            "admin_logados": admin_logados,
            "validador_total": validador_total,
            "validador_logados": validador_logados,
            "portaria_total": portaria_total,
            "portaria_logados": portaria_logados,
            "entregadores_total": entregadores_total,
            "entregadores_logados": entregadores_logados
        }
    })


@router.post("/api/admin/usuarios")
async def criar_usuario_admin(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Cria um novo membro da equipe com suporte a múltiplas roles e validação de hierarquia"""
    try:
        data = await request.json()
    except Exception:
        data = dict(await request.form())

    cpf_raw = data.get("cpf", "").strip()
    cpf_limpo = "".join([c for c in cpf_raw if c.isdigit()]).zfill(11)
    if len(cpf_limpo) != 11:
        raise HTTPException(status_code=400, detail="CPF inválido. Deve conter 11 dígitos.")

    stmt_existente = select(Usuario).where(Usuario.cpf == cpf_limpo)
    res_existente = await session.execute(stmt_existente)
    if res_existente.scalars().first():
        raise HTTPException(status_code=400, detail=f"Já existe um usuário cadastrado com o CPF {cpf_raw}.")

    nome = data.get("nome", "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="O nome do usuário é obrigatório.")

    email_raw = data.get("email", "").strip().lower()
    if not email_raw or "@" not in email_raw or "." not in email_raw.split("@")[-1]:
        raise HTTPException(status_code=400, detail="O e-mail é obrigatório e deve possuir um formato válido.")

    stmt_email = select(Usuario).where(
        Usuario.email.ilike(email_raw),
        Usuario.deleted_at.is_(None)
    )
    res_email = await session.execute(stmt_email)
    if res_email.scalars().first():
        raise HTTPException(status_code=400, detail=f"Já existe um usuário cadastrado com o e-mail '{email_raw}'.")

    # Processar múltiplas roles
    raw_roles = data.get("roles")
    roles_list = []
    if isinstance(raw_roles, list):
        roles_list = [r.strip().lower() for r in raw_roles if r.strip()]
    elif isinstance(raw_roles, str) and raw_roles.strip():
        roles_list = [r.strip().lower() for r in raw_roles.split(",") if r.strip()]
    elif data.get("role"):
        roles_list = [data.get("role").strip().lower()]

    if not roles_list:
        roles_list = ["portaria"]

    # Validação de hierarquia
    is_super = "admin_geral" in admin.get_roles_list()
    if ("admin_geral" in roles_list or "admin" in roles_list) and not is_super:
        raise HTTPException(
            status_code=403,
            detail="Apenas o Administrador Geral pode cadastrar Administradores."
        )

    # Definir primary role
    if "admin_geral" in roles_list:
        primary_role = UserRole.admin_geral
    elif "admin" in roles_list:
        primary_role = UserRole.admin
    elif "portaria" in roles_list:
        primary_role = UserRole.portaria
    elif "validador" in roles_list:
        primary_role = UserRole.validador
    elif "entregador" in roles_list:
        primary_role = UserRole.entregador
    else:
        primary_role = UserRole.servidor

    # Geração automática de senha provisória para primeiro acesso
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    senha_provisoria = "Fest@" + "".join(secrets.choice(chars) for _ in range(5))
    senha_hash = security.get_password_hash(senha_provisoria)

    novo_usuario = Usuario(
        cpf=cpf_limpo,
        nome=nome,
        role=primary_role,
        roles=",".join(roles_list),
        senha_hash=senha_hash,
        deve_trocar_senha=True,
        secretaria_id=None,  # Membros da equipe não têm secretaria
        setor="Equipe Operacional",
        vinculo="Staff",
        telefone=data.get("telefone", "").strip() or None,
        email=email_raw,
        validado=True,
        secretarias_validador=",".join(str(s).strip() for s in data.get("secretarias_validador", [])) if isinstance(data.get("secretarias_validador"), list) else (data.get("secretarias_validador", "").strip() or None)
    )
    session.add(novo_usuario)
    await session.commit()
    await session.refresh(novo_usuario)

    # Disparo automático de e-mail de apresentação com a senha temporária
    cpf_fmt = f"{cpf_limpo[:3]}.{cpf_limpo[3:6]}.{cpf_limpo[6:9]}-{cpf_limpo[9:]}"
    roles_formatadas = ", ".join([r.replace("_", " ").title() for r in roles_list])

    asyncio.create_task(
        send_team_credentials_email_async(
            to_email=email_raw,
            nome=nome,
            cpf=cpf_fmt,
            senha_provisoria=senha_provisoria,
            roles_str=roles_formatadas,
            is_reset=False
        )
    )

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": f"Membro da equipe {nome} cadastrado com sucesso! Uma senha provisória foi enviada para {email_raw}.",
        "id": novo_usuario.id
    })


@router.put("/api/admin/usuarios/{usuario_id}")
async def editar_usuario_admin(
    usuario_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Edita dados e múltiplas roles de um membro da equipe respeitando hierarquia"""
    try:
        data = await request.json()
    except Exception:
        data = dict(await request.form())

    stmt = select(Usuario).where(Usuario.id == usuario_id)
    res = await session.execute(stmt)
    usuario = res.scalars().first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    is_super = "admin_geral" in admin.get_roles_list()
    target_roles = usuario.get_roles_list()

    # Se o usuário alvo é admin/admin_geral, exige admin_geral para editar
    if ("admin_geral" in target_roles or "admin" in target_roles) and not is_super:
        raise HTTPException(
            status_code=403,
            detail="Apenas o Administrador Geral pode editar outros administradores."
        )

    if "nome" in data and data["nome"].strip():
        usuario.nome = data["nome"].strip()

    if "telefone" in data:
        usuario.telefone = data["telefone"].strip() if data.get("telefone") else None

    if "email" in data:
        email_clean = data["email"].strip().lower() if data.get("email") and data["email"].strip() else None
        if email_clean:
            if "@" not in email_clean or "." not in email_clean.split("@")[-1]:
                raise HTTPException(status_code=400, detail="E-mail inválido.")
            stmt_email = select(Usuario).where(
                Usuario.email.ilike(email_clean),
                Usuario.id != usuario_id,
                Usuario.deleted_at.is_(None)
            )
            res_email = await session.execute(stmt_email)
            if res_email.scalars().first():
                raise HTTPException(status_code=400, detail=f"O e-mail '{email_clean}' já está em uso por outro usuário.")
        usuario.email = email_clean

    # Atualizar roles
    if "roles" in data or "role" in data:
        raw_roles = data.get("roles")
        roles_list = []
        if isinstance(raw_roles, list):
            roles_list = [r.strip().lower() for r in raw_roles if r.strip()]
        elif isinstance(raw_roles, str) and raw_roles.strip():
            roles_list = [r.strip().lower() for r in raw_roles.split(",") if r.strip()]
        elif data.get("role"):
            roles_list = [data.get("role").strip().lower()]

        if roles_list:
            if ("admin_geral" in roles_list or "admin" in roles_list) and not is_super:
                raise HTTPException(
                    status_code=403,
                    detail="Apenas o Administrador Geral pode conceder privilégios de Administrador."
                )

            usuario.roles = ",".join(roles_list)
            if "admin_geral" in roles_list:
                usuario.role = UserRole.admin_geral
            elif "admin" in roles_list:
                usuario.role = UserRole.admin
            elif "portaria" in roles_list:
                usuario.role = UserRole.portaria
            elif "entregador" in roles_list:
                usuario.role = UserRole.entregador
            elif "validador" in roles_list:
                usuario.role = UserRole.validador

    if "secretarias_validador" in data:
        raw_sec = data["secretarias_validador"]
        if isinstance(raw_sec, list):
            usuario.secretarias_validador = ",".join(str(s).strip() for s in raw_sec if str(s).strip()) or None
        elif isinstance(raw_sec, str):
            usuario.secretarias_validador = raw_sec.strip() or None
        else:
            usuario.secretarias_validador = None
    usuario.secretaria_id = None  # Membros da equipe não têm secretaria
    session.add(usuario)
    await session.commit()
    await session.refresh(usuario)

    return JSONResponse(content={"sucesso": True, "mensagem": f"Usuário {usuario.nome} atualizado com sucesso!"})


@router.post("/api/admin/usuarios/{usuario_id}/senha")
async def gerenciar_senha_usuario_admin(
    usuario_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """A definição manual de senha foi descontinuada. Use a redefinição com envio provisório por e-mail."""
    raise HTTPException(
        status_code=400,
        detail="A inserção manual direta de senhas foi descontinuada por segurança. Utilize o botão 'Resetar Senha' para gerar e enviar uma senha provisória ao e-mail cadastrado."
    )


@router.post("/api/admin/usuarios/{usuario_id}/email")
@router.post("/api/admin/participantes/{usuario_id}/enviar-email")
async def enviar_email_usuario_admin(
    usuario_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Envia um e-mail personalizado para um usuário ou reenvia o seu ingresso oficial"""
    try:
        data = await request.json()
    except Exception:
        data = dict(await request.form())

    stmt = (
        select(Usuario)
        .where(Usuario.id == usuario_id)
        .options(
            selectinload(Usuario.secretaria),
            selectinload(Usuario.ingressos).selectinload(Ingresso.lote)
        )
    )
    res = await session.execute(stmt)
    usuario = res.scalars().first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    if not usuario.email:
        raise HTTPException(status_code=400, detail="Este usuário não possui um endereço de e-mail cadastrado.")

    tipo = data.get("tipo", "comunicado")

    if tipo == "ingresso":
        if not usuario.ingressos or len(usuario.ingressos) == 0:
            raise HTTPException(status_code=400, detail="O usuário não possui ingresso resgatado.")

        ultimo_ing = sorted(usuario.ingressos, key=lambda x: x.data_resgate, reverse=True)[0]
        lote_nome = ultimo_ing.lote.nome if ultimo_ing.lote else "Lote Oficial"

        cpf_fmt = f"{usuario.cpf[:3]}.{usuario.cpf[3:6]}.{usuario.cpf[6:9]}-{usuario.cpf[9:]}" if usuario.cpf and len(usuario.cpf) == 11 else (usuario.cpf or "")
        sec_nome = usuario.secretaria.nome if usuario.secretaria else "Geral"
        background_tasks.add_task(
            send_ticket_email_async,
            usuario_nome=usuario.nome,
            usuario_email=usuario.email,
            ingresso_token=ultimo_ing.qr_code_token,
            lote_nome=lote_nome,
            secretaria_nome=sec_nome,
            setor=usuario.setor,
            cpf_formatado=cpf_fmt
        )
        return JSONResponse(content={"sucesso": True, "enfileirado": True, "mensagem": f"Ingresso enfileirado para reenvio para {usuario.email}!"})

    else:
        assunto = data.get("assunto", "").strip() or "📢 Comunicado Oficial - Servindoor"
        mensagem = data.get("mensagem", "").strip()
        if not mensagem:
            raise HTTPException(status_code=400, detail="A mensagem do e-mail não pode ser vazia.")

        background_tasks.add_task(
            send_custom_message_email_async,
            usuario_email=usuario.email,
            usuario_nome=usuario.nome,
            assunto=assunto,
            mensagem=mensagem
        )
        return JSONResponse(content={"sucesso": True, "enfileirado": True, "mensagem": f"E-mail enfileirado com sucesso para {usuario.email}!"})


@router.delete("/api/admin/usuarios/{usuario_id}")
async def excluir_usuario_admin(
    usuario_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Realiza o soft-delete de um usuário da equipe ou participante"""
    stmt = select(Usuario).where(Usuario.id == usuario_id, Usuario.deleted_at.is_(None))
    res = await session.execute(stmt)
    usuario = res.scalars().first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado ou já excluído.")

    if usuario.id == admin.id:
        raise HTTPException(status_code=400, detail="Você não pode excluir a sua própria conta.")

    is_super = "admin_geral" in admin.get_roles_list()
    target_roles = usuario.get_roles_list()

    # Proteção de Administradores
    if ("admin_geral" in target_roles or "admin" in target_roles) and not is_super:
        raise HTTPException(
            status_code=403,
            detail="Apenas o Administrador Geral pode excluir administradores."
        )

    # Proteção de Participantes
    if usuario.role == UserRole.servidor and not is_super:
        raise HTTPException(
            status_code=403,
            detail="Apenas o Administrador Geral pode remover participantes."
        )

    # SOFT DELETE
    usuario.deleted_at = datetime.now(timezone.utc)
    usuario.ativo = False
    session.add(usuario)
    await session.commit()

    return JSONResponse(content={"sucesso": True, "mensagem": f"Usuário {usuario.nome} excluído com sucesso (soft-delete)."})


@router.post("/api/admin/usuarios/{usuario_id}/redefinir-senha-email")
async def redefinir_senha_usuario_email_admin(
    usuario_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Gera uma nova senha provisória e a envia diretamente ao e-mail cadastrado do membro da equipe"""
    stmt = select(Usuario).where(Usuario.id == usuario_id, Usuario.deleted_at.is_(None))
    res = await session.execute(stmt)
    u = res.scalars().first()
    if not u:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    if not u.email or "@" not in u.email:
        raise HTTPException(status_code=400, detail="Este usuário não possui um e-mail válido cadastrado.")

    is_super = "admin_geral" in admin.get_roles_list()
    u_roles = u.get_roles_list()
    if ("admin_geral" in u_roles or "admin" in u_roles) and not is_super:
        raise HTTPException(status_code=403, detail="Apenas o Administrador Geral pode redefinir senha de Administradores.")

    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    senha_provisoria = "Fest@" + "".join(secrets.choice(chars) for _ in range(5))
    u.senha_hash = security.get_password_hash(senha_provisoria)
    u.deve_trocar_senha = True
    u.remove_active_session()
    session.add(u)
    await session.commit()

    cpf_raw = u.cpf or ""
    cpf_fmt = f"{cpf_raw[:3]}.{cpf_raw[3:6]}.{cpf_raw[6:9]}-{cpf_raw[9:]}" if len(cpf_raw) == 11 else cpf_raw
    roles_formatadas = ", ".join([r.replace("_", " ").title() for r in u_roles])

    asyncio.create_task(
        send_team_credentials_email_async(
            to_email=u.email,
            nome=u.nome,
            cpf=cpf_fmt,
            senha_provisoria=senha_provisoria,
            roles_str=roles_formatadas,
            is_reset=True
        )
    )

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": f"Nova senha provisória gerada e enviada com sucesso para {u.email}!"
    })

@router.get("/api/admin/ingressos/{ingresso_id}/pdf")
async def download_ingresso_pdf_admin(
    ingresso_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Gera e retorna o PDF oficial do ingresso contendo exclusivamente o PNG do ingresso para o administrador"""
    from fastapi.responses import Response
    from app.services.ticket_generator import generate_ticket_pdf_bytes, mask_cpf

    stmt = (
        select(Ingresso)
        .where(
            Ingresso.id == ingresso_id,
            Ingresso.deleted_at.is_(None)
        )
        .options(
            selectinload(Ingresso.usuario).selectinload(Usuario.secretaria),
            selectinload(Ingresso.lote)
        )
    )
    res = await session.execute(stmt)
    ingresso = res.scalars().first()
    if not ingresso or not ingresso.usuario:
        raise HTTPException(status_code=404, detail="Ingresso não encontrado.")

    usuario = ingresso.usuario
    sec_nome = usuario.secretaria.nome if usuario.secretaria else "Prefeitura Municipal"
    lote_nome = ingresso.lote.nome if ingresso.lote else "Lote Geral"
    cpf_mascarado = mask_cpf(usuario.cpf)

    pdf_bytes = generate_ticket_pdf_bytes(
        nome=usuario.nome,
        cpf=cpf_mascarado,
        ingresso_token=ingresso.qr_code_token,
        lote_nome=lote_nome,
        secretaria_nome=sec_nome,
        setor=usuario.setor
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=ingresso_servindoor_{ingresso.qr_code_token}.pdf",
            "Cache-Control": "no-cache"
        }
    )
