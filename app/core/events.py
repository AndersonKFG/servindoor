import asyncio
import json
import logging
import os
import time
import uuid
from collections import OrderedDict, deque
from contextlib import suppress
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class LoteEventHub:
    """Eventos administrativos imediatos e mudanças de reserva agrupadas.

    A gravação HTTP apenas registra uma mudança em memória. Os publishers do
    lifespan calculam o estado público por janela e transportam eventos privados
    em lotes via PostgreSQL. O snapshot do banco continua sendo a referência
    após uma reconexão; o barramento SSE não participa da transação de cadastro.
    """

    _IDENTITY_FIELDS = ("device_fingerprint", "device_id", "browser_token_hash")
    _MAX_PENDING_PRIVATE = 4096
    _MAX_NOTIFY_BYTES = 7600
    _PUBLIC_STATUS_FIELDS = frozenset({
        "status_slug", "status_label", "badge_class", "pode_resgatar",
        "segundos_para_abrir", "quantidade_total", "quantidade_resgatada",
        "reservas_ativas", "vagas_disponiveis",
    })

    def __init__(self):
        self._listeners: Set[asyncio.Queue] = set()
        self._subscriptions: Dict[asyncio.Queue, dict] = {}
        self._identity_listeners: Dict[tuple, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._pg_sender: Optional[Callable] = None
        self._cache_invalidator: Optional[Callable] = None
        self._snapshot_loader: Optional[Callable] = None
        self._pid = os.getpid()
        self._state_version = int(time.time() * 1000)
        self._recent_events: deque = deque(maxlen=100)
        self._dirty_lotes: Set[int] = set()
        self._pending_private: OrderedDict = OrderedDict()
        self._dirty_signal = asyncio.Event()
        self._private_signal = asyncio.Event()
        self._publisher_tasks: List[asyncio.Task] = []
        self._seen_event_ids: OrderedDict = OrderedDict()
        self._private_reconciliation_pending = False

    @property
    def state_version(self) -> int:
        return self._state_version

    def next_version(self, minimum: int = 0) -> int:
        # A versão ordena a entrega neste worker. event_id identifica o mesmo
        # evento entre workers, cujos relógios/contadores não são uma sequência
        # global compartilhada.
        self._state_version = max(
            int(time.time() * 1000), self._state_version + 1, minimum,
        )
        return self._state_version

    async def subscribe(
        self,
        *,
        device_fingerprint: Optional[str] = None,
        device_id: Optional[str] = None,
        browser_token_hash: Optional[str] = None,
        lote_id: Optional[int] = None,
    ) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        identity = {
            "device_fingerprint": device_fingerprint,
            "device_id": device_id,
            "browser_token_hash": browser_token_hash,
            "lote_id": lote_id,
        }
        async with self._lock:
            self._listeners.add(q)
            self._subscriptions[q] = identity
            for field in self._IDENTITY_FIELDS:
                if identity[field]:
                    self._identity_listeners.setdefault((field, identity[field]), set()).add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue):
        async with self._lock:
            self._listeners.discard(q)
            identity = self._subscriptions.pop(q, {})
            for field in self._IDENTITY_FIELDS:
                key = (field, identity.get(field))
                listeners = self._identity_listeners.get(key)
                if listeners is not None:
                    listeners.discard(q)
                    if not listeners:
                        self._identity_listeners.pop(key, None)

    def _invalidate_cache(self):
        if self._cache_invalidator:
            try:
                self._cache_invalidator()
            except Exception:
                logger.exception("Falha ao invalidar o cache público de lotes")

    @staticmethod
    def _payload(event_type: str, data: dict) -> str:
        return (
            f"event: {event_type}\nid: {data['state_version']}\n"
            f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        )

    @staticmethod
    def _enqueue(q: asyncio.Queue, payload: str):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # Estado recente substitui mensagens antigas de um cliente lento;
            # as filas permanecem limitadas independentemente da carga.
            q._sse_needs_snapshot = True
            with suppress(asyncio.QueueEmpty):
                q.get_nowait()
            with suppress(asyncio.QueueFull):
                q.put_nowait(payload)

    def _broadcast_local(
        self, payload: str, version: int, event_type: str, data: dict,
        *, invalidate_cache: bool = True,
    ):
        if invalidate_cache:
            self._invalidate_cache()
        self._recent_events.append((version, event_type, data, payload))
        for q in tuple(self._listeners):
            identity = self._subscriptions.get(q, {})
            if identity.get("lote_id") and data.get("lote_id"):
                if identity["lote_id"] != data["lote_id"]:
                    continue
            if data.get("reconciliar_reservas"):
                q._sse_needs_snapshot = True
            self._enqueue(q, payload)

    def _remember_event(self, event_id: Optional[str]) -> bool:
        if not event_id:
            return True
        if event_id in self._seen_event_ids:
            return False
        self._seen_event_ids[event_id] = None
        if len(self._seen_event_ids) > self._MAX_PENDING_PRIVATE:
            self._seen_event_ids.popitem(last=False)
        return True

    def _private_data(self, data: dict, identity: dict) -> Optional[dict]:
        if identity.get("lote_id") and data.get("lote_id") != identity["lote_id"]:
            return None
        if not any(
            data.get(field) and data.get(field) == identity.get(field)
            for field in self._IDENTITY_FIELDS
        ):
            return None
        visible = dict(data)
        browser_hash = visible.pop("browser_token_hash", None)
        # Conhecer um fingerprint não autoriza receber o token de uma reserva.
        # O token só segue para o navegador que possui o cookie assinado.
        if not browser_hash or browser_hash != identity.get("browser_token_hash"):
            visible.pop("token_reserva", None)
        return visible

    def _deliver_private(self, data: dict):
        if not self._remember_event(data.get("event_id")):
            return
        version = self.next_version()
        meta = dict(data, state_version=version, timestamp_ms=int(time.time() * 1000))
        self._recent_events.append((version, "RESERVA_ATUALIZADA", meta, None))
        recipients: Set[asyncio.Queue] = set()
        for field in self._IDENTITY_FIELDS:
            if meta.get(field):
                recipients.update(self._identity_listeners.get((field, meta[field]), ()))
        # Esta iteração percorre apenas os streams do dono, não todos os VUs.
        for q in recipients:
            visible = self._private_data(meta, self._subscriptions.get(q, {}))
            if visible is not None:
                self._enqueue(q, self._payload("RESERVA_ATUALIZADA", visible))

    async def broadcast(self, event_type: str, data: Dict[str, Any], *, invalidate_cache: bool = True) -> bool:
        """Mantém o contrato imediato das alterações administrativas."""
        version = self.next_version()
        meta = dict(data, state_version=version, timestamp_ms=int(time.time() * 1000))
        meta.setdefault("event_id", uuid.uuid4().hex)
        self._remember_event(meta["event_id"])
        payload = self._payload(event_type, meta)
        self._broadcast_local(payload, version, event_type, meta, invalidate_cache=invalidate_cache)
        if self._pg_sender:
            try:
                await self._pg_sender(json.dumps({
                    "origin_pid": self._pid,
                    "event_type": event_type,
                    "data": meta,
                    "version": version,
                }, ensure_ascii=False))
            except Exception:
                logger.exception("Falha na propagação do estado público via PostgreSQL")
                return False
        return True

    def _queue_private(self, data: dict):
        key = (data.get("lote_id"), *(data.get(field) for field in self._IDENTITY_FIELDS))
        self._pending_private[key] = data
        self._pending_private.move_to_end(key)
        if len(self._pending_private) > self._MAX_PENDING_PRIVATE:
            self._pending_private.popitem(last=False)
            self._private_reconciliation_pending = True
            logger.warning("Fila SSE individual cheia; reconciliação de snapshot agendada")
        self._private_signal.set()

    def publish_reservation_change(self, data: Dict[str, Any]):
        """Registra uma mudança já confirmada; não consulta nem espera o banco."""
        lote_id = data.get("lote_id")
        if not isinstance(lote_id, int):
            raise ValueError("Uma mudança de reserva precisa de lote_id inteiro")
        private = dict(data)
        private["event_id"] = uuid.uuid4().hex
        self._deliver_private(private)
        self._queue_private(private)
        self.mark_reservation_lot_dirty(lote_id)

    def mark_reservation_lot_dirty(self, lote_id: int):
        """Agenda somente o estado público, por exemplo após expirações em lote."""
        if not isinstance(lote_id, int):
            raise ValueError("Uma mudança de capacidade precisa de lote_id inteiro")
        self._dirty_lotes.add(lote_id)
        self._dirty_signal.set()

    def on_bus_notification(self, raw_json: str):
        try:
            msg = json.loads(raw_json)
            if msg.get("origin_pid") == self._pid:
                return
            if msg.get("kind") == "reservation_batch":
                for data in msg.get("events", []):
                    self._deliver_private(data)
                return
            event_type = msg.get("event_type", "LOTE_ATUALIZADO")
            data = msg.get("data", {})
            if not self._remember_event(data.get("event_id")):
                return
            version = self.next_version(int(msg.get("version") or 0))
            meta = dict(data, state_version=version)
            payload = self._payload(event_type, meta)
            self._broadcast_local(payload, version, event_type, meta)
        except Exception:
            logger.exception("Erro ao processar notificação SSE entre workers")

    def get_events_since(
        self, last_version: Optional[int], *, device_fingerprint: Optional[str] = None,
        device_id: Optional[str] = None, browser_token_hash: Optional[str] = None,
        lote_id: Optional[int] = None,
    ) -> List[str]:
        if not last_version:
            return []
        identity = {
            "device_fingerprint": device_fingerprint, "device_id": device_id,
            "browser_token_hash": browser_token_hash, "lote_id": lote_id,
        }
        missed = []
        for version, event_type, data, payload in tuple(self._recent_events):
            if version <= last_version:
                continue
            if event_type == "RESERVA_ATUALIZADA" and payload is None:
                visible = self._private_data(data, identity)
                if visible is not None:
                    missed.append(self._payload(event_type, visible))
            elif not lote_id or not data.get("lote_id") or data["lote_id"] == lote_id:
                missed.append(payload)
        return missed

    def start_reservation_publisher(self, snapshot_loader: Callable, interval: float = 0.5):
        if self._publisher_tasks:
            raise RuntimeError("O publisher de reservas já está ativo")
        if interval <= 0:
            raise ValueError("O intervalo de publicação precisa ser positivo")
        self._snapshot_loader = snapshot_loader
        # O mesmo hub pode atravessar reinícios de lifespan em loops diferentes
        # (por exemplo, testes). Sinais novos não retêm o loop da execução antiga.
        self._dirty_signal = asyncio.Event()
        self._private_signal = asyncio.Event()
        if self._dirty_lotes:
            self._dirty_signal.set()
        if self._pending_private:
            self._private_signal.set()
        self._publisher_tasks = [
            asyncio.create_task(self._supervise_publisher(
                self._publish_private_batches, "individual",
            ), name="sse-reservas-individuais"),
            asyncio.create_task(self._supervise_publisher(
                lambda: self._publish_public_states(interval), "público",
            ), name="sse-estado-publico"),
        ]

    async def _supervise_publisher(self, factory: Callable, label: str):
        while True:
            try:
                await factory()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Publisher SSE %s interrompido tipo=%s; reiniciando", label, type(exc).__name__)
            else:
                logger.error("Publisher SSE %s terminou inesperadamente; reiniciando", label)
            await asyncio.sleep(0.5)

    async def stop_reservation_publisher(self):
        tasks, self._publisher_tasks = self._publisher_tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._pending_private.clear()
        self._dirty_lotes.clear()
        self._private_signal.clear()
        self._dirty_signal.clear()
        self._private_reconciliation_pending = False

    async def _publish_private_batches(self):
        while True:
            await self._private_signal.wait()
            await asyncio.sleep(0.05)
            self._private_signal.clear()
            pending, self._pending_private = self._pending_private, OrderedDict()
            if not self._pg_sender:
                continue
            events = list(pending.values())
            batch: List[dict] = []
            try:
                for data in events:
                    candidate = self._private_bus_payload([*batch, data])
                    if batch and len(candidate.encode("utf-8")) > self._MAX_NOTIFY_BYTES:
                        await self._pg_sender(self._private_bus_payload(batch))
                        batch = []
                    if len(self._private_bus_payload([data]).encode("utf-8")) > self._MAX_NOTIFY_BYTES:
                        logger.error("Evento individual SSE excedeu o limite do barramento")
                        continue
                    batch.append(data)
                if batch:
                    await self._pg_sender(self._private_bus_payload(batch))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Algumas exceções SQL incluem parâmetros da consulta. Não
                # registre o payload privado (token/hash) junto do diagnóstico.
                logger.error(
                    "Falha no barramento SSE individual tipo=%s; nova tentativa agendada",
                    type(exc).__name__,
                )
                # Repetições mantêm event_id e são eliminadas pelo receptor. Se
                # houver estado mais recente do mesmo dono, ele tem prioridade.
                for key, data in pending.items():
                    if key not in self._pending_private:
                        self._queue_private(data)
                await asyncio.sleep(0.5)

    def _private_bus_payload(self, events: List[dict]) -> str:
        return json.dumps({
            "kind": "reservation_batch", "origin_pid": self._pid, "events": events,
        }, ensure_ascii=False, separators=(",", ":"))

    async def _publish_public_states(self, interval: float):
        while True:
            await self._dirty_signal.wait()
            await asyncio.sleep(interval)
            self._dirty_signal.clear()
            dirty, self._dirty_lotes = self._dirty_lotes, set()
            self._invalidate_cache()
            reconcile = self._private_reconciliation_pending
            self._private_reconciliation_pending = False
            delivered_all = True
            for lote_id in dirty:
                try:
                    status = await self._snapshot_loader(lote_id)
                    public_status = {
                        key: value for key, value in status.items()
                        if key in self._PUBLIC_STATUS_FIELDS
                    }
                    data = {
                        "tipo": "reservas_atualizadas", "lote_id": lote_id, **public_status,
                    }
                    if reconcile:
                        data["reconciliar_reservas"] = True
                    delivered = await self.broadcast("LOTE_ATUALIZADO", data, invalidate_cache=False)
                    if not delivered:
                        delivered_all = False
                        self._dirty_lotes.add(lote_id)
                        self._dirty_signal.set()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    delivered_all = False
                    logger.exception("Falha ao recalcular o estado público do lote %s", lote_id)
                    self._dirty_lotes.add(lote_id)
                    self._dirty_signal.set()
            if reconcile and not delivered_all:
                self._private_reconciliation_pending = True

    def register_pg_sender(self, sender_func: Callable):
        self._pg_sender = sender_func

    def register_cache_invalidator(self, invalidator_func: Callable):
        self._cache_invalidator = invalidator_func

    @property
    def total_subscribers(self) -> int:
        return len(self._listeners)


lote_event_hub = LoteEventHub()
