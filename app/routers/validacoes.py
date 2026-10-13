import os
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, desc
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.all_models import Usuario, Lote, Ingresso, Secretaria, SolicitacaoValidacao, UserRole
from app.core.deps import get_current_validador
from app.core.cpf import formatar_cpf
from app.core.security import formatar_data_sp
from app.services.email_service import (
    send_ticket_email_async,
    send_validation_rejection_email_async
)

router = APIRouter(prefix="/api/admin/validacoes", tags=["Validação de Servidores"])


@router.get("")
async def listar_solicitacoes_validacao(
    status_filtro: Optional[str] = "pendente_analise",
    secretaria_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    validador: Usuario = Depends(get_current_validador)
):
    """
    Lista solicitações de validação de servidores.
    Validadores com 'secretarias_validador' definidas só têm acesso às suas secretarias atribuídas.
    Admin Geral tem acesso irrestrito.
    """
    is_superadmin = "admin_geral" in validador.get_roles_list() or validador.role == UserRole.admin_geral
    allowed_sec_ids = validador.get_secretarias_validador_ids()

    stmt = (
        select(SolicitacaoValidacao)
        .options(
            selectinload(SolicitacaoValidacao.usuario).selectinload(Usuario.secretaria),
            selectinload(SolicitacaoValidacao.lote),
            selectinload(SolicitacaoValidacao.secretaria),
            selectinload(SolicitacaoValidacao.analisado_por)
        )
        .order_by(
            SolicitacaoValidacao.status == "pendente_analise",
            desc(SolicitacaoValidacao.id)
        )
    )

    res = await session.execute(stmt)
    todas = res.scalars().all()

    # Aplica restrição de secretarias do validador (a menos que seja superadmin) (SEC-08)
    if not is_superadmin:
        if not allowed_sec_ids:
            todas = []
        else:
            todas = [
                s for s in todas
                if (s.secretaria_id in allowed_sec_ids or (s.usuario and s.usuario.secretaria_id in allowed_sec_ids))
            ]

    # KPIs de contagem
    kpis = {
        "total_pendentes": sum(1 for s in todas if s.status == "pendente_analise"),
        "total_confirmados_api": sum(1 for s in todas if s.status == "pendente_analise" and getattr(s, "identificado_api", False)),
        "total_aprovados": sum(1 for s in todas if s.status == "aprovado"),
        "total_rejeitados": sum(1 for s in todas if s.status == "rejeitado"),
        "total_geral": len(todas),
        "total_comunicacao_pendente": sum(1 for s in todas if s.status in ["aprovado", "rejeitado"] and not getattr(s, "comunicado", False)),
        "total_comunicados": sum(1 for s in todas if getattr(s, "comunicado", False))
    }

    # Filtragem por status e secretaria
    selecionadas = [
        s for s in todas
        if (not status_filtro or status_filtro == "todos" or s.status == status_filtro)
        and (not secretaria_id or s.secretaria_id == secretaria_id)
    ]
    estados_externos = {}
    if selecionadas:
        estados_externos = dict((await session.execute(text("""
            SELECT solicitacao_id, status FROM resgate_jobs
            WHERE job_type = 'external_validation'
              AND solicitacao_id = ANY(CAST(:ids AS INTEGER[]))
        """), {"ids": [s.id for s in selecionadas]})).all())
    lista_filtrada = []
    for s in selecionadas:
        u = s.usuario
        l = s.lote
        sec = s.secretaria or (u.secretaria if u else None)

        lista_filtrada.append({
            "id": s.id,
            "status": s.status,
            "identificado_api": bool(getattr(s, "identificado_api", False)),
            "validacao_externa_status": estados_externos.get(s.id),
            "criado_em": formatar_data_sp(s.criado_em) if s.criado_em else "-",
            "analisado_em": formatar_data_sp(s.analisado_em),
            "analisado_por_nome": s.analisado_por.nome if s.analisado_por else None,
            "motivo_rejeicao": s.motivo_rejeicao,
            "comunicado": bool(getattr(s, "comunicado", False)),
            "comunicado_em": formatar_data_sp(getattr(s, "comunicado_em", None)),
            "lote_nome": l.nome if l else "Lote Geral",
            "secretaria_nome": sec.nome if sec else "Não informada",
            "secretaria_id": sec.id if sec else None,
            "usuario": {
                "id": u.id if u else None,
                "nome": u.nome if u else "Desconhecido",
                "cpf": u.cpf if u else "",
                "cpf_formatado": formatar_cpf(u.cpf) if u else "",
                "email": u.email if u else "",
                "telefone": u.telefone if u else "",
                "setor": u.setor if u else "",
                "data_nascimento": u.data_nascimento if u else "",
                "vinculo": u.vinculo if u else "Servidor",
                "foto_rosto_url": u.foto_rosto_url if u else None
            }
        })

    return JSONResponse(content={
        "sucesso": True,
        "kpis": kpis,
        "solicitacoes": lista_filtrada,
        "is_superadmin": is_superadmin,
        "allowed_secretarias": allowed_sec_ids
    })


@router.post("/{solicitacao_id}/aprovar")
async def aprovar_solicitacao_validacao(
    solicitacao_id: int,
    session: AsyncSession = Depends(get_session),
    validador: Usuario = Depends(get_current_validador)
):
    """
    Aprova a solicitação de validação:
    - Marca solicitação como 'aprovado'
    - Gera o Ingresso oficial com token QR Code UUID
    - Dispara e-mail com QR Code ao participante
    """
    stmt = (
        select(SolicitacaoValidacao)
        .where(SolicitacaoValidacao.id == solicitacao_id)
        .with_for_update()
        .options(
            selectinload(SolicitacaoValidacao.usuario),
            selectinload(SolicitacaoValidacao.lote),
            selectinload(SolicitacaoValidacao.secretaria)
        )
    )
    res = await session.execute(stmt)
    solic = res.scalars().first()

    if not solic:
        raise HTTPException(status_code=404, detail="Solicitação de validação não encontrada.")

    if solic.status != "pendente_analise":
        raise HTTPException(status_code=400, detail=f"Esta solicitação já foi finalizada como '{solic.status}'.")

    # Verifica permissão da secretaria do validador (SEC-08)
    is_superadmin = "admin_geral" in validador.get_roles_list() or validador.role == UserRole.admin_geral
    allowed_ids = validador.get_secretarias_validador_ids()
    sec_id = solic.secretaria_id or (solic.usuario.secretaria_id if solic.usuario else None)
    if not is_superadmin and (not allowed_ids or sec_id not in allowed_ids):
        raise HTTPException(status_code=403, detail="Você não tem permissão para validar servidores desta secretaria.")

    agora = datetime.now(timezone.utc)
    solic.status = "aprovado"
    solic.analisado_em = agora
    solic.analisado_por_id = validador.id
    solic.comunicado = False
    solic.comunicado_em = None
    session.add(solic)

    # 1. Verifica se o usuário já possui um ingresso ativo emitido (SEC-01: Idempotência e prevenção de duplo resgate)
    stmt_ing_existente = select(Ingresso).where(
        Ingresso.usuario_id == solic.usuario_id,
        Ingresso.deleted_at.is_(None)
    )
    res_ing = await session.execute(stmt_ing_existente)
    ing_existente = res_ing.scalars().first()

    if ing_existente:
        await session.commit()
        return JSONResponse(content={
            "sucesso": True,
            "mensagem": f"Servidor {solic.usuario.nome if solic.usuario else ''} homologado com sucesso! Já possuía ingresso ativo.",
            "ingresso_id": ing_existente.id
        })

    # Emite o Ingresso Oficial apenas se não possuir ingresso ativo
    qr_token = str(uuid.uuid4())
    novo_ingresso = Ingresso(
        usuario_id=solic.usuario_id,
        lote_id=solic.lote_id,
        qr_code_token=qr_token,
        data_resgate=agora
    )
    session.add(novo_ingresso)
    await session.commit()
    await session.refresh(novo_ingresso)

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": f"Servidor {solic.usuario.nome if solic.usuario else ''} homologado com sucesso! Ingresso emitido no sistema e envio do e-mail aguardando liberação do Administrador Geral.",
        "ingresso_id": novo_ingresso.id
    })


@router.post("/aprovar-verificados")
async def aprovar_todos_verificados_api(
    session: AsyncSession = Depends(get_session),
    validador: Usuario = Depends(get_current_validador)
):
    """
    Aprova em lote todas as solicitações pendentes já identificadas pela API oficial.
    Emite os ingressos e envia os e-mails com QR Code automaticamente.
    """
    is_superadmin = "admin_geral" in validador.get_roles_list() or validador.role == UserRole.admin_geral
    allowed_ids = validador.get_secretarias_validador_ids()

    if not is_superadmin and not allowed_ids:
        return JSONResponse(content={
            "sucesso": False,
            "aprovados": 0,
            "mensagem": "Você não possui secretarias atribuídas para validação."
        })

    stmt = (
        select(SolicitacaoValidacao)
        .where(
            SolicitacaoValidacao.status == "pendente_analise",
            SolicitacaoValidacao.identificado_api == True
        )
        .options(
            selectinload(SolicitacaoValidacao.usuario),
            selectinload(SolicitacaoValidacao.lote),
            selectinload(SolicitacaoValidacao.secretaria)
        )
    )
    res = await session.execute(stmt)
    solicitacoes = res.scalars().all()

    if not is_superadmin:
        solicitacoes = [
            s for s in solicitacoes
            if (s.secretaria_id in allowed_ids or (s.usuario and s.usuario.secretaria_id in allowed_ids))
        ]

    if not solicitacoes:
        return JSONResponse(content={
            "sucesso": True,
            "aprovados": 0,
            "mensagem": "Nenhuma solicitação confirmada pela API pendente de homologação."
        })

    agora = datetime.now(timezone.utc)
    aprovados_count = 0
    usuarios_processados = set()

    for solic in solicitacoes:
        if solic.usuario_id in usuarios_processados:
            continue
        usuarios_processados.add(solic.usuario_id)

        solic.status = "aprovado"
        solic.analisado_em = agora
        solic.analisado_por_id = validador.id
        solic.comunicado = False
        solic.comunicado_em = None
        session.add(solic)

        # Checa se o usuário já tem ingresso ativo (SEC-01)
        stmt_ing_chk = select(Ingresso).where(
            Ingresso.usuario_id == solic.usuario_id,
            Ingresso.deleted_at.is_(None)
        )
        res_chk = await session.execute(stmt_ing_chk)
        if not res_chk.scalars().first():
            qr_token = str(uuid.uuid4())
            novo_ingresso = Ingresso(
                usuario_id=solic.usuario_id,
                lote_id=solic.lote_id,
                qr_code_token=qr_token,
                data_resgate=agora
            )
            session.add(novo_ingresso)
        aprovados_count += 1

    await session.commit()
    return JSONResponse(content={
        "sucesso": True,
        "aprovados": aprovados_count,
        "mensagem": f"{aprovados_count} servidor(es) confirmados pela API homologados com sucesso! Ingressos emitidos no sistema e envio dos e-mails aguardando liberação do Administrador Geral."
    })


@router.post("/{solicitacao_id}/rejeitar")
async def rejeitar_solicitacao_validacao(
    solicitacao_id: int,
    body: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
    validador: Usuario = Depends(get_current_validador)
):
    """
    Rejeita a solicitação de validação:
    - Marca solicitação como 'rejeitado'
    - Bloqueia usuário para resgates futuros (não é servidor)
    - Mantém a vaga consumida no lote
    - Dispara e-mail formal de negativa
    """
    stmt = (
        select(SolicitacaoValidacao)
        .where(SolicitacaoValidacao.id == solicitacao_id)
        .with_for_update()
        .options(
            selectinload(SolicitacaoValidacao.usuario),
            selectinload(SolicitacaoValidacao.lote)
        )
    )
    res = await session.execute(stmt)
    solic = res.scalars().first()

    if not solic:
        raise HTTPException(status_code=404, detail="Solicitação de validação não encontrada.")

    if solic.status != "pendente_analise":
        raise HTTPException(status_code=400, detail=f"Esta solicitação já foi finalizada como '{solic.status}'.")

    is_superadmin = "admin_geral" in validador.get_roles_list() or validador.role == UserRole.admin_geral
    allowed_ids = validador.get_secretarias_validador_ids()
    sec_id = solic.secretaria_id or (solic.usuario.secretaria_id if solic.usuario else None)
    if not is_superadmin and (not allowed_ids or sec_id not in allowed_ids):
        raise HTTPException(status_code=403, detail="Você não tem permissão para validar servidores desta secretaria.")

    motivo = body.get("motivo", "Vínculo de servidor público municipal não confirmado pela secretaria.")
    agora = datetime.now(timezone.utc)

    solic.status = "rejeitado"
    solic.motivo_rejeicao = motivo
    solic.analisado_em = agora
    solic.analisado_por_id = validador.id
    solic.comunicado = False
    solic.comunicado_em = None
    session.add(solic)

    # Bloqueia usuário de tentar em outros lotes
    if solic.usuario:
        solic.usuario.bloqueado_resgate = True
        session.add(solic.usuario)

    # Regra de negócio: rejeitar a homologação não libera a vaga retida no lote.
    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": "Solicitação indeferida com sucesso! A vaga permanece consumida no lote e a comunicação por e-mail fica aguardando liberação do Administrador Geral."
    })


@router.post("/{solicitacao_id}/comunicar")
async def comunicar_solicitacao_validacao(
    solicitacao_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_validador)
):
    """
    Liberação manual de comunicação por e-mail pelo Administrador Geral:
    - Se aprovado: envia o Ingresso com QR Code oficial por e-mail.
    - Se rejeitado: envia a justificativa do indeferimento por e-mail.
    - Marca a solicitação como comunicada.
    """
    is_superadmin = "admin_geral" in admin.get_roles_list() or admin.role == UserRole.admin_geral
    if not is_superadmin:
        raise HTTPException(status_code=403, detail="Apenas o Administrador Geral pode liberar o envio de comunicações.")

    stmt = (
        select(SolicitacaoValidacao)
        .where(SolicitacaoValidacao.id == solicitacao_id)
        .options(
            selectinload(SolicitacaoValidacao.usuario),
            selectinload(SolicitacaoValidacao.lote),
            selectinload(SolicitacaoValidacao.secretaria)
        )
    )
    res = await session.execute(stmt)
    solic = res.scalars().first()
    if not solic:
        raise HTTPException(status_code=404, detail="Solicitação de validação não encontrada.")

    if solic.status not in ["aprovado", "rejeitado"]:
        raise HTTPException(status_code=400, detail="Esta solicitação ainda está pendente de homologação.")

    if not solic.usuario or not solic.usuario.email:
        raise HTTPException(status_code=400, detail="O servidor não possui e-mail cadastrado para comunicação.")

    u = solic.usuario
    l = solic.lote
    sec = solic.secretaria or (u.secretaria if u else None)
    cpf_fmt = formatar_cpf(u.cpf)
    agora = datetime.now(timezone.utc)

    if solic.status == "aprovado":
        stmt_ing = select(Ingresso).where(
            Ingresso.usuario_id == solic.usuario_id,
            Ingresso.lote_id == solic.lote_id,
            Ingresso.deleted_at.is_(None)
        ).order_by(desc(Ingresso.id))
        res_ing = await session.execute(stmt_ing)
        ingresso = res_ing.scalars().first()
        if not ingresso:
            raise HTTPException(status_code=404, detail="Ingresso ativo correspondente não localizado para este servidor.")

        enfileirado = await send_ticket_email_async(
            usuario_nome=u.nome,
            usuario_email=u.email,
            ingresso_token=ingresso.qr_code_token,
            lote_nome=l.nome if l else "Lote Oficial",
            secretaria_nome=sec.nome if sec else None,
            setor=u.setor,
            cpf_formatado=cpf_fmt
        )
        msg = f"Ingresso enfileirado para envio ao e-mail {u.email}."
    else:
        enfileirado = await send_validation_rejection_email_async(
            usuario_nome=u.nome,
            usuario_email=u.email,
            lote_nome=l.nome if l else "Lote Oficial",
            motivo=solic.motivo_rejeicao or "Vínculo de servidor público municipal não confirmado pela secretaria."
        )
        msg = f"Notificação de indeferimento enfileirada para o e-mail {u.email}."

    if not enfileirado:
        raise HTTPException(status_code=503, detail="Não foi possível registrar o e-mail na fila. Tente novamente.")

    solic.comunicado = True
    solic.comunicado_em = agora
    session.add(solic)
    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": msg,
        "comunicado": True,
        "comunicado_em": formatar_data_sp(agora)
    })


@router.post("/comunicar-em-lote")
async def comunicar_em_lote_admin(
    tipo_filtro: str = Query("todos", description="todos, aprovados ou rejeitados"),
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_validador)
):
    """
    Dispara em lote as comunicações pendentes para todas as solicitações homologadas.
    Exclusivo para o Administrador Geral.
    """
    is_superadmin = "admin_geral" in admin.get_roles_list() or admin.role == UserRole.admin_geral
    if not is_superadmin:
        raise HTTPException(status_code=403, detail="Apenas o Administrador Geral pode liberar o envio de comunicações.")

    query = (
        select(SolicitacaoValidacao)
        .where(
            SolicitacaoValidacao.comunicado.is_(False),
            SolicitacaoValidacao.status.in_(["aprovado", "rejeitado"])
        )
        .options(
            selectinload(SolicitacaoValidacao.usuario),
            selectinload(SolicitacaoValidacao.lote),
            selectinload(SolicitacaoValidacao.secretaria)
        )
    )

    if tipo_filtro == "aprovados":
        query = query.where(SolicitacaoValidacao.status == "aprovado")
    elif tipo_filtro == "rejeitados":
        query = query.where(SolicitacaoValidacao.status == "rejeitado")

    res = await session.execute(query)
    solicitacoes = res.scalars().all()

    if not solicitacoes:
        return JSONResponse(content={
            "sucesso": True,
            "total": 0,
            "mensagem": "Nenhuma solicitação pendente de comunicação encontrada."
        })

    agora = datetime.now(timezone.utc)
    total_enfileirados = 0
    total_falhas = 0

    for solic in solicitacoes:
        u = solic.usuario
        if not u or not u.email:
            continue

        l = solic.lote
        sec = solic.secretaria or (u.secretaria if u else None)
        cpf_fmt = formatar_cpf(u.cpf)

        if solic.status == "aprovado":
            stmt_ing = select(Ingresso).where(
                Ingresso.usuario_id == solic.usuario_id,
                Ingresso.lote_id == solic.lote_id,
                Ingresso.deleted_at.is_(None)
            ).order_by(desc(Ingresso.id))
            res_ing = await session.execute(stmt_ing)
            ingresso = res_ing.scalars().first()
            if ingresso:
                enfileirado = await send_ticket_email_async(
                    usuario_nome=u.nome,
                    usuario_email=u.email,
                    ingresso_token=ingresso.qr_code_token,
                    lote_nome=l.nome if l else "Lote Oficial",
                    secretaria_nome=sec.nome if sec else None,
                    setor=u.setor,
                    cpf_formatado=cpf_fmt
                )
                if not enfileirado:
                    total_falhas += 1
                    continue
                solic.comunicado = True
                solic.comunicado_em = agora
                session.add(solic)
                total_enfileirados += 1
        elif solic.status == "rejeitado":
            enfileirado = await send_validation_rejection_email_async(
                usuario_nome=u.nome,
                usuario_email=u.email,
                lote_nome=l.nome if l else "Lote Oficial",
                motivo=solic.motivo_rejeicao or "Vínculo de servidor público municipal não confirmado pela secretaria."
            )
            if not enfileirado:
                total_falhas += 1
                continue
            solic.comunicado = True
            solic.comunicado_em = agora
            session.add(solic)
            total_enfileirados += 1

    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "total": total_enfileirados,
        "total_enfileirados": total_enfileirados,
        "falhas": total_falhas,
        "mensagem": f"{total_enfileirados} comunicação(ões) registrada(s) na fila; {total_falhas} falha(s) ao enfileirar."
    })
