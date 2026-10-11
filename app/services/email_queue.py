import asyncio
import logging
import time
from typing import Optional

from sqlalchemy import text

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
) -> bool:
    """Persiste o e-mail para envio; o worker central aplica a quota global do SES."""
    try:
        async with async_session() as session:
            await session.execute(
                text("""
                    INSERT INTO email_queue
                        (recipient, subject, html_body, sender_type, qr_image, ticket_image)
                    VALUES
                        (:recipient, :subject, :html_body, :sender_type, :qr_image, :ticket_image)
                """),
                {
                    "recipient": recipient,
                    "subject": subject,
                    "html_body": html_body,
                    "sender_type": sender_type,
                    "qr_image": qr_image,
                    "ticket_image": ticket_image,
                },
            )
            await session.commit()
        logger.info("E-mail enfileirado para %s (%s)", recipient, sender_type)
        return True
    except Exception:
        logger.exception("Falha ao enfileirar e-mail para %s", recipient)
        return False


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
                await asyncio.wait_for(stop_event.wait(), timeout=5)
                continue

            logger.info("Worker de e-mail assumiu o despacho global da fila")
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
                    if sent_today >= daily_cap:
                        await asyncio.wait_for(stop_event.wait(), timeout=60)
                        continue

                    row = (await session.execute(text("""
                        SELECT id, recipient, subject, html_body, sender_type, qr_image, ticket_image, attempts
                        FROM email_queue
                        WHERE status = 'queued' AND next_attempt_at <= NOW()
                        ORDER BY id
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    """))).mappings().first()
                    if row is None:
                        await asyncio.wait_for(stop_event.wait(), timeout=1)
                        continue
                    await session.execute(
                        text("UPDATE email_queue SET status = 'sending', attempts = attempts + 1 WHERE id = :id"),
                        {"id": row["id"]},
                    )
                    await session.commit()

                delay = interval - (time.monotonic() - last_dispatch)
                if delay > 0:
                    await asyncio.sleep(delay)
                last_dispatch = time.monotonic()
                sender = _sender_for_type(row["sender_type"])
                ok = await asyncio.to_thread(
                    _send_smtp_email_sync,
                    row["recipient"],
                    row["subject"],
                    row["html_body"],
                    row["qr_image"],
                    row["ticket_image"],
                    sender[0],
                    sender[1],
                )
                async with async_session() as session:
                    if ok:
                        await session.execute(text("""
                            UPDATE email_queue SET status = 'sent', sent_at = NOW(), last_error = NULL WHERE id = :id
                        """), {"id": row["id"]})
                    elif row["attempts"] + 1 >= 5:
                        await session.execute(text("""
                            UPDATE email_queue SET status = 'failed', last_error = 'SMTP delivery failed after 5 attempts'
                            WHERE id = :id
                        """), {"id": row["id"]})
                    else:
                        backoff = min(3600, 30 * (2 ** row["attempts"]))
                        await session.execute(text("""
                            UPDATE email_queue SET status = 'queued', next_attempt_at = NOW() + (:seconds * INTERVAL '1 second'),
                                last_error = 'SMTP delivery failed'
                            WHERE id = :id
                        """), {"id": row["id"], "seconds": backoff})
                    await session.commit()
        except asyncio.CancelledError:
            break
        except asyncio.TimeoutError:
            continue
        except Exception:
            logger.exception("Erro no dispatcher da fila de e-mail")
            await asyncio.sleep(5)
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
