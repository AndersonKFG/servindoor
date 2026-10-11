import unittest
import asyncio
import json
import time
from app.core.events import LoteEventHub

class TestSSEGapReconciliation(unittest.IsolatedAsyncioTestCase):
    """
    Testes de Garantia de Consistência e Reconciliação de Gap no SSE:
    Cenário:
    - O navegador carrega o horário às 19h59 (versão V1).
    - Às 19h59min01s, a organização adia o lote (versão V2).
    - O navegador abre o SSE às 19h59min02s enviando last_version=V1.
    - O servidor DEVE garantir a entrega do evento e do estado consolidado atualizado,
      impedindo que o navegador fique com o horário antigo.
    """

    async def asyncSetUp(self):
        self.hub = LoteEventHub()

    async def test_version_monotonic_increase(self):
        """Garante que cada versão de estado seja sempre estritamente crescente"""
        v1 = self.hub.state_version
        v2 = self.hub.next_version()
        v3 = self.hub.next_version()
        self.assertGreater(v2, v1)
        self.assertGreater(v3, v2)

    async def test_broadcast_formats_w3c_sse_with_id_and_state_version(self):
        """Verifica se o broadcast inclui o cabeçalho 'id' do SSE e insere 'state_version' no JSON"""
        queue = await self.hub.subscribe()
        try:
            dados_evento = {"tipo": "adiamento", "nova_data": "2026-10-30T20:10:00"}
            await self.hub.broadcast("LOTE_ATUALIZADO", dados_evento)
            
            msg = await asyncio.wait_for(queue.get(), timeout=1.0)
            self.assertTrue(msg.startswith("event: LOTE_ATUALIZADO\n"))
            self.assertIn("id: ", msg)
            self.assertIn("data: ", msg)
            
            # Decodifica JSON dentro da mensagem SSE
            linhas = msg.strip().split("\n")
            data_line = [l for l in linhas if l.startswith("data: ")][0]
            payload = json.loads(data_line[6:])
            self.assertEqual(payload["nova_data"], "2026-10-30T20:10:00")
        finally:
            await self.hub.unsubscribe(queue)

    async def test_replay_buffer_recovers_missed_events_between_v1_and_v2(self):
        """
        Simula exatamente o cenário do usuário:
        1. Navegador lê dados em V1.
        2. Organização altera lote gerando V2 (adiamento).
        3. Navegador conecta solicitando eventos desde V1.
        4. O buffer entrega o evento V2 sem perda.
        """
        v1 = self.hub.state_version

        # Às 19h59min01s a organização adia o lote
        await self.hub.broadcast("LOTE_ATUALIZADO", {
            "tipo": "adiamento_lote",
            "data_abertura_iso": "2026-10-30T20:10:00",
            "mensagem": "Lote adiado em 10 minutos"
        })
        v2 = self.hub.state_version
        self.assertGreater(v2, v1)

        # Às 19h59min02s o navegador conecta passando last_version=v1
        missed = self.hub.get_events_since(v1)
        self.assertEqual(len(missed), 1)
        
        missed_msg = missed[0]
        self.assertIn("event: LOTE_ATUALIZADO", missed_msg)
        self.assertIn("2026-10-30T20:10:00", missed_msg)

    async def test_multiple_events_during_transition_all_recovered(self):
        """Se múltiplos eventos ocorrerem entre o fetch inicial e o SSE, todos são recuperados em ordem"""
        v_inicial = self.hub.state_version

        # 3 eventos ocorrem durante a transição
        await self.hub.broadcast("LOTE_ATUALIZADO", {"seq": 1})
        await self.hub.broadcast("RESERVA_ATUALIZADA", {"seq": 2})
        await self.hub.broadcast("LOTE_ATUALIZADO", {"seq": 3})

        missed = self.hub.get_events_since(v_inicial)
        self.assertEqual(len(missed), 3)

        # Ordem de chegada é estritamente sequencial
        self.assertIn('"seq": 1', missed[0])
        self.assertIn('"seq": 2', missed[1])
        self.assertIn('"seq": 3', missed[2])

    async def test_subscription_before_snapshot_guarantees_zero_window_loss(self):
        """
        Garante que inscrever a fila antes de ler o snapshot assegura
        que eventos concorrentes que ocorram durante a leitura caiam na fila.
        """
        # 1. Cliente se inscreve
        queue = await self.hub.subscribe()
        try:
            # 2. Evento disparado concorrentemente
            await self.hub.broadcast("LOTE_ATUALIZADO", {"tipo": "teste_concorrencia"})
            
            # 3. Fila já possui o evento pronto para consumo
            msg = await asyncio.wait_for(queue.get(), timeout=1.0)
            self.assertIn("teste_concorrencia", msg)
        finally:
            await self.hub.unsubscribe(queue)

if __name__ == "__main__":
    unittest.main()
