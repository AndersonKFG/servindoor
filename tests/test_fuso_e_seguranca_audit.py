import unittest
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import (
    extrair_ip_cliente,
    is_ip_privado_ou_local,
    formatar_iso_sp,
    para_epoch_ms_sp,
    TZ_SAO_PAULO
)

test_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
LOTE_TESTE_FUSO_ID = 995


class TestFusoHorarioESegurancaAudit(unittest.IsolatedAsyncioTestCase):
    """
    Testes de Auditoria:
    1. Garantia de que a aplicação e o PostgreSQL operam estritamente no fuso America/Sao_Paulo.
    2. Simulação de cliente tentando forçar fuso horário UTC ou adulterado para tentar acesso antecipado.
    3. Bloqueio soberano de qualquer requisição antecipada pelo backend com HTTP 400.
    4. Proteção contra IP spoofing em cadeias de proxies reversos.
    """

    BASE_URL = "http://127.0.0.1:8000"

    async def asyncSetUp(self):
        async with test_engine.begin() as conn:
            # Cria lote com abertura no futuro (2 horas à frente no fuso de São Paulo)
            agora_sp = datetime.now()
            abertura_futura = agora_sp + timedelta(hours=2)
            fechamento_futuro = agora_sp + timedelta(days=2)

            await conn.execute(text("""
                INSERT INTO lotes (id, nome, quantidade_total, quantidade_resgatada, ativo, data_abertura, data_fechamento)
                VALUES (:lote_id, 'Lote Teste Fuso Futuro', 100, 0, true, :abertura, :fechamento)
                ON CONFLICT (id) DO UPDATE SET 
                    ativo = true, 
                    quantidade_total = 100, 
                    quantidade_resgatada = 0, 
                    data_abertura = :abertura, 
                    data_fechamento = :fechamento;
            """), {
                "lote_id": LOTE_TESTE_FUSO_ID,
                "abertura": abertura_futura,
                "fechamento": fechamento_futuro
            })

            await conn.execute(text("DELETE FROM reservas_ingressos WHERE lote_id = :lote_id;"), {"lote_id": LOTE_TESTE_FUSO_ID})

    async def asyncTearDown(self):
        async with test_engine.begin() as conn:
            await conn.execute(text("DELETE FROM reservas_ingressos WHERE lote_id = :lote_id;"), {"lote_id": LOTE_TESTE_FUSO_ID})
            await conn.execute(text("DELETE FROM lotes WHERE id = :lote_id;"), {"lote_id": LOTE_TESTE_FUSO_ID})

    # =========================================================================
    # 1. ALINHAMENTO DO POSTGRESQL COM AMERICA/SAO_PAULO
    # =========================================================================
    async def test_01_postgres_opera_estritamente_em_america_sao_paulo(self):
        """Verifica se o PostgreSQL (festa_db) retorna TimeZone = America/Sao_Paulo"""
        async with test_engine.connect() as conn:
            tz = (await conn.execute(text("SHOW timezone;"))).scalar()
            offset_str = (await conn.execute(text("SELECT to_char(NOW(), 'OF');"))).scalar()

        self.assertEqual(tz, "America/Sao_Paulo", "O PostgreSQL deve operar no fuso America/Sao_Paulo")
        self.assertEqual(offset_str, "-03", "Offset do PostgreSQL nativo deve ser -03 (America/Sao_Paulo)")

    # =========================================================================
    # 2. SERIALIZAÇÃO DA API COM TIMEZONE ESTABELECIDO (-03:00)
    # =========================================================================
    async def test_02_api_publica_serializa_iso_com_offset_sp_e_epoch_ms(self):
        """Garante que a API live-status retorna data_abertura_iso com -03:00 e data_abertura_ms"""
        url = f"{self.BASE_URL}/api/lote/live-status?lote_id={LOTE_TESTE_FUSO_ID}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())

        self.assertIn("data_abertura_iso", data)
        self.assertIn("data_abertura_ms", data)
        self.assertIn("server_timezone", data)
        self.assertEqual(data["server_timezone"], "America/Sao_Paulo")

        # Deve conter o offset explícito -03:00
        self.assertTrue(data["data_abertura_iso"].endswith("-03:00"), "ISO de abertura deve conter offset -03:00")
        self.assertIsInstance(data["data_abertura_ms"], int)
        self.assertGreater(data["data_abertura_ms"], data["server_time_ms"])

    # =========================================================================
    # 3. CLIENTE FORÇANDO FUSO HORÁRIO DIVERGENTE TENTANDO ACESSO ANTECIPADO
    # =========================================================================
    async def test_03_cliente_com_fuso_utc_nao_consegue_antecipar_horario(self):
        """
        Simula cliente configurado em fuso horário UTC (3 horas à frente de Brasília):
        Garante que, com a data serializada com -03:00, o parsing do cliente produz
        exatamente o mesmo timestamp absoluto em milissegundos que o servidor,
        mantendo o status como 'agendado' e impedindo abertura indevida.
        """
        url = f"{self.BASE_URL}/api/lote/live-status?lote_id={LOTE_TESTE_FUSO_ID}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        iso_abertura = data["data_abertura_iso"]
        server_time_ms = data["server_time_ms"]

        # Parse simulando navegador com timezone UTC
        dt_utc = datetime.fromisoformat(iso_abertura).astimezone(ZoneInfo("UTC"))
        abertura_ms_via_utc = int(dt_utc.timestamp() * 1000)

        # Parse simulando navegador com timezone Japão (UTC+9)
        dt_jst = datetime.fromisoformat(iso_abertura).astimezone(ZoneInfo("Asia/Tokyo"))
        abertura_ms_via_jst = int(dt_jst.timestamp() * 1000)

        # Parse oficial no servidor em São Paulo
        dt_sp = datetime.fromisoformat(iso_abertura).astimezone(TZ_SAO_PAULO)
        abertura_ms_sp = int(dt_sp.timestamp() * 1000)

        # Em QUALQUER fuso do planeta, o instante absoluto em ms é estritamente IDÊNTICO
        self.assertEqual(abertura_ms_via_utc, abertura_ms_sp)
        self.assertEqual(abertura_ms_via_jst, abertura_ms_sp)
        self.assertEqual(data["data_abertura_ms"], abertura_ms_sp)

        # O momento de abertura ainda NÃO chegou em nenhum fuso
        self.assertGreater(abertura_ms_sp, server_time_ms)
        self.assertEqual(data["status_slug"], "agendado")
        self.assertFalse(data["pode_resgatar"])

    async def test_04_bloqueio_soberano_de_requisicao_antecipada_pelo_backend(self):
        """
        Simula participante que altera relógio/fuso ou tenta chamar a API de resgate
        diretamente antes do horário de abertura.
        O backend DEVE rejeitar com HTTP 400 ('nao_iniciado') e zero vagas criadas.
        """
        url_resgate = f"{self.BASE_URL}/api/resgate/{LOTE_TESTE_FUSO_ID}"
        # Cliente tenta forjar headers de data/fuso para simular que já é o horário de abertura
        headers = {
            "Accept": "application/json",
            "X-Client-Timezone": "UTC",
            "X-Client-Date": (datetime.now() + timedelta(hours=3)).isoformat()
        }

        req = urllib.request.Request(url_resgate, headers=headers)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400, "Backend deve barrar com HTTP 400 requisições antes do horário")
        err_body = json.loads(ctx.exception.read().decode())
        self.assertEqual(err_body.get("codigo"), "nao_iniciado")
        self.assertIn("ainda não iniciou", err_body.get("detail", ""))

        # Verifica no PostgreSQL: NENHUMA reserva foi criada
        async with test_engine.connect() as conn:
            total_reservas = (await conn.execute(text("SELECT count(*) FROM reservas_ingressos WHERE lote_id = :l"), {"l": LOTE_TESTE_FUSO_ID})).scalar()

        self.assertEqual(total_reservas, 0, "Zero reservas podem ser persistidas para lote não iniciado")

    # =========================================================================
    # 4. PROTEÇÃO CONTRA IP SPOOFING EM PROXY REVERSO
    # =========================================================================
    def test_05_anti_spoofing_ignora_ip_forjado_em_x_forwarded_for(self):
        """
        Atacante injeta header X-Forwarded-For: 1.1.1.1, 187.65.20.10 através de proxy local.
        A aplicação deve selecionar o IP real de borda 187.65.20.10 e ignorar o spoofed 1.1.1.1.
        """
        class MockRequest:
            def __init__(self, host, headers):
                class Client:
                    def __init__(self, h): self.host = h
                self.client = Client(host)
                self.headers = headers

        req = MockRequest("172.18.0.1", {
            "x-forwarded-for": "1.1.1.1, 187.65.20.10, 10.0.0.1"
        })
        ip_resolvido = extrair_ip_cliente(req)
        self.assertEqual(ip_resolvido, "187.65.20.10", "Deve selecionar o IP público de borda real")

    def test_06_anti_spoofing_prioriza_x_real_ip_confiavel(self):
        """Proxy Nginx com X-Real-IP configurado tem prioridade estrita contra X-Forwarded-For adulterado"""
        class MockRequest:
            def __init__(self, host, headers):
                class Client:
                    def __init__(self, h): self.host = h
                self.client = Client(host)
                self.headers = headers

        req = MockRequest("127.0.0.1", {
            "x-real-ip": "189.40.10.2",
            "x-forwarded-for": "1.1.1.1, 2.2.2.2"
        })
        ip_resolvido = extrair_ip_cliente(req)
        self.assertEqual(ip_resolvido, "189.40.10.2")

    def test_07_anti_spoofing_sanitiza_conteudo_malformado(self):
        """Header X-Forwarded-For com injeção ou caracteres inválidos é descartado sem erro 500"""
        class MockRequest:
            def __init__(self, host, headers):
                class Client:
                    def __init__(self, h): self.host = h
                self.client = Client(host)
                self.headers = headers

        req = MockRequest("127.0.0.1", {
            "x-forwarded-for": "malicious; DROP TABLE usuarios, <script>alert(1)</script>"
        })
        ip_resolvido = extrair_ip_cliente(req)
        self.assertEqual(ip_resolvido, "127.0.0.1", "Deve fazer fallback seguro para host da conexão")


if __name__ == "__main__":
    unittest.main()
