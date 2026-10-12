import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status, Body
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, desc
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_staff, get_current_portaria
from app.db.session import get_session
from app.models.all_models import Usuario, Ingresso, LogAcesso, MovimentoTipo, Secretaria
from app.core.security import extrair_ip_cliente
from app.core.cpf import limpar_cpf

router = APIRouter()
VUE_INDEX_PATH = "app/static/dist/index.html"


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
        if ingresso and ingresso.usuario:
            if not ingresso.usuario.ativo or ingresso.usuario.deleted_at is not None:
                return JSONResponse(
                    status_code=403,
                    content={
                        "sucesso": False,
                        "mensagem": f"O cadastro do servidor {ingresso.usuario.nome} foi desativado ou cancelado pela organização."
                    }
                )
            usuario = ingresso.usuario

    # 2. Se não encontrou por QR Code ou se foi digitado CPF
    if not usuario:
        cpf_limpo = limpar_cpf(termo)
        if len(cpf_limpo) == 11 and cpf_limpo != "00000000000":
            stmt_usr = (
                select(Usuario)
                .where(Usuario.cpf == cpf_limpo, Usuario.deleted_at.is_(None), Usuario.ativo == True)
                .options(selectinload(Usuario.secretaria))
            )
            res_usr = await session.execute(stmt_usr)
            usuario = res_usr.scalars().first()
            if usuario:
                # SEC-05: Busca exclusivamente ingresso ATIVO (não cancelado)
                stmt_ing_ativo = (
                    select(Ingresso)
                    .where(Ingresso.usuario_id == usuario.id, Ingresso.deleted_at.is_(None))
                    .order_by(desc(Ingresso.id))
                )
                res_ing_ativo = await session.execute(stmt_ing_ativo)
                ingresso = res_ing_ativo.scalars().first()

    if not usuario:
        return JSONResponse(
            status_code=404,
            content={
                "sucesso": False,
                "mensagem": "Participante não encontrado com este QR Code ou CPF."
            }
        )

    # 3. Verifica se possui ingresso ativo emitido (SEC-05)
    if not ingresso:
        stmt_ing_check = select(Ingresso).where(Ingresso.usuario_id == usuario.id, Ingresso.deleted_at.is_(None))
        res_ing_check = await session.execute(stmt_ing_check)
        ingresso = res_ing_check.scalars().first()

    if not ingresso:
        # Checa se o usuário teve seu ingresso cancelado
        stmt_ing_cancelado = (
            select(Ingresso)
            .where(Ingresso.usuario_id == usuario.id, Ingresso.deleted_at.is_not(None))
            .order_by(desc(Ingresso.id))
        )
        res_cancelado = await session.execute(stmt_ing_cancelado)
        if res_cancelado.scalars().first():
            return JSONResponse(
                status_code=403,
                content={
                    "sucesso": False,
                    "cancelado": True,
                    "mensagem": f"O ingresso do servidor {usuario.nome} foi CANCELADO e não permite entrada no evento."
                }
            )

        return JSONResponse(
            status_code=400,
            content={
                "sucesso": False,
                "cancelado": False,
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
    request: Request,
    usuario_id: int = Body(..., embed=True),
    novo_status: str = Body(..., embed=True),  # "entrada" ou "saida"
    device_id: Optional[str] = Body(None, embed=True),
    metodo_validacao: Optional[str] = Body("manual", embed=True),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_staff)
):
    """
    Registra nova movimentação (entrada ou saida) para o participante com auditoria completa.
    """
    usuario = await session.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    # SEC-09: Valida se o participante possui ingresso ATIVO no evento
    stmt_ing = select(Ingresso).where(
        Ingresso.usuario_id == usuario.id,
        Ingresso.deleted_at.is_(None)
    )
    res_ing = await session.execute(stmt_ing)
    ingresso_ativo = res_ing.scalars().first()
    if not ingresso_ativo:
        raise HTTPException(
            status_code=403,
            detail="Participante não possui ingresso ativo para entrada no evento."
        )

    tipo_movimento = MovimentoTipo.entrada if novo_status == "entrada" else MovimentoTipo.saida
    agora = datetime.now(timezone.utc)

    # SEC-09: Validação de transição de estado na portaria
    stmt_last_log = (
        select(LogAcesso)
        .where(LogAcesso.usuario_id == usuario.id)
        .order_by(desc(LogAcesso.data_hora))
        .limit(1)
    )
    res_last = await session.execute(stmt_last_log)
    last_log = res_last.scalars().first()
    if last_log and last_log.tipo == tipo_movimento:
        status_txt = "dentro" if tipo_movimento == MovimentoTipo.entrada else "fora"
        raise HTTPException(
            status_code=400,
            detail=f"Participante já se encontra registrado como '{status_txt}' no evento."
        )

    client_ip = extrair_ip_cliente(request)

    # SEC-10: Auditoria detalhada em logs_acesso
    novo_log = LogAcesso(
        usuario_id=usuario.id,
        operador_id=current_user.id,
        ingresso_id=ingresso_ativo.id,
        tipo=tipo_movimento,
        data_hora=agora,
        device_id=device_id or request.headers.get("x-device-fingerprint"),
        ip_origem=client_ip,
        metodo_validacao=metodo_validacao or "manual"
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
