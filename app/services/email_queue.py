import asyncio
import logging
import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session, engine

logger = logging.getLogger(__name__)
_LEADER_LOCK_ID = 918274611


async def enqueue_email(
    recipient: str,
    subject: str,
    html_body: str,
    sender_type: str,
    qr_image: Optional[bytes] = None,
    ticket_image: Optional[bytes] = None,
    *,
    session: Optional[AsyncSession] = None,
    idempotency_key: Optional[str] = None,
) -> bool:
    """Persiste o e-mail; com session, participa da transação do chamador."""
    statement = text("""
        INSERT INTO email_queue
            (recipient, subject, html_body, sender_type, qr_image, ticket_image)
        VALUES
            (:recipient, :subject, :html_body, :sender_type, :qr_image, :ticket_image)
        RETURNING id
    """)
    parameters = {
        "recipient": recipient,
        "subject": subject,
        "html_body": html_body,
        "sender_type": sender_type,
        "qr_image": qr_image,
        "ticket_image": ticket_image,
    }
    if idempotency_key is not None:
        statement = text("""
            INSERT INTO email_queue
                (recipient, subject, html_body, sender_type, qr_image, ticket_image, idempotency_key)
            VALUES
                (:recipient, :subject, :html_body, :sender_type, :qr_image, :ticket_image, :idempotency_key)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
        """)
        parameters["idempotency_key"] = idempotency_key
    try:
        if session is not None:
            email_id = (await session.execute(statement, parameters)).scalar_one_or_none()
            logger.info("E-mail id=%s tipo=%s registrado na transação", email_id, sender_type)
        else:
            async with async_session() as own_session:
                email_id = (await own_session.execute(statement, parameters)).scalar_one_or_none()
                await own_session.commit()
            logger.info("E-mail id=%s tipo=%s enfileirado", email_id, sender_type)
        return True
    except Exception as exc:
        # Exceções SQLAlchemy podem incluir os parâmetros SQL (corpo e código 2FA).
        original = getattr(exc, "orig", exc)
        logger.error("Falha ao enfileirar e-mail tipo=%s erro=%s sqlstate=%s",
                     sender_type, type(original).__name__, getattr(original, "sqlstate", None))
        return False


async def _wait_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    """O timeout de uma espera ociosa não deve encerrar a liderança do worker."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def email_queue_worker(stop_event: asyncio.Event) -> None:
    """Eleito via advisory lock PostgreSQL: apenas um dispatcher envia em toda a aplicação."""
    from app.services.email_service import _send_smtp_email_sync

    while not stop_event.is_set():
        lock_connection = None
        try:
            lock_connection = await engine.connect()
            acquired = await lock_connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": _LEADER_LOCK_ID}
            )
            await lock_connection.commit()
            if not acquired:
                await lock_connection.close()
                lock_connection = None
                await _wait_or_stop(stop_event, 5)
                continue

            logger.info("Worker de e-mail assumiu a fila; SMTP host=%s porta=%s autenticação=%s",
                        settings.SMTP_HOST or "não configurado", settings.SMTP_PORT,
                        bool(settings.SMTP_USER and settings.SMTP_PASSWORD))
            async with async_session() as session:
                await session.execute(text("UPDATE email_queue SET status = 'queued' WHERE status = 'sending'"))
                await session.commit()

            interval = 1 / max(1, min(settings.EMAIL_SEND_RATE_PER_SECOND, 13))
            last_dispatch = 0.0
            while not stop_event.is_set():
                async with async_session() as session:
                    sent_today = await session.scalar(text("""
                        SELECT COUNT(*) FROM email_queue
                        WHERE status = 'sent' AND (sent_at AT TIME ZONE 'UTC')::date = (NOW() AT TIME ZONE 'UTC')::date
                    """))
                    daily_cap = max(1, settings.EMAIL_DAILY_LIMIT)
                    row = None
                    if sent_today < daily_cap:
                        row = (await session.execute(text("""
                        SELECT id, recipient, subject, html_body, sender_type, qr_image, ticket_image, attempts
                        FROM email_queue
                        WHERE status = 'queued' AND next_attempt_at <= NOW()
                        ORDER BY id
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                        """))).mappings().first()
                    if row is not None:
                        await session.execute(
                            text("UPDATE email_queue SET status = 'sending', attempts = attempts + 1 WHERE id = :id"),
                            {"id": row["id"]},
                        )
                        await session.commit()

                if sent_today >= daily_cap:
                    logger.warning("Envio de e-mail aguardando quota diária: %s/%s", sent_today, daily_cap)
                    await _wait_or_stop(stop_event, 60)
                    continue
                if row is None:
                    await _wait_or_stop(stop_event, 1)
                    continue

                delay = interval - (time.monotonic() - last_dispatch)
                if delay > 0:
                    await asyncio.sleep(delay)
                last_dispatch = time.monotonic()
                sender = _sender_for_type(row["sender_type"])
                attempt = row["attempts"] + 1
                logger.info("Enviando e-mail id=%s tipo=%s tentativa=%s remetente=%s",
                            row["id"], row["sender_type"], attempt, sender[0])
                error_detail = "SMTP delivery failed"
                try:
                    ok = await asyncio.to_thread(
                        _send_smtp_email_sync,
                        row["recipient"], row["subject"], row["html_body"],
                        row["qr_image"], row["ticket_image"], sender[0], sender[1],
                        raise_on_error=True,
                        queue_id=row["id"],
                    )
                except Exception as exc:
                    ok = False
                    error_detail = f"{type(exc).__name__}: {exc}"[:1000]
                    logger.error("Falha SMTP e-mail id=%s tentativa=%s: %s",
                                 row["id"], attempt, error_detail)
                async with async_session() as session:
                    if ok:
                        await session.execute(text("""
                            UPDATE email_queue SET status = 'sent', sent_at = NOW(), last_error = NULL WHERE id = :id
                        """), {"id": row["id"]})
                    elif row["attempts"] + 1 >= 5:
                        await session.execute(text("""
                            UPDATE email_queue SET status = 'failed', last_error = :error
                            WHERE id = :id
                        """), {"id": row["id"], "error": error_detail})
                    else:
                        backoff = min(3600, 30 * (2 ** row["attempts"]))
                        await session.execute(text("""
                            UPDATE email_queue SET status = 'queued', next_attempt_at = NOW() + (:seconds * INTERVAL '1 second'),
                                last_error = :error
                            WHERE id = :id
                        """), {"id": row["id"], "seconds": backoff, "error": error_detail})
                    await session.commit()
                if ok:
                    logger.info("E-mail id=%s aceito pelo servidor SMTP", row["id"])
                elif attempt >= 5:
                    logger.error("E-mail id=%s falhou após %s tentativas", row["id"], attempt)
                else:
                    logger.warning("E-mail id=%s terá nova tentativa em %ss", row["id"], backoff)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Erro no dispatcher da fila de e-mail")
            await _wait_or_stop(stop_event, 5)
        finally:
            if lock_connection is not None:
                try:
                    await lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": _LEADER_LOCK_ID}
                    )
                    await lock_connection.commit()
                except Exception:
                    pass
                await lock_connection.close()


def _sender_for_type(sender_type: str) -> tuple[str, str]:
    senders = {
        "ticket": (settings.SMTP_FROM, settings.SMTP_FROM_NAME),
        "security": (settings.SMTP_FROM_SECURITY, f"{settings.SMTP_FROM_NAME} | Segurança"),
        "communications": (settings.SMTP_FROM_COMMUNICATIONS, f"{settings.SMTP_FROM_NAME} | Comunicados"),
        "team": (settings.SMTP_FROM_TEAM, f"{settings.SMTP_FROM_NAME} | Equipe"),
    }
    return senders.get(sender_type, senders["ticket"])
