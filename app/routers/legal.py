"""A gestão inteira exige Super Administrador; o público só lê versões publicadas."""
import asyncio
import secrets
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.deps import get_current_admin_geral
from app.db.session import get_session
from app.models.all_models import Usuario
from app.models.legal import (LegalConfig, LegalDocument, LegalAcceptance, LegalInvitation,
                              LegalAudit, utcnow)
from app.services import legal
from app.services.legal_uploads import MAX_FILE_BYTES, validate_document
from app.services.email_queue import enqueue_email


async def same_origin_action(request: Request):
    # Header não simples exige preflight entre origens; esta aplicação não habilita CORS.
    if request.method not in {"GET", "HEAD"}:
        if request.headers.get("x-legal-action") != "1":
            raise HTTPException(403, "Requisição de origem não autorizada.")
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site == "cross-site":
            raise HTTPException(403, "Requisição de origem não autorizada.")
        # O navegador define este header protegido antes de qualquer proxy.
        # Uma requisição same-origin pode chegar com Host/esquema internos diferentes.
        if fetch_site == "same-origin":
            return
        origin = request.headers.get("origin")
        allowed = {settings.PUBLIC_BASE_URL.rstrip("/"), str(request.base_url).rstrip("/")}
        if origin and origin not in allowed:
            raise HTTPException(403, "Requisição de origem não autorizada.")


router = APIRouter(prefix="/api/legal", dependencies=[Depends(same_origin_action)])
admin_router = APIRouter(prefix="/api/admin/legal", dependencies=[
    Depends(get_current_admin_geral), Depends(same_origin_action)])


class Controls(BaseModel):
    require_on_redemption: bool = False
    voluntary_enabled: bool = False
    communications_enabled: bool = False
    token_days: int = Field(default=30, ge=1, le=180)


class Pair(BaseModel):
    terms_id: int
    privacy_id: int


class CampaignRequest(Pair):
    confirmation: str


class ConfirmRequest(Pair):
    accepted: Literal[True]


@router.get("/current")
async def current(session: AsyncSession = Depends(get_session)):
    cfg = await legal.config(session)
    docs = (await session.execute(select(LegalDocument).options(defer(LegalDocument.content)).where(
        LegalDocument.status == "published"))).scalars().all()
    return {"require_on_redemption": cfg.require_on_redemption,
            "documents": [legal.document_info(doc) for doc in docs]}


def file_response(document, download):
    mime = "application/pdf" if document.extension == "pdf" else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    disposition = "attachment" if download or document.extension != "pdf" else "inline"
    return Response(document.content, media_type=mime, headers={
        "Content-Disposition": f'{disposition}; filename="documento-{document.id}.{document.extension}"',
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store", "Content-Security-Policy": "sandbox; default-src 'none'; frame-ancestors 'self'",
    })


@router.get("/documents/{document_id}/file")
async def public_file(document_id: int, download: bool = False, session: AsyncSession = Depends(get_session)):
    document = await session.get(LegalDocument, document_id)
    if not document or document.published_at is None or document.status not in {"published", "archived"}:
        raise HTTPException(404, "Documento publicado não disponível.")
    return file_response(document, download)


@admin_router.get("/documents/{document_id}/file")
async def admin_file(document_id: int, download: bool = False, session: AsyncSession = Depends(get_session)):
    document = await session.get(LegalDocument, document_id)
    if not document:
        raise HTTPException(404, "Documento não encontrado.")
    return file_response(document, download)


@admin_router.get("/documents")
async def documents(session: AsyncSession = Depends(get_session)):
    docs = (await session.execute(select(LegalDocument).options(defer(LegalDocument.content)).order_by(LegalDocument.id.desc()))).scalars().all()
    return [legal.document_info(doc, admin=True) for doc in docs]


@admin_router.post("/documents", status_code=201)
async def upload_document(kind: Literal["terms", "privacy"] = Form(...),
                          title: str = Form(..., min_length=1, max_length=200),
                          version: str = Form(..., min_length=1, max_length=50),
                          notes: str = Form("", max_length=4000), file: UploadFile = File(...),
                          actor: Usuario = Depends(get_current_admin_geral),
                          session: AsyncSession = Depends(get_session)):
    if not title.strip() or not version.strip():
        raise HTTPException(400, "Informe título e versão.")
    content = await file.read(MAX_FILE_BYTES + 1)
    await file.close()
    extension = await asyncio.to_thread(validate_document, content, file.filename or "")
    doc = LegalDocument(kind=kind, title=title.strip(), version=version.strip(), notes=notes.strip(),
                        extension=extension, content=content, size=len(content),
                        sha256=legal.digest(content), created_by=actor.id)
    session.add(doc)
    try:
        await session.flush()
        legal.audit(session, actor, "document_drafted", document_id=doc.id, sha256=doc.sha256)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Já existe essa versão para o tipo de documento. Cadastre uma nova versão.") from None
    return legal.document_info(doc, admin=True)


@admin_router.post("/documents/{document_id}/publish")
async def publish(document_id: int, actor: Usuario = Depends(get_current_admin_geral),
                   session: AsyncSession = Depends(get_session)):
    cfg = await legal.config(session, lock=True)
    doc = await session.get(LegalDocument, document_id)
    if not doc:
        raise HTTPException(404, "Documento não encontrado.")
    if doc.status == "published":
        return legal.document_info(doc, admin=True)
    if doc.status != "draft" or doc.published_at is not None:
        raise HTTPException(409, "Uma versão anterior não pode ser republicada. Cadastre nova versão.")
    if legal.digest(doc.content) != doc.sha256:
        raise HTTPException(409, "O hash do arquivo não corresponde ao conteúdo cadastrado.")
    await session.execute(text("UPDATE legal_documents SET status='archived' WHERE kind=:kind AND status='published'"), {"kind": doc.kind})
    doc.status = "published"
    doc.published_at = utcnow()
    doc.published_by = actor.id
    session.add(doc)
    await session.flush()
    # Congela o público anterior quando o primeiro par fica disponível; não altera nenhum controle.
    if cfg.legacy_cutoff is None:
        count = await session.scalar(select(func.count(LegalDocument.id)).where(LegalDocument.status == "published"))
        if count == 2:
            cfg.legacy_cutoff = utcnow()
            session.add(cfg)
    legal.audit(session, actor, "document_published", document_id=doc.id, sha256=doc.sha256, version=doc.version)
    await session.commit()
    return legal.document_info(doc, admin=True)


@admin_router.post("/documents/{document_id}/archive")
async def archive(document_id: int, actor: Usuario = Depends(get_current_admin_geral),
                   session: AsyncSession = Depends(get_session)):
    cfg = await legal.config(session, lock=True)
    doc = await session.get(LegalDocument, document_id)
    if not doc:
        raise HTTPException(404, "Documento não encontrado.")
    if doc.status == "published" and (cfg.require_on_redemption or cfg.voluntary_enabled or cfg.communications_enabled):
        raise HTTPException(409, "Desative os controles antes de arquivar um documento vigente ou publique sua substituição.")
    doc.status = "archived"
    session.add(doc)
    legal.audit(session, actor, "document_archived", document_id=doc.id)
    await session.commit()
    return {"ok": True}


@admin_router.get("/settings")
async def get_controls(session: AsyncSession = Depends(get_session)):
    return await legal.config(session)


@admin_router.put("/settings")
async def set_controls(body: Controls, actor: Usuario = Depends(get_current_admin_geral),
                        session: AsyncSession = Depends(get_session)):
    cfg = await legal.config(session, lock=True)
    if body.require_on_redemption or body.voluntary_enabled or body.communications_enabled:
        await legal.published_pair(session)
    for key, value in body.model_dump().items():
        setattr(cfg, key, value)
    session.add(cfg)
    legal.audit(session, actor, "settings_updated", **body.model_dump())
    await session.commit()
    return cfg


@admin_router.get("/dashboard")
async def dashboard(session: AsyncSession = Depends(get_session)):
    cfg = await legal.config(session)
    total = 0
    confirmed = 0
    eligible = 0
    pending = 0
    current_terms = await session.scalar(select(LegalDocument.id).where(
        LegalDocument.kind == "terms", LegalDocument.status == "published"))
    if cfg.legacy_cutoff:
        users = legal.legacy_users(cfg.legacy_cutoff)
        total = await session.scalar(select(func.count()).select_from(users.subquery()))
        eligible = await session.scalar(select(func.count(Usuario.id)).where(
            Usuario.id.in_(users), Usuario.email.is_not(None), Usuario.email != "",
            ~select(LegalAcceptance.id).where(LegalAcceptance.user_id == Usuario.id,
                                               LegalAcceptance.terms_id == current_terms).exists()))
        pending = await session.scalar(select(func.count(Usuario.id)).where(
            Usuario.id.in_(users), Usuario.email.is_not(None), Usuario.email != "",
            ~select(LegalAcceptance.id).where(LegalAcceptance.user_id == Usuario.id,
                                               LegalAcceptance.terms_id == current_terms).exists(),
            ~select(LegalInvitation.id).where(LegalInvitation.user_id == Usuario.id,
                                               LegalInvitation.terms_id == current_terms,
                                               LegalInvitation.status.notin_(["pending", "ineligible"])).exists()))
        confirmed = await session.scalar(select(func.count(LegalAcceptance.id)).where(
            LegalAcceptance.user_id.in_(users), LegalAcceptance.terms_id == current_terms))
    statuses = (await session.execute(text("""
        SELECT COALESCE(q.status, i.status) AS status, COUNT(*) AS count FROM legal_invitations i
        LEFT JOIN email_queue q ON q.idempotency_key = 'legal:' || CAST(i.id AS VARCHAR) || ':' || CAST(i.generation AS VARCHAR)
        GROUP BY COALESCE(q.status, i.status)
    """))).mappings().all()
    counts = {row["status"]: row["count"] for row in statuses}
    return {"total": total, "eligible": eligible, "confirmed": confirmed, "without_confirmation": total - confirmed,
            "percentage": round(100 * confirmed / total, 1) if total else 0,
            "pending": pending, "queued": counts.get("queued", 0) + counts.get("sending", 0),
            "sent": counts.get("sent", 0), "failed": counts.get("failed", 0), "uncertain": counts.get("uncertain", 0)}


@admin_router.get("/acceptances")
async def acceptances(page: int = Query(1, ge=1), session: AsyncSession = Depends(get_session)):
    total = await session.scalar(select(func.count(LegalAcceptance.id)))
    rows = (await session.execute(select(LegalAcceptance, Usuario.nome).join(
        Usuario, Usuario.id == LegalAcceptance.user_id).order_by(LegalAcceptance.id.desc())
        .offset((page - 1) * 25).limit(25))).all()
    return {"total": total, "items": [dict(acceptance.model_dump(), name=name) for acceptance, name in rows]}


@admin_router.get("/history")
async def history(page: int = Query(1, ge=1), session: AsyncSession = Depends(get_session)):
    total = await session.scalar(select(func.count(LegalAudit.id)))
    items = (await session.execute(select(LegalAudit).order_by(LegalAudit.id.desc())
                                  .offset((page - 1) * 25).limit(25))).scalars().all()
    return {"total": total, "items": items}


@admin_router.get("/communications")
async def communications(page: int = Query(1, ge=1), status: str = "all", session: AsyncSession = Depends(get_session)):
    # Consulta restrita: nunca retorna hash/token, URL personalizada nem corpo do e-mail.
    base = """
        FROM legal_invitations i JOIN usuarios u ON u.id=i.user_id
        LEFT JOIN email_queue q ON q.idempotency_key='legal:' || CAST(i.id AS VARCHAR) || ':' || CAST(i.generation AS VARCHAR)
        LEFT JOIN legal_acceptances a ON a.user_id=i.user_id AND a.terms_id=i.terms_id
    """
    condition = " WHERE a.id IS NULL" if status == "pending" else ""
    total = await session.scalar(text("SELECT COUNT(*) " + base + condition))
    rows = (await session.execute(text("""
        SELECT i.id, i.terms_id, i.privacy_id, u.nome, u.email, i.expires_at,
               COALESCE(q.status, i.status) AS status, q.attempts, q.sent_at,
               CASE WHEN q.last_error IS NOT NULL THEN 'Falha no provedor; consulte a operação de e-mail.' END AS error,
               a.accepted_at AS confirmed_at
    """ + base + condition + " ORDER BY i.id DESC LIMIT 25 OFFSET :offset"), {"offset": (page - 1) * 25})).mappings().all()
    return {"total": total, "items": rows}


@admin_router.post("/email-preview")
async def email_preview(body: Pair, session: AsyncSession = Depends(get_session)):
    await legal.published_pair(session, body.terms_id, body.privacy_id)
    return {"subject": legal.SUBJECT, "html": legal.email_body("Participante", "#confirmacao-de-exemplo")}


@admin_router.post("/email-test")
async def email_test(body: Pair, actor: Usuario = Depends(get_current_admin_geral),
                     session: AsyncSession = Depends(get_session)):
    cfg = await legal.config(session, lock=True)
    if not cfg.communications_enabled:
        raise HTTPException(409, "Habilite os comunicados antes do envio de teste.")
    await legal.published_pair(session, body.terms_id, body.privacy_id)
    if not actor.email:
        raise HTTPException(409, "Cadastre um e-mail autorizado na sua conta de Super Administrador.")
    # Não gera token de participante nem registra concordância no teste.
    url = settings.PUBLIC_BASE_URL.rstrip("/") + "/termos-de-uso"
    enqueued = await enqueue_email(actor.email, "[TESTE] " + legal.SUBJECT,
                        legal.email_body(actor.nome.split()[0], url), "legal_test", session=session,
                        idempotency_key=f"legal-test:{actor.id}:{secrets.token_hex(16)}")
    if not enqueued:
        await session.rollback()
        raise HTTPException(503, "Não foi possível registrar o teste na fila. Tente novamente.")
    legal.audit(session, actor, "test_email_requested", terms_id=body.terms_id, privacy_id=body.privacy_id)
    await session.commit()
    return {"message": "Teste enfileirado para o e-mail da sua conta. O botão do teste abre os documentos públicos."}


@admin_router.post("/campaigns")
async def campaign(body: CampaignRequest, actor: Usuario = Depends(get_current_admin_geral),
                    session: AsyncSession = Depends(get_session)):
    if body.confirmation != "AUTORIZAR ENVIO":
        raise HTTPException(400, "Confirme explicitamente o disparo digitando AUTORIZAR ENVIO.")
    campaign_id = await legal.start_campaign(session, actor, body.terms_id, body.privacy_id)
    return {"campaign_id": campaign_id}


@admin_router.post("/communications/{invitation_id}/retry")
async def retry(invitation_id: int, actor: Usuario = Depends(get_current_admin_geral),
                session: AsyncSession = Depends(get_session)):
    cfg = await legal.config(session, lock=True)
    if not cfg.communications_enabled or not cfg.voluntary_enabled:
        raise HTTPException(409, "Os comunicados e a confirmação voluntária precisam estar habilitados.")
    invitation = await session.get(LegalInvitation, invitation_id, with_for_update=True)
    if not invitation or invitation.consumed_at:
        raise HTTPException(409, "Comunicação indisponível ou já confirmada.")
    queue = (await session.execute(text("SELECT status FROM email_queue WHERE idempotency_key=:key FOR UPDATE"),
                                  {"key": f"legal:{invitation.id}:{invitation.generation}"})).scalar_one_or_none()
    expired = invitation.expires_at and legal.aware(invitation.expires_at) <= utcnow()
    if queue != "failed" and not (expired and queue == "sent") and invitation.status != "ineligible":
        raise HTTPException(409, "A mensagem ainda está pendente ou já foi enviada com um link válido.")
    invitation.generation += 1
    invitation.status = "pending"
    invitation.token_hash = None
    invitation.expires_at = None
    session.add(invitation)
    legal.audit(session, actor, "communication_retry", invitation_id=invitation.id)
    await session.commit()
    return {"ok": True}


@router.get("/confirmation")
async def confirmation(request: Request, session: AsyncSession = Depends(get_session)):
    await legal.limit_public(session, request, "view")
    cfg = await legal.config(session)
    if not cfg.voluntary_enabled:
        raise HTTPException(404, "A confirmação voluntária está indisponível. Seu ingresso permanece válido.")
    invitation = await legal.invitation_for_token(session, request.headers.get("x-legal-token", ""))
    accepted = await session.scalar(select(LegalAcceptance.id).where(
        LegalAcceptance.user_id == invitation.user_id, LegalAcceptance.terms_id == invitation.terms_id))
    if invitation.consumed_at or accepted:
        return {"status": "confirmed", "message": "Concordância já registrada. Seu ingresso permanece válido."}
    if not invitation.expires_at or legal.aware(invitation.expires_at) <= utcnow():
        return {"status": "expired", "message": "Este link expirou. Solicite outro link para o e-mail já cadastrado."}
    terms, privacy = await legal.published_pair(session, invitation.terms_id, invitation.privacy_id, current=False)
    user = await session.get(Usuario, invitation.user_id)
    if not user or not user.ativo or user.deleted_at:
        raise HTTPException(404, "Link inválido ou indisponível.")
    return {"status": "pending", "first_name": user.nome.split()[0],
            "terms": legal.document_info(terms), "privacy": legal.document_info(privacy)}


@router.post("/confirmation")
async def confirm(body: ConfirmRequest, request: Request, session: AsyncSession = Depends(get_session)):
    await legal.limit_public(session, request, "confirm", 10)
    cfg = await legal.config(session, lock=True)
    if not cfg.voluntary_enabled:
        raise HTTPException(409, "Confirmação voluntária desativada. Seu ingresso permanece válido.")
    invitation = await legal.invitation_for_token(session, request.headers.get("x-legal-token", ""), lock=True)
    if body.terms_id != invitation.terms_id or body.privacy_id != invitation.privacy_id:
        raise HTTPException(409, "A versão consultada não corresponde ao link recebido.")
    if invitation.consumed_at:
        return {"status": "confirmed", "message": "Concordância já registrada. Seu ingresso permanece válido."}
    if not invitation.expires_at or legal.aware(invitation.expires_at) <= utcnow():
        raise HTTPException(410, "Este link expirou. Solicite um novo link.")
    user = await session.get(Usuario, invitation.user_id)
    if not user or not user.ativo or user.deleted_at:
        raise HTTPException(404, "Link inválido ou indisponível.")
    pair = await legal.published_pair(session, invitation.terms_id, invitation.privacy_id, current=False)
    await legal.record_acceptance(session, invitation.user_id, pair, "email_link", f"invitation:{invitation.id}")
    invitation.consumed_at = utcnow()
    invitation.status = "confirmed"
    session.add(invitation)
    await session.commit()
    return {"status": "confirmed", "message": "Confirmação registrada com sucesso. Seu ingresso permanece válido."}


@router.post("/confirmation/renew")
async def renew(request: Request, session: AsyncSession = Depends(get_session)):
    await legal.limit_public(session, request, "renew", 3)
    cfg = await legal.config(session, lock=True)
    if not cfg.voluntary_enabled or not cfg.communications_enabled:
        raise HTTPException(409, "Solicite um novo link à equipe Servindoor. Seu ingresso permanece válido.")
    invitation = await legal.invitation_for_token(session, request.headers.get("x-legal-token", ""), lock=True)
    if invitation.consumed_at:
        return {"message": "Concordância já registrada. Seu ingresso permanece válido."}
    if not invitation.expires_at or legal.aware(invitation.expires_at) > utcnow():
        raise HTTPException(409, "Use o link válido que você já recebeu.")
    queue_status = await session.scalar(text("SELECT status FROM email_queue WHERE idempotency_key=:key"),
                                        {"key": f"legal:{invitation.id}:{invitation.generation}"})
    if queue_status in {"queued", "sending"}:
        raise HTTPException(409, "Aguarde o processamento do envio atual.")
    invitation.generation += 1
    invitation.status = "pending"
    invitation.token_hash = None
    invitation.expires_at = None
    session.add(invitation)
    await session.commit()
    return {"message": "Um novo link será enviado ao e-mail já cadastrado. Seu ingresso permanece válido."}
