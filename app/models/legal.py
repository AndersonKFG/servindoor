"""Documentos privados e evidências legais, independentes do ciclo dos ingressos."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, LargeBinary, Text, UniqueConstraint, Index, text
from sqlmodel import Field, SQLModel


def utcnow():
    return datetime.now(timezone.utc)


class LegalConfig(SQLModel, table=True):
    __tablename__ = "legal_config"
    __table_args__ = (CheckConstraint("id = 1 AND token_days BETWEEN 1 AND 180", name="ck_legal_config"),)
    id: int = Field(default=1, primary_key=True)
    require_on_redemption: bool = Field(default=False)
    voluntary_enabled: bool = Field(default=False)
    communications_enabled: bool = Field(default=False)
    token_days: int = Field(default=30)
    legacy_cutoff: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class LegalDocument(SQLModel, table=True):
    __tablename__ = "legal_documents"
    __table_args__ = (
        CheckConstraint("kind IN ('terms', 'privacy') AND status IN ('draft', 'published', 'archived')", name="ck_legal_document_state"),
        CheckConstraint("extension IN ('pdf', 'docx') AND size > 0 AND size <= 5242880", name="ck_legal_document_file"),
        UniqueConstraint("kind", "version", name="uq_legal_document_version"),
        Index("uq_legal_current_kind", "kind", unique=True,
              postgresql_where=text("status = 'published'"), sqlite_where=text("status = 'published'")),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    title: str
    version: str
    notes: str = Field(default="", sa_column=Column(Text, nullable=False))
    status: str = Field(default="draft", index=True)
    extension: str
    content: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    sha256: str
    size: int
    created_by: int = Field(foreign_key="usuarios.id")
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
    published_by: Optional[int] = Field(default=None, foreign_key="usuarios.id")
    published_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class LegalAcceptance(SQLModel, table=True):
    __tablename__ = "legal_acceptances"
    __table_args__ = (UniqueConstraint("user_id", "terms_id", name="uq_legal_acceptance"),
                      CheckConstraint("method IN ('resgate', 'email_link')", name="ck_legal_acceptance_method"))
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="usuarios.id", index=True)
    terms_id: int = Field(foreign_key="legal_documents.id")
    privacy_id: int = Field(foreign_key="legal_documents.id")
    terms_hash: str
    privacy_hash: str
    method: str
    # A operação fica auditável sem coletar IP, CPF ou user-agent adicionais.
    operation: str
    accepted_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))


class LegalCampaign(SQLModel, table=True):
    __tablename__ = "legal_campaigns"
    __table_args__ = (UniqueConstraint("terms_id", "privacy_id", name="uq_legal_campaign_pair"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    terms_id: int = Field(foreign_key="legal_documents.id")
    privacy_id: int = Field(foreign_key="legal_documents.id")
    created_by: int = Field(foreign_key="usuarios.id")
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))


class LegalInvitation(SQLModel, table=True):
    __tablename__ = "legal_invitations"
    __table_args__ = (UniqueConstraint("user_id", "terms_id", "privacy_id", name="uq_legal_invitation"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="legal_campaigns.id", index=True)
    user_id: int = Field(foreign_key="usuarios.id", index=True)
    terms_id: int = Field(foreign_key="legal_documents.id")
    privacy_id: int = Field(foreign_key="legal_documents.id")
    token_hash: Optional[str] = Field(default=None, unique=True, index=True)
    expires_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    consumed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    generation: int = Field(default=0)
    status: str = Field(default="pending", index=True)


class LegalAudit(SQLModel, table=True):
    __tablename__ = "legal_audit"
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_id: int = Field(foreign_key="usuarios.id")
    action: str
    details: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
