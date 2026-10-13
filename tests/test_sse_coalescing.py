"""Contratos SSE de carga e privacidade; nenhum banco real é consultado."""
import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.events import LoteEventHub


def data_of(payload):
    return json.loads(next(line[6:] for line in payload.splitlines() if line.startswith("data: ")))


class TestReservationCoalescing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hub = LoteEventHub()

    async def asyncTearDown(self):
        await self.hub.stop_reservation_publisher()

    def change(self, number=1, **extra):
        return {
            "tipo": "reserva_criada", "lote_id": 99,
            "device_fingerprint": f"fp-{number}", "device_id": f"dev-{number}",
            "browser_token_hash": f"hash-{number}", "token_reserva": f"token-{number}",
            "expira_em_ms": 301000, "segundos_restantes": 300,
            **extra,
        }

    async def test_duas_mil_mudancas_geram_um_estado_publico_por_janela(self):
        queues = [await self.hub.subscribe(device_fingerprint=f"fp-{number}", lote_id=99)
                  for number in range(2000)]
        anonymous = await self.hub.subscribe()
        loaded = asyncio.Event()
        calls = []
        invalidations = []

        async def loader(lote_id):
            calls.append(lote_id)
            loaded.set()
            # Mesmo um carregador que retorne campos extras não pode vazar
            # tokens/identificadores na atualização pública agrupada.
            return {"status_slug": "reservado", "pode_resgatar": True,
                    "token_reserva": "secret", "device_fingerprint": "private",
                    "browser_token_hash": "private"}

        self.hub.register_cache_invalidator(lambda: invalidations.append(True))
        self.hub.start_reservation_publisher(loader, interval=0.02)
        for number in range(2000):
            self.hub.publish_reservation_change(self.change(number))
        self.assertEqual(anonymous.qsize(), 0)
        self.assertEqual(invalidations, [])
        self.assertTrue(all(q.qsize() == 1 for q in queues))
        await asyncio.wait_for(loaded.wait(), 2)
        public = data_of(await asyncio.wait_for(anonymous.get(), 1))
        self.assertEqual(calls, [99])
        self.assertEqual(len(invalidations), 1)
        self.assertEqual(public["tipo"], "reservas_atualizadas")
        self.assertEqual(public["status_slug"], "reservado")
        self.assertNotIn("token_reserva", public)
        self.assertNotIn("device_fingerprint", public)
        self.assertNotIn("browser_token_hash", public)
        self.assertTrue(all(q.qsize() == 2 for q in queues))

    async def test_token_somente_para_cookie_forte_e_replay_filtra_dono(self):
        version = self.hub.state_version
        strong = await self.hub.subscribe(browser_token_hash="hash-1", lote_id=99)
        fingerprint_only = await self.hub.subscribe(device_fingerprint="fp-1", lote_id=99)
        stranger = await self.hub.subscribe(device_fingerprint="fp-2", lote_id=99)
        other_lot = await self.hub.subscribe(browser_token_hash="hash-1", lote_id=100)
        self.hub.publish_reservation_change(self.change())
        owner_data = data_of(strong.get_nowait())
        fingerprint_data = data_of(fingerprint_only.get_nowait())
        self.assertEqual(owner_data["token_reserva"], "token-1")
        self.assertNotIn("token_reserva", fingerprint_data)
        self.assertNotIn("browser_token_hash", owner_data)
        self.assertEqual(fingerprint_data["expira_em_ms"], 301000)
        self.assertEqual(stranger.qsize(), 0)
        self.assertEqual(other_lot.qsize(), 0)
        self.assertEqual(self.hub.get_events_since(version), [])
        own_replay = self.hub.get_events_since(version, browser_token_hash="hash-1", lote_id=99)
        fp_replay = self.hub.get_events_since(version, device_fingerprint="fp-1", lote_id=99)
        self.assertEqual(data_of(own_replay[0])["token_reserva"], "token-1")
        self.assertNotIn("token_reserva", data_of(fp_replay[0]))

    async def test_publicacao_http_nao_espera_barramento_lento(self):
        sender_started = asyncio.Event()
        blocked = asyncio.Event()

        async def sender(payload):
            sender_started.set()
            await blocked.wait()

        self.hub.register_pg_sender(sender)
        self.hub.start_reservation_publisher(AsyncMock(return_value={}), interval=0.02)
        own = await self.hub.subscribe(device_fingerprint="fp-1")
        self.hub.publish_reservation_change(self.change())
        self.assertEqual(own.qsize(), 1)
        await asyncio.wait_for(sender_started.wait(), 1)
        self.hub.publish_reservation_change(self.change(2))
        self.assertIn(99, self.hub._dirty_lotes)
        blocked.set()

    async def test_particiona_notify_por_bytes_e_deduplica_eventos_entre_workers(self):
        remote = LoteEventHub()
        self.hub._pid = 101
        remote._pid = 202
        remote_owner = await remote.subscribe(browser_token_hash="hash-1")
        stranger = await remote.subscribe(device_fingerprint="fp-2")
        messages = []
        private_sent = asyncio.Event()

        async def sender(payload):
            self.assertLessEqual(len(payload.encode("utf-8")), self.hub._MAX_NOTIFY_BYTES)
            messages.append(payload)
            remote.on_bus_notification(payload)
            remote.on_bus_notification(payload)
            if json.loads(payload).get("kind") == "reservation_batch":
                private_sent.set()

        self.hub.register_pg_sender(sender)
        self.hub.start_reservation_publisher(AsyncMock(return_value={}), interval=1)
        for number in range(80):
            self.hub.publish_reservation_change(self.change(number, motivo="ç" * 250))
        await asyncio.wait_for(private_sent.wait(), 1)
        batches = [json.loads(msg) for msg in messages if json.loads(msg).get("kind") == "reservation_batch"]
        self.assertGreater(len(batches), 1)
        self.assertEqual(sum(len(batch["events"]) for batch in batches), 80)
        self.assertEqual(remote_owner.qsize(), 1)
        self.assertEqual(stranger.qsize(), 1)
        self.assertEqual(data_of(remote_owner.get_nowait())["token_reserva"], "token-1")
        self.assertNotIn("token_reserva", data_of(stranger.get_nowait()))

    async def test_fila_limitada_e_estado_mais_recente_por_dispositivo(self):
        self.hub._MAX_PENDING_PRIVATE = 3
        for number in range(3):
            self.hub.publish_reservation_change(self.change(number))
        self.hub.publish_reservation_change(self.change(1, tipo="reserva_liberada"))
        self.assertEqual(len(self.hub._pending_private), 3)
        latest = list(self.hub._pending_private.values())[-1]
        self.assertEqual(latest["tipo"], "reserva_liberada")
        with self.assertLogs("app.core.events", level="WARNING"):
            self.hub.publish_reservation_change(self.change(4))
        self.assertEqual(len(self.hub._pending_private), 3)

    async def test_barramento_reenvia_falha_transitoria_sem_duplicar_entrega(self):
        remote = LoteEventHub()
        remote._pid = self.hub._pid + 1
        owner = await remote.subscribe(device_fingerprint="fp-1")
        delivered = asyncio.Event()
        attempts = 0

        async def sender(payload):
            nonlocal attempts
            if json.loads(payload).get("kind") != "reservation_batch":
                return
            attempts += 1
            remote.on_bus_notification(payload)
            if attempts == 1:
                # O remetente pode perder a confirmação depois de o receptor
                # já ter recebido a mensagem. A repetição mantém o mesmo ID.
                raise RuntimeError("confirmação de transporte perdida")
            delivered.set()

        self.hub.register_pg_sender(sender)
        self.hub.start_reservation_publisher(AsyncMock(return_value={}), interval=0.02)
        with self.assertLogs("app.core.events", level="ERROR"):
            self.hub.publish_reservation_change(self.change())
            await asyncio.wait_for(delivered.wait(), 2)
        self.assertEqual(attempts, 2)
        self.assertEqual(owner.qsize(), 1)
        self.assertEqual(data_of(owner.get_nowait())["tipo"], "reserva_criada")

    async def test_overflow_individual_solicita_snapshot_na_publicacao_agrupada(self):
        self.hub._MAX_PENDING_PRIVATE = 3
        public = await self.hub.subscribe()
        self.hub.start_reservation_publisher(AsyncMock(return_value={}), interval=0.01)
        with self.assertLogs("app.core.events", level="WARNING"):
            for number in range(4):
                self.hub.publish_reservation_change(self.change(number))
        state = data_of(await asyncio.wait_for(public.get(), 1))
        self.assertTrue(state["reconciliar_reservas"])
        self.assertTrue(public._sse_needs_snapshot)

    async def test_expiracao_em_lote_agenda_so_estado_publico(self):
        owner = await self.hub.subscribe(device_fingerprint="fp-1")
        loader = AsyncMock(return_value={"status_slug": "aberto"})
        self.hub.start_reservation_publisher(loader, interval=0.01)
        self.hub.mark_reservation_lot_dirty(99)
        self.hub.mark_reservation_lot_dirty(99)
        self.assertEqual(owner.qsize(), 0)
        self.assertEqual(len(self.hub._pending_private), 0)
        public = data_of(await asyncio.wait_for(owner.get(), 1))
        self.assertEqual(public["tipo"], "reservas_atualizadas")
        loader.assert_awaited_once_with(99)

    async def test_falha_transitoria_de_snapshot_preserva_mudanca_pendente(self):
        ready = asyncio.Event()
        attempts = 0

        async def loader(lote_id):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("indisponibilidade simulada")
            ready.set()
            return {"status_slug": "aberto"}

        self.hub.start_reservation_publisher(loader, interval=0.01)
        with self.assertLogs("app.core.events", level="ERROR"):
            self.hub.publish_reservation_change(self.change())
            await asyncio.wait_for(ready.wait(), 1)
        self.assertEqual(attempts, 2)
        self.assertTrue(all(not task.done() for task in self.hub._publisher_tasks))

    async def test_nova_mudanca_durante_snapshot_nao_e_perdida(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        second = asyncio.Event()
        calls = 0

        async def loader(lote_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            else:
                second.set()
            return {}

        self.hub.start_reservation_publisher(loader, interval=0.01)
        self.hub.publish_reservation_change(self.change())
        await asyncio.wait_for(entered.wait(), 1)
        self.hub.publish_reservation_change(self.change(2))
        release.set()
        await asyncio.wait_for(second.wait(), 1)
        self.assertEqual(calls, 2)

    async def test_evento_admin_continua_imediato_e_versao_bus_local_monotonica(self):
        queue = await self.hub.subscribe()
        await self.hub.broadcast("LOTE_ATUALIZADO", {"tipo": "pausado", "lote_id": 99})
        first = data_of(queue.get_nowait())
        self.hub.on_bus_notification(json.dumps({
            "origin_pid": self.hub._pid + 1, "event_type": "LOTE_ATUALIZADO",
            "version": first["state_version"] - 1000,
            "data": {"tipo": "aberto", "event_id": "remote-1"},
        }))
        second = data_of(queue.get_nowait())
        self.assertGreater(second["state_version"], first["state_version"])
        self.assertEqual(second["event_id"], "remote-1")

    async def test_shutdown_cancela_publishers_e_remove_indices_de_assinante(self):
        queue = await self.hub.subscribe(device_fingerprint="fp-1", browser_token_hash="hash-1")
        self.hub.start_reservation_publisher(AsyncMock(return_value={}))
        tasks = list(self.hub._publisher_tasks)
        self.hub.publish_reservation_change(self.change())
        await self.hub.stop_reservation_publisher()
        await self.hub.unsubscribe(queue)
        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual(self.hub._identity_listeners, {})
        self.assertEqual(len(self.hub._pending_private), 0)


class TestPublicSnapshotCoalescing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.routers import public
        from starlette.requests import Request
        self.public = public
        self.request = Request({"type": "http", "method": "GET", "path": "/api/lote/stream",
                                "headers": [], "query_string": b""})
        self.hub = LoteEventHub()
        self.patch = patch.object(public, "lote_event_hub", self.hub)
        self.patch.start()
        public._live_status_cache.clear()

    async def asyncTearDown(self):
        self.patch.stop()
        self.public._live_status_cache.clear()

    async def test_snapshot_publico_compartilhado_sem_serializar_leitura_individual(self):
        calls = 0
        active = 0
        max_active = 0

        async def base(session, request, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return {"has_lote": True, "id": 99, "status_slug": "aberto"}

        async def own(session, request, lote_id, device_id, now):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"minha_reserva_token": device_id}

        with patch.object(self.public, "_coletar_base_live_status", base), \
                patch.object(self.public, "_obter_prazo_reserva_sse", own):
            results = await asyncio.gather(*(
                self.public.coletar_dados_live_status(object(), self.request, lote_id=99, device_id=str(i))
                for i in range(50)
            ))
        self.assertEqual(calls, 1)
        self.assertGreater(max_active, 1)
        self.assertEqual([r["minha_reserva_token"] for r in results], [str(i) for i in range(50)])
        self.assertNotIn("minha_reserva_token", self.public._live_status_cache["base_status_99"]["content"])

    async def test_evento_durante_snapshot_tem_versao_posterior_e_nao_vaza_token(self):
        session = AsyncMock()

        async def collector(session, request, **kwargs):
            self.hub.publish_reservation_change({
                "tipo": "reserva_criada", "lote_id": 99,
                "device_fingerprint": "fp-1", "token_reserva": "private",
            })
            return {"has_lote": True, "id": 99, "state_version": self.hub.state_version}

        with patch.object(self.public, "coletar_dados_live_status", collector):
            response = await self.public.stream_lote_eventos(
                self.request, last_version=self.hub.state_version + 1000,
                device_fingerprint="fp-1", lote_id=99, session=session,
            )
        await anext(response.body_iterator)
        snapshot = data_of(await anext(response.body_iterator))
        future = data_of(await asyncio.wait_for(anext(response.body_iterator), 1))
        self.assertGreater(future["state_version"], snapshot["state_version"])
        self.assertNotIn("token_reserva", future)
        session.close.assert_awaited_once()
        await response.body_iterator.aclose()
        self.assertEqual(self.hub.total_subscribers, 0)

    async def test_cookie_legado_simples_nao_autoriza_token_no_snapshot(self):
        from starlette.requests import Request
        request = Request({"type": "http", "method": "GET", "path": "/api/lote/stream",
                           "headers": [(b"cookie", b"festa_device_id=known-legacy-device")],
                           "query_string": b""})
        now = datetime.now(timezone.utc)
        reservation = SimpleNamespace(
            token="must-not-leak", device_id="known-legacy-device",
            browser_token_hash="signed-owner-hash",
            criada_em=now - timedelta(seconds=5), expira_em=now + timedelta(minutes=5),
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [reservation]
        session = AsyncMock()
        session.execute.return_value = result
        prazo = await self.public._obter_prazo_reserva_sse(session, request, 99, None, now)
        self.assertIsNone(prazo["minha_reserva_token"])
        self.assertEqual(prazo["minha_reserva_segundos"], 300)

    async def test_overflow_da_fila_reconcilia_snapshot_com_sessao_curta(self):
        session = AsyncMock()
        reconciliation_session = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__.return_value = reconciliation_session
        calls = []

        async def collector(current_session, request, **kwargs):
            calls.append(current_session)
            return {"has_lote": True, "id": 99, "state_version": self.hub.state_version,
                    "nome": f"snapshot-{len(calls)}"}

        with patch.object(self.public, "coletar_dados_live_status", collector), \
                patch.object(self.public, "async_session", factory):
            response = await self.public.stream_lote_eventos(
                self.request, last_version=None, device_fingerprint="fp-1", lote_id=99, session=session,
            )
            await anext(response.body_iterator)
            first = data_of(await anext(response.body_iterator))
            for number in range(60):
                await self.hub.broadcast("LOTE_ATUALIZADO", {"lote_id": 99, "seq": number})
            second = data_of(await asyncio.wait_for(anext(response.body_iterator), 1))
            await response.body_iterator.aclose()
        self.assertEqual(first["nome"], "snapshot-1")
        self.assertEqual(second["nome"], "snapshot-2")
        self.assertEqual(calls, [session, reconciliation_session])
        factory.return_value.__aexit__.assert_awaited_once()
        self.assertEqual(self.hub.total_subscribers, 0)

    async def test_cookie_assinado_do_dono_recupera_token_no_snapshot(self):
        from starlette.requests import Request
        from app.routers.resgate import assinar_browser_token, hash_token
        browser_id = "signed-browser-owner-123456789"
        cookie = assinar_browser_token(browser_id)
        request = Request({"type": "http", "method": "GET", "path": "/api/lote/stream",
                           "headers": [(b"cookie", f"festa_browser_id={cookie}".encode())],
                           "query_string": b""})
        now = datetime.now(timezone.utc)
        reservation = SimpleNamespace(
            token="owned-token", device_id="dev-1", browser_token_hash=hash_token(browser_id),
            criada_em=now - timedelta(seconds=5), expira_em=now + timedelta(minutes=5),
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [reservation]
        session = AsyncMock()
        session.execute.return_value = result
        prazo = await self.public._obter_prazo_reserva_sse(session, request, 99, None, now)
        self.assertEqual(prazo["minha_reserva_token"], "owned-token")


if __name__ == "__main__":
    unittest.main()
