"""Solicitação administrativa e troca de foto por um link de uso único."""

import asyncio
import base64
import hashlib
import io
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.deps import get_current_admin
from app.core.validators import validar_email
from app.db.session import get_session
from app.models.all_models import SolicitacaoCorrecaoFoto, Usuario
from app.services.email_service import send_photo_correction_email_async

router = APIRouter()
FOTOS_DIR = Path("app/static/uploads/fotos")
VALIDADE_HORAS = 72


class SolicitarCorrecaoFotoRequest(BaseModel):
    motivo: str = Field(default="", max_length=2000)


class CorrigirFotoRequest(BaseModel):
    foto_base64: str = Field(max_length=6 * 1024 * 1024)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _validar_solicitacao(solicitacao, usuario):
    if not solicitacao or not usuario or usuario.deleted_at or not usuario.ativo:
        raise HTTPException(status_code=404, detail="Link de correção inválido ou indisponível.")
    if solicitacao.status != "pendente":
        raise HTTPException(status_code=410, detail="Este link já foi utilizado ou substituído por uma nova solicitação.")
    expira_em = solicitacao.expira_em
    if expira_em.tzinfo is None:
        expira_em = expira_em.replace(tzinfo=timezone.utc)
    if expira_em <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="O link expirou. Solicite um novo link à organização.")
    if (usuario.email or "").strip().lower() != solicitacao.email_destino:
        raise HTTPException(status_code=410, detail="O e-mail do cadastro mudou. Solicite um novo link à organização.")


async def _buscar_solicitacao(token, session):
    if len(token) != 43:
        raise HTTPException(status_code=404, detail="Link de correção inválido ou indisponível.")
    return (await session.execute(select(SolicitacaoCorrecaoFoto).where(
        SolicitacaoCorrecaoFoto.token_hash == _hash_token(token)
    ))).scalars().first()


@router.post("/api/admin/participantes/{participante_id}/solicitar-correcao-foto")
async def solicitar_correcao_foto(
    participante_id: int,
    dados: SolicitarCorrecaoFotoRequest,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin),
):
    # O mesmo lock serializa reenvios administrativos e trocas de foto.
    usuario = (await session.execute(select(Usuario).where(
        Usuario.id == participante_id, Usuario.deleted_at.is_(None), Usuario.ativo == True
    ).with_for_update())).scalars().first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Participante não encontrado ou inativo.")
    if usuario.has_role("admin", "admin_geral") and not admin.has_role("admin_geral"):
        raise HTTPException(status_code=403, detail="Apenas o Administrador Geral pode solicitar correções a outros administradores.")
    try:
        email = validar_email(usuario.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not email:
        raise HTTPException(status_code=400, detail="Cadastre um e-mail válido para este participante antes de solicitar a correção.")

    pendentes = (await session.execute(select(SolicitacaoCorrecaoFoto).where(
        SolicitacaoCorrecaoFoto.usuario_id == usuario.id,
        SolicitacaoCorrecaoFoto.status == "pendente",
    ))).scalars().all()
    for anterior in pendentes:
        anterior.status = "substituida"
        session.add(anterior)
    token = secrets.token_urlsafe(32)
    solicitacao = SolicitacaoCorrecaoFoto(
        usuario_id=usuario.id, solicitado_por_id=admin.id,
        token_hash=_hash_token(token), email_destino=email,
        motivo=dados.motivo.strip() or None,
        expira_em=datetime.now(timezone.utc) + timedelta(hours=VALIDADE_HORAS),
    )
    session.add(solicitacao)
    # Fragmento evita que o segredo apareça no acesso HTTP da página ou no Referer.
    link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/corrigir-foto#{token}"
    enfileirado = await send_photo_correction_email_async(
        usuario_nome=usuario.nome, usuario_email=email, link=link,
        motivo=solicitacao.motivo, validade_horas=VALIDADE_HORAS, session=session,
    )
    if not enfileirado:
        await session.rollback()
        raise HTTPException(status_code=503, detail="Não foi possível enfileirar o e-mail. Tente novamente.")
    # Solicitação, invalidação dos links anteriores e e-mail são atômicos.
    await session.commit()
    return {"sucesso": True, "enfileirado": True,
            "mensagem": f"Solicitação de correção de foto enfileirada para {email}.",
            "expira_em": solicitacao.expira_em.isoformat()}


@router.get("/api/correcao-foto/{token}")
async def consultar_correcao_foto(
    token: str, response: Response, session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    solicitacao = await _buscar_solicitacao(token, session)
    usuario = await session.get(Usuario, solicitacao.usuario_id) if solicitacao else None
    _validar_solicitacao(solicitacao, usuario)
    return {"nome": usuario.nome, "motivo": solicitacao.motivo,
            "expira_em": solicitacao.expira_em.isoformat()}


def _gravar_foto(foto_base64):
    if not foto_base64.startswith("data:image/jpeg;base64,"):
        raise HTTPException(status_code=400, detail="Envie uma foto JPEG válida.")
    try:
        conteudo = base64.b64decode(foto_base64.split(",", 1)[1], validate=True)
        if len(conteudo) > 4 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="A foto excede o limite de 4 MB.")
        with Image.open(io.BytesIO(conteudo)) as imagem:
            if imagem.format != "JPEG" or imagem.width * imagem.height > 20_000_000:
                raise ValueError("Imagem inválida ou muito grande")
            imagem.verify()
        # Reencoda para descartar metadados e garantir que o JPEG decodifica.
        with Image.open(io.BytesIO(conteudo)) as imagem:
            imagem = imagem.convert("RGB")
            imagem.thumbnail((1600, 1600))
            buffer = io.BytesIO()
            imagem.save(buffer, format="JPEG", quality=90)
            conteudo = buffer.getvalue()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail="Não foi possível ler a foto. Selecione outra imagem.")
    FOTOS_DIR.mkdir(parents=True, exist_ok=True)
    destino = FOTOS_DIR / f"correcao_{secrets.token_hex(16)}.jpg"
    temporario = destino.with_suffix(".part")
    try:
        with temporario.open("xb") as arquivo:
            arquivo.write(conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
    finally:
        temporario.unlink(missing_ok=True)
    return f"/static/uploads/fotos/{destino.name}", destino


@router.post("/api/correcao-foto/{token}")
async def corrigir_foto(
    token: str, dados: CorrigirFotoRequest, response: Response,
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    solicitacao = await _buscar_solicitacao(token, session)
    if not solicitacao:
        raise HTTPException(status_code=404, detail="Link de correção inválido ou indisponível.")
    usuario = (await session.execute(select(Usuario).where(
        Usuario.id == solicitacao.usuario_id
    ).with_for_update())).scalars().first()
    # Recarrega após obter o lock: outra requisição pode ter consumido o link.
    solicitacao = (await session.execute(select(SolicitacaoCorrecaoFoto).where(
        SolicitacaoCorrecaoFoto.id == solicitacao.id
    ).with_for_update().execution_options(populate_existing=True))).scalars().first()
    _validar_solicitacao(solicitacao, usuario)
    tarefa = asyncio.create_task(asyncio.to_thread(_gravar_foto, dados.foto_base64))
    try:
        foto_url, caminho = await asyncio.shield(tarefa)
    except asyncio.CancelledError:
        _, caminho = await tarefa
        caminho.unlink(missing_ok=True)
        raise
    usuario.foto_rosto_url = foto_url
    solicitacao.status = "concluida"
    solicitacao.concluido_em = datetime.now(timezone.utc)
    session.add(usuario)
    session.add(solicitacao)
    try:
        await session.commit()
    except BaseException:
        await session.rollback()
        # Preserva o arquivo em falhas de confirmação: COMMIT pode ter ocorrido.
        raise
    return {"sucesso": True, "mensagem": "Sua foto foi atualizada com sucesso!"}
