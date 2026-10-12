import unittest
import asyncio
import json
import secrets
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from app.core.config import settings
from app.routers.resgate import (
    assinar_browser_token,
    validar_browser_token,
    hash_token,
    COOKIE_BROWSER_ID
)

# Engine dedicado para testes de integração com NullPool para evitar conexões presas entre event loops
test_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)

LOTE_ID_TESTE = 999
LOTE_ID_CROSS = 998
LOTE_ID_ULTIMA_VAGA = 997


class TestReservaPostgresIntegracao(unittest.IsolatedAsyncioTestCase):
    """
    Suíte Completa de Testes de Integração Concorrentes com PostgreSQL Real (festa_db) e FastAPI:
    1. Expiração sob throttle de 3s (CPF) adquire nova reserva sem conflito no índice parcial.
    2. Expiração sob throttle de 3s (Navegador) adquire nova reserva sem conflito.
    3. Concorrência real de 2 requisições vinculando o mesmo CPF (ThreadPoolExecutor).
    4. Concorrência real de 2 requisições com a mesma identidade de navegador.
    5. Concorrência real de 2 requisições simultâneas em lotes diferentes.
    6. Concorrência real na disputa pela última vaga disponível (5 workers simultâneos).
    7. Suporte a NAT com 150 participantes legítimos no mesmo IP sem bloqueio.
    8. Proteção ativa contra flood script que excede o limite calibrado (300 req/min).
    9. Cookie forjado é descartado e reemitido assinado via HMAC-SHA256.
    10. Anti-hijacking: navegador distinto não pode operar reserva de terceiro (403).
    11. Falha recuperável (foto inválida) preserva reserva ativa.
    12. Falha definitiva libera reserva secundária e preserva reserva primária.
    """

    BASE_URL = "http://127.0.0.1:8000"

    async def asyncSetUp(self):
        async with test_engine.begin() as conn:
            # Garante que os lotes de teste dedicados existam e Lote 1 NUNCA seja alterado
            await conn.execute(text("""
                INSERT INTO lotes (id, nome, quantidade_total, quantidade_resgatada, ativo, data_abertura, data_fechamento)
                VALUES (:lote_id, 'Lote Teste Integracao', 300, 0, true, '2026-01-01 00:00:00', '2026-12-31 23:59:59')
                ON CONFLICT (id) DO UPDATE SET ativo = true, quantidade_total = 300, quantidade_resgatada = 0, data_abertura = '2026-01-01 00:00:00';
            """), {"lote_id": LOTE_ID_TESTE})

            await conn.execute(text("DELETE FROM rate_limit_tentativas WHERE ip LIKE '192.168.%' OR ip LIKE '10.0.%' OR ip LIKE '187.65.%' OR ip = '127.0.0.1';"))
            await conn.execute(text("""
                DELETE FROM reservas_ingressos 
                WHERE token LIKE 'test-%' 
                   OR lote_id IN (:l1, :l2, :l3)
                   OR cpf IN ('52998224725', '85111094393', '63420847777', '35651962034', '26473861025', '12345678909', '70912345672');
            """), {"l1": LOTE_ID_TESTE, "l2": LOTE_ID_CROSS, "l3": LOTE_ID_ULTIMA_VAGA})

    async def asyncTearDown(self):
        async with test_engine.begin() as conn:
            await conn.execute(text("DELETE FROM rate_limit_tentativas WHERE ip LIKE '192.168.%' OR ip LIKE '10.0.%' OR ip LIKE '187.65.%' OR ip = '127.0.0.1';"))
            await conn.execute(text("""
                DELETE FROM reservas_ingressos 
                WHERE token LIKE 'test-%' 
                   OR lote_id IN (:l1, :l2, :l3)
                   OR cpf IN ('52998224725', '85111094393', '63420847777', '35651962034', '26473861025', '12345678909', '70912345672');
            """), {"l1": LOTE_ID_TESTE, "l2": LOTE_ID_CROSS, "l3": LOTE_ID_ULTIMA_VAGA})
            await conn.execute(text("DELETE FROM lotes WHERE id IN (:l1, :l2, :l3);"), {"l1": LOTE_ID_TESTE, "l2": LOTE_ID_CROSS, "l3": LOTE_ID_ULTIMA_VAGA})

    # =========================================================================
    # 1. EXPIRAÇÃO SOB THROTTLE E UNICIDADE NO POSTGRESQL
    # =========================================================================
    async def test_01_expiracao_sob_throttle_cpf_adquire_nova_reserva_sem_conflito(self):
        """
        Reproduz reserva com expira_em vencido que ainda conserva status = 'ativa'
        devido ao throttle de 3s. Garante que requisição com mesmo CPF adquire nova reserva
        sem colisão indevida no índice uq_reserva_cpf_ativa e sem permitir duas ativas.
        """
        cpf = "12345678909"
        agora = datetime.now()
        vencido = agora - timedelta(seconds=2)

        # Insere reserva R1 vencida com status = 'ativa'
        async with test_engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
                VALUES ('test-vencida-throttle-cpf', :lote_id, :criada, :vencido, 'ativa', :cpf, 'hash-throttle-cpf-1');
            """), {"lote_id": LOTE_ID_TESTE, "criada": vencido - timedelta(minutes=5), "vencido": vencido, "cpf": cpf})

        # Nova requisição HTTP com o mesmo CPF via API
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        req = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}?cpf={cpf}", headers={"Accept": "application/json"})
        resp = opener.open(req)
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode())
        novo_token = data.get("token_reserva")
        self.assertIsNotNone(novo_token)
        self.assertNotEqual(novo_token, "test-vencida-throttle-cpf")

        # Verifica no banco: R1 foi atualizada para 'expirada' e R2 está como 'ativa'
        async with test_engine.connect() as conn:
            r1_status = (await conn.execute(text("SELECT status FROM reservas_ingressos WHERE token = 'test-vencida-throttle-cpf'"))).scalar()
            r2_status = (await conn.execute(text("SELECT status FROM reservas_ingressos WHERE token = :t"), {"t": novo_token})).scalar()
            ativas_cpf = (await conn.execute(text("SELECT count(*) FROM reservas_ingressos WHERE cpf = :cpf AND status = 'ativa'"), {"cpf": cpf})).scalar()

        self.assertEqual(r1_status, "expirada")
        self.assertEqual(r2_status, "ativa")
        self.assertEqual(ativas_cpf, 1, "Nunca deve permitir mais de 1 reserva ativa por CPF")

    async def test_02_expiracao_sob_throttle_browser_adquire_nova_reserva_sem_conflito(self):
        """
        Reproduz reserva com expira_em vencido e status = 'ativa' vinculada a um browser.
        Garante que nova requisição do mesmo browser adquire nova reserva sem falso conflito.
        """
        payload_browser = secrets.token_urlsafe(32)
        cookie_assinado = assinar_browser_token(payload_browser)
        b_hash = hash_token(payload_browser)
        agora = datetime.now()
        vencido = agora - timedelta(seconds=2)

        # Insere reserva R1 vencida para este navegador
        async with test_engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, browser_token_hash)
                VALUES ('test-vencida-throttle-browser', :lote_id, :criada, :vencido, 'ativa', :b_hash);
            """), {"lote_id": LOTE_ID_TESTE, "criada": vencido - timedelta(minutes=5), "vencido": vencido, "b_hash": b_hash})

        # Nova requisição HTTP pelo mesmo navegador
        req = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}")
        req.add_header("Cookie", f"{COOKIE_BROWSER_ID}={cookie_assinado}")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            novo_token = data.get("token_reserva")

        self.assertIsNotNone(novo_token)
        self.assertNotEqual(novo_token, "test-vencida-throttle-browser")

        async with test_engine.connect() as conn:
            r1_status = (await conn.execute(text("SELECT status FROM reservas_ingressos WHERE token = 'test-vencida-throttle-browser'"))).scalar()
            r2_status = (await conn.execute(text("SELECT status FROM reservas_ingressos WHERE token = :t"), {"t": novo_token})).scalar()
            ativas_browser = (await conn.execute(text("SELECT count(*) FROM reservas_ingressos WHERE browser_token_hash = :h AND status = 'ativa'"), {"h": b_hash})).scalar()

        self.assertEqual(r1_status, "expirada")
        self.assertEqual(r2_status, "ativa")
        self.assertEqual(ativas_browser, 1, "Nunca deve permitir mais de 1 reserva ativa por navegador")

    # =========================================================================
    # 2. TESTES DE CONCORRÊNCIA REAL COM THREADPOOLEXECUTOR
    # =========================================================================
    async def test_03_concorrencia_real_dois_navegadores_mesmo_cpf(self):
        """
        Dois navegadores independentes tentam associar SIMULTANEAMENTE o mesmo CPF.
        Exatamente 1 deve ter sucesso; o outro deve ser rejeitado e ter sua vaga liberada.
        """
        cpf = "52998224725"

        # 1. Navegador 1 e Navegador 2 adquirem reservas R1 e R2
        cj1 = http.cookiejar.CookieJar()
        op1 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj1))
        tok1 = json.loads(op1.open(urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={"Accept": "application/json"})).read())["token_reserva"]

        cj2 = http.cookiejar.CookieJar()
        op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj2))
        tok2 = json.loads(op2.open(urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={"Accept": "application/json"})).read())["token_reserva"]

        self.assertNotEqual(tok1, tok2)

        # 2. Disparamos simultaneamente em threads reais a validação do mesmo CPF
        def associar_cpf(opener, tok):
            url = f"{self.BASE_URL}/api/resgate/validar-cpf?cpf={cpf}&token_reserva={tok}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            resp = opener.open(req)
            return json.loads(resp.read().decode())

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(associar_cpf, op1, tok1)
            fut2 = executor.submit(associar_cpf, op2, tok2)
            res1 = fut1.result()
            res2 = fut2.result()

        resultados = [res1.get("valido"), res2.get("valido")]
        self.assertEqual(resultados.count(True), 1, "Exatamente uma requisição concorrente deve ser válida")
        self.assertEqual(resultados.count(False), 1, "Exatamente uma requisição concorrente deve ser rejeitada")

        # Verifica no banco: a rejeitada deve estar 'cancelada' e a aceita como 'ativa'
        async with test_engine.connect() as conn:
            status1 = (await conn.execute(text("SELECT status FROM reservas_ingressos WHERE token = :t"), {"t": tok1})).scalar()
            status2 = (await conn.execute(text("SELECT status FROM reservas_ingressos WHERE token = :t"), {"t": tok2})).scalar()
            ativas_cpf = (await conn.execute(text("SELECT count(*) FROM reservas_ingressos WHERE cpf = :cpf AND status = 'ativa'"), {"cpf": cpf})).scalar()

        statuses = [status1, status2]
        self.assertIn("ativa", statuses)
        self.assertIn("cancelada", statuses)
        self.assertEqual(ativas_cpf, 1)

    async def test_04_concorrencia_real_mesmo_navegador_requisicoes_simultaneas(self):
        """
        Mesmo navegador dispara duas requisições simultâneas em paralelo para criar reserva.
        Garante que ambas completam com controle e exatamente 1 reserva ativa é persistida.
        """
        cookie_payload = secrets.token_urlsafe(32)
        cookie_val = assinar_browser_token(cookie_payload)
        b_hash = hash_token(cookie_payload)

        def requisitar():
            req = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={"Accept": "application/json"})
            req.add_header("Cookie", f"{COOKIE_BROWSER_ID}={cookie_val}")
            try:
                with urllib.request.urlopen(req) as resp:
                    return resp.status, json.loads(resp.read().decode())
            except urllib.error.HTTPError as err:
                return err.code, json.loads(err.read().decode())

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(requisitar)
            fut2 = executor.submit(requisitar)
            st1, d1 = fut1.result()
            st2, d2 = fut2.result()

        # Ambas devem ser 200 (re-atachamento) ou uma 200 e outra 409 controlada (sem 500)
        self.assertIn(st1, [200, 409])
        self.assertIn(st2, [200, 409])

        async with test_engine.connect() as conn:
            ativas = (await conn.execute(text("SELECT count(*) FROM reservas_ingressos WHERE browser_token_hash = :h AND status = 'ativa'"), {"h": b_hash})).scalar()

        self.assertEqual(ativas, 1, "Exatamente 1 reserva ativa deve existir para o navegador")

    async def test_05_concorrencia_real_mesmo_participante_lotes_diferentes(self):
        """
        Mesmo participante dispara simultaneamente requisição no Lote 998 e Lote 999.
        No máximo 1 lote pode conceder a reserva.
        """
        cpf = "70912345672"

        async with test_engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO lotes (id, nome, quantidade_total, quantidade_resgatada, ativo, data_abertura, data_fechamento)
                VALUES (:lote_id, 'Lote Cross Real', 50, 0, true, '2026-01-01 00:00:00', '2026-12-31 23:59:59')
                ON CONFLICT (id) DO UPDATE SET ativo = true, data_abertura = '2026-01-01 00:00:00';
            """), {"lote_id": LOTE_ID_CROSS})

        def requisitar_lote(lote_id):
            cj = http.cookiejar.CookieJar()
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            req = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{lote_id}?cpf={cpf}", headers={"Accept": "application/json"})
            try:
                res = op.open(req)
                return res.status, json.loads(res.read().decode())
            except urllib.error.HTTPError as err:
                return err.code, json.loads(err.read().decode())

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(requisitar_lote, LOTE_ID_TESTE)
            f2 = executor.submit(requisitar_lote, LOTE_ID_CROSS)
            st1, d1 = f1.result()
            st2, d2 = f2.result()

        status_codes = [st1, st2]
        # Pelo menos uma deve ter sido rejeitada com 400 ou 409
        self.assertTrue(400 in status_codes or 409 in status_codes, "Uma das requisições cross-lote deve ser rejeitada")
        self.assertNotIn(500, status_codes, "Nunca deve produzir erro 500")

        async with test_engine.connect() as conn:
            total_ativas = (await conn.execute(text("SELECT count(*) FROM reservas_ingressos WHERE cpf = :cpf AND status = 'ativa'"), {"cpf": cpf})).scalar()

        self.assertLessEqual(total_ativas, 1, "Nunca deve permitir reservas ativas em lotes diferentes")

    async def test_06_concorrencia_real_disputa_pela_ultima_vaga(self):
        """
        Disputa concorrente real pela última vaga (lote com capacidade total = 1).
        5 requisições simultâneas em paralelo: exatamente 1 obtém sucesso e 4 são rejeitadas com 400.
        """
        async with test_engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO lotes (id, nome, quantidade_total, quantidade_resgatada, ativo, data_abertura, data_fechamento)
                VALUES (:lote_id, 'Lote Ultima Vaga', 1, 0, true, '2026-01-01 00:00:00', '2026-12-31 23:59:59')
                ON CONFLICT (id) DO UPDATE SET ativo = true, quantidade_total = 1, quantidade_resgatada = 0, data_abertura = '2026-01-01 00:00:00';
            """), {"lote_id": LOTE_ID_ULTIMA_VAGA})

        def disputar():
            cj = http.cookiejar.CookieJar()
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            req = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_ULTIMA_VAGA}", headers={"Accept": "application/json"})
            try:
                res = op.open(req)
                return res.status, json.loads(res.read().decode())
            except urllib.error.HTTPError as err:
                return err.code, json.loads(err.read().decode())

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(disputar) for _ in range(5)]
            resultados = [f.result() for f in futures]

        status_list = [st for st, _ in resultados]
        sucessos_200 = status_list.count(200)
        rejeitados_400 = status_list.count(400)

        self.assertEqual(sucessos_200, 1, "Exatamente 1 participante deve ganhar a última vaga")
        self.assertEqual(rejeitados_400, 4, "Exatamente 4 participantes devem ser rejeitados")
        self.assertNotIn(500, status_list, "Zero erros 500 durante disputa concorrente")

        async with test_engine.connect() as conn:
            ativas = (await conn.execute(text("SELECT count(*) FROM reservas_ingressos WHERE lote_id = :l AND status = 'ativa'"), {"l": LOTE_ID_ULTIMA_VAGA})).scalar()

        self.assertEqual(ativas, 1)

    # =========================================================================
    # 3. RATE LIMITING EM NAT COM 150 PARTICIPANTES LEGÍTIMOS
    # =========================================================================
    async def test_07_rate_limit_nat_150_participantes_mesmo_ip_sem_bloqueio(self):
        """
        Valida que 150 participantes legítimos em rede compartilhada (NAT da prefeitura)
        compartilhando o mesmo IP público conseguem realizar requisições sem bloqueio coletivo indevido.
        """
        ip_compartilhado = "187.65.20.10"
        async with test_engine.begin() as conn:
            await conn.execute(text("DELETE FROM rate_limit_tentativas WHERE ip = :ip"), {"ip": ip_compartilhado})

        sucessos = 0
        bloqueios_429 = 0

        # Executa 150 requisições simulando servidores municipais distintos pelo mesmo gateway
        for i in range(150):
            cj = http.cookiejar.CookieJar()
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            req = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={
                "Accept": "application/json",
                "X-Forwarded-For": ip_compartilhado
            })
            try:
                res = op.open(req)
                if res.status == 200:
                    sucessos += 1
            except urllib.error.HTTPError as err:
                if err.code == 429:
                    bloqueios_429 += 1

        self.assertEqual(sucessos, 150, "Todos os 150 participantes legítimos em NAT devem conseguir reservar")
        self.assertEqual(bloqueios_429, 0, "Zero bloqueios indevidos 429 para participantes em rede compartilhada")

    async def test_08_rate_limit_nat_bloqueio_de_flood_acima_do_limite(self):
        """
        Valida que scripts automatizados de flood que ultrapassem o limite de 300 reqs/min
        a partir do mesmo IP são devidamente barrados com HTTP 429.
        """
        ip_flood = "187.65.99.99"
        agora = datetime.utcnow()

        # Pré-popula 300 tentativas para este IP na tabela compartilhada do PostgreSQL
        async with test_engine.begin() as conn:
            await conn.execute(text("DELETE FROM rate_limit_tentativas WHERE ip = :ip"), {"ip": ip_flood})
            inserts = [
                {"ip": ip_flood, "acao": "reserva", "ts": agora - timedelta(seconds=10)}
                for _ in range(300)
            ]
            await conn.execute(text("""
                INSERT INTO rate_limit_tentativas (ip, acao, criado_em)
                VALUES (:ip, :acao, :ts)
            """), inserts)

        # A 301ª requisição deve ser barrada com 429
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        req = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={
            "Accept": "application/json",
            "X-Forwarded-For": ip_flood
        })
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            op.open(req)

        self.assertEqual(ctx.exception.code, 429)
        err_data = json.loads(ctx.exception.read().decode())
        self.assertEqual(err_data.get("codigo"), "rate_limit")

    # =========================================================================
    # 4. VALIDAÇÃO DE IDENTIDADE, ANTI-HIJACKING E RECUPERABILIDADE
    # =========================================================================
    async def test_09_cookie_arbitrario_descartado_e_substituido_por_token_assinado(self):
        cookie_falso = "meu_cookie_forjado_sem_assinatura_valida"
        req = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}")
        req.add_header("Cookie", f"{COOKIE_BROWSER_ID}={cookie_falso}")
        req.add_header("Accept", "application/json")

        with urllib.request.urlopen(req) as resp:
            headers = resp.info()
            set_cookies = headers.get_all("Set-Cookie") or []

        cookie_emitido = None
        for cookie in set_cookies:
            if f"{COOKIE_BROWSER_ID}=" in cookie:
                cookie_emitido = cookie.split(f"{COOKIE_BROWSER_ID}=")[1].split(";")[0]
                break

        self.assertIsNotNone(cookie_emitido)
        self.assertNotEqual(cookie_emitido, cookie_falso)

        payload_validado = validar_browser_token(cookie_emitido)
        self.assertIsNotNone(payload_validado)
        self.assertGreaterEqual(len(payload_validado), 16)

    async def test_10_navegador_distinto_nao_pode_operar_reserva_alheia(self):
        cj1 = http.cookiejar.CookieJar()
        op1 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj1))
        req1 = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={"Accept": "application/json"})
        tok1 = json.loads(op1.open(req1).read())["token_reserva"]

        cj2 = http.cookiejar.CookieJar()
        op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj2))
        req2 = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={"Accept": "application/json"})
        tok2 = json.loads(op2.open(req2).read())["token_reserva"]

        post_data = urllib.parse.urlencode({"token_reserva": tok1}).encode("utf-8")
        req_desistir = urllib.request.Request(f"{self.BASE_URL}/api/resgate/desistir", data=post_data, headers={"Accept": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            op2.open(req_desistir)
        self.assertEqual(ctx.exception.code, 403)
        data = json.loads(ctx.exception.read().decode())
        self.assertFalse(data.get("sucesso"))

    async def test_11_falha_recuperavel_preserva_reserva_ativa(self):
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

        req = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={"Accept": "application/json"})
        tok = json.loads(opener.open(req).read())["token_reserva"]

        post_data = urllib.parse.urlencode({
            "token_reserva": tok,
            "cpf": "26473861025",
            "nome": "Servidor Teste",
            "data_nascimento": "1990-05-15",
            "setor": "Financeiro",
            "secretaria_id": "1",
            "vinculo": "Efetivo",
            "telefone": "(11) 99999-9999",
            "email": "servidor@teste.com",
            "foto_base64": "invalido_sem_data_image"
        }).encode("utf-8")

        req_post = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", data=post_data, headers={"Accept": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(req_post)
        self.assertEqual(ctx.exception.code, 400)

        async with test_engine.connect() as conn:
            st = (await conn.execute(text("SELECT status FROM reservas_ingressos WHERE token = :t"), {"t": tok})).scalar()
        self.assertEqual(st, "ativa")

    async def test_12_falha_definitiva_libera_reserva_secundaria(self):
        cpf = "35651962034"

        cj1 = http.cookiejar.CookieJar()
        op1 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj1))
        req1 = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={"Accept": "application/json"})
        tok1 = json.loads(op1.open(req1).read())["token_reserva"]
        req_val1 = urllib.request.Request(f"{self.BASE_URL}/api/resgate/validar-cpf?cpf={cpf}&token_reserva={tok1}", headers={"Accept": "application/json"})
        op1.open(req_val1)

        cj2 = http.cookiejar.CookieJar()
        op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj2))
        req2 = urllib.request.Request(f"{self.BASE_URL}/api/resgate/{LOTE_ID_TESTE}", headers={"Accept": "application/json"})
        tok2 = json.loads(op2.open(req2).read())["token_reserva"]

        req_val2 = urllib.request.Request(f"{self.BASE_URL}/api/resgate/validar-cpf?cpf={cpf}&token_reserva={tok2}", headers={"Accept": "application/json"})
        res2 = json.loads(op2.open(req_val2).read())
        self.assertFalse(res2["valido"])

        async with test_engine.connect() as conn:
            r1_status = (await conn.execute(text("SELECT status FROM reservas_ingressos WHERE token = :t"), {"t": tok1})).scalar()
            r2_status = (await conn.execute(text("SELECT status FROM reservas_ingressos WHERE token = :t"), {"t": tok2})).scalar()

        self.assertEqual(r1_status, "ativa")
        self.assertEqual(r2_status, "cancelada")


if __name__ == "__main__":
    unittest.main()
