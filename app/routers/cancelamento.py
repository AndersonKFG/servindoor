import uuid
import os
import re
import time
import base64
import secrets
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, or_
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.all_models import Usuario, Ingresso, Lote, SolicitacaoCancelamento, SolicitacaoValidacao, LogAcesso
from app.core.deps import get_current_admin
from app.core.security import extrair_ip_cliente, gerar_codigo_2fa_criptografico, formatar_data_sp
from app.services.email_service import (
    send_cancellation_code_email_async,
    send_cancellation_result_email_async
)

router = APIRouter(tags=["Cancelamento de Ingresso"])
logger = logging.getLogger(__name__)

_consultas_rate_limit = {}

def verificar_rate_limit_consulta(ip: str, limite: int = 5, janela_segundos: int = 60) -> bool:
    agora = time.time()
    historico = _consultas_rate_limit.setdefault(ip, [])
    _consultas_rate_limit[ip] = [t for t in historico if agora - t < janela_segundos]
    if len(_consultas_rate_limit[ip]) >= limite:
        return False
    _consultas_rate_limit[ip].append(agora)
    return True


async def contar_envios_codigo_recentes(
    session: AsyncSession,
    usuario_id: int,
    ingresso_id: int,
    agora: datetime
) -> tuple[int, Optional[datetime]]:
    limite = agora - timedelta(hours=1)
    stmt = select(
        func.coalesce(func.sum(SolicitacaoCancelamento.codigo_envios), 0),
        func.max(SolicitacaoCancelamento.codigo_ultimo_envio_em)
    ).where(
        SolicitacaoCancelamento.usuario_id == usuario_id,
        SolicitacaoCancelamento.ingresso_id == ingresso_id,
        SolicitacaoCancelamento.codigo_ultimo_envio_em >= limite
    )
    result = await session.execute(stmt)
    total, ultimo_envio = result.one()
    return int(total or 0), ultimo_envio


UPLOADS_FOTOS_DIR = "app/static/uploads/fotos"
os.makedirs(UPLOADS_FOTOS_DIR, exist_ok=True)


def normalizar_cpf(cpf: str) -> str:
    """Extrai somente os 11 dígitos numéricos do CPF"""
    return "".join(c for c in (cpf or "") if c.isdigit()).zfill(11)


def formatar_cpf(cpf: str) -> str:
    c = normalizar_cpf(cpf)
    if len(c) == 11:
        return f"{c[:3]}.***.***-{c[-2:]}"
    return "000.***.***-00"


from app.core.validators import normalizar_data_nascimento as _core_normalizar_nasc

def normalizar_data_nascimento(data_str: str) -> str:
    """Normaliza a data de nascimento para o padrão YYYY-MM-DD utilizando o validador central."""
    try:
        return _core_normalizar_nasc(data_str) or ""
    except ValueError:
        return (data_str or "").strip()


def mascarar_email(email: str) -> str:
    """Mascara o e-mail para exibição segura, ex: anderson.silva@gmail.com -> an***va@gmail.com"""
    if not email or "@" not in email:
        return "seu e-mail cadastrado"
    user_part, domain_part = email.split("@", 1)
    if len(user_part) <= 2:
        masked_user = user_part[0] + "***"
    else:
        masked_user = user_part[:2] + "***" + user_part[-1]
    return f"{masked_user}@{domain_part}"


# ==============================================================================
# 1. ROTAS PÚBLICAS - FLUXO DO SERVIDOR (MEU INGRESSO)
# ==============================================================================

@router.post("/api/meu-ingresso/consultar")
async def consultar_meu_ingresso(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    Permite ao participante consultar seu ingresso utilizando CPF e Data de Nascimento.
    Retorna o status do ingresso (ativo com token QR Code), status de validação pendente/rejeitada,
    ou cancelado.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Formato de requisição inválido.")

    cpf_raw = body.get("cpf", "")
    nascimento_raw = body.get("data_nascimento", "")

    cpf_limpo = normalizar_cpf(cpf_raw)
    nascimento_norm = normalizar_data_nascimento(nascimento_raw)

    if not cpf_limpo or len(cpf_limpo) != 11:
        raise HTTPException(status_code=400, detail="CPF inválido. Digite os 11 dígitos do CPF.")

    if not nascimento_norm:
        raise HTTPException(status_code=400, detail="A data de nascimento é obrigatória.")

    # SEC-06: Rate limiting estrito para impedir ataques de enumeração e brute-force
    client_ip = extrair_ip_cliente(request)
    if not verificar_rate_limit_consulta(client_ip, limite=5, janela_segundos=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas de consulta. Aguarde 1 minuto."
        )

    # 1. Localiza o usuário no banco de dados
    stmt_user = (
        select(Usuario)
        .where(
            Usuario.cpf == cpf_limpo,
            Usuario.deleted_at.is_(None),
            Usuario.ativo == True
        )
        .options(selectinload(Usuario.secretaria))
    )
    res_user = await session.execute(stmt_user)
    usuario = res_user.scalars().first()

    if not usuario:
        raise HTTPException(
            status_code=404,
            detail="Nenhum cadastro encontrado para o CPF informado."
        )

    # 2. Confere data de nascimento
    user_nascimento_norm = normalizar_data_nascimento(usuario.data_nascimento or "")
    if not user_nascimento_norm or user_nascimento_norm != nascimento_norm:
        raise HTTPException(
            status_code=400,
            detail="CPF ou Data de Nascimento não conferem com o cadastro oficial."
        )

    sec_nome = usuario.secretaria.nome if usuario.secretaria else "Não informada"

    # 3. Busca ingresso ativo (não cancelado)
    stmt_ing = (
        select(Ingresso)
        .where(
            Ingresso.usuario_id == usuario.id,
            Ingresso.deleted_at.is_(None)
        )
        .options(selectinload(Ingresso.lote))
        .order_by(Ingresso.id.desc())
    )
    res_ing = await session.execute(stmt_ing)
    ingresso = res_ing.scalars().first()

    if ingresso:
        # Verifica se o participante já realizou check-in de entrada na portaria
        stmt_checkin = (
            select(LogAcesso)
            .where(
                LogAcesso.usuario_id == usuario.id,
                LogAcesso.tipo == "entrada"
            )
        )
        res_checkin = await session.execute(stmt_checkin)
        presente = res_checkin.scalars().first() is not None

        return JSONResponse(
            status_code=200,
            content={
                "sucesso": True,
                "status": "ingresso_ativo",
                "usuario": {
                    "id": usuario.id,
                    "nome": usuario.nome,
                    "cpf": usuario.cpf,
                    "cpf_formatado": formatar_cpf(usuario.cpf),
                    "email": mascarar_email(usuario.email),
                    "email_mascarado": mascarar_email(usuario.email),
                    "secretaria_nome": sec_nome,
                    "setor": usuario.setor or "",
                    "vinculo": usuario.vinculo or "Servidor",
                    "foto_rosto_url": usuario.foto_rosto_url
                },
                "ingresso": {
                    "id": ingresso.id,
                    "qr_code_token": ingresso.qr_code_token,
                    "lote_nome": ingresso.lote.nome if ingresso.lote else "Lote Oficial",
                    "presente": presente,
                    "data_resgate": formatar_data_sp(ingresso.data_resgate) if ingresso.data_resgate else "-"
                }
            }
        )

    # 4. Se não tem ingresso ativo, verifica se tem solicitação de validação
    stmt_val = (
        select(SolicitacaoValidacao)
        .where(SolicitacaoValidacao.usuario_id == usuario.id)
        .order_by(SolicitacaoValidacao.id.desc())
        .options(selectinload(SolicitacaoValidacao.lote))
    )
    res_val = await session.execute(stmt_val)
    solic_val = res_val.scalars().first()

    if solic_val:
        if solic_val.status == "pendente_analise":
            return JSONResponse(
                status_code=200,
                content={
                    "sucesso": True,
                    "status": "validacao_pendente",
                    "protocolo": f"VAL-{solic_val.id:06d}",
                    "mensagem": "Sua solicitação de ingresso foi recebida com sucesso e está aguardando homologação cadastral pela comissão organizadora.",
                    "previsao": "Prazo de retorno de até 3 dias úteis. Sua vaga no lote está pré-reservada.",
                    "usuario": {
                        "nome": usuario.nome,
                        "cpf_formatado": formatar_cpf(usuario.cpf),
                        "secretaria_nome": sec_nome
                    }
                }
            )
        elif solic_val.status == "rejeitado":
            return JSONResponse(
                status_code=200,
                content={
                    "sucesso": True,
                    "status": "validacao_rejeitada",
                    "protocolo": f"VAL-{solic_val.id:06d}",
                    "motivo": solic_val.motivo_rejeicao or "Vínculo funcional não confirmado junto aos quadros do município.",
                    "mensagem": "Sua solicitação de validação foi indeferida pela organização."
                }
            )

    # 5. Verifica se teve ingresso cancelado
    stmt_cancel = (
        select(Ingresso)
        .where(
            Ingresso.usuario_id == usuario.id,
            Ingresso.deleted_at.is_not(None)
        )
        .order_by(Ingresso.id.desc())
    )
    res_cancel = await session.execute(stmt_cancel)
    ing_cancelado = res_cancel.scalars().first()
    if ing_cancelado:
        return JSONResponse(
            status_code=200,
            content={
                "sucesso": True,
                "status": "ingresso_cancelado",
                "mensagem": "Seu ingresso para a festa foi cancelado anteriormente."
            }
        )

    raise HTTPException(
        status_code=404,
        detail="Nenhum ingresso emitido ou solicitação ativa encontrada para este CPF."
    )


@router.post("/api/meu-ingresso/iniciar")
async def iniciar_cancelamento(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    Etapa 1: Valida CPF e Data de Nascimento obrigatórios.
    Localiza o ingresso ativo do servidor, gera o código de segurança 2FA de 6 dígitos
    e dispara o e-mail de confirmação.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Formato de requisição inválido.")

    cpf_raw = body.get("cpf", "")
    nascimento_raw = body.get("data_nascimento", "")

    cpf_limpo = normalizar_cpf(cpf_raw)
    nascimento_norm = normalizar_data_nascimento(nascimento_raw)

    if not cpf_limpo or len(cpf_limpo) != 11:
        raise HTTPException(status_code=400, detail="CPF inválido. Digite os 11 dígitos do CPF.")

    if not nascimento_norm:
        raise HTTPException(status_code=400, detail="A data de nascimento é obrigatória.")

    # 1. Localiza o usuário no banco de dados
    stmt_user = (
        select(Usuario)
        .where(
            Usuario.cpf == cpf_limpo,
            Usuario.deleted_at.is_(None),
            Usuario.ativo == True
        )
        .options(selectinload(Usuario.secretaria))
    )
    res_user = await session.execute(stmt_user)
    usuario = res_user.scalars().first()

    if not usuario:
        raise HTTPException(
            status_code=404,
            detail="Nenhum participante encontrado com o CPF informado."
        )

    # 2. Confere obrigatoriamente a data de nascimento
    user_nascimento_norm = normalizar_data_nascimento(usuario.data_nascimento or "")
    if not user_nascimento_norm or user_nascimento_norm != nascimento_norm:
        raise HTTPException(
            status_code=400,
            detail="CPF ou Data de Nascimento não conferem com o cadastro oficial."
        )

    # 3. Verifica se o servidor possui ingresso ativo (não cancelado)
    stmt_ing = (
        select(Ingresso)
        .where(
            Ingresso.usuario_id == usuario.id,
            Ingresso.deleted_at.is_(None)
        )
        .options(selectinload(Ingresso.lote))
        .order_by(Ingresso.id.desc())
    )
    res_ing = await session.execute(stmt_ing)
    ingresso = res_ing.scalars().first()

    if not ingresso:
        raise HTTPException(
            status_code=404,
            detail="Você não possui nenhum ingresso ativo no momento para cancelar."
        )

    # 3.1 Verifica se o participante já entrou no evento (SEC-19)
    stmt_acesso = (
        select(LogAcesso)
        .where(
            LogAcesso.usuario_id == usuario.id,
            LogAcesso.tipo == "entrada"
        )
        .limit(1)
    )
    res_acesso = await session.execute(stmt_acesso)
    if res_acesso.scalars().first():
        raise HTTPException(
            status_code=400,
            detail="Cancelamento não permitido: este participante já efetuou check-in de entrada no evento."
        )

    # 4. Verifica e-mail do participante
    if not usuario.email or "@" not in usuario.email:
        raise HTTPException(
            status_code=400,
            detail="Não há um e-mail válido registrado em seu cadastro para envio do código de segurança. Por favor, procure o suporte presencial ou a organização."
        )

    # 5. Verifica se já existe solicitação pendente de análise para este ingresso
    stmt_solic = (
        select(SolicitacaoCancelamento)
        .where(
            SolicitacaoCancelamento.ingresso_id == ingresso.id,
            SolicitacaoCancelamento.status == "pendente_analise"
        )
    )
    res_solic = await session.execute(stmt_solic)
    solic_pendente = res_solic.scalars().first()

    if solic_pendente:
        return JSONResponse(
            status_code=200,
            content={
                "sucesso": True,
                "ja_em_analise": True,
                "token": solic_pendente.token,
                "status": "pendente_analise",
                "protocolo": f"CAN-{solic_pendente.id:06d}",
                "mensagem": "Você já possui uma solicitação de cancelamento em análise pela organização."
            }
        )

    # Retoma a etapa em andamento sem gerar novos e-mails ao voltar à tela.
    stmt_fluxo_ativo = (
        select(SolicitacaoCancelamento)
        .where(
            SolicitacaoCancelamento.ingresso_id == ingresso.id,
            SolicitacaoCancelamento.status.in_(["pendente_codigo", "pendente_foto"])
        )
        .order_by(SolicitacaoCancelamento.id.desc())
        .with_for_update()
    )
    res_fluxo = await session.execute(stmt_fluxo_ativo)
    fluxo_ativo = res_fluxo.scalars().first()
    if fluxo_ativo:
        agora = datetime.now(timezone.utc)
        ultimo_envio = fluxo_ativo.codigo_ultimo_envio_em or fluxo_ativo.criado_em
        segundos_reenvio = max(0, int((ultimo_envio + timedelta(seconds=60) - agora).total_seconds()))
        codigo_expirado = (
            fluxo_ativo.status == "pendente_codigo"
            and agora > fluxo_ativo.codigo_expira_em
        )
        logger.info("Cancelamento retomado sem novo envio; solicitação id=%s status=%s",
                    fluxo_ativo.id, fluxo_ativo.status)
        return JSONResponse(
            status_code=200,
            content={
                "sucesso": True,
                "token": fluxo_ativo.token,
                "status": fluxo_ativo.status,
                "retomado": True,
                "codigo_expirado": codigo_expirado,
                "reenviar_em_segundos": segundos_reenvio,
                "email_mascarado": mascarar_email(usuario.email),
                "protocolo": f"CAN-{fluxo_ativo.id:06d}",
                "mensagem": "Etapa de cancelamento retomada. Nenhum novo e-mail foi enviado."
            }
        )

    total_envios, ultimo_envio = await contar_envios_codigo_recentes(
        session, usuario.id, ingresso.id, datetime.now(timezone.utc)
    )
    if total_envios >= 3:
        aguardar = max(60, int((ultimo_envio + timedelta(hours=1) - datetime.now(timezone.utc)).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="Limite de códigos por e-mail atingido. Aguarde antes de iniciar outra tentativa.",
            headers={"Retry-After": str(aguardar)}
        )

    # 6. Gera código de 6 dígitos criptograficamente seguro e token de sessão (SEC-12)
    codigo_verificacao = gerar_codigo_2fa_criptografico(6)
    token_sessao = secrets.token_hex(24)
    agora = datetime.now(timezone.utc)
    expira_em = agora + timedelta(minutes=15)
    ip_origem = extrair_ip_cliente(request)

    # Reutiliza ou cria novo registro de solicitação
    motivo_iniciar = (body.get("motivo") or "").strip() or "Desistência voluntária pelo servidor."
    solicitacao = SolicitacaoCancelamento(
        token=token_sessao,
        usuario_id=usuario.id,
        ingresso_id=ingresso.id,
        codigo_verificacao=codigo_verificacao,
        codigo_expira_em=expira_em,
        codigo_validado=False,
        codigo_tentativas=0,
        codigo_envios=1,
        codigo_ultimo_envio_em=agora,
        status="pendente_codigo",
        motivo=motivo_iniciar,
        ip_origem=ip_origem
    )
    session.add(solicitacao)
    # A solicitação e o envio persistido devem ser confirmados juntos.
    enfileirado = await send_cancellation_code_email_async(
        usuario_nome=usuario.nome,
        usuario_email=usuario.email,
        codigo=codigo_verificacao,
        session=session,
    )
    if not enfileirado:
        await session.rollback()
        raise HTTPException(status_code=503, detail="Não foi possível solicitar o envio do código. Tente novamente.")
    await session.commit()
    await session.refresh(solicitacao)
    logger.info("Código de cancelamento solicitado; solicitação id=%s", solicitacao.id)

    return JSONResponse(
        status_code=200,
        content={
            "sucesso": True,
            "token": token_sessao,
            "status": "pendente_codigo",
            "email_mascarado": mascarar_email(usuario.email),
            "usuario_nome": usuario.nome,
            "lote_nome": ingresso.lote.nome if ingresso.lote else "Lote Oficial",
            "expira_em_minutos": 15,
            "mensagem": f"Envio do código solicitado para {mascarar_email(usuario.email)}."
        }
    )


@router.post("/api/meu-ingresso/reenviar-codigo")
async def reenviar_codigo(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Reenvia um novo código criptograficamente seguro de 6 dígitos para o participante (SEC-12)"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Formato de requisição inválido.")

    token = body.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Token de sessão não fornecido.")

    stmt = (
        select(SolicitacaoCancelamento)
        .where(SolicitacaoCancelamento.token == token)
        .with_for_update()
        .options(selectinload(SolicitacaoCancelamento.usuario))
    )
    res = await session.execute(stmt)
    solic = res.scalars().first()

    if not solic or solic.status != "pendente_codigo":
        raise HTTPException(status_code=404, detail="Sessão de cancelamento não encontrada ou já expirada.")

    agora = datetime.now(timezone.utc)
    ultimo_envio_sessao = solic.codigo_ultimo_envio_em or solic.criado_em
    if agora - ultimo_envio_sessao >= timedelta(hours=1):
        solic.codigo_envios = 0

    segundos_ate_reenvio = int((ultimo_envio_sessao + timedelta(seconds=60) - agora).total_seconds())
    if segundos_ate_reenvio > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Aguarde {segundos_ate_reenvio} segundos antes de solicitar outro código.",
            headers={"Retry-After": str(segundos_ate_reenvio)}
        )

    total_envios, ultimo_envio = await contar_envios_codigo_recentes(
        session, solic.usuario_id, solic.ingresso_id, agora
    )
    if total_envios >= 3:
        aguardar = max(60, int((ultimo_envio + timedelta(hours=1) - agora).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="Limite de 3 códigos por hora atingido. Aguarde antes de solicitar outro.",
            headers={"Retry-After": str(aguardar)}
        )

    if not solic.usuario or not solic.usuario.email or "@" not in solic.usuario.email:
        raise HTTPException(status_code=400, detail="Não há um e-mail válido cadastrado para enviar o código.")

    novo_codigo = gerar_codigo_2fa_criptografico(6)
    solic.codigo_verificacao = novo_codigo
    solic.codigo_expira_em = agora + timedelta(minutes=15)
    solic.codigo_tentativas = 0
    solic.codigo_validado = False
    solic.status = "pendente_codigo"
    solic.codigo_envios = min(solic.codigo_envios, 3) + 1
    solic.codigo_ultimo_envio_em = agora

    session.add(solic)
    enfileirado = await send_cancellation_code_email_async(
        usuario_nome=solic.usuario.nome,
        usuario_email=solic.usuario.email,
        codigo=novo_codigo,
        session=session,
    )
    if not enfileirado:
        await session.rollback()
        raise HTTPException(status_code=503, detail="Não foi possível solicitar o reenvio do código. Tente novamente.")
    await session.commit()
    logger.info("Reenvio de código de cancelamento solicitado; solicitação id=%s", solic.id)

    return JSONResponse(
        status_code=200,
        content={
            "sucesso": True,
            "mensagem": f"Envio de novo código solicitado para {mascarar_email(solic.usuario.email)}."
        }
    )


@router.post("/api/meu-ingresso/validar-codigo")
async def validar_codigo(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    Etapa 2: Confere se o código digitado de 6 dígitos é igual ao gerado (tempo constante) e se não expirou.
    Apenas após validação com sucesso, libera a etapa 3 (captura de foto ao vivo).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Formato de requisição inválido.")

    token = body.get("token")
    codigo_digitado = str(body.get("codigo", "")).strip()

    if not token or not codigo_digitado:
        raise HTTPException(status_code=400, detail="Token e código de confirmação são obrigatórios.")

    stmt = select(SolicitacaoCancelamento).where(SolicitacaoCancelamento.token == token)
    res = await session.execute(stmt)
    solic = res.scalars().first()

    if not solic:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada. Reinicie o processo.")

    if solic.codigo_tentativas >= 6:
        raise HTTPException(
            status_code=429,
            detail="Número máximo de tentativas excedido por segurança. Solicite o reenvio de um novo código."
        )

    if solic.status != "pendente_codigo":
        raise HTTPException(status_code=400, detail="Esta etapa de confirmação já foi concluída ou não está mais ativa.")

    if datetime.now(timezone.utc) > solic.codigo_expira_em:
        raise HTTPException(
            status_code=400,
            detail="Código expirado (limite de 15 minutos). Por favor, clique em 'Reenviar Código'."
        )

    # SEC-12: Comparação de tempo constante contra ataques de timing
    if not secrets.compare_digest(solic.codigo_verificacao, codigo_digitado):
        solic.codigo_tentativas += 1
        session.add(solic)
        await session.commit()
        tentativas_restantes = max(0, 6 - solic.codigo_tentativas)
        raise HTTPException(
            status_code=400,
            detail=f"Código de confirmação incorreto. Verifique sua caixa de entrada e tente novamente ({tentativas_restantes} tentativas restantes)."
        )

    # Código confirmado com sucesso!
    solic.codigo_validado = True
    solic.status = "pendente_foto"
    session.add(solic)
    await session.commit()

    return JSONResponse(
        status_code=200,
        content={
            "sucesso": True,
            "status": "pendente_foto",
            "mensagem": "Código confirmado com sucesso! Prossiga agora para a captura da sua foto ao vivo."
        }
    )


@router.post("/api/meu-ingresso/enviar-foto")
@router.post("/api/meu-ingresso/concluir")
async def enviar_foto_ao_vivo(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    Etapa 3: Recebe a foto facial capturada ao vivo pela webcam do participante.
    Salva a imagem em disco e coloca o cancelamento em status 'pendente_analise' para aprovação do admin.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Formato de requisição inválido.")

    token = body.get("token")
    foto_base64 = body.get("foto_ao_vivo") or body.get("foto_base64") or ""

    if not token or not foto_base64:
        raise HTTPException(status_code=400, detail="Token e foto ao vivo são obrigatórios.")

    stmt = (
        select(SolicitacaoCancelamento)
        .where(SolicitacaoCancelamento.token == token)
        .options(selectinload(SolicitacaoCancelamento.usuario))
    )
    res = await session.execute(stmt)
    solic = res.scalars().first()

    if not solic:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")

    if not solic.codigo_validado:
        raise HTTPException(status_code=403, detail="O código de confirmação de e-mail ainda não foi validado.")

    # Converte e salva a imagem em disco
    try:
        if "," in foto_base64:
            header, encoded = foto_base64.split(",", 1)
        else:
            encoded = foto_base64

        img_bytes = base64.b64decode(encoded)
        if len(img_bytes) < 1000:
            raise ValueError("Foto corrompida ou vazia.")

        cpf_user = solic.usuario.cpf if solic.usuario else "semcpf"
        filename = f"cancelamento_{uuid.uuid4().hex}.jpg"
        filepath = os.path.join(UPLOADS_FOTOS_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(img_bytes)

        motivo_envio = (body.get("motivo") or "").strip()
        if motivo_envio:
            solic.motivo = motivo_envio
        elif not solic.motivo:
            solic.motivo = "Desist?ncia volunt?ria pelo servidor."

        solic.foto_ao_vivo_url = f"/static/uploads/fotos/{filename}"
        solic.status = "pendente_analise"
        session.add(solic)
        await session.commit()
        await session.refresh(solic)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao processar imagem capturada: {str(e)}")

    protocolo = f"CAN-{solic.id:06d}"
    return JSONResponse(
        status_code=200,
        content={
            "sucesso": True,
            "status": "pendente_analise",
            "protocolo": protocolo,
            "mensagem": "Foto ao vivo enviada com sucesso! Sua solicitação foi encaminhada para a análise facial da organização."
        }
    )


@router.get("/api/meu-ingresso/status")
async def consultar_status_cancelamento(
    token: str,
    session: AsyncSession = Depends(get_session)
):
    """Permite ao participante checar o andamento de sua solicitação"""
    if not token:
        raise HTTPException(status_code=400, detail="Token é obrigatório.")

    stmt = (
        select(SolicitacaoCancelamento)
        .where(SolicitacaoCancelamento.token == token)
        .options(
            selectinload(SolicitacaoCancelamento.usuario),
            selectinload(SolicitacaoCancelamento.ingresso)
        )
    )
    res = await session.execute(stmt)
    solic = res.scalars().first()

    if not solic:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")

    return JSONResponse(
        status_code=200,
        content={
            "sucesso": True,
            "protocolo": f"CAN-{solic.id:06d}",
            "status": solic.status,
            "motivo_rejeicao": solic.motivo_rejeicao,
            "criado_em": formatar_data_sp(solic.criado_em),
            "analisado_em": formatar_data_sp(solic.analisado_em)
        }
    )


# ==============================================================================
# 2. ROTAS ADMINISTRATIVAS - TELA DE APROVAÇÃO E COMPARAÇÃO FACIAL
# ACESSÍVEL POR QUALQUER NÍVEL DE ADMINISTRADOR (admin e admin_geral)
# ==============================================================================

@router.get("/api/admin/cancelamentos")
async def listar_solicitacoes_cancelamento(
    status_filtro: Optional[str] = None,
    busca: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Lista as solicitações de cancelamento para análise visual comparativa da organização.
    Retorna os KPIs gerais e a lista com fotos lado a lado.
    """
    stmt = (
        select(SolicitacaoCancelamento)
        .options(
            selectinload(SolicitacaoCancelamento.usuario).selectinload(Usuario.secretaria),
            selectinload(SolicitacaoCancelamento.ingresso).selectinload(Ingresso.lote),
            selectinload(SolicitacaoCancelamento.analisado_por)
        )
        .order_by(
            # Pendentes sempre aparecem no topo
            SolicitacaoCancelamento.status == "pendente_analise",
            SolicitacaoCancelamento.id.desc()
        )
    )

    res = await session.execute(stmt)
    todas_solicitacoes = res.scalars().all()

    # Cálculo dos KPIs em memória
    total_geral = len(todas_solicitacoes)
    total_pendentes = sum(1 for s in todas_solicitacoes if s.status == "pendente_analise")
    total_aprovados = sum(1 for s in todas_solicitacoes if s.status == "aprovado")
    total_rejeitados = sum(1 for s in todas_solicitacoes if s.status == "rejeitado")

    lista_formatada = []
    for s in todas_solicitacoes:
        # Filtro de Status
        if status_filtro and status_filtro != "todos":
            if s.status != status_filtro:
                continue

        usr = s.usuario
        ing = s.ingresso
        lote = ing.lote if ing else None
        sec = usr.secretaria if usr else None

        # Filtro de Busca (Nome ou CPF)
        if busca and busca.strip():
            b = busca.strip().lower()
            nome_ok = usr and b in usr.nome.lower()
            cpf_ok = usr and b in usr.cpf
            protocolo_ok = f"can-{s.id:06d}".lower() in b or str(s.id) in b
            if not (nome_ok or cpf_ok or protocolo_ok):
                continue

        lista_formatada.append({
            "id": s.id,
            "protocolo": f"CAN-{s.id:06d}",
            "status": s.status,
            "criado_em": formatar_data_sp(s.criado_em) if s.criado_em else "-",
            "analisado_em": formatar_data_sp(s.analisado_em),
            "motivo": s.motivo,
            "motivo_rejeicao": s.motivo_rejeicao,
            "analisado_por_nome": s.analisado_por.nome if s.analisado_por else None,
            "foto_ao_vivo_url": s.foto_ao_vivo_url,
            "ip_origem": s.ip_origem,
            "usuario": {
                "id": usr.id if usr else None,
                "nome": usr.nome if usr else "Desconhecido",
                "cpf": usr.cpf if usr else "",
                "cpf_formatado": formatar_cpf(usr.cpf) if usr else "",
                "email": usr.email if usr else "",
                "telefone": usr.telefone if usr else "",
                "setor": usr.setor if usr else "",
                "data_nascimento": usr.data_nascimento if usr else "",
                "secretaria_nome": sec.nome if sec else "Não informada",
                "foto_original_url": usr.foto_rosto_url if usr else None
            },
            "ingresso": {
                "id": ing.id if ing else None,
                "lote_nome": lote.nome if lote else "Lote",
                "qr_code_token": ing.qr_code_token if ing else "",
                "data_resgate": formatar_data_sp(ing.data_resgate) if ing and ing.data_resgate else "-",
                "deleted_at": formatar_data_sp(ing.deleted_at) if ing else None
            }
        })

    return JSONResponse(
        status_code=200,
        content={
            "sucesso": True,
            "kpis": {
                "total_pendentes": total_pendentes,
                "total_aprovados": total_aprovados,
                "total_rejeitados": total_rejeitados,
                "total_geral": total_geral
            },
            "solicitacoes": lista_formatada
        }
    )


@router.post("/api/admin/cancelamentos/{solicitacao_id}/aprovar")
async def aprovar_cancelamento(
    solicitacao_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Aprova o cancelamento do ingresso após conferência facial positiva pelo administrador.
    Cancela automaticamente o ingresso (soft-delete), preserva a ocupação do lote,
    atualiza o status da solicitação e envia o e-mail de confirmação ao servidor.
    """
    stmt = (
        select(SolicitacaoCancelamento)
        .where(SolicitacaoCancelamento.id == solicitacao_id)
        .with_for_update()
        .options(
            selectinload(SolicitacaoCancelamento.usuario),
            selectinload(SolicitacaoCancelamento.ingresso).selectinload(Ingresso.lote)
        )
    )
    res = await session.execute(stmt)
    solic = res.scalars().first()

    if not solic:
        raise HTTPException(status_code=404, detail="Solicitação de cancelamento não encontrada.")

    if solic.status != "pendente_analise":
        if solic.status in ["aprovado", "rejeitado"]:
            raise HTTPException(
                status_code=400,
                detail=f"Esta solicitação já foi finalizada anteriormente com o status: {solic.status}."
            )
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível aprovar cancelamento: a solicitação ainda aguarda confirmação do participante (status atual: {solic.status})."
        )

    # SEC-19: Bloqueia aprovação se o participante já entrou no evento
    if solic.usuario_id:
        stmt_check_ent = (
            select(LogAcesso)
            .where(
                LogAcesso.usuario_id == solic.usuario_id,
                LogAcesso.tipo == "entrada"
            )
            .limit(1)
        )
        res_check_ent = await session.execute(stmt_check_ent)
        if res_check_ent.scalars().first():
            raise HTTPException(
                status_code=400,
                detail="Não é possível aprovar cancelamento: participante já efetuou check-in de entrada no evento."
            )

    ingresso = solic.ingresso
    if not ingresso:
        raise HTTPException(status_code=404, detail="Ingresso associado não encontrado.")

    agora = datetime.now(timezone.utc)

    # 1. Soft-delete do ingresso se ainda estiver ativo
    if ingresso.deleted_at is None:
        ingresso.deleted_at = agora
        session.add(ingresso)

        # A cota já consumida permanece ocupada; cancelamentos não reabrem lotes.

    # 3. Atualiza os dados da solicitação
    solic.status = "aprovado"
    solic.analisado_por_id = admin.id
    solic.analisado_em = agora
    session.add(solic)

    # Bloqueia compulsoriamente o participante para quaisquer novos resgates
    if solic.usuario:
        solic.usuario.bloqueado_resgate = True
        session.add(solic.usuario)

    await session.commit()

    # 4. Dispara e-mail oficial comunicando o cancelamento
    if solic.usuario and solic.usuario.email:
        asyncio.create_task(
            send_cancellation_result_email_async(
                usuario_nome=solic.usuario.nome,
                usuario_email=solic.usuario.email,
                aprovado=True
            )
        )

    return JSONResponse(
        status_code=200,
        content={
            "sucesso": True,
            "mensagem": "Cancelamento aprovado com sucesso! O ingresso foi cancelado e a ocupação do lote foi mantida."
        }
    )


@router.post("/api/admin/cancelamentos/{solicitacao_id}/rejeitar")
async def rejeitar_cancelamento(
    solicitacao_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin)
):
    """
    Rejeita a solicitação de cancelamento caso as fotos não confiram ou haja inconsistência.
    Mantém o ingresso ativo e notifica o servidor com a justificativa.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        motivo = "A foto ao vivo enviada não conferiu com a foto de identificação cadastrada no sistema."

    stmt = (
        select(SolicitacaoCancelamento)
        .where(SolicitacaoCancelamento.id == solicitacao_id)
        .options(
            selectinload(SolicitacaoCancelamento.usuario),
            selectinload(SolicitacaoCancelamento.ingresso)
        )
    )
    res = await session.execute(stmt)
    solic = res.scalars().first()

    if not solic:
        raise HTTPException(status_code=404, detail="Solicitação de cancelamento não encontrada.")

    if solic.status != "pendente_analise":
        raise HTTPException(
            status_code=400,
            detail=f"Esta solicitação já foi processada anteriormente com o status: {solic.status}."
        )

    agora = datetime.now(timezone.utc)
    solic.status = "rejeitado"
    solic.motivo_rejeicao = motivo
    solic.analisado_por_id = admin.id
    solic.analisado_em = agora
    session.add(solic)

    await session.commit()

    # Dispara e-mail de aviso de rejeição
    if solic.usuario and solic.usuario.email:
        asyncio.create_task(
            send_cancellation_result_email_async(
                usuario_nome=solic.usuario.nome,
                usuario_email=solic.usuario.email,
                aprovado=False,
                motivo=motivo
            )
        )

    return JSONResponse(
        status_code=200,
        content={
            "sucesso": True,
            "mensagem": "Solicitação rejeitada com sucesso. O ingresso do servidor permanece ativo."
        }
    )


@router.get("/api/meu-ingresso/download-imagem/{token}")
async def download_ingresso_imagem(token: str, session: AsyncSession = Depends(get_session)):
    """Permite ao participante visualizar e baixar o ingresso oficial 9:16 de alta resolução"""
    from fastapi.responses import Response
    from app.services.ticket_generator import generate_ticket_png_bytes

    token_limpo = (token or "").strip()
    if not token_limpo:
        raise HTTPException(status_code=400, detail="Token do ingresso obrigatório.")

    stmt = (
        select(Ingresso)
        .where(
            Ingresso.qr_code_token == token_limpo,
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

    ticket_png = generate_ticket_png_bytes(
        nome=usuario.nome,
        cpf=usuario.cpf,
        ingresso_token=ingresso.qr_code_token,
        lote_nome=lote_nome,
        secretaria_nome=sec_nome,
        setor=usuario.setor
    )

    return Response(
        content=ticket_png,
        media_type="image/png",
        headers={
            "Content-Disposition": f"inline; filename=ingresso_servindoor_{token_limpo}.png",
            "Cache-Control": "public, max-age=3600"
        }
    )

@router.get("/api/meu-ingresso/download-pdf/{token}")
@router.get("/api/ingresso/{token}/pdf")
async def download_ingresso_pdf(token: str, session: AsyncSession = Depends(get_session)):
    """Permite baixar ou visualizar o PDF oficial contendo exclusivamente o PNG do ingresso (modelo oficial enviado por e-mail)"""
    from fastapi.responses import Response
    from app.services.ticket_generator import generate_ticket_pdf_bytes, mask_cpf

    token_limpo = (token or "").strip()
    if not token_limpo:
        raise HTTPException(status_code=400, detail="Token do ingresso obrigatório.")

    stmt = (
        select(Ingresso)
        .where(
            Ingresso.qr_code_token == token_limpo,
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
            "Content-Disposition": f"inline; filename=ingresso_servindoor_{token_limpo}.pdf",
            "Cache-Control": "public, max-age=3600"
        }
    )
