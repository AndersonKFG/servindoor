"""Validação externa durável, executada depois da confirmação do cadastro.

O claim usa uma transação curta e um lease: chamadas à API nunca seguram uma
sessão de banco. Um processo interrompido pode ser substituído após o lease.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.services.validacao_servidor_service import ServidorValidationService

logger = logging.getLogger(__name__)

RESGATE_JOBS_DDL = """
    CREATE TABLE IF NOT EXISTS resgate_jobs (
        id BIGSERIAL PRIMARY KEY,
        job_type VARCHAR NOT NULL DEFAULT 'external_validation',
        solicitacao_id INTEGER NOT NULL REFERENCES solicitacoes_validacao(id) ON DELETE CASCADE,
        status VARCHAR NOT NULL DEFAULT 'queued',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        lease_expires_at TIMESTAMPTZ,
        lease_token VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMPTZ,
        last_error VARCHAR,
        CONSTRAINT uq_resgate_jobs_request UNIQUE (job_type, solicitacao_id),
        CONSTRAINT ck_resgate_jobs_status
            CHECK (status IN ('queued', 'processing', 'done', 'skipped', 'failed'))
    )
"""
RESGATE_JOBS_INDEX_DDL = """
    CREATE INDEX IF NOT EXISTS idx_resgate_jobs_pending
    ON resgate_jobs (status, next_attempt_at, id)
"""

MAX_ATTEMPTS = 5
LEASE_SECONDS = 60
VALIDATION_TIMEOUT_SECONDS = 15


async def enqueue_external_validation(session: AsyncSession, solicitacao_id: int) -> None:
    """Participa da transação do cadastro; duplicatas não criam outra tarefa."""
    await session.execute(text("""
        INSERT INTO resgate_jobs (job_type, solicitacao_id)
        VALUES ('external_validation', :solicitacao_id)
        ON CONFLICT (job_type, solicitacao_id) DO NOTHING
    """), {"solicitacao_id": solicitacao_id})


async def get_external_validation_status(session: AsyncSession, solicitacao_id: int) -> str | None:
    """None identifica cadastros legados que não têm tarefa de validação."""
    return await session.scalar(text("""
        SELECT status FROM resgate_jobs
        WHERE job_type = 'external_validation' AND solicitacao_id = :solicitacao_id
    """), {"solicitacao_id": solicitacao_id})


async def _claim_job(session_factory) -> dict[str, Any] | None:
    lease_token = uuid.uuid4().hex
    async with session_factory() as session:
        # O último claim pode ter sido interrompido. O limite inclui tentativas
        # com crash para não deixar uma tarefa defeituosa rodando eternamente.
        await session.execute(text("""
            UPDATE resgate_jobs
            SET status = 'failed', finished_at = NOW(), lease_token = NULL,
                lease_expires_at = NULL, last_error = 'lease_expired_attempt_limit'
            WHERE job_type = 'external_validation' AND status = 'processing'
              AND lease_expires_at <= NOW() AND attempts >= :max_attempts
        """), {"max_attempts": MAX_ATTEMPTS})
        row = (await session.execute(text("""
            WITH candidate AS (
                SELECT id FROM resgate_jobs
                WHERE job_type = 'external_validation' AND attempts < :max_attempts
                  AND ((status = 'queued' AND next_attempt_at <= NOW())
                    OR (status = 'processing' AND lease_expires_at <= NOW()))
                ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE resgate_jobs AS job
            SET status = 'processing', attempts = attempts + 1,
                lease_token = :lease_token,
                lease_expires_at = NOW() + (:lease_seconds * INTERVAL '1 second')
            FROM candidate WHERE job.id = candidate.id
            RETURNING job.id, job.solicitacao_id, job.attempts, job.lease_token
        """), {"max_attempts": MAX_ATTEMPTS, "lease_token": lease_token,
                  "lease_seconds": LEASE_SECONDS})).mappings().first()
        await session.commit()
        return dict(row) if row else None


async def _validation_snapshot(session_factory, solicitacao_id: int) -> dict[str, Any] | None:
    async with session_factory() as session:
        row = (await session.execute(text("""
            SELECT s.usuario_id, u.cpf
            FROM solicitacoes_validacao s JOIN usuarios u ON u.id = s.usuario_id
            WHERE s.id = :id AND s.status = 'pendente_analise'
              AND u.ativo = TRUE AND u.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM solicitacoes_validacao newer
                  WHERE newer.usuario_id = s.usuario_id AND newer.id > s.id
                    AND newer.status IN ('pendente_analise', 'aprovado')
              )
        """), {"id": solicitacao_id})).mappings().first()
        return dict(row) if row else None


async def _finish_job(session_factory, job, snapshot, identified: bool) -> bool:
    async with session_factory() as session:
        owned = (await session.execute(text("""
            SELECT id FROM resgate_jobs
            WHERE id = :id AND status = 'processing' AND lease_token = :lease_token
            FOR UPDATE
        """), job)).scalar_one_or_none()
        if owned is None:
            return False  # Outro worker já recuperou o lease; resultado antigo.

        applied = False
        if snapshot is not None:
            # Ordem usuário -> solicitação também protege a avaliação contra
            # edição/cancelamento concorrente pela equipe administrativa.
            user_id = (await session.execute(text("""
                SELECT id FROM usuarios WHERE id = :usuario_id AND cpf = :cpf
                    AND ativo = TRUE AND deleted_at IS NULL FOR UPDATE
            """), snapshot)).scalar_one_or_none()
            if user_id is not None:
                current = (await session.execute(text("""
                    SELECT s.id FROM solicitacoes_validacao s
                    WHERE s.id = :solicitacao_id AND s.usuario_id = :usuario_id
                      AND s.status = 'pendente_analise'
                      AND NOT EXISTS (
                          SELECT 1 FROM solicitacoes_validacao newer
                          WHERE newer.usuario_id = s.usuario_id AND newer.id > s.id
                            AND newer.status IN ('pendente_analise', 'aprovado')
                      ) FOR UPDATE OF s
                """), {**job, **snapshot})).scalar_one_or_none()
                if current is not None:
                    await session.execute(text("""
                        UPDATE solicitacoes_validacao SET identificado_api = :identified
                        WHERE id = :id
                    """), {"id": current, "identified": identified})
                    if identified:
                        # Uma resposta negativa não revoga validação manual.
                        await session.execute(text("""
                            UPDATE usuarios SET validado = TRUE WHERE id = :id
                        """), {"id": user_id})
                    applied = True

        await session.execute(text("""
            UPDATE resgate_jobs
            SET status = :status, finished_at = NOW(), last_error = NULL,
                lease_token = NULL, lease_expires_at = NULL
            WHERE id = :id AND lease_token = :lease_token
        """), {**job, "status": "done" if applied else "skipped"})
        await session.commit()
        return applied


async def _retry_job(session_factory, job, error: str) -> None:
    failed = job["attempts"] >= MAX_ATTEMPTS
    async with session_factory() as session:
        await session.execute(text("""
            UPDATE resgate_jobs
            SET status = :status, last_error = :error,
                next_attempt_at = NOW() + (:delay * INTERVAL '1 second'),
                finished_at = CASE WHEN :failed THEN NOW() ELSE NULL END,
                lease_token = NULL, lease_expires_at = NULL
            WHERE id = :id AND status = 'processing' AND lease_token = :lease_token
        """), {**job, "status": "failed" if failed else "queued", "failed": failed,
                  "error": error, "delay": min(300, 5 * (2 ** (job["attempts"] - 1)))})
        await session.commit()
    logger.warning("Validacao externa job=%s tentativa=%s estado=%s erro=%s",
                   job["id"], job["attempts"], "failed" if failed else "queued", error)


async def process_next_external_validation(
    *, session_factory=None, validator: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
) -> bool:
    """Processa até uma tarefa; factory/validator permitem regressões isoladas."""
    session_factory = session_factory or async_session
    validator = validator or ServidorValidationService.verificar_servidor
    job = await _claim_job(session_factory)
    if job is None:
        return False
    snapshot = await _validation_snapshot(session_factory, job["solicitacao_id"])
    if snapshot is None:
        await _finish_job(session_factory, job, None, False)
        return True

    # As sessões de claim e leitura já saíram de seus contextos neste ponto.
    try:
        result = await asyncio.wait_for(validator(snapshot["cpf"]), VALIDATION_TIMEOUT_SECONDS)
        if not isinstance(result, dict) or type(result.get("is_servidor")) is not bool:
            raise ValueError("invalid_provider_response")
        if result.get("modo") == "fallback":
            raise ConnectionError("provider_unavailable")
    except asyncio.CancelledError:
        # Deixa o lease persistido para retomada após encerramento do processo.
        raise
    except Exception as exc:
        # Mensagens livres da API podem conter CPF/credenciais; guarda só tipo.
        await _retry_job(session_factory, job, type(exc).__name__)
    else:
        await _finish_job(session_factory, job, snapshot, result["is_servidor"])
    return True


async def resgate_jobs_worker(stop_event: asyncio.Event, *, session_factory=None, validator=None) -> None:
    """Workers cooperam com SKIP LOCKED, sem conexão permanente de liderança."""
    while not stop_event.is_set():
        try:
            processed = await process_next_external_validation(
                session_factory=session_factory, validator=validator,
            )
            if processed:
                continue
            delay = 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Falha no worker de validacao externa erro=%s", type(exc).__name__)
            delay = 5
        try:
            await asyncio.wait_for(stop_event.wait(), delay)
        except asyncio.TimeoutError:
            pass
