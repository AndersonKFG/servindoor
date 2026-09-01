import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status, Body
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, desc
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_staff, get_current_portaria
from app.db.session import get_session
from app.models.all_models import Usuario, Ingresso, LogAcesso, MovimentoTipo, Secretaria

router = APIRouter()
VUE_INDEX_PATH = "app/static/dist/index.html"


def limpar_cpf(cpf_str: str) -> str:
    return "".join(ch for ch in cpf_str if ch.isdigit()).zfill(11)


@router.get("/portaria")
async def portaria_view(
    request: Request,
    current_user: Usuario = Depends(get_current_staff)
):
    if os.path.exists(VUE_INDEX_PATH):
        return FileResponse(VUE_INDEX_PATH)
    return JSONResponse(content={"status": "ok", "user": current_user.nome})


@router.post("/api/portaria/buscar")
async def buscar_participante_portaria(
    identificador: str = Body(..., embed=True),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_staff)
):
    """
    Busca rápida de participante por Token de QR Code OU CPF (11 dígitos).
    Retorna foto, nome completo, CPF sem máscara e status atual (dentro ou fora).
    """
    termo = identificador.strip()
    if not termo:
        raise HTTPException(status_code=400, detail="Identificador não fornecido.")

    usuario = None
    ingresso = None

    # 1. Se parecer com UUID / Token do QR Code
    if len(termo) > 15 or "-" in termo:
        stmt_ing = (
            select(Ingresso)
            .where(Ingresso.qr_code_token == termo, Ingresso.deleted_at.is_(None))
            .options(selectinload(Ingresso.usuario).selectinload(Usuario.secretaria))
        )
        res_ing = await session.execute(stmt_ing)
        ingresso = res_ing.scalars().first()
        if ingresso:
            usuario = ingresso.usuario

    # 2. Se não encontrou por QR Code ou se foi digitado CPF
    if not usuario:
        cpf_limpo = limpar_cpf(termo)
        if len(cpf_limpo) == 11 and cpf_limpo != "00000000000":
            stmt_usr = (
                select(Usuario)
                .where(Usuario.cpf == cpf_limpo, Usuario.deleted_at.is_(None), Usuario.ativo == True)
                .options(selectinload(Usuario.secretaria), selectinload(Usuario.ingressos))
            )
            res_usr = await session.execute(stmt_usr)
            usuario = res_usr.scalars().first()
            if usuario and usuario.ingressos:
                ingresso = usuario.ingressos[0]

    if not usuario:
        return JSONResponse(
            status_code=404,
            content={
                "sucesso": False,
                "mensagem": "Participante não encontrado com este QR Code ou CPF."
            }
        )

    # 3. Verifica se possui ingresso emitido
    if not ingresso:
        stmt_ing_check = select(Ingresso).where(Ingresso.usuario_id == usuario.id, Ingresso.deleted_at.is_(None))
        res_ing_check = await session.execute(stmt_ing_check)
        ingresso = res_ing_check.scalars().first()

    if not ingresso:
        return JSONResponse(
            status_code=400,
            content={
                "sucesso": False,
                "mensagem": f"O servidor {usuario.nome} está cadastrado, mas não possui ingresso emitido para o evento."
            }
        )

    # 4. Busca o último LogAcesso para saber se está DENTRO ou FORA
    stmt_log = (
        select(LogAcesso)
        .where(LogAcesso.usuario_id == usuario.id)
        .order_by(desc(LogAcesso.data_hora))
        .limit(1)
    )
    res_log = await session.execute(stmt_log)
    ultimo_log = res_log.scalars().first()

    status_atual = "fora"
    ultimo_registro_texto = "Nenhum acesso registrado ainda"

    if ultimo_log:
        if ultimo_log.tipo == MovimentoTipo.entrada:
            status_atual = "dentro"
            ultimo_registro_texto = f"Última ENTRADA às {ultimo_log.data_hora.strftime('%H:%M:%S (%d/%m)')}"
        else:
            status_atual = "fora"
            ultimo_registro_texto = f"Última SAÍDA às {ultimo_log.data_hora.strftime('%H:%M:%S (%d/%m)')}"

    secretaria_nome = usuario.secretaria.nome if usuario.secretaria else "Geral"

    return JSONResponse(content={
        "sucesso": True,
        "usuario_id": usuario.id,
        "nome": usuario.nome,
        "cpf": usuario.cpf,
        "foto_url": usuario.foto_rosto_url or usuario.foto_url,
        "secretaria": secretaria_nome,
        "setor": usuario.setor or "Geral",
        "vinculo": usuario.vinculo or "Servidor",
        "status": status_atual,  # "dentro" | "fora"
        "ultimo_registro": ultimo_registro_texto,
        "token_ingresso": ingresso.qr_code_token
    })


@router.post("/api/portaria/alterar-status")
async def alterar_status_portaria(
    usuario_id: int = Body(..., embed=True),
    novo_status: str = Body(..., embed=True),  # "entrada" ou "saida"
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_staff)
):
    """
    Registra nova movimentação (entrada ou saida) para o participante.
    """
    usuario = await session.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    tipo_movimento = MovimentoTipo.entrada if novo_status == "entrada" else MovimentoTipo.saida
    agora = datetime.now()

    novo_log = LogAcesso(
        usuario_id=usuario.id,
        tipo=tipo_movimento,
        data_hora=agora
    )
    session.add(novo_log)
    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "status": "dentro" if tipo_movimento == MovimentoTipo.entrada else "fora",
        "mensagem": f"{'ENTRADA' if tipo_movimento == MovimentoTipo.entrada else 'SAÍDA'} registrada com sucesso!",
        "hora_registro": agora.strftime("%H:%M:%S")
    })


# Endpoint legado para compatibilidade com formulários clássicos
@router.post("/portaria")
async def validar_acesso_legado(
    request: Request,
    token: str = Form(...),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_staff)
):
    return await buscar_participante_portaria(identificador=token, session=session, current_user=current_user)
