from app.core import security
from app.services.email_service import send_custom_message_email_async, send_ticket_email_async
import csv
import io
import os
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, or_
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.all_models import Lote, Usuario, Ingresso, Secretaria, LogAcesso, MovimentoTipo, UserRole, ReservaIngresso
from app.core.deps import get_current_admin, get_current_admin_geral

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
VUE_INDEX_PATH = "app/static/dist/index.html"

def calcular_status_lote(lote: Lote) -> dict:
    """
    Calcula o status do lote com base na regra soberana do período de resgate:
    1. Se agora > data_fechamento -> Encerrado (não pode toggle)
    2. Se agora < data_abertura -> Agendado (não pode toggle; período soberano)
    3. Se data_abertura <= agora <= data_fechamento -> Período de resgate ativo (pode toggle pausar/despausar)
    """
    agora = datetime.now()
    
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

async def obter_dados_dashboard(session: AsyncSession):
    stmt_lotes = (
        select(Lote)
        .options(selectinload(Lote.secretaria))
        .order_by(Lote.id.asc())
    )
    res_lotes = await session.execute(stmt_lotes)
    lotes_raw = res_lotes.scalars().all()

    stmt_vagas = select(func.sum(Lote.quantidade_total))
    res_vagas = await session.execute(stmt_vagas)
    total_vagas = res_vagas.scalar() or 0

    stmt_resgates = select(func.count(Ingresso.id))
    res_resgates = await session.execute(stmt_resgates)
    total_resgatados = res_resgates.scalar() or 0

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
                    "data_abertura": item["model"].data_abertura.isoformat() if item["model"].data_abertura else None,
                    "data_fechamento": item["model"].data_fechamento.isoformat() if item["model"].data_fechamento else None,
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
    agora = datetime.now()
    dt_abertura = datetime.fromisoformat(data_abertura)
    dt_fechamento = datetime.fromisoformat(data_fechamento) if data_fechamento and data_fechamento.strip() else None

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

    agora = datetime.now()
    dt_abertura = datetime.fromisoformat(data_abertura)
    dt_fechamento = datetime.fromisoformat(data_fechamento) if data_fechamento and data_fechamento.strip() else None

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

    lote.data_fechamento = datetime.now()
    session.add(lote)
    await session.commit()

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/admin/lote/{lote_id}/excluir")
async def excluir_lote(
    lote_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    lote = await session.get(Lote, lote_id)
    if not lote:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    stmt_reservas = select(ReservaIngresso).where(ReservaIngresso.lote_id == lote_id)
    res_reservas = await session.execute(stmt_reservas)
    for r in res_reservas.scalars().all():
        await session.delete(r)

    stmt_ingressos = select(Ingresso).where(Ingresso.lote_id == lote_id)
    res_ing = await session.execute(stmt_ingressos)
    for ing in res_ing.scalars().all():
        await session.delete(ing)

    await session.delete(lote)
    await session.commit()

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

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

    stmt = (
        select(Ingresso)
        .where(Ingresso.lote_id == lote_id)
        .options(selectinload(Ingresso.usuario).selectinload(Usuario.secretaria))
        .order_by(Ingresso.data_resgate.desc())
    )
    resultado = await session.execute(stmt)
    ingressos_raw = resultado.scalars().all()

    stmt_logs = select(LogAcesso.usuario_id).where(LogAcesso.tipo == MovimentoTipo.entrada)
    res_logs = await session.execute(stmt_logs)
    usuarios_presentes = set(res_logs.scalars().all())

    ingressos_processados = []
    for ing in ingressos_raw:
        u = ing.usuario
        sec_nome = u.secretaria.nome if u and u.secretaria else "Geral / Não informada"
        ja_entrou = ing.usuario_id in usuarios_presentes
        ingressos_processados.append({
            "model": ing,
            "usuario": u,
            "secretaria_nome": sec_nome,
            "ja_entrou": ja_entrou
        })

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({
            "lote": {
                "id": lote.id,
                "nome": lote.nome,
                "quantidade_total": lote.quantidade_total,
                "data_abertura": lote.data_abertura.isoformat() if lote.data_abertura else None,
                "data_fechamento": lote.data_fechamento.isoformat() if lote.data_fechamento else None
            },
            "total_ingressos": len(ingressos_raw),
            "ingressos": [
                {
                    "model": {
                        "id": item["model"].id,
                        "data_resgate": item["model"].data_resgate.isoformat()
                    },
                    "usuario": {
                        "id": item["usuario"].id,
                        "nome": item["usuario"].nome,
                        "cpf": item["usuario"].cpf,
                        "setor": item["usuario"].setor,
                        "vinculo": item["usuario"].vinculo,
                        "telefone": item["usuario"].telefone
                    } if item["usuario"] else None,
                    "secretaria_nome": item["secretaria_nome"],
                    "ja_entrou": item["ja_entrou"]
                } for item in ingressos_processados
            ]
        })

    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)

    return templates.TemplateResponse(
        request=request,
        name="lote_ingressos.html",
        context={
            "user": current_user,
            "lote": lote,
            "ingressos": ingressos_processados,
            "total_ingressos": len(ingressos_raw)
        }
    )

@router.post("/api/admin/ingressos/{ingresso_id}/cancelar")
@router.post("/admin/ingresso/{ingresso_id}/cancelar")
async def cancelar_ingresso(
    ingresso_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin_geral)
):
    """Realiza o soft-delete do ingresso e devolve a vaga para o lote correspondente"""
    stmt = (
        select(Ingresso)
        .where(
            Ingresso.id == ingresso_id,
            Ingresso.deleted_at.is_(None)
        )
        .options(selectinload(Ingresso.lote))
    )
    res = await session.execute(stmt)
    ingresso = res.scalars().first()
    if not ingresso:
        raise HTTPException(status_code=404, detail="Ingresso não encontrado ou já cancelado.")

    # Soft delete do ingresso
    ingresso.deleted_at = datetime.now()
    session.add(ingresso)

    if ingresso.lote and ingresso.lote.quantidade_resgatada > 0:
        ingresso.lote.quantidade_resgatada -= 1
        session.add(ingresso.lote)

    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": "Ingresso cancelado com sucesso e vaga devolvida ao lote."
    })

@router.get("/admin/lote/{lote_id}/exportar-csv")
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
        "ID Ingresso", 
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
        sec_nome = u.secretaria.nome if u and u.secretaria else "Geral / Não informada"
        writer.writerow([
            ing.id,
            f"'{u.cpf}" if u else "",
            u.nome if u else "",
            u.data_nascimento if u else "",
            u.setor if u else "",
            sec_nome,
            u.vinculo if u else "",
            u.telefone if u else "",
            u.email if u else "",
            ing.data_resgate.strftime("%d/%m/%Y %H:%M:%S"),
            ing.qr_code_token or ""
        ])

    output.seek(0)
    nome_arquivo = f"ingressos_lote_{lote.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
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
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """Lista exclusivamente os servidores que resgataram ingressos com KPIs de presença"""
    stmt = (
        select(Usuario)
        .where(
            Usuario.deleted_at.is_(None),
            Usuario.ativo == True
        )
        .options(
            selectinload(Usuario.secretaria),
            selectinload(Usuario.ingressos).selectinload(Ingresso.lote),
            selectinload(Usuario.logs_acesso)
        )
        .order_by(Usuario.nome.asc())
    )
    res = await session.execute(stmt)
    todos = res.scalars().all()

    lista_participantes = []
    total_ingressos_resgatados = 0
    total_presentes = 0

    for u in todos:
        # Filtra apenas quem é servidor ou tem ingresso emitido
        if not (u.role == UserRole.servidor or (u.ingressos and len(u.ingressos) > 0)):
            continue

        cpf_raw = u.cpf or ""
        cpf_fmt = f"{cpf_raw[:3]}.{cpf_raw[3:6]}.{cpf_raw[6:9]}-{cpf_raw[9:]}" if len(cpf_raw) == 11 else cpf_raw

        ing_info = None
        ingressos_ativos = [i for i in u.ingressos if i.deleted_at is None] if u.ingressos else []
        if ingressos_ativos:
            ultimo_ing = sorted(ingressos_ativos, key=lambda x: x.data_resgate, reverse=True)[0]
            ing_info = {
                "id": ultimo_ing.id,
                "lote_id": ultimo_ing.lote_id,
                "lote_nome": ultimo_ing.lote.nome if ultimo_ing.lote else f"Lote #{ultimo_ing.lote_id}",
                "qr_code_token": ultimo_ing.qr_code_token,
                "data_resgate": ultimo_ing.data_resgate.strftime("%d/%m/%Y %H:%M:%S")
            }
            total_ingressos_resgatados += 1

        situacao_evento = {
            "status_slug": "sem_ingresso",
            "label": "Sem Ingresso",
            "badge_class": "bg-secondary",
            "dentro": False,
            "ultima_movimentacao": None
        }

        if ing_info:
            situacao_evento = {
                "status_slug": "fora",
                "label": "Fora do Evento (Ingresso Emitido)",
                "badge_class": "bg-info",
                "dentro": False,
                "ultima_movimentacao": None
            }

        if u.logs_acesso and len(u.logs_acesso) > 0:
            ultimo_log = sorted(u.logs_acesso, key=lambda x: x.data_hora, reverse=True)[0]
            tipo_str = ultimo_log.tipo.value if hasattr(ultimo_log.tipo, "value") else str(ultimo_log.tipo)
            data_fmt = ultimo_log.data_hora.strftime("%d/%m às %H:%M:%S")
            if tipo_str == "entrada":
                total_presentes += 1
                situacao_evento = {
                    "status_slug": "presente",
                    "label": f"Presente no Evento (Entrada às {ultimo_log.data_hora.strftime('%H:%M')})",
                    "badge_class": "bg-success",
                    "dentro": true if False else True,
                    "ultima_movimentacao": f"Entrada em {data_fmt}"
                }
            else:
                situacao_evento = {
                    "status_slug": "fora",
                    "label": f"Fora do Evento (Saída às {ultimo_log.data_hora.strftime('%H:%M')})",
                    "badge_class": "bg-warning",
                    "dentro": False,
                    "ultima_movimentacao": f"Saída em {data_fmt}"
                }

        lista_participantes.append({
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
                    "data_hora": log.data_hora.strftime("%d/%m/%Y %H:%M:%S")
                }
                for log in sorted(u.logs_acesso, key=lambda x: x.data_hora, reverse=True)[:10]
            ] if u.logs_acesso else []
        })

    total_fora = max(0, total_ingressos_resgatados - total_presentes)

    return JSONResponse(content={
        "participantes": lista_participantes,
        "kpis": {
            "total_ingressos_resgatados": total_ingressos_resgatados,
            "total_presentes": total_presentes,
            "total_fora": total_fora
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

    agora = datetime.now()
    lista_equipe = []

    admin_geral_total, admin_geral_logados = 0, 0
    admin_total, admin_logados = 0, 0
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
            ultimo_acesso_fmt = u.ultimo_acesso.strftime("%d/%m/%Y às %H:%M")

        if "admin_geral" in roles_list:
            admin_geral_total += 1
            if is_logado: admin_geral_logados += 1
        if "admin" in roles_list:
            admin_total += 1
            if is_logado: admin_logados += 1
        if "portaria" in roles_list:
            portaria_total += 1
            if is_logado: portaria_logados += 1
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
            "is_admin_geral": "admin_geral" in roles_list,
            "is_admin": "admin" in roles_list,
            "has_senha": bool(u.senha_hash),
            "is_logado": is_logado,
            "ultimo_acesso": ultimo_acesso_fmt
        })

    return JSONResponse(content={
        "usuarios": lista_equipe,
        "kpis": {
            "admin_geral_total": admin_geral_total,
            "admin_geral_logados": admin_geral_logados,
            "admin_total": admin_total,
            "admin_logados": admin_logados,
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
    elif "entregador" in roles_list:
        primary_role = UserRole.entregador
    else:
        primary_role = UserRole.servidor

    senha = data.get("senha", "").strip()
    senha_hash = security.get_password_hash(senha) if senha else None

    novo_usuario = Usuario(
        cpf=cpf_limpo,
        nome=nome,
        role=primary_role,
        roles=",".join(roles_list),
        senha_hash=senha_hash,
        secretaria_id=None,  # Membros da equipe não têm secretaria
        setor="Equipe Operacional",
        vinculo="Staff",
        telefone=data.get("telefone", "").strip() or None,
        email=data.get("email", "").strip() or None,
        validado=True
    )
    session.add(novo_usuario)
    await session.commit()
    await session.refresh(novo_usuario)

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": f"Membro da equipe {nome} cadastrado com sucesso!",
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

    if "email" in data:
        usuario.email = data["email"].strip() or None

    if "telefone" in data:
        usuario.telefone = data["telefone"].strip() or None

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
    """Altera ou reseta a senha de um usuário da equipe"""
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

    if ("admin_geral" in target_roles or "admin" in target_roles) and not is_super:
        raise HTTPException(
            status_code=403,
            detail="Apenas o Administrador Geral pode alterar a senha de outros administradores."
        )

    nova_senha = data.get("nova_senha", "").strip()
    if not nova_senha:
        raise HTTPException(status_code=400, detail="A nova senha não pode ser vazia.")

    usuario.senha_hash = security.get_password_hash(nova_senha)
    session.add(usuario)
    await session.commit()

    return JSONResponse(content={"sucesso": True, "mensagem": f"Senha do usuário {usuario.nome} alterada com sucesso!"})


@router.post("/api/admin/usuarios/{usuario_id}/email")
async def enviar_email_usuario_admin(
    usuario_id: int,
    request: Request,
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

        enviado = await send_ticket_email_async(
            destinatario=usuario.email,
            nome_servidor=usuario.nome,
            cpf_servidor=usuario.cpf,
            lote_nome=lote_nome,
            qr_code_token=ultimo_ing.qr_code_token
        )
        if not enviado:
            raise HTTPException(status_code=500, detail="Falha ao enviar e-mail via Amazon SES. Verifique as credenciais.")

        return JSONResponse(content={"sucesso": True, "mensagem": f"Ingresso reenviado com sucesso para {usuario.email}!"})

    else:
        assunto = data.get("assunto", "").strip() or "📢 Comunicado Oficial - Servindoor"
        mensagem = data.get("mensagem", "").strip()
        if not mensagem:
            raise HTTPException(status_code=400, detail="A mensagem do e-mail não pode ser vazia.")

        enviado = await send_custom_message_email_async(
            destinatario=usuario.email,
            nome_servidor=usuario.nome,
            assunto=assunto,
            mensagem=mensagem
        )
        if not enviado:
            raise HTTPException(status_code=500, detail="Falha ao enviar e-mail via Amazon SES.")

        return JSONResponse(content={"sucesso": True, "mensagem": f"E-mail enviado com sucesso para {usuario.email}!"})


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
    usuario.deleted_at = datetime.now()
    usuario.ativo = False
    session.add(usuario)
    await session.commit()

    return JSONResponse(content={"sucesso": True, "mensagem": f"Usuário {usuario.nome} excluído com sucesso (soft-delete)."})
