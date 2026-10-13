"""Agrupa reservas do mesmo lote para confirmar várias vagas em um único commit.

Cada processo tem seu próprio actor. O lock PostgreSQL do lote e locks globais
das identidades continuam coordenando os processos; a fila não decide capacidade.
"""

import asyncio
import hashlib
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, or_, select, update

from app.db.session import async_session
from app.models.all_models import Lote, RateLimitTentativa, ReservaIngresso

logger = logging.getLogger(__name__)


@dataclass
class ReservationResult:
    status_code: int
    codigo: str | None = None
    detail: str | None = None
    reserva: ReservaIngresso | None = None
    created: bool = False
    lote: Lote | None = None


@dataclass
class _Request:
    lote_id: int
    fp: str | None
    device_id: str | None
    browser_hash: str | None
    cpf: str | None
    ip: str
    rate_key: str
    future: asyncio.Future
    cancelled: bool = False


def _lock_key(namespace: str, value: str) -> int:
    return int.from_bytes(hashlib.sha256(
        f"servindoor:reserva_batch:v1:{namespace}:{value}".encode()
    ).digest()[:8], "big", signed=True)


async def _advisory_locks(session: AsyncSession, keys: set[int]) -> None:
    if keys and session.bind.dialect.name == "postgresql":
        await session.execute(text("""
            WITH ordered_keys AS MATERIALIZED (
                SELECT DISTINCT UNNEST(CAST(:keys AS BIGINT[])) AS k ORDER BY k
            )
            SELECT pg_advisory_xact_lock(k) FROM ordered_keys
        """), {"keys": sorted(keys)})


class ReservaBatchService:
    def __init__(self, session_factory=None, *, max_batch=64, window_seconds=0.01,
                 max_queue=4096, rate_limit=300):
        self.session_factory = session_factory
        self.max_batch = max(1, min(int(max_batch), 256))
        self.window_seconds = max(0, min(float(window_seconds), 0.05))
        self.max_queue = max(1, int(max_queue))
        self.rate_limit = max(1, int(rate_limit))
        self._queue = None
        self._task = None
        self._stopping = False
        self._waiting = set()

    async def start(self):
        if self._task is not None and not self._task.done():
            return
        self._queue = asyncio.Queue(maxsize=self.max_queue)
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="reserva_batch")

    async def stop(self):
        self._stopping = True
        if self._task is None:
            return
        if not self._task.done():
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                pass  # A fila cheia já acordará o consumidor.
            await self._task
        self._task = None

    async def reserve(self, *, lote_id, fp=None, device_id=None, browser_hash=None,
                      cpf=None, ip, rate_key=None):
        if self._stopping:
            return self._busy("O serviço de reservas está reiniciando. Tente novamente.")
        if self._task is None or self._task.done():
            await self.start()
        if len(self._waiting) >= self.max_queue:
            return self._busy("Muitos pedidos de reserva em andamento. Tente novamente.")
        future = asyncio.get_running_loop().create_future()
        request = _Request(lote_id, fp, device_id or fp, browser_hash, cpf, ip,
                           rate_key or ip, future)
        self._waiting.add(future)
        try:
            self._queue.put_nowait(request)
        except asyncio.QueueFull:
            self._waiting.discard(future)
            return self._busy("Muitos pedidos de reserva em andamento. Tente novamente.")
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            request.cancelled = True
            future.cancel()
            self._waiting.discard(future)
            raise

    @staticmethod
    def _busy(detail="Não foi possível confirmar a reserva. Tente novamente."):
        return ReservationResult(503, "reserva_ocupada", detail)

    def _complete(self, request, result):
        self._waiting.discard(request.future)
        if not request.future.done():
            request.future.set_result(result)

    async def _run(self):
        try:
            while not self._stopping:
                first = await self._queue.get()
                if first is None:
                    break
                requests = [first]
                if self._queue.qsize() < self.max_batch - 1 and self.window_seconds:
                    await asyncio.sleep(self.window_seconds)
                while len(requests) < self.max_batch:
                    try:
                        item = self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if item is None:
                        self._stopping = True
                        break
                    requests.append(item)
                groups = defaultdict(list)
                for request in requests:
                    if not request.cancelled:
                        groups[request.lote_id].append(request)
                for group in groups.values():
                    if self._stopping:
                        for request in group:
                            self._complete(request, self._busy())
                    else:
                        await self._serve_batch(group)
        finally:
            while True:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is not None:
                    self._complete(item, self._busy())
            # Também encerra futuros de um batch se o próprio actor for cancelado.
            for future in tuple(self._waiting):
                if not future.done():
                    future.set_result(self._busy())
                self._waiting.discard(future)

    async def _serve_batch(self, requests):
        requests = [item for item in requests if not item.cancelled]
        if not requests:
            return
        try:
            factory = self.session_factory or async_session
            async with factory() as session:
                results = await self._transaction(session, requests)
                # _transaction já fez flush. Desanexa antes do commit para
                # preservar os campos mesmo com expire_on_commit=True.
                for result in results:
                    if result.reserva is not None and result.reserva in session:
                        session.expunge(result.reserva)
                    if result.lote is not None and result.lote in session:
                        session.expunge(result.lote)
                await session.commit()
            for request, result in zip(requests, results):
                self._complete(request, result)
        except asyncio.CancelledError:
            for request in requests:
                self._complete(request, self._busy())
            raise
        except Exception as exc:
            logger.error("Falha no batch de reservas lote_id=%s erro=%s",
                         requests[0].lote_id, type(exc).__name__)
            for request in requests:
                self._complete(request, self._busy())

    async def _transaction(self, session, requests):
        keys = {item.rate_key for item in requests}
        # Locks de rate sempre vêm antes de lote/identidades, em ordem global.
        await _advisory_locks(session, {_lock_key("rate", key) for key in keys})
        lote = (await session.execute(select(Lote).where(
            Lote.id == requests[0].lote_id, Lote.deleted_at.is_(None),
        ).with_for_update())).scalars().first()
        now = datetime.now(timezone.utc)

        def finish(results):
            for result in results:
                result.lote = lote
            return results

        if lote is None or not lote.ativo:
            return finish([ReservationResult(400, "lote_inativo", "Este lote está pausado ou inativo.") for _ in requests])
        if lote.data_abertura and now < lote.data_abertura:
            return finish([ReservationResult(400, "nao_iniciado", "O período deste lote ainda não iniciou.") for _ in requests])
        if lote.data_fechamento and now > lote.data_fechamento:
            return finish([ReservationResult(400, "encerrado", "O período deste lote já encerrou.") for _ in requests])

        fingerprints = {item.fp for item in requests if item.fp}
        devices = {item.device_id for item in requests if item.device_id}
        browsers = {item.browser_hash for item in requests if item.browser_hash}
        cpfs = {item.cpf for item in requests if item.cpf}
        identity_keys = set()
        for namespace, values in (("fp", fingerprints), ("device", devices),
                                  ("browser", browsers), ("cpf", cpfs)):
            identity_keys.update(_lock_key(namespace, value) for value in values)
        await _advisory_locks(session, identity_keys)
        # Outro lote pode ter retido a identidade; o relógio anterior à espera
        # não pode renovar uma reserva que venceu enquanto o pedido aguardava.
        now = datetime.now(timezone.utc)
        if lote.data_fechamento and now > lote.data_fechamento:
            return finish([ReservationResult(400, "encerrado", "O período deste lote já encerrou.") for _ in requests])

        conditions = []
        for column, values in ((ReservaIngresso.device_fingerprint, fingerprints),
                               (ReservaIngresso.device_id, devices),
                               (ReservaIngresso.browser_token_hash, browsers),
                               (ReservaIngresso.cpf, cpfs)):
            if values:
                conditions.append(column.in_(values))
        identities = or_(*conditions) if conditions else text("FALSE")
        # Libera unicidade de CPF/browser vencidos antes das novas inserções.
        await session.execute(update(ReservaIngresso).where(
            ReservaIngresso.status == "ativa", ReservaIngresso.expira_em <= now,
            identities,
        ).values(status="expirada"))
        active = (await session.execute(select(ReservaIngresso).where(
            ReservaIngresso.status == "ativa", ReservaIngresso.utilizada == False,
            ReservaIngresso.expira_em > now, identities,
        ).order_by(ReservaIngresso.expira_em.desc()))).scalars().all()
        maps = {"fp": {}, "device": {}, "browser": {}, "cpf": {}}

        def remember(reserva):
            for name, value in (("fp", reserva.device_fingerprint), ("device", reserva.device_id),
                                ("browser", reserva.browser_token_hash), ("cpf", reserva.cpf)):
                if value:
                    maps[name].setdefault(value, reserva)

        for reserva in active:
            remember(reserva)
        count = await session.scalar(select(func.count(ReservaIngresso.id)).where(
            ReservaIngresso.lote_id == lote.id, ReservaIngresso.status == "ativa",
            ReservaIngresso.expira_em > now,
        ))
        remaining = max(0, lote.quantidade_total - lote.quantidade_resgatada - count)
        rows = (await session.execute(select(RateLimitTentativa.ip, func.count(RateLimitTentativa.id)).where(
            RateLimitTentativa.ip.in_(keys), RateLimitTentativa.acao == "reserva",
            RateLimitTentativa.criado_em > now - timedelta(seconds=60),
        ).group_by(RateLimitTentativa.ip))).all()
        rate_counts = dict(rows)
        additions = []
        results = []
        for item in requests:
            if item.cancelled:
                results.append(self._busy())
                continue
            existing = maps["fp"].get(item.fp) or maps["device"].get(item.device_id) or maps["browser"].get(item.browser_hash)
            if existing:
                if existing.lote_id != lote.id:
                    results.append(ReservationResult(400, "reserva_outro_lote", "Este dispositivo tem uma reserva em outro lote."))
                elif existing.browser_token_hash and existing.browser_token_hash != item.browser_hash:
                    results.append(ReservationResult(403, "reserva_outro_navegador", "A reserva pertence a outro navegador."))
                elif item.cpf and existing.cpf and item.cpf != existing.cpf:
                    results.append(ReservationResult(409, "reserva_existente", "A reserva já está vinculada a outro CPF."))
                elif item.cpf and maps["cpf"].get(item.cpf) not in (None, existing):
                    results.append(ReservationResult(409, "reserva_existente", "Este CPF já possui uma reserva ativa."))
                else:
                    if item.cpf and not existing.cpf:
                        existing.cpf = item.cpf
                        maps["cpf"][item.cpf] = existing
                        session.add(existing)
                    results.append(ReservationResult(200, reserva=existing))
                continue
            if rate_counts.get(item.rate_key, 0) >= self.rate_limit:
                results.append(ReservationResult(429, "rate_limit", "Muitas tentativas. Aguarde um instante."))
                continue
            rate_counts[item.rate_key] = rate_counts.get(item.rate_key, 0) + 1
            additions.append(RateLimitTentativa(ip=item.rate_key, acao="reserva", criado_em=now))
            if item.cpf and item.cpf in maps["cpf"]:
                results.append(ReservationResult(409, "reserva_existente", "Este CPF já possui uma reserva ativa."))
                continue
            if remaining <= 0:
                code = "esgotado" if lote.quantidade_resgatada >= lote.quantidade_total else "em_preenchimento"
                results.append(ReservationResult(400, code, "Todas as vagas estão ocupadas ou em preenchimento."))
                continue
            reserva = ReservaIngresso(token=str(uuid.uuid4()), lote_id=lote.id,
                criada_em=now, expira_em=now + timedelta(minutes=5), utilizada=False,
                status="ativa", cpf=item.cpf, browser_token_hash=item.browser_hash,
                device_fingerprint=item.fp, device_id=item.device_id, ip_origem=item.ip)
            additions.append(reserva)
            remember(reserva)
            remaining -= 1
            results.append(ReservationResult(200, reserva=reserva, created=True))
        session.add_all(additions)
        await session.flush()
        return finish(results)


reserva_batch_service = ReservaBatchService()
