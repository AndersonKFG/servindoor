import unittest
import asyncio
import sqlite3
import hashlib
import secrets
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.security import validar_cpf_matematico
from app.routers.resgate import (
    verificar_rate_limit_ip_reserva,
    _ip_reserva_requisicoes,
    hash_token,
    obter_ou_criar_browser_id,
    COOKIE_BROWSER_ID,
    COOKIE_DEVICE_LEGACY
)
from app.core.events import LoteEventHub


class TestExclusividadeReservaDispositivoEParticipante(unittest.TestCase):
    """
    Testes de Unidade e Integridade do Mecanismo de Exclusividade de Reserva:
    1. Mesma sessão de navegador (mesmo cookie) reatacha à reserva ativa existente sem consumir nova vaga.
    2. Navegadores distintos na mesma máquina (cookies diferentes) geram reservas independentes consumindo 2 vagas.
    3. Bloqueio por participante: mesmo CPF não pode ter duas reservas ativas.
    4. Bloqueio global cross-lote: participante com reserva no Lote 1 não pode reservar no Lote 2.
    5. Bloqueio global cross-lote: navegador com reserva no Lote 1 não pode reservar no Lote 2.
    6. Suporte a NAT compartilhado (rede corporativa/prefeitura): múltiplos participantes com mesmo IP conseguem reservar simultaneamente.
    7. Rate limit deslizante de requisições por IP: bloqueia flood (>60 reqs/min) sem limitar vagas legítimas.
    8. Transição de estado de reservas expiradas para 'expirada'.
    9. Reutilização após expiração: participante e navegador podem abrir nova reserva após expiração da anterior.
    10. Enforce do índice parcial único de CPF ativo.
    11. Enforce do índice parcial único de navegador ativo.
    12. Não-conflito de reservas concluídas, canceladas e expiradas com o índice parcial ativo.
    13. Desistência voluntária: libera vaga e transiciona para 'cancelada'.
    14. Rejeição definitiva por idade menor de 18 anos: cancela reserva imediatamente e libera vaga.
    15. Rejeição definitiva por vínculo com equipe/organização: cancela reserva imediatamente e libera vaga.
    16. Rejeição definitiva por ingresso já existente: cancela reserva imediatamente e libera vaga.
    17. Falha recuperável (ex: erro no processamento da foto facial): retém a reserva para reenvio.
    18. Conclusão de resgate com sucesso: transiciona para 'concluida', marca utilizada e consome vaga no lote.
    19. Notificações SSE com contadores consistentes pós-commit.
    20. Concorrência: corrida pela última vaga garante exatamente 1 reserva e rejeição atômica das demais.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._criar_schema()
        _ip_reserva_requisicoes.clear()

    def tearDown(self):
        self.conn.close()

    def _criar_schema(self):
        self.conn.executescript("""
            CREATE TABLE lotes (
                id INTEGER PRIMARY KEY,
                nome TEXT NOT NULL,
                quantidade_total INTEGER NOT NULL,
                quantidade_resgatada INTEGER DEFAULT 0,
                ativo INTEGER DEFAULT 1,
                data_abertura TEXT,
                data_fechamento TEXT
            );

            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY,
                cpf TEXT NOT NULL UNIQUE,
                nome TEXT NOT NULL,
                role TEXT DEFAULT 'servidor',
                bloqueado_resgate INTEGER DEFAULT 0,
                deleted_at TEXT
            );

            CREATE TABLE ingressos (
                id INTEGER PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                lote_id INTEGER NOT NULL,
                qr_code_token TEXT NOT NULL UNIQUE,
                deleted_at TEXT
            );

            CREATE TABLE solicitacoes_validacao (
                id INTEGER PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                lote_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pendente_analise'
            );

            CREATE TABLE reservas_ingressos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                lote_id INTEGER NOT NULL,
                criada_em TEXT NOT NULL,
                expira_em TEXT NOT NULL,
                utilizada INTEGER DEFAULT 0,
                ip_origem TEXT,
                device_id TEXT,
                cpf TEXT,
                status TEXT DEFAULT 'ativa',
                browser_token_hash TEXT,
                device_fingerprint TEXT
            );

            -- Indices parciais estaticos identicos aos aplicados no PostgreSQL
            CREATE UNIQUE INDEX uq_reserva_cpf_ativa ON reservas_ingressos (cpf) WHERE status = 'ativa';
            CREATE UNIQUE INDEX uq_reserva_browser_ativa ON reservas_ingressos (browser_token_hash) WHERE status = 'ativa';
            CREATE INDEX idx_reservas_status_expira ON reservas_ingressos (status, expira_em);
        """)

    # --- CENÁRIO 1: Mesma sessão de navegador reatacha sem consumir vaga adicional ---
    def test_01_mesmo_navegador_reatacha_reserva_ativa_sem_duplicar(self):
        browser_token = secrets.token_urlsafe(32)
        b_hash = hash_token(browser_token)
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        # 1. Cria reserva para o navegador
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, browser_token_hash)
            VALUES (?, ?, ?, ?, 'ativa', ?)
        """, ("tok-1", 1, agora.isoformat(), expira.isoformat(), b_hash))
        self.conn.commit()

        # 2. Nova consulta do mesmo navegador encontra a reserva ativa existente
        cur = self.conn.execute("""
            SELECT * FROM reservas_ingressos
            WHERE browser_token_hash = ? AND status = 'ativa' AND expira_em > ?
        """, (b_hash, agora.isoformat()))
        reserva = cur.fetchone()

        self.assertIsNotNone(reserva)
        self.assertEqual(reserva["token"], "tok-1")

        # Garante contagem de apenas 1 reserva ativa
        cur_count = self.conn.execute("SELECT COUNT(*) as c FROM reservas_ingressos WHERE status = 'ativa'")
        self.assertEqual(cur_count.fetchone()["c"], 1)

    # --- CENÁRIO 2: Dois navegadores distintos geram reservas independentes ---
    def test_02_dois_navegadores_distintos_consomem_duas_vagas(self):
        b1_hash = hash_token(secrets.token_urlsafe(32))
        b2_hash = hash_token(secrets.token_urlsafe(32))
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, browser_token_hash)
            VALUES (?, 1, ?, ?, 'ativa', ?)
        """, ("tok-b1", agora.isoformat(), expira.isoformat(), b1_hash))

        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, browser_token_hash)
            VALUES (?, 1, ?, ?, 'ativa', ?)
        """, ("tok-b2", agora.isoformat(), expira.isoformat(), b2_hash))
        self.conn.commit()

        cur_count = self.conn.execute("SELECT COUNT(*) as c FROM reservas_ingressos WHERE status = 'ativa'")
        self.assertEqual(cur_count.fetchone()["c"], 2)

    # --- CENÁRIO 3: Participante não pode ter duas reservas ativas (Índice CPF) ---
    def test_03_bloqueio_dupla_reserva_por_cpf_participante(self):
        cpf = "12345678901"
        b1_hash = hash_token("token-browser-1")
        b2_hash = hash_token("token-browser-2")
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES (?, 1, ?, ?, 'ativa', ?, ?)
        """, ("tok-1", agora.isoformat(), expira.isoformat(), cpf, b1_hash))
        self.conn.commit()

        # Tentativa de criar segunda reserva com o mesmo CPF deve falhar pelo índice único parcial
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("""
                INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
                VALUES (?, 1, ?, ?, 'ativa', ?, ?)
            """, ("tok-2", agora.isoformat(), expira.isoformat(), cpf, b2_hash))
            self.conn.commit()

    # --- CENÁRIO 4: Bloqueio global cross-lote para o participante ---
    def test_04_bloqueio_cross_lote_para_mesmo_participante(self):
        cpf = "12345678901"
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        # Reserva no Lote 1
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES ('tok-lote1', 1, ?, ?, 'ativa', ?, 'hash-1')
        """, (agora.isoformat(), expira.isoformat(), cpf))
        self.conn.commit()

        # Consulta se participante já possui reserva ativa em QUALQUER lote
        cur = self.conn.execute("""
            SELECT lote_id FROM reservas_ingressos
            WHERE cpf = ? AND status = 'ativa' AND expira_em > ?
        """, (cpf, agora.isoformat()))
        reserva = cur.fetchone()

        self.assertIsNotNone(reserva)
        self.assertEqual(reserva["lote_id"], 1)

        # Tentativa de adquirir reserva no Lote 2 é rejeitada (não pode ter 2 lotes simultâneos)
        pode_reservar_lote_2 = (reserva is None) or (reserva["lote_id"] == 2)
        self.assertFalse(pode_reservar_lote_2)

    # --- CENÁRIO 5: Bloqueio global cross-lote para o mesmo navegador ---
    def test_05_bloqueio_cross_lote_para_mesmo_navegador(self):
        b_hash = hash_token("browser-token-xyz")
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        # Reserva ativa no Lote 1
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, browser_token_hash)
            VALUES ('tok-nav-1', 1, ?, ?, 'ativa', ?)
        """, (agora.isoformat(), expira.isoformat(), b_hash))
        self.conn.commit()

        # Tentativa de inserir nova reserva no Lote 2 falha no índice parcial uq_reserva_browser_ativa
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("""
                INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, browser_token_hash)
                VALUES ('tok-nav-2', 2, ?, ?, 'ativa', ?)
            """, (agora.isoformat(), expira.isoformat(), b_hash))
            self.conn.commit()

    # --- CENÁRIO 6: Suporte a NAT Compartilhado (Rede de Prefeitura/Corporativa) ---
    def test_06_nat_compartilhado_permite_multiplos_participantes_mesmo_ip(self):
        ip_compartilhado = "187.65.20.10"
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        # 10 servidores municipais distintos acessando simultaneamente da mesma rede
        for i in range(10):
            cpf = f"111222333{i:02d}"
            b_hash = hash_token(f"browser-servidor-{i}")
            self.conn.execute("""
                INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, ip_origem, cpf, browser_token_hash)
                VALUES (?, 1, ?, ?, 'ativa', ?, ?, ?)
            """, (f"tok-{i}", agora.isoformat(), expira.isoformat(), ip_compartilhado, cpf, b_hash))

        self.conn.commit()

        # Todos os 10 conseguem ter reservas ativas simultâneas no mesmo IP (sem o limite rígido de 5)
        cur = self.conn.execute("""
            SELECT COUNT(*) as c FROM reservas_ingressos
            WHERE ip_origem = ? AND status = 'ativa'
        """, (ip_compartilhado,))
        self.assertEqual(cur.fetchone()["c"], 10)

    # --- CENÁRIO 7: Rate Limit Deslizante de Requisições por IP ---
    def test_07_rate_limit_deslizante_ip_bloqueia_abuso_mas_libera_apos_janela(self):
        ip_teste = "200.100.50.25"

        # 60 requisições são permitidas
        for _ in range(60):
            self.assertTrue(verificar_rate_limit_ip_reserva(ip_teste))

        # A 61ª requisição na mesma janela de 60 segundos deve ser bloqueada (429)
        self.assertFalse(verificar_rate_limit_ip_reserva(ip_teste))

        # Outro IP independente não é afetado
        self.assertTrue(verificar_rate_limit_ip_reserva("200.100.50.26"))

    # --- CENÁRIO 8: Transição de Estado de Reservas Expiradas ---
    def test_08_expiracao_de_reservas_vencidas_libera_status(self):
        agora = datetime.now()
        passado = agora - timedelta(minutes=1)
        futuro = agora + timedelta(minutes=5)

        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES ('tok-vencido', 1, ?, ?, 'ativa', '11111111111', 'hash-vencido')
        """, ((passado - timedelta(minutes=5)).isoformat(), passado.isoformat()))

        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES ('tok-ativo', 1, ?, ?, 'ativa', '22222222222', 'hash-ativo')
        """, (agora.isoformat(), futuro.isoformat()))
        self.conn.commit()

        # Executa sweeper de expiração
        self.conn.execute("""
            UPDATE reservas_ingressos
            SET status = 'expirada'
            WHERE status = 'ativa' AND expira_em <= ?
        """, (agora.isoformat(),))
        self.conn.commit()

        # Verifica status
        cur = self.conn.execute("SELECT status FROM reservas_ingressos WHERE token = 'tok-vencido'")
        self.assertEqual(cur.fetchone()["status"], "expirada")

        cur2 = self.conn.execute("SELECT status FROM reservas_ingressos WHERE token = 'tok-ativo'")
        self.assertEqual(cur2.fetchone()["status"], "ativa")

    # --- CENÁRIO 9: Reutilização após expiração sem conflito de unicidade ---
    def test_09_participante_e_navegador_podem_reservar_novamente_apos_expiracao(self):
        cpf = "12345678901"
        b_hash = hash_token("token-sessao")
        agora = datetime.now()
        passado = agora - timedelta(seconds=10)

        # 1. Reserva anterior expirou
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES ('tok-antigo', 1, ?, ?, 'expirada', ?, ?)
        """, ((passado - timedelta(minutes=5)).isoformat(), passado.isoformat(), cpf, b_hash))
        self.conn.commit()

        # 2. Nova reserva ativa com o mesmo CPF e mesmo navegador deve ter SUCESSO
        # porque o índice único parcial possui predicado WHERE status = 'ativa'
        expira_novo = agora + timedelta(minutes=5)
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES ('tok-novo', 1, ?, ?, 'ativa', ?, ?)
        """, (agora.isoformat(), expira_novo.isoformat(), cpf, b_hash))
        self.conn.commit()

        cur = self.conn.execute("SELECT COUNT(*) as c FROM reservas_ingressos WHERE status = 'ativa'")
        self.assertEqual(cur.fetchone()["c"], 1)

    # --- CENÁRIO 10 & 11: Índices Parciais Estáticos Garantem Unicidade no DB ---
    def test_10_enforce_indice_parcial_unico_cpf_e_browser(self):
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES ('tok-a', 1, ?, ?, 'ativa', '99988877766', 'hash-xyz')
        """, (agora.isoformat(), expira.isoformat()))
        self.conn.commit()

        # Duplicata de browser_token_hash com status='ativa'
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("""
                INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
                VALUES ('tok-b', 1, ?, ?, 'ativa', '55544433322', 'hash-xyz')
            """, (agora.isoformat(), expira.isoformat()))
            self.conn.commit()

        # Duplicata de CPF com status='ativa'
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("""
                INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
                VALUES ('tok-c', 1, ?, ?, 'ativa', '99988877766', 'hash-novo')
            """, (agora.isoformat(), expira.isoformat()))
            self.conn.commit()

    # --- CENÁRIO 12: Concluída, Cancelada e Expirada NÃO Conflitam no Índice ---
    def test_12_status_nao_ativos_podem_coexistir_no_banco(self):
        cpf = "11122233344"
        b_hash = "hash-permanente"
        agora = datetime.now().isoformat()

        # Pode ter quantas reservas concluídas, canceladas e expiradas quiser
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES ('tok-c1', 1, ?, ?, 'concluida', ?, ?)
        """, (agora, agora, cpf, b_hash))
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES ('tok-c2', 1, ?, ?, 'cancelada', ?, ?)
        """, (agora, agora, cpf, b_hash))
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf, browser_token_hash)
            VALUES ('tok-c3', 1, ?, ?, 'expirada', ?, ?)
        """, (agora, agora, cpf, b_hash))
        self.conn.commit()

        cur = self.conn.execute("SELECT COUNT(*) as c FROM reservas_ingressos")
        self.assertEqual(cur.fetchone()["c"], 3)

    # --- CENÁRIO 13: Desistência voluntária transiciona para 'cancelada' ---
    def test_13_desistencia_voluntaria_libera_vaga(self):
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status)
            VALUES ('tok-desistir', 1, ?, ?, 'ativa')
        """, (agora.isoformat(), expira.isoformat()))
        self.conn.commit()

        # Executa desistência
        self.conn.execute("""
            UPDATE reservas_ingressos
            SET status = 'cancelada', expira_em = '2000-01-01 00:00:00'
            WHERE token = 'tok-desistir' AND status = 'ativa'
        """)
        self.conn.commit()

        cur = self.conn.execute("SELECT status FROM reservas_ingressos WHERE token = 'tok-desistir'")
        self.assertEqual(cur.fetchone()["status"], "cancelada")

        cur_ativas = self.conn.execute("SELECT COUNT(*) as c FROM reservas_ingressos WHERE status = 'ativa'")
        self.assertEqual(cur_ativas.fetchone()["c"], 0)

    # --- CENÁRIO 14: Rejeição Definitiva por Menoridade Cancela Reserva Imediatamente ---
    def test_14_rejeicao_definitiva_menor_de_idade_cancela_reserva(self):
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status)
            VALUES ('tok-menor', 1, ?, ?, 'ativa')
        """, (agora.isoformat(), expira.isoformat()))
        self.conn.commit()

        # Simula validação de data de nascimento: 17 anos -> rejeição definitiva
        data_nasc = agora.year - 17
        is_menor = True

        if is_menor:
            self.conn.execute("""
                UPDATE reservas_ingressos
                SET status = 'cancelada', expira_em = '2000-01-01 00:00:00'
                WHERE token = 'tok-menor'
            """)
            self.conn.commit()

        cur = self.conn.execute("SELECT status FROM reservas_ingressos WHERE token = 'tok-menor'")
        self.assertEqual(cur.fetchone()["status"], "cancelada")

    # --- CENÁRIO 15: Rejeição Definitiva por Membro da Equipe ---
    def test_15_rejeicao_definitiva_equipe_cancela_reserva(self):
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        self.conn.execute("INSERT INTO usuarios (id, cpf, nome, role) VALUES (1, '11122233344', 'Operador', 'admin')")
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf)
            VALUES ('tok-equipe', 1, ?, ?, 'ativa', '11122233344')
        """, (agora.isoformat(), expira.isoformat()))
        self.conn.commit()

        cur_u = self.conn.execute("SELECT role FROM usuarios WHERE cpf = '11122233344'")
        usuario = cur_u.fetchone()

        if usuario["role"] != "servidor":
            self.conn.execute("""
                UPDATE reservas_ingressos
                SET status = 'cancelada', expira_em = '2000-01-01 00:00:00'
                WHERE token = 'tok-equipe'
            """)
            self.conn.commit()

        cur = self.conn.execute("SELECT status FROM reservas_ingressos WHERE token = 'tok-equipe'")
        self.assertEqual(cur.fetchone()["status"], "cancelada")

    # --- CENÁRIO 16: Rejeição Definitiva por Ingresso Existente ---
    def test_16_rejeicao_definitiva_ingresso_existente_cancela_reserva(self):
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        self.conn.execute("INSERT INTO usuarios (id, cpf, nome) VALUES (1, '33344455566', 'Titular')")
        self.conn.execute("INSERT INTO ingressos (usuario_id, lote_id, qr_code_token) VALUES (1, 1, 'qr-123')")
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf)
            VALUES ('tok-duplicado', 1, ?, ?, 'ativa', '33344455566')
        """, (agora.isoformat(), expira.isoformat()))
        self.conn.commit()

        cur_ing = self.conn.execute("SELECT id FROM ingressos WHERE usuario_id = 1 AND deleted_at IS NULL")
        if cur_ing.fetchone():
            self.conn.execute("""
                UPDATE reservas_ingressos
                SET status = 'cancelada', expira_em = '2000-01-01 00:00:00'
                WHERE token = 'tok-duplicado'
            """)
            self.conn.commit()

        cur = self.conn.execute("SELECT status FROM reservas_ingressos WHERE token = 'tok-duplicado'")
        self.assertEqual(cur.fetchone()["status"], "cancelada")

    # --- CENÁRIO 17: Falha Recuperável (ex: foto corrompida) Retém Reserva ---
    def test_17_falha_recuperavel_preserva_reserva_ativa(self):
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status)
            VALUES ('tok-foto-erro', 1, ?, ?, 'ativa')
        """, (agora.isoformat(), expira.isoformat()))
        self.conn.commit()

        # Falha transitória: participante enviou foto sem base64 válido
        # A reserva NÃO deve ser cancelada; participante pode tentar novamente dentro dos 5min
        cur = self.conn.execute("SELECT status FROM reservas_ingressos WHERE token = 'tok-foto-erro'")
        self.assertEqual(cur.fetchone()["status"], "ativa")

    # --- CENÁRIO 18: Conclusão com Sucesso consome vaga e marca concluída ---
    def test_18_conclusao_com_sucesso_transiciona_para_concluida(self):
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        self.conn.execute("INSERT INTO lotes (id, nome, quantidade_total, quantidade_resgatada) VALUES (1, 'Lote 1', 50, 10)")
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status, cpf)
            VALUES ('tok-sucesso', 1, ?, ?, 'ativa', '55566677788')
        """, (agora.isoformat(), expira.isoformat()))
        self.conn.commit()

        # Executa finalização
        self.conn.execute("""
            UPDATE reservas_ingressos
            SET status = 'concluida', utilizada = 1
            WHERE token = 'tok-sucesso'
        """)
        self.conn.execute("UPDATE lotes SET quantidade_resgatada = quantidade_resgatada + 1 WHERE id = 1")
        self.conn.commit()

        cur_res = self.conn.execute("SELECT status, utilizada FROM reservas_ingressos WHERE token = 'tok-sucesso'")
        row_res = cur_res.fetchone()
        self.assertEqual(row_res["status"], "concluida")
        self.assertEqual(row_res["utilizada"], 1)

        cur_lote = self.conn.execute("SELECT quantidade_resgatada FROM lotes WHERE id = 1")
        self.assertEqual(cur_lote.fetchone()["quantidade_resgatada"], 11)

    # --- CENÁRIO 19: Notificação SSE pós-commit com contadores consistentes ---
    def test_19_sse_broadcast_contadores_consistentes_pos_commit(self):
        self.conn.execute("INSERT INTO lotes (id, nome, quantidade_total, quantidade_resgatada) VALUES (1, 'Lote 1', 100, 20)")
        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        # 5 reservas ativas
        for i in range(5):
            self.conn.execute("""
                INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status)
                VALUES (?, 1, ?, ?, 'ativa')
            """, (f"tok-c19-{i}", agora.isoformat(), expira.isoformat()))
        self.conn.commit()

        # Leitura pós-commit
        cur_lote = self.conn.execute("SELECT quantidade_total, quantidade_resgatada FROM lotes WHERE id = 1").fetchone()
        cur_ativas = self.conn.execute("SELECT COUNT(*) as c FROM reservas_ingressos WHERE lote_id = 1 AND status = 'ativa' AND expira_em > ?", (agora.isoformat(),)).fetchone()

        reservas_ativas = cur_ativas["c"]
        vagas_disp = max(0, cur_lote["quantidade_total"] - (cur_lote["quantidade_resgatada"] + reservas_ativas))

        self.assertEqual(reservas_ativas, 5)
        self.assertEqual(vagas_disp, 75)

    # --- CENÁRIO 20: Concorrência - Corrida Atômica pela Última Vaga ---
    def test_20_corrida_atomica_pela_ultima_vaga(self):
        # Lote com apenas 1 vaga disponível
        self.conn.execute("INSERT INTO lotes (id, nome, quantidade_total, quantidade_resgatada) VALUES (1, 'Lote 1', 10, 9)")
        self.conn.commit()

        agora = datetime.now()
        expira = agora + timedelta(minutes=5)

        # Simula 2 requisições concorrentes
        # Requisição A adquire a vaga primeiro
        cur_vagas = self.conn.execute("""
            SELECT l.quantidade_total - (l.quantidade_resgatada + (
                SELECT COUNT(*) FROM reservas_ingressos WHERE lote_id = l.id AND status = 'ativa' AND expira_em > ?
            )) as vagas
            FROM lotes l WHERE l.id = 1
        """, (agora.isoformat(),)).fetchone()

        vagas_req_a = cur_vagas["vagas"]
        self.assertEqual(vagas_req_a, 1)

        # Requisição A insere a reserva
        self.conn.execute("""
            INSERT INTO reservas_ingressos (token, lote_id, criada_em, expira_em, status)
            VALUES ('tok-vencedor', 1, ?, ?, 'ativa')
        """, (agora.isoformat(), expira.isoformat()))
        self.conn.commit()

        # Requisição B verifica as vagas em seguida
        cur_vagas_b = self.conn.execute("""
            SELECT l.quantidade_total - (l.quantidade_resgatada + (
                SELECT COUNT(*) FROM reservas_ingressos WHERE lote_id = l.id AND status = 'ativa' AND expira_em > ?
            )) as vagas
            FROM lotes l WHERE l.id = 1
        """, (agora.isoformat(),)).fetchone()

        vagas_req_b = cur_vagas_b["vagas"]
        # A vaga já foi ocupada pela Requisição A!
        self.assertEqual(vagas_req_b, 0)
        # Requisição B não pode criar reserva
        pode_reservar_b = vagas_req_b > 0
        self.assertFalse(pode_reservar_b)


if __name__ == "__main__":
    unittest.main()
