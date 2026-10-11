import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Set, Dict, Any, Optional, Callable, List

logger = logging.getLogger(__name__)

class LoteEventHub:
    """
    Hub de transmissão Server-Sent Events (SSE) com suporte a múltiplos processos (Gunicorn multi-worker)
    via PostgreSQL LISTEN / NOTIFY e transmissão em memória para propagação instantânea (<50ms).
    Possui buffer de histórico de eventos e versionamento monotônico de estado para evitar qualquer
    gap ou perda de eventos entre a requisição inicial HTTP e o estabelecimento do stream.
    """
    def __init__(self):
        self._listeners: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._pg_sender: Optional[Callable] = None
        self._cache_invalidator: Optional[Callable] = None
        self._pid = os.getpid()
        self._state_version = int(time.time() * 1000)
        self._recent_events: deque = deque(maxlen=100)

    @property
    def state_version(self) -> int:
        return self._state_version

    def next_version(self) -> int:
        now_ms = int(time.time() * 1000)
        if now_ms <= self._state_version:
            self._state_version += 1
        else:
            self._state_version = now_ms
        return self._state_version

    async def subscribe(self) -> asyncio.Queue:
        """Registra um novo cliente SSE com fila assíncrona dedicada"""
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        async with self._lock:
            self._listeners.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue):
        """Remove o cliente SSE desconectado"""
        async with self._lock:
            self._listeners.discard(q)

    def _broadcast_local(self, payload: str, version: int, event_type: str, data: Dict[str, Any]):
        """Entrega o payload SSE para todos os clientes conectados a este worker e guarda no buffer histórico"""
        if self._cache_invalidator:
            try:
                self._cache_invalidator()
            except Exception:
                pass

        # Registra no buffer de replay com retenção dos últimos 100 eventos
        self._recent_events.append((version, event_type, data, payload))

        active_listeners = list(self._listeners)
        for q in active_listeners:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"Falha ao enviar evento SSE: {e}")

    async def broadcast(self, event_type: str, data: Dict[str, Any]):
        """
        Transmite o evento em formato Server-Sent Events (SSE) padrão para todos os clientes.
        Transmite localmente de imediato e, em ambiente multi-worker, dispara via PostgreSQL NOTIFY.
        Formato W3C SSE: event: <event_type>\nid: <version>\ndata: <json>\n\n
        """
        version = self.next_version()
        data_with_meta = dict(data)
        data_with_meta["state_version"] = version
        data_with_meta["timestamp_ms"] = int(time.time() * 1000)

        payload = f"event: {event_type}\nid: {version}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        self._broadcast_local(payload, version, event_type, data_with_meta)

        # Se houver barramento PostgreSQL ativo, propaga para os outros workers do Gunicorn
        if self._pg_sender:
            try:
                bus_msg = json.dumps({
                    "origin_pid": self._pid,
                    "event_type": event_type,
                    "data": data,
                    "version": version
                }, ensure_ascii=False)
                await self._pg_sender(bus_msg)
            except Exception as e:
                logger.debug(f"Falha na propagação inter-worker via PostgreSQL NOTIFY: {e}")

    def on_bus_notification(self, raw_json: str):
        """Recebe notificação de outro worker via PostgreSQL LISTEN e propaga aos clientes locais"""
        try:
            msg = json.loads(raw_json)
            # Evita duplicidade se este próprio worker foi quem emitiu
            if msg.get("origin_pid") == self._pid:
                return

            event_type = msg.get("event_type", "LOTE_ATUALIZADO")
            data = msg.get("data", {})
            version = msg.get("version", self.next_version())
            if version > self._state_version:
                self._state_version = version

            payload = f"id: {version}\nevent: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            self._broadcast_local(payload, version, event_type, data)
        except Exception as e:
            logger.debug(f"Erro ao processar notificação inter-worker: {e}")

    def get_events_since(self, last_version: Optional[int]) -> List[str]:
        """Recupera eventos que ocorreram após last_version para replay contínuo sem perda ou gap"""
        if not last_version:
            return []
        missed = []
        for ver, ev_type, data, payload in list(self._recent_events):
            if ver > last_version:
                missed.append(payload)
        return missed

    def register_pg_sender(self, sender_func: Callable):
        self._pg_sender = sender_func

    def register_cache_invalidator(self, invalidator_func: Callable):
        self._cache_invalidator = invalidator_func

    @property
    def total_subscribers(self) -> int:
        return len(self._listeners)

# Instância global do Hub de Eventos
lote_event_hub = LoteEventHub()
