"""Identidade durável da comunicação, independente da marcação da solicitação."""

from sqlalchemy import DateTime, String, cast, column, literal, select, table

from app.models.all_models import SolicitacaoValidacao


email_queue = table(
    "email_queue", column("id"), column("idempotency_key"),
    column("created_at", DateTime(timezone=True)),
)


def chave_comunicacao(solicitacao_id: int, status: str) -> str:
    return f"validacao:{solicitacao_id}:{status}"


def comunicacao_registrada_em():
    chave = (literal("validacao:") + cast(SolicitacaoValidacao.id, String)
             + literal(":") + SolicitacaoValidacao.status)
    return (
        select(email_queue.c.created_at)
        .where(email_queue.c.idempotency_key == chave)
        .correlate(SolicitacaoValidacao)
        .scalar_subquery()
    )
