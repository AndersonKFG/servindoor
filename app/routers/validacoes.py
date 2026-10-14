import os
import uuid
import asyncio
import re
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, bindparam, case, cast, false, func, literal, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, desc
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.all_models import Usuario, Lote, Ingresso, Secretaria, SolicitacaoValidacao, UserRole
from app.core.deps import get_current_admin_geral, get_current_validador
from app.core.cpf import formatar_cpf, validar_cpf_matematico
from app.core.security import formatar_data_sp
from app.services.email_service import (
    send_ticket_email_async,
    send_validation_rejection_email_async
)

router = APIRouter(prefix="/api/admin/validacoes", tags=["Validação de Servidores"])


class HomologarListaCpfsRequest(BaseModel):
    lista_cpfs: str = Field(min_length=1, max_length=200000)
    confirmar: bool = False


@router.post("/homologar-por-cpfs")
async def homologar_por_lista_cpfs(
    body: HomologarListaCpfsRequest,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin_geral),
):
    """Confere ou homologa apenas pendências da lista; não enfileira e-mails."""
    entradas = [item for item in re.split(r"[\s,;]+", body.lista_cpfs.strip()) if item]
    if not entradas or len(entradas) > 10000:
        raise HTTPException(status_code=400, detail="Informe entre 1 e 10.000 CPFs por lista.")

    cpfs = set()
    invalidos = duplicados = 0
    for entrada in entradas:
        if not re.fullmatch(r"(?:[0-9]{11}|[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2})", entrada):
            invalidos += 1
            continue
        cpf = entrada.replace(".", "").replace("-", "")
        if not validar_cpf_matematico(cpf):
            invalidos += 1
        elif cpf in cpfs:
            duplicados += 1
        else:
            cpfs.add(cpf)
    if not cpfs:
        raise HTTPException(status_code=400, detail="Nenhum CPF válido encontrado. Use 11 dígitos, com ou sem pontuação.")

    # O lock por usuário serializa listas concorrentes, inclusive com pendências em lotes diferentes.
    usuarios_stmt = (
        select(Usuario).where(
            Usuario.cpf.in_(cpfs), Usuario.ativo.is_(True), Usuario.deleted_at.is_(None),
            Usuario.id.in_(select(SolicitacaoValidacao.usuario_id).where(
                SolicitacaoValidacao.status == "pendente_analise"
            )),
        ).order_by(Usuario.id)
    )
    if body.confirmar:
        usuarios_stmt = usuarios_stmt.with_for_update()
    usuarios = (await session.execute(usuarios_stmt)).scalars().all()
    usuarios_por_id = {u.id: u for u in usuarios}
    solicitacoes_stmt = (
        select(SolicitacaoValidacao).where(
            SolicitacaoValidacao.status == "pendente_analise",
            SolicitacaoValidacao.usuario_id.in_(usuarios_por_id),
        ).order_by(SolicitacaoValidacao.id)
    )
    if body.confirmar:
        solicitacoes_stmt = solicitacoes_stmt.with_for_update()
    solicitacoes = (await session.execute(solicitacoes_stmt)).scalars().all()
    ids_encontrados = {s.usuario_id for s in solicitacoes}
    resultado = {
        "sucesso": True,
        "confirmado": body.confirmar,
        "total_informados": len(entradas),
        "cpfs_validos": len(cpfs),
        "cpfs_invalidos": invalidos,
        "cpfs_duplicados": duplicados,
        "cpfs_com_pendencia": len(ids_encontrados),
        "cpfs_sem_pendencia": len(cpfs) - len(ids_encontrados),
        "pendentes_encontrados": len(solicitacoes),
        "aprovados": 0,
        "ingressos_emitidos": 0,
    }
    if not body.confirmar:
        resultado["servidores_a_homologar"] = [
            {
                "usuario_id": usuario.id,
                "nome": usuario.nome,
                "cpf": usuario.cpf,
                "cpf_formatado": formatar_cpf(usuario.cpf),
            }
            for usuario in sorted(
                (usuarios_por_id[identifier] for identifier in ids_encontrados),
                key=lambda usuario: (usuario.nome.casefold(), usuario.cpf),
            )
        ]
        return JSONResponse(content=resultado)

    usuarios_com_ingresso = set((await session.execute(select(Ingresso.usuario_id).where(
        Ingresso.usuario_id.in_(ids_encontrados), Ingresso.deleted_at.is_(None),
    ))).scalars().all())
    agora = datetime.now(timezone.utc)
    for solic in solicitacoes:
        solic.status = "aprovado"
        solic.analisado_em = agora
        solic.analisado_por_id = admin.id
        solic.comunicado = False
        solic.comunicado_em = None
        session.add(solic)
        usuario = usuarios_por_id[solic.usuario_id]
        usuario.validado = True
        session.add(usuario)
        if solic.usuario_id not in usuarios_com_ingresso:
            session.add(Ingresso(
                usuario_id=solic.usuario_id, lote_id=solic.lote_id,
                qr_code_token=str(uuid.uuid4()), data_resgate=agora,
            ))
            usuarios_com_ingresso.add(solic.usuario_id)
            resultado["ingressos_emitidos"] += 1
        resultado["aprovados"] += 1
    await session.commit()
    resultado["mensagem"] = (
        f"{resultado['aprovados']} solicitação(ões) homologada(s); "
        f"{resultado['ingressos_emitidos']} ingresso(s) emitido(s). "
        "O envio por e-mail aguarda liberação pelo Administrador Geral."
    )
    return JSONResponse(content=resultado)


@router.get("")
async def listar_solicitacoes_validacao(
    status_filtro: Optional[str] = "pendente_analise",
    secretaria_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    validador: Usuario = Depends(get_current_validador),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=50),
    busca: str = Query(default="", max_length=200),
):
    """
    Lista solicitações de validação de servidores.
    Validadores com 'secretarias_validador' definidas só têm acesso às suas secretarias atribuídas.
    Administradores (admin e admin_geral) podem consultar todas as secretarias.
    """
    is_superadmin = "admin_geral" in validador.get_roles_list() or validador.role == UserRole.admin_geral
    acesso_global = is_superadmin or validador.has_role("admin")
    allowed_sec_ids = validador.get_secretarias_validador_ids()

    # Permissões são aplicadas no banco antes de contar, filtrar ou paginar.
    secretaria_efetiva = func.coalesce(SolicitacaoValidacao.secretaria_id, Usuario.secretaria_id)
    escopo_stmt = (
        select(
            SolicitacaoValidacao.id, SolicitacaoValidacao.status,
            SolicitacaoValidacao.identificado_api, SolicitacaoValidacao.comunicado,
            secretaria_efetiva.label("secretaria_id"),
            Secretaria.nome.label("secretaria_nome"), Usuario.nome, Usuario.cpf,
        )
        .select_from(SolicitacaoValidacao)
        .outerjoin(Usuario, Usuario.id == SolicitacaoValidacao.usuario_id)
        .outerjoin(Secretaria, Secretaria.id == secretaria_efetiva)
    )
    if not acesso_global:
        escopo_stmt = escopo_stmt.where(or_(
            SolicitacaoValidacao.secretaria_id.in_(allowed_sec_ids),
            Usuario.secretaria_id.in_(allowed_sec_ids),
        ) if allowed_sec_ids else false())
    escopo = escopo_stmt.subquery()

    def contar(condicao):
        return func.coalesce(func.sum(case((condicao, 1), else_=0)), 0)

    kpis = dict((await session.execute(select(
        contar(escopo.c.status == "pendente_analise").label("total_pendentes"),
        contar((escopo.c.status == "pendente_analise") & escopo.c.identificado_api.is_(True)).label("total_confirmados_api"),
        contar(escopo.c.status == "aprovado").label("total_aprovados"),
        contar(escopo.c.status == "rejeitado").label("total_rejeitados"),
        func.count().label("total_geral"),
        contar(escopo.c.status.in_(["aprovado", "rejeitado"]) & escopo.c.comunicado.is_(False)).label("total_comunicacao_pendente"),
        contar(escopo.c.comunicado.is_(True)).label("total_comunicados"),
    ).select_from(escopo))).mappings().one())

    secretarias_disponiveis = [dict(row) for row in (await session.execute(
        select(escopo.c.secretaria_id.label("id"), escopo.c.secretaria_nome.label("nome"))
        .where(escopo.c.secretaria_id.is_not(None)).distinct().order_by(escopo.c.secretaria_nome)
    )).mappings().all()]

    ids_filtrados = select(escopo.c.id)
    if status_filtro == "confirmados_api":
        ids_filtrados = ids_filtrados.where(
            escopo.c.status == "pendente_analise", escopo.c.identificado_api.is_(True)
        )
    elif status_filtro and status_filtro != "todos":
        ids_filtrados = ids_filtrados.where(escopo.c.status == status_filtro)
    if secretaria_id:
        ids_filtrados = ids_filtrados.where(escopo.c.secretaria_id == secretaria_id)
    termo = busca.strip()
    if termo:
        id_texto = cast(escopo.c.id, String)
        # Mesmo protocolo VAL-000001 exibido no card, incluindo buscas parciais.
        protocolo = literal("val-") + case(
            (func.length(id_texto) < 6, func.substr(literal("000000") + id_texto, func.length(id_texto) + 1, 6)),
            else_=id_texto,
        )
        ids_filtrados = ids_filtrados.where(or_(
            escopo.c.nome.icontains(termo, autoescape=True),
            escopo.c.cpf.icontains(termo, autoescape=True),
            escopo.c.secretaria_nome.icontains(termo, autoescape=True),
            protocolo.icontains(termo, autoescape=True),
        ))
    total = (await session.execute(select(func.count()).select_from(ids_filtrados.subquery()))).scalar_one()
    total_pages = max(1, (total + limit - 1) // limit)
    page = min(page, total_pages)
    ids_pagina = ids_filtrados.order_by(
        escopo.c.status == "pendente_analise", desc(escopo.c.id)
    ).offset((page - 1) * limit).limit(limit)
    stmt = (
        select(SolicitacaoValidacao).where(SolicitacaoValidacao.id.in_(ids_pagina))
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
    selecionadas = res.scalars().all()
    estados_externos = {}
    if selecionadas:
        estados_externos = dict((await session.execute(text("""
            SELECT solicitacao_id, status FROM resgate_jobs
            WHERE job_type = 'external_validation'
              AND solicitacao_id IN :ids
        """).bindparams(bindparam("ids", expanding=True)), {"ids": [s.id for s in selecionadas]})).all())
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
        "pagination": {"page": page, "limit": limit, "total": total, "total_pages": total_pages},
        "secretarias_disponiveis": secretarias_disponiveis,
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
    - Aguarda liberação do Administrador Geral para enfileirar o e-mail
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
    Emite os ingressos e aguarda liberação do Administrador Geral para o e-mail.
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
    - Aguarda liberação do Administrador Geral para enfileirar a negativa
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
        .with_for_update()
        .options(
            selectinload(SolicitacaoValidacao.usuario).selectinload(Usuario.secretaria),
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

    if solic.comunicado:
        return JSONResponse(content={
            "sucesso": True,
            "mensagem": "Esta comunicação já foi registrada na fila de e-mails.",
            "comunicado": True,
            "comunicado_em": formatar_data_sp(solic.comunicado_em),
        })

    async with session.begin_nested():
        msg = await _enfileirar_comunicacao_validacao(solic, session)
    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": msg,
        "comunicado": True,
        "comunicado_em": formatar_data_sp(solic.comunicado_em),
    })


async def _enfileirar_comunicacao_validacao(solic: SolicitacaoValidacao, session: AsyncSession) -> str:
    """Fila e liberação são persistidas juntas, sem confirmar entrega pelo SMTP."""
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
            cpf_formatado=cpf_fmt,
            session=session,
        )
        msg = f"Ingresso enfileirado para envio ao e-mail {u.email}."
    else:
        enfileirado = await send_validation_rejection_email_async(
            usuario_nome=u.nome,
            usuario_email=u.email,
            lote_nome=l.nome if l else "Lote Oficial",
            motivo=solic.motivo_rejeicao or "Vínculo de servidor público municipal não confirmado pela secretaria.",
            session=session,
        )
        msg = f"Notificação de indeferimento enfileirada para o e-mail {u.email}."

    if not enfileirado:
        raise HTTPException(status_code=503, detail="Não foi possível registrar o e-mail na fila. Tente novamente.")

    solic.comunicado = True
    solic.comunicado_em = agora
    session.add(solic)
    return msg


@router.post("/comunicar-em-lote")
async def comunicar_em_lote_admin(
    tipo_filtro: str = Query("todos", description="todos, aprovados ou rejeitados"),
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_validador),
    limit: int = Query(default=25, ge=1, le=50),
    after_id: int = Query(default=0, ge=0),
):
    """
    Enfileira uma página de comunicações pendentes, retornando cursor para continuar.
    Exclusivo para o Administrador Geral.
    """
    is_superadmin = "admin_geral" in admin.get_roles_list() or admin.role == UserRole.admin_geral
    if not is_superadmin:
        raise HTTPException(status_code=403, detail="Apenas o Administrador Geral pode liberar o envio de comunicações.")

    if tipo_filtro not in ("todos", "aprovados", "rejeitados"):
        raise HTTPException(status_code=400, detail="Filtro de comunicação inválido.")

    condicoes = [
        SolicitacaoValidacao.comunicado.is_(False),
        SolicitacaoValidacao.status.in_(["aprovado", "rejeitado"]),
    ]
    if tipo_filtro == "aprovados":
        condicoes.append(SolicitacaoValidacao.status == "aprovado")
    elif tipo_filtro == "rejeitados":
        condicoes.append(SolicitacaoValidacao.status == "rejeitado")

    query = (
        select(SolicitacaoValidacao)
        .where(*condicoes, SolicitacaoValidacao.id > after_id)
        .order_by(SolicitacaoValidacao.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .options(
            selectinload(SolicitacaoValidacao.usuario).selectinload(Usuario.secretaria),
            selectinload(SolicitacaoValidacao.lote),
            selectinload(SolicitacaoValidacao.secretaria)
        )
    )

    res = await session.execute(query)
    solicitacoes = res.scalars().all()

    proximo_id = solicitacoes[-1].id if solicitacoes else after_id
    total_enfileirados = 0
    total_falhas = 0
    falhas_por_motivo = {"sem_email": 0, "sem_ingresso": 0, "fila": 0}

    for solic in solicitacoes:
        try:
            async with session.begin_nested():
                await _enfileirar_comunicacao_validacao(solic, session)
            total_enfileirados += 1
        except HTTPException as exc:
            total_falhas += 1
            motivo = {400: "sem_email", 404: "sem_ingresso"}.get(exc.status_code, "fila")
            falhas_por_motivo[motivo] += 1

    tem_mais = (await session.execute(
        select(SolicitacaoValidacao.id)
        .where(*condicoes, SolicitacaoValidacao.id > proximo_id).limit(1)
    )).first() is not None
    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "total": total_enfileirados,
        "total_enfileirados": total_enfileirados,
        "falhas": total_falhas,
        "falhas_por_motivo": falhas_por_motivo,
        "proximo_id": proximo_id,
        "tem_mais": tem_mais,
        "mensagem": f"{total_enfileirados} comunicação(ões) registrada(s) na fila; {total_falhas} falha(s) ao enfileirar."
    })
