"""Regras legais compartilhadas por resgates, painel e fila existente."""
import hashlib
import html
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import defer
from sqlmodel import select

from app.core.config import settings
from app.models.all_models import Usuario, Ingresso, RateLimitTentativa
from app.models.legal import (LegalConfig, LegalDocument, LegalAcceptance, LegalInvitation,
                              LegalCampaign, LegalAudit, utcnow)
from app.services.email_queue import enqueue_email

SUBJECT = "Servindoor | Termos de Uso e Política de Privacidade"


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def config(session, lock=False):
    statement = select(LegalConfig).where(LegalConfig.id == 1)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(statement)).scalar_one_or_none() or LegalConfig()


async def published_pair(session, terms_id=None, privacy_id=None, current=True):
    statement = select(LegalDocument).options(defer(LegalDocument.content)).where(LegalDocument.published_at.is_not(None))
    if current:
        statement = statement.where(LegalDocument.status == "published")
    documents = (await session.execute(statement)).scalars().all()
    terms = next((d for d in documents if d.kind == "terms" and (terms_id is None or d.id == terms_id)), None)
    privacy = next((d for d in documents if d.kind == "privacy" and (privacy_id is None or d.id == privacy_id)), None)
    if not terms or not privacy:
        raise HTTPException(409, "Publique versões válidas dos Termos de Uso e da Política de Privacidade.")
    return terms, privacy


def document_info(doc, admin=False):
    data = {key: getattr(doc, key) for key in
            ("id", "kind", "title", "version", "status", "extension", "sha256", "size", "published_at")}
    data["file_url"] = f"/api/legal/documents/{doc.id}/file"
    if admin:
        data.update(notes=doc.notes, created_by=doc.created_by, created_at=doc.created_at,
                    published_by=doc.published_by, file_url=f"/api/admin/legal/documents/{doc.id}/file")
    return data


def audit(session, actor, action, **details):
    session.add(LegalAudit(actor_id=actor.id, action=action,
                           details=json.dumps(details, ensure_ascii=False)))


async def validate_redemption(session, form):
    # FOR SHARE mantém a configuração estável até o commit; resgates podem correr em paralelo.
    cfg = (await session.execute(select(LegalConfig).where(LegalConfig.id == 1)
                                 .with_for_update(read=True))).scalar_one_or_none()
    if not cfg or not cfg.require_on_redemption:
        return None
    terms, privacy = await published_pair(session)
    if (form.get("legal_accepted") != "true" or str(terms.id) != form.get("legal_terms_id")
            or str(privacy.id) != form.get("legal_privacy_id")):
        raise HTTPException(409, "Leia os documentos publicados e confirme a concordância com a versão atual dos Termos de Uso.")
    return terms, privacy


async def record_acceptance(session, user_id, pair, method, operation):
    terms, privacy = pair
    values = dict(user_id=user_id, terms_id=terms.id, privacy_id=privacy.id,
                  terms_hash=terms.sha256, privacy_hash=privacy.sha256,
                  method=method, operation=operation, accepted_at=utcnow())
    if session.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        dialect_insert = insert
    await session.execute(dialect_insert(LegalAcceptance).values(**values)
                          .on_conflict_do_nothing(index_elements=["user_id", "terms_id"]))


def legacy_users(cutoff):
    return select(Usuario.id).where(
        Usuario.deleted_at.is_(None), Usuario.ativo.is_(True),
        select(Ingresso.id).where(Ingresso.usuario_id == Usuario.id,
                                  Ingresso.deleted_at.is_(None),
                                  Ingresso.data_resgate < cutoff).exists())


def email_body(first_name, confirm_url, *, public_base_url=None):
    base = (public_base_url or settings.PUBLIC_BASE_URL).rstrip("/")
    name = html.escape(first_name)
    action_url = html.escape(confirm_url, quote=True)
    public_url = html.escape(base, quote=True)
    # E-mail não carrega o CSS do site: cores da identidade visual e estilos inline,
    # com tabelas de apresentação e fundos sólidos para leitores sem gradientes.
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="dark">
  <meta name="supported-color-schemes" content="dark">
  <title>Servindoor | Termos de Uso e Política de Privacidade</title>
</head>
<body bgcolor="#07090e" style="margin:0;padding:0;background-color:#07090e;color:#f8fafc;font-family:'Segoe UI',Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;">
  <div aria-hidden="true" style="display:none;max-height:0;max-width:0;overflow:hidden;opacity:0;">
    Consulte os documentos da Servindoor. Seu ingresso permanece válido e a confirmação é voluntária.
  </div>
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" bgcolor="#07090e" style="width:100%;background-color:#07090e;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <!--[if mso]><table role="presentation" width="600" align="center" border="0" cellspacing="0" cellpadding="0"><tr><td><![endif]-->
        <!-- A largura fluida mantém o comunicado legível também no celular. -->
        <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" bgcolor="#0f172a" style="width:100%;max-width:600px;background-color:#0f172a;border:1px solid #283449;border-radius:20px;border-spacing:0;overflow:hidden;">
          <tr>
            <td style="padding:0;">
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td width="33%" height="5" bgcolor="#d946ef" style="height:5px;line-height:5px;font-size:0;background-color:#d946ef;border-top-left-radius:20px;">&nbsp;</td>
                  <td width="34%" height="5" bgcolor="#f59e0b" style="height:5px;line-height:5px;font-size:0;background-color:#f59e0b;">&nbsp;</td>
                  <td width="33%" height="5" bgcolor="#06b6d4" style="height:5px;line-height:5px;font-size:0;background-color:#06b6d4;border-top-right-radius:20px;">&nbsp;</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 28px 24px;border-bottom:1px solid #283449;">
              <p style="margin:0 0 6px;font-size:27px;line-height:34px;font-weight:800;letter-spacing:-1px;color:#f8fafc;">Serv<span style="color:#06b6d4;">indoor</span></p>
              <p style="margin:0;font-size:11px;line-height:18px;letter-spacing:2px;text-transform:uppercase;color:#94a3b8;">Festa do Servidor</p>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 28px 0;">
              <p style="margin:0 0 12px;font-size:11px;line-height:18px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;color:#06b6d4;">Comunicado oficial</p>
              <h1 style="margin:0;font-size:26px;line-height:34px;font-weight:700;letter-spacing:-0.5px;color:#f8fafc;">Termos de Uso e<br>Política de Privacidade</h1>
              <p style="margin:12px 0 0;font-size:14px;line-height:23px;color:#94a3b8;">Mais transparência para você, em cada etapa.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 28px 0;font-size:15px;line-height:26px;color:#cbd5e1;">
              <p style="margin:0 0 18px;font-size:17px;line-height:26px;color:#f8fafc;">Olá, <strong>{name}</strong>!</p>
              <p style="margin:0 0 16px;">Com o objetivo de reforçar nosso compromisso com a transparência e a proteção dos dados pessoais, a Servindoor está formalizando e disponibilizando seus <strong style="color:#f8fafc;">Termos de Uso</strong> e sua <strong style="color:#f8fafc;">Política de Privacidade</strong>.</p>
              <p style="margin:0;">Os documentos consolidam as regras já divulgadas e esclarecem os procedimentos adotados pela plataforma, incluindo a utilização e a proteção das informações dos participantes.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 28px 0;">
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" bgcolor="#0b2529" style="width:100%;background-color:#0b2529;border:1px solid #164e57;border-left:3px solid #06b6d4;border-radius:12px;">
                <tr>
                  <td style="padding:18px 20px;">
                    <p style="margin:0 0 6px;font-size:14px;line-height:22px;font-weight:700;color:#67e8f9;">Seu ingresso permanece válido</p>
                    <p style="margin:0;font-size:13px;line-height:22px;color:#cbd5e1;">Essa publicação não altera as regras previamente estabelecidas nem a validade dos ingressos já emitidos.</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 28px 0;font-size:15px;line-height:26px;color:#cbd5e1;">
              <p style="margin:0;">Você pode consultar os documentos e, <strong style="color:#f8fafc;">voluntariamente</strong>, registrar sua concordância por meio do botão abaixo.</p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:24px 28px 28px;">
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="width:100%;max-width:360px;">
                <tr>
                  <td align="center" bgcolor="#06b6d4" style="background-color:#06b6d4;border-radius:12px;mso-padding-alt:16px 20px;">
                    <a href="{action_url}" style="display:block;padding:16px 20px;border:1px solid #06b6d4;border-radius:12px;font-size:14px;line-height:22px;font-weight:700;text-align:center;text-decoration:none;color:#07090e;">Consultar documentos e confirmar</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td align="center" bgcolor="#0b0f19" style="padding:24px;background-color:#0b0f19;border-top:1px solid #283449;border-bottom-left-radius:20px;border-bottom-right-radius:20px;">
              <p style="margin:0 0 14px;font-size:12px;line-height:22px;color:#94a3b8;">
                <a href="{public_url}/termos-de-uso" style="display:inline-block;padding:4px 6px;font-weight:600;color:#67e8f9;text-decoration:underline;">Termos de Uso</a>
                &nbsp;&middot;&nbsp;
                <a href="{public_url}/politica-de-privacidade" style="display:inline-block;padding:4px 6px;font-weight:600;color:#67e8f9;text-decoration:underline;">Política de Privacidade</a>
              </p>
              <p style="margin:0;font-size:13px;line-height:22px;font-weight:600;color:#f8fafc;">Equipe Servindoor — Festa do Servidor</p>
              <p style="margin:6px 0 0;font-size:11px;line-height:18px;color:#94a3b8;">Transparência e cuidado com seus dados.</p>
            </td>
          </tr>
        </table>
        <!--[if mso]></td></tr></table><![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>"""


async def limit_public(session, request, action, maximum=30):
    from app.routers.resgate import extrair_ip_cliente
    # Lock por IP/ação; tentativas inválidas também são persistidas, sem guardar tokens.
    ip = extrair_ip_cliente(request)
    if session.bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                              {"key": f"legal:{ip}:{action}"})
    since = utcnow() - timedelta(minutes=10)
    count = await session.scalar(select(func.count(RateLimitTentativa.id)).where(
        RateLimitTentativa.ip == ip, RateLimitTentativa.acao == f"legal_{action}",
        RateLimitTentativa.criado_em > since))
    if count >= maximum:
        await session.rollback()
        raise HTTPException(429, "Aguarde alguns minutos antes de tentar novamente.")
    session.add(RateLimitTentativa(ip=ip, acao=f"legal_{action}", criado_em=utcnow()))
    await session.commit()


async def invitation_for_token(session, token, lock=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(404, "Link inválido ou indisponível.")
    stmt = select(LegalInvitation).where(LegalInvitation.token_hash == digest(token))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    invitation = (await session.execute(stmt)).scalar_one_or_none()
    if not invitation:
        raise HTTPException(404, "Link inválido ou indisponível.")
    return invitation


async def prepare_legal_batch(session, size=50):
    """Chamado pelo dispatcher eleito. Apenas campanhas explicitamente autorizadas têm destinatários."""
    cfg = await config(session, lock=True)
    if not cfg.communications_enabled or not cfg.voluntary_enabled:
        return 0
    invitations = (await session.execute(select(LegalInvitation).where(
        LegalInvitation.status == "pending").order_by(LegalInvitation.id).limit(size)
        .with_for_update(skip_locked=True))).scalars().all()
    processed = 0
    for invitation in invitations:
        user = await session.get(Usuario, invitation.user_id)
        if not user or not user.ativo or user.deleted_at or not user.email:
            invitation.status = "ineligible"
            continue
        accepted = await session.scalar(select(LegalAcceptance.id).where(
            LegalAcceptance.user_id == user.id, LegalAcceptance.terms_id == invitation.terms_id))
        if accepted:
            invitation.status = "confirmed"
            continue
        token = secrets.token_urlsafe(32)
        invitation.token_hash = digest(token)
        invitation.expires_at = utcnow() + timedelta(days=cfg.token_days)
        url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/confirmar_termos/{token}"
        ok = await enqueue_email(user.email, SUBJECT, email_body(user.nome.split()[0], url),
                                 "legal", session=session,
                                 idempotency_key=f"legal:{invitation.id}:{invitation.generation}")
        if not ok:
            raise RuntimeError("Falha ao registrar comunicação legal na fila")
        invitation.status = "queued"
        session.add(invitation)
        processed += 1
    await session.commit()
    return processed


async def start_campaign(session, actor, terms_id, privacy_id):
    cfg = await config(session, lock=True)
    if not cfg.communications_enabled or not cfg.voluntary_enabled:
        raise HTTPException(409, "Habilite a confirmação voluntária e os comunicados antes do disparo.")
    terms, privacy = await published_pair(session, terms_id, privacy_id)
    existing = await session.scalar(select(LegalCampaign.id).where(
        LegalCampaign.terms_id == terms.id, LegalCampaign.privacy_id == privacy.id))
    if existing:
        # Um grupo aberto para envio individual não autoriza o público geral.
        # Somente esta ação explícita pode congelar o público da campanha completa.
        events = (await session.execute(select(LegalAudit.action, LegalAudit.details).where(
            LegalAudit.action.in_(["individual_campaign_created", "campaign_authorized"])))).all()
        relevant = {action for action, details in events if json.loads(details).get("campaign_id") == existing}
        if "individual_campaign_created" not in relevant or "campaign_authorized" in relevant:
            return existing
        campaign = await session.get(LegalCampaign, existing)
    else:
        campaign = LegalCampaign(terms_id=terms.id, privacy_id=privacy.id, created_by=actor.id)
        session.add(campaign)
        await session.flush()
    # Um INSERT SELECT congela o público; geração de tokens/e-mails ocorre em lotes no worker.
    await session.execute(text("""
        INSERT INTO legal_invitations
            (campaign_id, user_id, terms_id, privacy_id, generation, status)
        SELECT :campaign, u.id, :terms, :privacy, 0, 'pending' FROM usuarios u
        WHERE u.deleted_at IS NULL AND u.ativo = TRUE AND u.email IS NOT NULL AND u.email <> ''
          AND EXISTS (SELECT 1 FROM ingressos i WHERE i.usuario_id = u.id
                      AND i.deleted_at IS NULL AND i.data_resgate < :cutoff)
          AND NOT EXISTS (SELECT 1 FROM legal_acceptances a WHERE a.user_id = u.id AND a.terms_id = :terms)
        ON CONFLICT (user_id, terms_id, privacy_id) DO NOTHING
    """), {"campaign": campaign.id, "terms": terms.id, "privacy": privacy.id, "cutoff": cfg.legacy_cutoff})
    audit(session, actor, "campaign_authorized", campaign_id=campaign.id, terms_id=terms.id, privacy_id=privacy.id)
    await session.commit()
    return campaign.id


async def start_individual_communication(session, actor, user_id, *, public_base_url=None):
    """Autoriza um único destinatário, sem congelar ou expandir o público geral."""
    if (not actor.ativo or actor.deleted_at
            or ("admin_geral" not in actor.get_roles_list() and actor.role != "admin_geral")):
        raise HTTPException(403, "Envio individual restrito ao Super Administrador.")
    cfg = await config(session, lock=True)
    if not cfg.communications_enabled or not cfg.voluntary_enabled:
        raise HTTPException(409, "Os comunicados e a confirmação voluntária precisam estar habilitados.")
    user = await session.get(Usuario, user_id)
    if not user or not user.ativo or user.deleted_at or not user.email:
        raise HTTPException(409, "Destinatário indisponível ou sem e-mail cadastrado.")
    ticket = await session.scalar(select(Ingresso.id).where(
        Ingresso.usuario_id == user.id, Ingresso.deleted_at.is_(None)).limit(1))
    if not ticket:
        raise HTTPException(409, "O destinatário não possui ingresso ativo.")
    terms, privacy = await published_pair(session)
    accepted = await session.scalar(select(LegalAcceptance.id).where(
        LegalAcceptance.user_id == user.id, LegalAcceptance.terms_id == terms.id))
    if accepted:
        raise HTTPException(409, "O participante já confirmou esta versão dos Termos.")
    invitation = await session.scalar(select(LegalInvitation).where(
        LegalInvitation.user_id == user.id, LegalInvitation.terms_id == terms.id,
        LegalInvitation.privacy_id == privacy.id).with_for_update())
    if invitation:
        # Reexecutar esta operação não gera outro token nem outro e-mail.
        return invitation.id
    campaign = await session.scalar(select(LegalCampaign).where(
        LegalCampaign.terms_id == terms.id, LegalCampaign.privacy_id == privacy.id))
    if not campaign:
        campaign = LegalCampaign(terms_id=terms.id, privacy_id=privacy.id, created_by=actor.id)
        session.add(campaign)
        await session.flush()
        audit(session, actor, "individual_campaign_created", campaign_id=campaign.id)
    token = secrets.token_urlsafe(32)
    invitation = LegalInvitation(campaign_id=campaign.id, user_id=user.id,
        terms_id=terms.id, privacy_id=privacy.id, token_hash=digest(token),
        expires_at=utcnow() + timedelta(days=cfg.token_days), status="queued")
    session.add(invitation)
    await session.flush()
    base = (public_base_url or settings.PUBLIC_BASE_URL).rstrip("/")
    enqueued = await enqueue_email(user.email, SUBJECT,
        email_body(user.nome.split()[0], f"{base}/confirmar_termos/{token}", public_base_url=base),
        "legal", session=session, idempotency_key=f"legal:{invitation.id}:{invitation.generation}")
    if not enqueued:
        await session.rollback()
        raise HTTPException(503, "Não foi possível registrar o envio individual.")
    audit(session, actor, "individual_communication_authorized", campaign_id=campaign.id,
          invitation_id=invitation.id, recipient_user_id=user.id, terms_id=terms.id, privacy_id=privacy.id)
    await session.commit()
    return invitation.id
