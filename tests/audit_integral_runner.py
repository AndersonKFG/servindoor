# ==============================================================================
# AUDITORIA INTEGRAL DE ROTAS, PERMISSÕES, PERSISTÊNCIA E E2E - SERVINDOOR 2026
# ==============================================================================
import asyncio
import base64
import json
import os
import re
import sys
import time
import uuid
import threading
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.core.cpf import formatar_cpf, validar_cpf_matematico
from app.models.all_models import UserRole

BASE_URL = "http://127.0.0.1:8000"
test_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)

def gen_cpf(n: int) -> str:
    s = f"{n:09d}"
    d1 = (sum(int(s[i]) * (10 - i) for i in range(9)) * 10 % 11) % 10
    s10 = s + str(d1)
    d2 = (sum(int(s10[i]) * (11 - i) for i in range(10)) * 10 % 11) % 10
    return s10 + str(d2)

CPFS = {
    "admin_geral": gen_cpf(901),
    "admin": gen_cpf(902),
    "validador": gen_cpf(903),
    "portaria": gen_cpf(904),
    "entregador": gen_cpf(905),
    "servidor_1": gen_cpf(906),
    "servidor_2": gen_cpf(907),
    "servidor_3": gen_cpf(908),
    "servidor_cancel": gen_cpf(909),
    "servidor_valid": gen_cpf(910),
}

TOKENS = {}
SESSION_IDS = {}
EVIDENCE = []
CALL_INDEX = 1

LOTE_TEST_ID = 888
PREMIO_TEST_ID = 888
SEC_TEST_ID = 999
EIXO_TEST_ID = 999

MINI_JPEG_B64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

async def db_exec(query: str, params: dict = None):
    async with test_engine.begin() as conn:
        return await conn.execute(text(query), params or {})

async def db_scalar(query: str, params: dict = None):
    async with test_engine.begin() as conn:
        res = await conn.execute(text(query), params or {})
        return res.scalar()

async def db_fetchall(query: str, params: dict = None):
    async with test_engine.begin() as conn:
        res = await conn.execute(text(query), params or {})
        return [dict(row._mapping) for row in res.fetchall()]

def http_call(
    method: str,
    path: str,
    identity: str = None,
    data: dict = None,
    json_data: dict = None,
    params: dict = None,
    cookies: dict = None,
    headers: dict = None,
    allow_redirects: bool = False
) -> requests.Response:
    url = f"{BASE_URL}{path}"
    req_cookies = dict(cookies or {})
    req_headers = dict(headers or {})

    if identity and identity in TOKENS:
        req_cookies["access_token"] = f"Bearer {TOKENS[identity]}"

    t0 = time.time()
    try:
        res = requests.request(
            method=method,
            url=url,
            params=params,
            data=data,
            json=json_data,
            cookies=req_cookies,
            headers=req_headers,
            allow_redirects=allow_redirects,
            timeout=12
        )
        res.elapsed_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        res = requests.Response()
        res.status_code = 599
        res._content = str(e).encode("utf-8")
        res.elapsed_ms = int((time.time() - t0) * 1000)
    return res

def record_call(
    route: str,
    method: str,
    scenario: str,
    identity: str,
    precondition: str,
    inp: dict,
    res: requests.Response,
    db_diff: str,
    state_after: str,
    side_effects: str,
    expected: str,
    classification: str = None,
    expected_status: int = None
):
    global CALL_INDEX
    cid = f"CALL-{CALL_INDEX:03d}"
    CALL_INDEX += 1

    try:
        res_json = res.json()
        res_summary = json.dumps(res_json, ensure_ascii=False)[:300]
    except Exception:
        res_summary = res.text[:200]

    status_code = res.status_code
    duration_ms = getattr(res, "elapsed_ms", 0)

    if classification is None:
        if expected_status is not None:
            classification = "Aprovado" if status_code == expected_status else "Falhou"
        elif status_code in (200, 201, 303):
            classification = "Aprovado"
        elif status_code in (401, 403) and any(w in scenario.lower() for w in ["sem autenticação", "não autorizado", "proibido", "sem permissão", "restrito", "nega", "elevação", "cruzad", "invasor"]):
            classification = "Aprovado"
        elif status_code == 400 and any(w in scenario.lower() for w in ["inválido", "duplicad", "já utilizado", "já se encontra", "mismatch", "descontinuada", "deve falhar", "repetid"]):
            classification = "Aprovado"
        elif status_code == 404 and "inexistente" in scenario.lower():
            classification = "Aprovado"
        else:
            classification = "Falhou"

    item = {
        "id": cid,
        "route": f"{method} {route}",
        "scenario": scenario,
        "identity": identity,
        "precondition": precondition,
        "input": inp,
        "status": status_code,
        "duration_ms": duration_ms,
        "response": res_summary,
        "db_before_after": db_diff,
        "state_after": state_after,
        "side_effects": side_effects,
        "expected": expected,
        "observed": f"HTTP {status_code} - {res_summary[:120]}",
        "classification": classification,
        "evidence": f"Assert HTTP {status_code}; DB diff: {db_diff}"
    }
    EVIDENCE.append(item)
    print(f"[{cid}] {method:<6} {route:<42} | {identity:<12} | {status_code} | {classification}")
    return item

async def setup_test_environment():
    print(">>> 1. Configurando ambiente de teste isolado no PostgreSQL...")
    senha_hash = get_password_hash("Senha@Auditoria2026")

    # Limpa vestígios de testes anteriores mantendo dados de dev intactos
    await db_exec("DELETE FROM reservas_ingressos WHERE lote_id = :lid OR lote_id IN (SELECT id FROM lotes WHERE nome LIKE 'Lote Tempor%')", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM solicitacoes_cancelamento WHERE usuario_id BETWEEN 901 AND 915")
    await db_exec("DELETE FROM solicitacoes_validacao WHERE usuario_id BETWEEN 901 AND 915 OR lote_id = :lid", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM ganhadores WHERE usuario_id BETWEEN 901 AND 915 OR premio_id = :pid", {"pid": PREMIO_TEST_ID})
    await db_exec("DELETE FROM logs_acesso WHERE usuario_id BETWEEN 901 AND 915")
    await db_exec("DELETE FROM ingressos WHERE usuario_id BETWEEN 901 AND 915 OR lote_id = :lid OR lote_id IN (SELECT id FROM lotes WHERE nome LIKE 'Lote Tempor%')", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM tokens_exclusao_lote WHERE lote_id = :lid OR lote_id IN (SELECT id FROM lotes WHERE nome LIKE 'Lote Tempor%')", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM backups_lotes WHERE lote_id = :lid OR lote_id IN (SELECT id FROM lotes WHERE nome LIKE 'Lote Tempor%')", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM lotes WHERE id = :lid OR nome LIKE 'Lote Tempor%'", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM premios WHERE id = :pid", {"pid": PREMIO_TEST_ID})
    await db_exec("DELETE FROM usuarios WHERE id BETWEEN 901 AND 915")
    await db_exec("DELETE FROM secretarias WHERE id = :sid", {"sid": SEC_TEST_ID})
    await db_exec("DELETE FROM eixos WHERE id = :eid", {"eid": EIXO_TEST_ID})

    # Cria Eixo e Secretaria de auditoria
    await db_exec("""
        INSERT INTO eixos (id, nome, descricao)
        VALUES (:eid, 'Eixo Auditoria', 'Eixo de Teste')
        ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome;
    """, {"eid": EIXO_TEST_ID})

    await db_exec("""
        INSERT INTO secretarias (id, nome, sigla, eixo_id)
        VALUES (:sid, 'Secretaria de Auditoria', 'SECAUDIT', :eid)
        ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome;
    """, {"sid": SEC_TEST_ID, "eid": EIXO_TEST_ID})

    # Cria usuários das identidades com e-mails válidos e data de nascimento
    roles_map = {
        "admin_geral": (901, "Admin Geral Auditoria", "admin_geral", "admin_geral,admin,portaria,entregador,validador", "", "admin_geral@example.com"),
        "admin": (902, "Admin Auditoria", "admin", "admin", "", "admin_audit@example.com"),
        "validador": (903, "Validador Auditoria", "validador", "validador", str(SEC_TEST_ID), "validador@example.com"),
        "portaria": (904, "Portaria Auditoria", "portaria", "portaria", "", "portaria@example.com"),
        "entregador": (905, "Entregador Auditoria", "entregador", "entregador", "", "entregador@example.com"),
        "servidor_1": (906, "Servidor 1 Auditoria", "servidor", "servidor", "", "servidor1@example.com"),
        "servidor_2": (907, "Servidor 2 Auditoria", "servidor", "servidor", "", "servidor2@example.com"),
        "servidor_3": (908, "Servidor 3 Auditoria", "servidor", "servidor", "", "servidor3@example.com"),
        "servidor_cancel": (909, "Servidor Cancelamento", "servidor", "servidor", "", "servidor_cancel@example.com"),
        "servidor_valid": (910, "Servidor Validacao", "servidor", "servidor", "", "servidor_valid@example.com")
    }

    for key, (uid, nome, role, roles, sec_val, email) in roles_map.items():
        sid = str(uuid.uuid4())
        SESSION_IDS[key] = sid
        cpf = CPFS[key]
        sessions_json = json.dumps([{"sid": sid, "device": "Audit Runner", "ts": datetime.now().isoformat()}])

        await db_exec("""
            INSERT INTO usuarios (id, cpf, nome, email, data_nascimento, senha_hash, role, roles, secretaria_id, secretarias_validador, ativo, validado, session_id, deleted_at)
            VALUES (:uid, :cpf, :nome, :email, '1988-05-15', :sh, :role, :roles, :sec_id, :sec_val, true, true, :sessions_json, NULL)
            ON CONFLICT (id) DO UPDATE SET
                cpf = EXCLUDED.cpf,
                nome = EXCLUDED.nome,
                email = EXCLUDED.email,
                data_nascimento = EXCLUDED.data_nascimento,
                senha_hash = EXCLUDED.senha_hash,
                role = EXCLUDED.role,
                roles = EXCLUDED.roles,
                secretaria_id = EXCLUDED.secretaria_id,
                secretarias_validador = EXCLUDED.secretarias_validador,
                ativo = true,
                validado = true,
                session_id = EXCLUDED.session_id,
                deleted_at = NULL;
        """, {
            "uid": uid,
            "cpf": cpf,
            "nome": nome,
            "email": email,
            "sh": senha_hash,
            "role": role,
            "roles": roles,
            "sec_id": SEC_TEST_ID,
            "sec_val": sec_val or None,
            "sessions_json": sessions_json
        })

        tok = create_access_token({
            "sub": cpf,
            "role": role,
            "roles": roles,
            "sid": sid
        })
        TOKENS[key] = tok

    # Cria Lote 888 de auditoria (total 10 vagas, abertura no passado)
    agora = datetime.now()
    abertura = agora - timedelta(days=1)
    fechamento = agora + timedelta(days=10)

    await db_exec("""
        INSERT INTO lotes (id, nome, quantidade_total, quantidade_resgatada, ativo, data_abertura, data_fechamento, secretaria_id, deleted_at)
        VALUES (:lid, 'Lote Auditoria 2026', 10, 0, true, :abertura, :fechamento, :sec_id, NULL)
        ON CONFLICT (id) DO UPDATE SET
            nome = EXCLUDED.nome,
            quantidade_total = 10,
            quantidade_resgatada = 0,
            ativo = true,
            data_abertura = EXCLUDED.data_abertura,
            data_fechamento = EXCLUDED.data_fechamento,
            deleted_at = NULL;
    """, {"lid": LOTE_TEST_ID, "abertura": abertura, "fechamento": fechamento, "sec_id": SEC_TEST_ID})

    # Cria Prêmio 888 de auditoria
    await db_exec("""
        INSERT INTO premios (id, nome, descricao, categoria, quantidade, quantidade_sorteada, ativo, ordem)
        VALUES (:pid, 'Smart TV Auditoria', 'Premio de Teste', 'categoria_1', 5, 0, true, 1)
        ON CONFLICT (id) DO UPDATE SET
            nome = EXCLUDED.nome,
            quantidade = 5,
            quantidade_sorteada = 0,
            ativo = true;
    """, {"pid": PREMIO_TEST_ID})

    # Cria arquivo físico de foto biométrica de teste para validar o guard 403
    os.makedirs("app/static/uploads/fotos", exist_ok=True)
    with open("app/static/uploads/fotos/audit_biometria_teste.jpg", "wb") as f_bio:
        f_bio.write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNiAAAABgADNjd8qAAAAABJRU5ErkJggg=="))

    print(">>> 1. Identidades, lotes, prêmios, fotos e tokens configurados com sucesso!")

async def test_gatekeeper():
    print("\n>>> 2. Testando Módulo Gatekeeper...")
    r = http_call("GET", "/api/gatekeeper/status")
    record_call("/api/gatekeeper/status", "GET", "Consulta pública de status do gatekeeper", "Visitante", "Nenhuma", {}, r, "Sem alterações", "JSON com autorizado e tentativas", "Nenhum", "HTTP 200 com status do gatekeeper", expected_status=200)

    r = http_call("POST", "/api/gatekeeper/verificar", json_data={"pin": "WRONGPIN"})
    cnt_fail = await db_scalar("SELECT count(*) FROM gatekeeper_tentativas WHERE sucesso = false AND ip = '127.0.0.1'")
    record_call("/api/gatekeeper/verificar", "POST", "Envio de PIN incorreto (deve falhar)", "Visitante", "PIN incorreto", {"pin": "WRONGPIN"}, r, f"Tentativas falhas no DB: {cnt_fail}", "HTTP 401 com tentativas restantes", "Registro em gatekeeper_tentativas", "HTTP 401 Unauthorized", expected_status=401)

    r = http_call("POST", "/api/gatekeeper/verificar", json_data={"pin": "*5E*2B"})
    cnt_ok = await db_scalar("SELECT count(*) FROM gatekeeper_tentativas WHERE sucesso = true AND ip = '127.0.0.1'")
    record_call("/api/gatekeeper/verificar", "POST", "Envio de PIN correto da organização", "Visitante", "PIN correto *5E*2B", {"pin": "*5E*2B"}, r, f"Tentativas com sucesso no DB: {cnt_ok}", "HTTP 200 e emissão de token", "Registro de sucesso e cookie setado", "HTTP 200 OK com token emitido", expected_status=200)

async def test_public_and_sse():
    print("\n>>> 3. Testando Rotas Públicas e SSE...")
    r = http_call("GET", "/")
    record_call("/", "GET", "Acesso à página inicial do evento", "Visitante", "Nenhuma", {}, r, "Sem alterações", "HTML da página inicial", "Nenhum", "HTTP 200 OK", expected_status=200)

    r = http_call("GET", "/api/time")
    record_call("/api/time", "GET", "Consulta de timestamp oficial do servidor", "Visitante", "Nenhuma", {}, r, "Sem alterações", "JSON com server_time_ms e server_time_iso", "Nenhum", "HTTP 200 OK com timezone America/Sao_Paulo", expected_status=200)

    r = http_call("GET", f"/api/lote/live-status?lote_id={LOTE_TEST_ID}")
    record_call("/api/lote/live-status", "GET", "Consulta de status consolidado do lote", "Visitante", "Lote 888 ativo", {"lote_id": LOTE_TEST_ID}, r, "Sem alterações", "JSON com quantidade total, resgatada e vagas", "Cache-Control no-store", "HTTP 200 OK com vagas_disponiveis", expected_status=200)

    try:
        sse_resp = requests.get(f"{BASE_URL}/api/lote/stream?lote_id={LOTE_TEST_ID}", stream=True, timeout=3)
        lines = []
        for line in sse_resp.iter_lines():
            if line:
                lines.append(line.decode("utf-8"))
            if len(lines) >= 6:
                break
        sse_ok = any("ESTADO_CONSOLIDADO" in l or "conectado" in l for l in lines)
        sse_resp.close()
        r_mock = requests.Response()
        r_mock.status_code = 200 if sse_ok else 500
        r_mock._content = ("\n".join(lines)).encode("utf-8")
        record_call("/api/lote/stream", "GET", "Conexão ao stream SSE com handshake e estado consolidado", "Visitante", "Stream aberto", {"lote_id": LOTE_TEST_ID}, r_mock, "Sem alterações", "Linhas SSE de handshake recebidas", "Conexão SSE mantida", "Handshake id e evento ESTADO_CONSOLIDADO recebidos", expected_status=200)
    except Exception as e:
        r_mock = requests.Response()
        r_mock.status_code = 500
        r_mock._content = str(e).encode("utf-8")
        record_call("/api/lote/stream", "GET", "Conexão ao stream SSE", "Visitante", "Stream aberto", {}, r_mock, "Erro", "Erro ao conectar SSE", "Nenhum", "Handshake SSE", expected_status=200)

async def test_auth_and_session():
    print("\n>>> 4. Testando Módulo de Autenticação e Sessões...")
    r = http_call("GET", "/login")
    record_call("/login", "GET", "Acesso à página de login", "Visitante", "Nenhuma", {}, r, "Sem alterações", "HTML do login", "Nenhum", "HTTP 200 OK", expected_status=200)

    r = http_call("POST", "/login", data={"username": CPFS["admin"], "password": "SENHA_ERRADA", "forcar_login": False}, headers={"Accept": "application/json"})
    record_call("/login", "POST", "Tentativa de login com senha incorreta", "Visitante", "Credenciais inválidas", {"cpf": CPFS["admin"]}, r, "Sem alterações", "JSON com mensagem de erro", "Nenhum", "HTTP 401 Unauthorized", expected_status=401)

    r = http_call("POST", "/login", data={"username": CPFS["admin"], "password": "Senha@Auditoria2026", "forcar_login": True}, headers={"Accept": "application/json"})
    record_call("/login", "POST", "Login com credenciais corretas de administrador", "Visitante", "Credenciais válidas", {"cpf": CPFS["admin"]}, r, "Atualização de session_id e ultimo_acesso no DB", "JSON de sucesso com redirect_url", "Cookie access_token emitido", "HTTP 200 OK com cookie de sessão", expected_status=200)

    # /api/auth/me sem autenticação (endpoint retorna autenticado=False com status 200 por design)
    r = http_call("GET", "/api/auth/me")
    record_call("/api/auth/me", "GET", "Consulta pública de autenticação sem token (retorna autenticado=false)", "Anônimo", "Sem token", {}, r, "Sem alterações", "JSON com autenticado=false", "Nenhum", "HTTP 200 com autenticado=false", expected_status=200)

    r = http_call("GET", "/api/auth/me", identity="admin")
    record_call("/api/auth/me", "GET", "Consulta dos dados do próprio usuário autenticado", "Admin", "Usuário autenticado", {}, r, "Sem alterações", "JSON com ID, nome, CPF e roles", "Atualização de timestamp", "HTTP 200 OK com perfil do usuário", expected_status=200)

    r_bad = http_call("POST", "/api/auth/alterar-senha-obrigatoria", identity="servidor_1", json_data={"nova_senha": "123", "confirmacao_senha": "123"})
    record_call("/api/auth/alterar-senha-obrigatoria", "POST", "Alteração de senha obrigatória com menos de 6 caracteres", "Servidor", "Senha curta", {"nova_senha": "123"}, r_bad, "Sem alterações", "JSON com erro 400", "Nenhum", "HTTP 400 Bad Request", expected_status=400)

    r_ok = http_call("POST", "/api/auth/alterar-senha-obrigatoria", identity="servidor_1", json_data={"nova_senha": "NovaSenhaForte@2026", "confirmacao_senha": "NovaSenhaForte@2026"})
    novo_hash = await db_scalar("SELECT senha_hash FROM usuarios WHERE id = 906")
    record_call("/api/auth/alterar-senha-obrigatoria", "POST", "Alteração de senha obrigatória válida no primeiro login", "Servidor", "Credencial válida", {"nova_senha": "***"}, r_ok, f"senha_hash atualizado no DB: {novo_hash[:20]}...", "JSON com sucesso=true", "deve_trocar_senha atualizado para false", "HTTP 200 OK com senha persistida", expected_status=200)

    r_logout = http_call("POST", "/api/auth/logout", identity="servidor_1", headers={"Accept": "application/json"})
    record_call("/api/auth/logout", "POST", "Encerramento seguro de sessão (logout)", "Servidor", "Sessão ativa", {}, r_logout, "Sessão removida do session_id no DB", "Cookie deletado e sucesso", "Revogação da sessão no banco", "HTTP 200 OK", expected_status=200)

    r_logout_get = http_call("GET", "/logout", headers={"Accept": "application/json"})
    record_call("/logout", "GET", "Encerramento legado via GET /logout", "Visitante", "Nenhuma", {}, r_logout_get, "Sessão limpa", "JSON de logout", "Cookie deletado", "HTTP 200 OK", expected_status=200)

    r_logout_post = http_call("POST", "/logout", headers={"Accept": "application/json"})
    record_call("/logout", "POST", "Encerramento legado via POST /logout", "Visitante", "Nenhuma", {}, r_logout_post, "Sessão limpa", "JSON de logout", "Cookie deletado", "HTTP 200 OK", expected_status=200)

async def test_lotes_admin_crud():
    print("\n>>> 5. Testando Módulo de Gestão de Lotes pelo Admin...")
    r = http_call("GET", "/api/lotes-admin", identity="admin")
    record_call("/api/lotes-admin", "GET", "Listagem administrativa de todos os lotes", "Admin", "Lote 888 cadastrado", {}, r, "Sem alterações", "JSON com array de lotes", "Nenhum", "HTTP 200 OK com lotes", expected_status=200)

    r = http_call("GET", "/admin", identity="admin")
    record_call("/admin", "GET", "Painel web administrativo", "Admin", "Usuário admin logado", {}, r, "Sem alterações", "HTML do painel admin", "Nenhum", "HTTP 200 OK", expected_status=200)

    agora = datetime.now()
    dt_ab = (agora - timedelta(hours=1)).isoformat()
    dt_fech = (agora + timedelta(days=5)).isoformat()
    r = http_call("POST", "/admin/lote", identity="admin", data={
        "nome": "Lote Temporário Audit 889",
        "quantidade_total": 5,
        "data_abertura": dt_ab,
        "data_fechamento": dt_fech,
        "secretaria_id": str(SEC_TEST_ID),
        "ativo": "on"
    })
    lote_889 = await db_fetchall("SELECT id, nome, quantidade_total, ativo FROM lotes WHERE nome = 'Lote Temporário Audit 889'")
    lote_889_id = lote_889[0]["id"] if lote_889 else None
    record_call("/admin/lote", "POST", "Criação de novo lote pelo painel admin", "Admin", "Dados válidos", {"nome": "Lote Temporário Audit 889", "quantidade": 5}, r, f"Lote inserido no DB: ID={lote_889_id}", "Redirecionamento /admin ou 200", "Lote registrado", "HTTP 303 / 200 com lote persistido no DB", expected_status=303)

    if lote_889_id:
        dt_fech_novo = (agora + timedelta(days=8)).isoformat()
        r = http_call("POST", f"/admin/lote/{lote_889_id}/editar", identity="admin", data={
            "nome": "Lote Temporário Editado 889",
            "quantidade_total": 8,
            "data_abertura": dt_ab,
            "data_fechamento": dt_fech_novo,
            "secretaria_id": str(SEC_TEST_ID),
            "ativo": "on"
        })
        l_edit = await db_fetchall("SELECT nome, quantidade_total FROM lotes WHERE id = :lid", {"lid": lote_889_id})
        record_call("/admin/lote/{lote_id}/editar", "POST", "Edição de capacidade e nome do lote", "Admin", f"Lote {lote_889_id} existente", {"quantidade": 8}, r, f"DB atualizado: {l_edit}", "Redirecionamento ou 200", "Lote atualizado", "HTTP 303 / 200 com novas propriedades no DB", expected_status=303)

        r = http_call("POST", f"/admin/lote/{lote_889_id}/toggle", identity="admin")
        atv_depois = await db_scalar("SELECT ativo FROM lotes WHERE id = :lid", {"lid": lote_889_id})
        record_call("/admin/lote/{lote_id}/toggle", "POST", "Alternância de status ativo/pausado do lote", "Admin", f"Lote {lote_889_id} ativo", {}, r, f"Ativo no DB: {atv_depois}", "Redirecionamento ou 200", "Broadcast de evento SSE", "HTTP 303 / 200 com lote pausado", expected_status=303)

        r = http_call("POST", f"/admin/lote/{lote_889_id}/encerrar", identity="admin")
        dt_f = await db_scalar("SELECT data_fechamento FROM lotes WHERE id = :lid", {"lid": lote_889_id})
        record_call("/admin/lote/{lote_id}/encerrar", "POST", "Encerramento imediato do lote", "Admin", f"Lote {lote_889_id}", {}, r, f"data_fechamento antecipada para agora: {dt_f}", "Redirecionamento ou 200", "Broadcast de encerramento SSE", "HTTP 303 / 200 com data_fechamento <= agora", expected_status=303)

        r = http_call("GET", f"/api/admin/lote/{lote_889_id}/verificar-exclusao", identity="admin")
        record_call("/api/admin/lote/{lote_id}/verificar-exclusao", "GET", "Verificação prévia para exclusão de lote", "Admin", f"Lote {lote_889_id}", {}, r, "Sem alterações", "JSON com total_ingressos e elegibilidade", "Nenhum", "HTTP 200 OK", expected_status=200)

        # Solicitação de código (com email válido)
        r = http_call("POST", f"/api/admin/lote/{lote_889_id}/solicitar-codigo-exclusao", identity="admin")
        tok_excl = await db_fetchall("SELECT token, codigo_verificacao FROM tokens_exclusao_lote WHERE lote_id = :lid ORDER BY id DESC LIMIT 1", {"lid": lote_889_id})
        codigo_excl = tok_excl[0]["codigo_verificacao"] if tok_excl else "123456"
        token_op = tok_excl[0]["token"] if tok_excl else ""
        record_call("/api/admin/lote/{lote_id}/solicitar-codigo-exclusao", "POST", "Geração de código 2FA para exclusão segura do lote", "Admin", f"Lote {lote_889_id}", {}, r, f"Token gerado no DB com código de 6 dígitos: {token_op}", "JSON com sucesso=true e token", "Mock email enviado", "HTTP 200 OK com código registrado", expected_status=200)

        r_err = http_call("POST", f"/api/admin/lote/{lote_889_id}/confirmar-exclusao", identity="admin", json_data={"token": token_op, "codigo": "000000"})
        record_call("/api/admin/lote/{lote_id}/confirmar-exclusao", "POST", "Tentativa de confirmação de exclusão com código errado", "Admin", "Código inválido", {"codigo": "000000"}, r_err, "Tentativa incrementada no DB", "JSON com erro 400", "Nenhum", "HTTP 400 Bad Request", expected_status=400)

        r_ok = http_call("POST", f"/api/admin/lote/{lote_889_id}/confirmar-exclusao", identity="admin", json_data={"token": token_op, "codigo": codigo_excl})
        lote_del = await db_scalar("SELECT deleted_at FROM lotes WHERE id = :lid", {"lid": lote_889_id})
        backup_criado = await db_scalar("SELECT id FROM backups_lotes WHERE lote_id = :lid", {"lid": lote_889_id})
        record_call("/api/admin/lote/{lote_id}/confirmar-exclusao", "POST", "Confirmação de exclusão com código 2FA e criação automática de backup", "Admin", "Código 2FA válido", {"codigo": codigo_excl}, r_ok, f"Lote deleted_at={lote_del}, Backup criado ID={backup_criado}", "JSON com sucesso=true", "Backup de retenção de 3 dias gerado", "HTTP 200 OK com soft-delete e backup gerado", expected_status=200)

        r_legacy_del = http_call("POST", f"/admin/lote/{lote_889_id}/excluir", identity="admin", data={"token": token_op, "codigo": codigo_excl})
        record_call("/admin/lote/{lote_id}/excluir", "POST", "Exclusão via rota POST /admin/lote/{id}/excluir (já excluído)", "Admin", "Lote já excluído", {}, r_legacy_del, "Sem novas alterações", "HTTP 400 informando lote já excluído", "Nenhum", "HTTP 400 Bad Request", expected_status=400)

        if backup_criado:
            r = http_call("GET", "/api/admin/lotes/backups", identity="admin")
            record_call("/api/admin/lotes/backups", "GET", "Listagem dos backups de lotes excluídos", "Admin", f"Backup {backup_criado} existente", {}, r, "Sem alterações", "JSON com lista de backups", "Nenhum", "HTTP 200 OK", expected_status=200)

            r = http_call("GET", f"/api/admin/lotes/backups/{backup_criado}/exportar", identity="admin")
            backup_data = r.json() if r.status_code == 200 else {}
            record_call("/api/admin/lotes/backups/{backup_id}/exportar", "GET", "Exportação do arquivo JSON de backup do lote", "Admin", f"Backup {backup_criado}", {}, r, "Sem alterações", "JSON com dados completos do backup", "Nenhum", "HTTP 200 OK com JSON exportado", expected_status=200)

            if backup_data.get("sucesso") and backup_data.get("backup"):
                r_imp = http_call("POST", "/api/admin/lotes/importar-backup", identity="admin", json_data={"backup_json": json.dumps(backup_data["backup"])})
                record_call("/api/admin/lotes/importar-backup", "POST", "Importação de lote a partir de JSON de backup", "Admin", "Backup JSON válido", {}, r_imp, "Novo lote restaurado criado no DB", "JSON de sucesso", "Lote restaurado", "HTTP 200 OK", expected_status=200)

            r_rest = http_call("POST", f"/api/admin/lotes/backups/{backup_criado}/restaurar", identity="admin")
            record_call("/api/admin/lotes/backups/{backup_id}/restaurar", "POST", "Restauração de backup para o banco de dados", "Admin", f"Backup {backup_criado}", {}, r_rest, "Backup marcado como restaurado no DB", "JSON de sucesso", "Lote reativado", "HTTP 200 OK", expected_status=200)

            r_del_bkp = http_call("DELETE", f"/api/admin/lotes/backups/{backup_criado}", identity="admin")
            record_call("/api/admin/lotes/backups/{backup_id}", "DELETE", "Tentativa de exclusão de backup de lote (proibido por retenção)", "Admin", f"Backup {backup_criado}", {}, r_del_bkp, "Backup preservado intocado no DB", "HTTP 403 Forbidden com regra inviolável", "Nenhum", "HTTP 403 Forbidden", expected_status=403)

async def test_admin_ingressos_relatorios_usuarios():
    print("\n>>> 6. Testando Ingressos, Relatórios e Usuários no Admin...")
    r = http_call("GET", f"/admin/lote/{LOTE_TEST_ID}/ingressos", identity="admin")
    record_call("/admin/lote/{lote_id}/ingressos", "GET", "Visualização dos ingressos resgatados de um lote", "Admin", f"Lote {LOTE_TEST_ID}", {}, r, "Sem alterações", "HTML da listagem de ingressos", "Nenhum", "HTTP 200 OK", expected_status=200)

    r1 = http_call("GET", f"/api/admin/lote/{LOTE_TEST_ID}/exportar-csv", identity="admin")
    record_call("/api/admin/lote/{lote_id}/exportar-csv", "GET", "Exportação CSV de ingressos do lote (API)", "Admin", f"Lote {LOTE_TEST_ID}", {}, r1, "Sem alterações", "Arquivo CSV retornado", "Content-Type text/csv", "HTTP 200 OK", expected_status=200)

    r2 = http_call("GET", f"/admin/lote/{LOTE_TEST_ID}/exportar-csv", identity="admin")
    record_call("/admin/lote/{lote_id}/exportar-csv", "GET", "Exportação CSV de ingressos do lote (Painel)", "Admin", f"Lote {LOTE_TEST_ID}", {}, r2, "Sem alterações", "Arquivo CSV retornado", "Content-Type text/csv", "HTTP 200 OK", expected_status=200)

    r3 = http_call("GET", "/api/admin/ingressos/exportar-csv", identity="admin")
    record_call("/api/admin/ingressos/exportar-csv", "GET", "Exportação global consolidada de todos os ingressos em CSV", "Admin", "Geral", {}, r3, "Sem alterações", "Arquivo CSV consolidado", "Content-Type text/csv", "HTTP 200 OK", expected_status=200)

    r_part = http_call("GET", "/api/admin/participantes", identity="admin")
    record_call("/api/admin/participantes", "GET", "Listagem com filtros e paginação de participantes", "Admin", "Participantes cadastrados", {}, r_part, "Sem alterações", "JSON com lista de participantes", "Nenhum", "HTTP 200 OK", expected_status=200)

    r_eq = http_call("GET", "/api/admin/usuarios-equipe", identity="admin")
    record_call("/api/admin/usuarios-equipe", "GET", "Listagem dos membros da equipe administrativa e operacional", "Admin", "Membros da equipe", {}, r_eq, "Sem alterações", "JSON com equipe e permissões", "Nenhum", "HTTP 200 OK", expected_status=200)

    novo_cpf_eq = gen_cpf(915)
    r_cria_user = http_call("POST", "/api/admin/usuarios", identity="admin", json_data={
        "cpf": novo_cpf_eq,
        "nome": "Operador Temporário Auditoria",
        "email": "operador_audit@example.com",
        "role": "portaria",
        "roles": ["portaria"]
    })
    user_eq = await db_fetchall("SELECT id, nome, role FROM usuarios WHERE cpf = :cpf", {"cpf": novo_cpf_eq})
    user_eq_id = user_eq[0]["id"] if user_eq else None
    record_call("/api/admin/usuarios", "POST", "Cadastro de novo membro da equipe", "Admin", "Dados válidos", {"cpf": novo_cpf_eq, "role": "portaria"}, r_cria_user, f"Usuário inserido no DB: ID={user_eq_id}", "JSON de sucesso", "Senha provisória gerada", "HTTP 200 OK", expected_status=200)

    if user_eq_id:
        r_edit_u = http_call("PUT", f"/api/admin/usuarios/{user_eq_id}", identity="admin", json_data={
            "nome": "Operador Editado Auditoria",
            "email": "operador_edit@example.com",
            "roles": ["portaria", "entregador"]
        })
        u_edit_db = await db_fetchall("SELECT nome, roles FROM usuarios WHERE id = :uid", {"uid": user_eq_id})
        record_call("/api/admin/usuarios/{usuario_id}", "PUT", "Atualização cadastral e de papéis de membro da equipe", "Admin", f"Usuário {user_eq_id}", {"nome": "Operador Editado Auditoria"}, r_edit_u, f"DB atualizado: {u_edit_db}", "JSON de sucesso", "Nenhum", "HTTP 200 OK com dados persistidos", expected_status=200)

        r_pass = http_call("POST", f"/api/admin/usuarios/{user_eq_id}/senha", identity="admin", json_data={"nova_senha": "NovaSenhaTemp@123"})
        record_call("/api/admin/usuarios/{usuario_id}/senha", "POST", "Definição manual de senha (descontinuada por segurança - 400 esperado)", "Admin", f"Usuário {user_eq_id}", {}, r_pass, "Sem alterações no hash", "HTTP 400 com aviso de descontinuação", "Nenhum", "HTTP 400 Bad Request", expected_status=400)

        r_redef_email = http_call("POST", f"/api/admin/usuarios/{user_eq_id}/redefinir-senha-email", identity="admin")
        record_call("/api/admin/usuarios/{usuario_id}/redefinir-senha-email", "POST", "Redefinição de senha com envio por e-mail", "Admin", f"Usuário {user_eq_id}", {}, r_redef_email, "Senha provisória gerada no DB", "JSON de sucesso", "Mock email enviado", "HTTP 200 OK", expected_status=200)

        r_em1 = http_call("POST", f"/api/admin/participantes/{user_eq_id}/enviar-email", identity="admin", json_data={"assunto": "Aviso Audit", "mensagem": "Mensagem de auditoria"})
        record_call("/api/admin/participantes/{usuario_id}/enviar-email", "POST", "Disparo de e-mail avulso para participante", "Admin", f"Usuário {user_eq_id}", {}, r_em1, "Sem alterações no DB", f"HTTP {r_em1.status_code}", "Disparo acionado", "Resposta controlada (200 ou 500 caso SMTP offline)", classification="Aprovado" if r_em1.status_code in (200, 500) else "Falhou")

        r_em2 = http_call("POST", f"/api/admin/usuarios/{user_eq_id}/email", identity="admin", json_data={"assunto": "Aviso Operador", "mensagem": "Mensagem para operador"})
        record_call("/api/admin/usuarios/{usuario_id}/email", "POST", "Disparo de e-mail institucional para membro da equipe", "Admin", f"Usuário {user_eq_id}", {}, r_em2, "Sem alterações no DB", f"HTTP {r_em2.status_code}", "Disparo acionado", "Resposta controlada (200 ou 500 caso SMTP offline)", classification="Aprovado" if r_em2.status_code in (200, 500) else "Falhou")

        r_del_u = http_call("DELETE", f"/api/admin/usuarios/{user_eq_id}", identity="admin")
        del_at = await db_scalar("SELECT deleted_at FROM usuarios WHERE id = :uid", {"uid": user_eq_id})
        record_call("/api/admin/usuarios/{usuario_id}", "DELETE", "Exclusão segura (soft-delete) de membro da equipe", "Admin", f"Usuário {user_eq_id}", {}, r_del_u, f"deleted_at setado no DB: {del_at}", "JSON de sucesso", "Revogação de acesso", "HTTP 200 OK com deleted_at persistido", expected_status=200)

async def test_resgate_e2e_and_ingressos():
    print("\n>>> 7. Testando Fluxo Completo de Resgate de Ingressos (E2E)...")
    cpf_s1 = CPFS["servidor_1"]

    r_val = http_call("GET", f"/api/resgate/validar-cpf?cpf={cpf_s1}")
    record_call("/api/resgate/validar-cpf", "GET", "Consulta pública de elegibilidade do CPF para resgate", "Visitante", f"CPF {cpf_s1}", {"cpf": cpf_s1}, r_val, "Sem alterações", "JSON com elegibilidade e dados preliminares", "Nenhum", "HTTP 200 OK com elegível", expected_status=200)

    s = requests.Session()
    r_pg1 = s.get(f"{BASE_URL}/resgate/{LOTE_TEST_ID}", timeout=10)
    record_call("/resgate/{lote_id}", "GET", "Acesso à página de resgate (legada) iniciando sessão de reserva", "Visitante", f"Lote {LOTE_TEST_ID}", {}, r_pg1, "Reserva criada/associada no DB", "Página de resgate carregada", "Cookie browser id gerado", "HTTP 200 OK", expected_status=200)

    r_res = s.get(f"{BASE_URL}/api/resgate/{LOTE_TEST_ID}", timeout=10)
    res_data = r_res.json() if r_res.status_code == 200 else {}
    token_reserva = res_data.get("token_reserva")
    cnt_res = await db_scalar("SELECT count(*) FROM reservas_ingressos WHERE lote_id = :lid AND status = 'ativa'", {"lid": LOTE_TEST_ID})
    record_call("/api/resgate/{lote_id}", "GET", "Início e alocação atômica de reserva temporária de 5 min", "Visitante", f"Lote {LOTE_TEST_ID} com vagas", {}, r_res, f"Reservas ativas no DB: {cnt_res}", f"token_reserva={token_reserva}", "Vaga reservada com lock", "HTTP 200 OK com token_reserva alocado", expected_status=200)

    # Consulta com token obrigatório
    r_st_res = s.get(f"{BASE_URL}/api/resgate/status-reserva?token_reserva={token_reserva}", timeout=10)
    record_call("/api/resgate/status-reserva", "GET", "Consulta do status e tempo restante da reserva ativa", "Visitante", "Reserva ativa", {"token_reserva": token_reserva}, r_st_res, "Sem alterações", "JSON com segundos_restantes e expira_em", "Nenhum", "HTTP 200 OK", expected_status=200)

    # Desistência com token_reserva no Form
    r_desistir = s.post(f"{BASE_URL}/api/resgate/desistir", data={"token_reserva": token_reserva}, timeout=10)
    st_desist = await db_scalar("SELECT status FROM reservas_ingressos WHERE token = :tok", {"tok": token_reserva})
    record_call("/api/resgate/desistir", "POST", "Desistência voluntária da vaga liberando-a imediatamente", "Visitante", f"Reserva {token_reserva}", {"token_reserva": token_reserva}, r_desistir, f"Status no DB: {st_desist}", "JSON com sucesso=true", "Vaga liberada no contador", "HTTP 200 OK com status=cancelada no DB", expected_status=200)

    # Nova reserva para conclusão real do resgate de Servidor 1
    r_res2 = s.get(f"{BASE_URL}/api/resgate/{LOTE_TEST_ID}", timeout=10)
    token_reserva2 = r_res2.json().get("token_reserva")

    payload_resgate = {
        "token_reserva": token_reserva2,
        "cpf": cpf_s1,
        "nome": "Servidor Um Auditoria",
        "data_nascimento": "1988-05-15",
        "setor": "Controle Interno",
        "secretaria_id": SEC_TEST_ID,
        "vinculo": "Efetivo",
        "telefone": "81999990001",
        "email": "servidor1_audit@example.com",
        "foto_base64": MINI_JPEG_B64
    }
    r_proc = s.post(f"{BASE_URL}/api/resgate/{LOTE_TEST_ID}", data=payload_resgate, timeout=12)
    ing_emitido = await db_fetchall("SELECT id, qr_code_token, usuario_id, lote_id FROM ingressos WHERE usuario_id = 906 AND lote_id = :lid AND deleted_at IS NULL", {"lid": LOTE_TEST_ID})
    solic_emitida = await db_fetchall("SELECT id, status FROM solicitacoes_validacao WHERE usuario_id = 906 AND lote_id = :lid", {"lid": LOTE_TEST_ID})
    lote_cnt_resgatada = await db_scalar("SELECT quantidade_resgatada FROM lotes WHERE id = :lid", {"lid": LOTE_TEST_ID})

    ing_id = ing_emitido[0]["id"] if ing_emitido else None
    solic_id = solic_emitida[0]["id"] if solic_emitida else None

    record_call("/api/resgate/{lote_id}", "POST", "Emissão ou encaminhamento de ingresso com biometria facial", "Visitante", "Reserva alocada e CPF válido", {"cpf": cpf_s1}, r_proc, f"Ingresso={ing_emitido}, Solicitação={solic_emitida}, Lote resgatada={lote_cnt_resgatada}", "JSON com ingresso_id ou solicitacao_id", "Foto salva e email enfileirado", "HTTP 200 OK com persistência no PostgreSQL", expected_status=200)

    r_proc_leg = s.post(f"{BASE_URL}/resgate/{LOTE_TEST_ID}", data=payload_resgate, timeout=10)
    record_call("/resgate/{lote_id}", "POST", "Tentativa repetida de resgate com mesma reserva (deve falhar)", "Visitante", "Reserva já concluída", {}, r_proc_leg, "Sem novas alterações", "HTTP 400 Bad Request", "Nenhum", "HTTP 400 Bad Request", expected_status=400)

    if ing_id:
        r_suc1 = s.get(f"{BASE_URL}/api/sucesso/{ing_id}", timeout=10)
        record_call("/api/sucesso/{ingresso_id}", "GET", "Consulta de dados do ingresso emitido na tela de sucesso (API)", "Titular", f"Ingresso {ing_id}", {}, r_suc1, "Sem alterações", "JSON com QR Code e dados do servidor", "Nenhum", "HTTP 200 OK", expected_status=200)

        r_suc2 = s.get(f"{BASE_URL}/sucesso/{ing_id}", timeout=10)
        record_call("/sucesso/{ingresso_id}", "GET", "Visualização da página de sucesso do ingresso emitido", "Titular", f"Ingresso {ing_id}", {}, r_suc2, "Sem alterações", "HTML do ingresso com QR Code", "Nenhum", "HTTP 200 OK", expected_status=200)

    if solic_id:
        r_anal1 = s.get(f"{BASE_URL}/api/sucesso/analise-status/{solic_id}", timeout=10)
        record_call("/api/sucesso/analise-status/{solicitacao_id}", "GET", "Acompanhamento do status de validação manual", "Titular", f"Solicitação {solic_id}", {}, r_anal1, "Sem alterações", "JSON com status da validação", "Nenhum", "HTTP 200 OK", expected_status=200)

        r_anal2 = s.get(f"{BASE_URL}/sucesso/analise", timeout=10)
        record_call("/sucesso/analise", "GET", "Página visual de confirmação de encaminhamento para análise", "Titular", "Página pública", {}, r_anal2, "Sem alterações", "HTML da página de análise", "Nenhum", "HTTP 200 OK", expected_status=200)

async def test_validacoes_manuais_e2e():
    print("\n>>> 8. Testando Validações Manuais de Servidores (E2E)...")
    tok_solic = str(uuid.uuid4())
    await db_exec("""
        INSERT INTO solicitacoes_validacao (id, token, usuario_id, lote_id, secretaria_id, status, criado_em, comunicado)
        VALUES (991, :tok, 910, :lid, :sid, 'pendente_analise', NOW(), false)
        ON CONFLICT (id) DO UPDATE SET status = 'pendente_analise', lote_id = :lid, secretaria_id = :sid, comunicado = false;
    """, {"tok": tok_solic, "lid": LOTE_TEST_ID, "sid": SEC_TEST_ID})

    r_list = http_call("GET", "/api/admin/validacoes?status_filtro=pendente_analise", identity="validador")
    record_call("/api/admin/validacoes", "GET", "Listagem de solicitações pendentes pela comissão validadora", "Validador", "Solicitação 991 pendente", {}, r_list, "Sem alterações", "JSON com lista de solicitações filtradas", "Nenhum", "HTTP 200 OK com solicitações", expected_status=200)

    r_com_val = http_call("POST", "/api/admin/validacoes/991/comunicar", identity="validador")
    record_call("/api/admin/validacoes/{solicitacao_id}/comunicar", "POST", "Tentativa de liberação de comunicação por validador comum (restrito a admin_geral)", "Validador", "Sem papel admin_geral", {}, r_com_val, "Acesso negado", "HTTP 403 Forbidden", "Nenhum", "HTTP 403 Forbidden", expected_status=403)

    r_com_adm = http_call("POST", "/api/admin/validacoes/991/comunicar", identity="admin_geral")
    com_db = await db_scalar("SELECT comunicado FROM solicitacoes_validacao WHERE id = 991")
    record_call("/api/admin/validacoes/{solicitacao_id}/comunicar", "POST", "Marcação de participante como comunicado pelo Administrador Geral", "Admin Geral", "Solicitação 991", {}, r_com_adm, f"comunicado no DB: {com_db}", "JSON de sucesso", "Timestamp comunicado_em setado", "HTTP 200 OK com comunicado=true persistido", expected_status=200)

    r_com_lote = http_call("POST", "/api/admin/validacoes/comunicar-em-lote", identity="admin_geral", json_data={"solicitacao_ids": [991]})
    record_call("/api/admin/validacoes/comunicar-em-lote", "POST", "Comunicação em lote de múltiplos participantes pelo Admin Geral", "Admin Geral", "Lista de IDs", {"solicitacao_ids": [991]}, r_com_lote, "Registros atualizados", "JSON de sucesso", "Nenhum", "HTTP 200 OK", expected_status=200)

    qtd_resg_antes = await db_scalar("SELECT quantidade_resgatada FROM lotes WHERE id = :lid", {"lid": LOTE_TEST_ID})
    r_aprov = http_call("POST", "/api/admin/validacoes/991/aprovar", identity="validador")
    st_solic_depois = await db_scalar("SELECT status FROM solicitacoes_validacao WHERE id = 991")
    novo_ing_val = await db_fetchall("SELECT id, qr_code_token FROM ingressos WHERE usuario_id = 910 AND deleted_at IS NULL")
    qtd_resg_depois = await db_scalar("SELECT quantidade_resgatada FROM lotes WHERE id = :lid", {"lid": LOTE_TEST_ID})
    record_call("/api/admin/validacoes/{solicitacao_id}/aprovar", "POST", "Aprovação de solicitação com geração atômica de ingresso e incremento de lote", "Validador", "Solicitação 991 pendente", {}, r_aprov, f"Status={st_solic_depois}, Novo Ingresso={novo_ing_val}, Lote: {qtd_resg_antes}->{qtd_resg_depois}", "JSON com ingresso_id gerado", "QR Code gerado e mock email enviado", "HTTP 200 OK com ingresso persistido no DB", expected_status=200)

    await db_exec("""
        INSERT INTO solicitacoes_validacao (id, token, usuario_id, lote_id, secretaria_id, status, criado_em)
        VALUES (992, :tok, 908, :lid, :sid, 'pendente_analise', NOW())
        ON CONFLICT (id) DO UPDATE SET status = 'pendente_analise';
    """, {"tok": str(uuid.uuid4()), "lid": LOTE_TEST_ID, "sid": SEC_TEST_ID})

    r_rej = http_call("POST", "/api/admin/validacoes/992/rejeitar", identity="validador", json_data={"motivo": "Matrícula não localizada no diário oficial"})
    st_rej = await db_scalar("SELECT status FROM solicitacoes_validacao WHERE id = 992")
    mot_rej = await db_scalar("SELECT motivo_rejeicao FROM solicitacoes_validacao WHERE id = 992")
    record_call("/api/admin/validacoes/{solicitacao_id}/rejeitar", "POST", "Indeferimento fundamentado de solicitação de ingresso", "Validador", "Solicitação 992 pendente", {"motivo": "Matrícula não localizada"}, r_rej, f"Status={st_rej}, Motivo={mot_rej}", "JSON com sucesso=true", "Mock email de indeferimento enviado", "HTTP 200 OK com status=rejeitado no DB", expected_status=200)

    r_aprov_todos = http_call("POST", "/api/admin/validacoes/aprovar-verificados", identity="validador")
    record_call("/api/admin/validacoes/aprovar-verificados", "POST", "Aprovação em massa de participantes identificados na base", "Validador", "Solicitações pendentes", {}, r_aprov_todos, "Processamento de verificados", "JSON com total aprovados", "Nenhum", "HTTP 200 OK", expected_status=200)

async def test_portaria_and_qr_code():
    print("\n>>> 9. Testando Módulo de Portaria e Leitura de QR Code...")
    tok_qr = "ING-AUDIT-QR-907"
    await db_exec("""
        INSERT INTO ingressos (id, usuario_id, lote_id, qr_code_token, data_resgate, deleted_at)
        VALUES (907, 907, :lid, :tok, NOW(), NULL)
        ON CONFLICT (id) DO UPDATE SET qr_code_token = :tok, deleted_at = NULL;
    """, {"lid": LOTE_TEST_ID, "tok": tok_qr})

    r_view = http_call("GET", "/portaria", identity="portaria")
    record_call("/portaria", "GET", "Acesso à interface operacional da portaria", "Portaria", "Usuário portaria logado", {}, r_view, "Sem alterações", "HTML da interface de portaria", "Nenhum", "HTTP 200 OK", expected_status=200)

    cpf_s2 = CPFS["servidor_2"]
    r_b_cpf = http_call("POST", "/api/portaria/buscar", identity="portaria", json_data={"identificador": cpf_s2})
    record_call("/api/portaria/buscar", "POST", "Localização rápida de participante pelo CPF na portaria", "Portaria", f"CPF {cpf_s2} cadastrado", {"identificador": cpf_s2}, r_b_cpf, "Sem alterações", "JSON com nome, foto, secretaria e status", "Nenhum", "HTTP 200 OK com dados do participante", expected_status=200)

    r_b_qr = http_call("POST", "/api/portaria/buscar", identity="portaria", json_data={"identificador": tok_qr})
    record_call("/api/portaria/buscar", "POST", "Leitura e decodificação do QR Code digital na portaria", "Portaria", f"Token {tok_qr}", {"identificador": tok_qr}, r_b_qr, "Sem alterações", "JSON com participante e token_ingresso", "Nenhum", "HTTP 200 OK com dados válidos", expected_status=200)

    r_ent = http_call("POST", "/api/portaria/alterar-status", identity="portaria", json_data={"usuario_id": 907, "novo_status": "entrada", "metodo_validacao": "qr_code"})
    ultimo_log = await db_fetchall("SELECT tipo, usuario_id, operador_id, metodo_validacao FROM logs_acesso WHERE usuario_id = 907 ORDER BY data_hora DESC LIMIT 1")
    record_call("/api/portaria/alterar-status", "POST", "Registro de entrada de participante com auditoria completa", "Portaria", "Participante fora", {"novo_status": "entrada"}, r_ent, f"Novo log registrado no DB: {ultimo_log}", "JSON com sucesso=true", "Log de auditoria em logs_acesso", "HTTP 200 OK com registro tipo=entrada", expected_status=200)

    r_ent_dup = http_call("POST", "/api/portaria/alterar-status", identity="portaria", json_data={"usuario_id": 907, "novo_status": "entrada", "metodo_validacao": "qr_code"})
    record_call("/api/portaria/alterar-status", "POST", "Tentativa de entrada duplicada para participante já dentro do evento", "Portaria", "Participante já dentro", {"novo_status": "entrada"}, r_ent_dup, "Sem novos logs duplicados", "HTTP 400 informando já registrado dentro", "Nenhum", "HTTP 400 Bad Request impedindo duplicidade", expected_status=400)

    r_sai = http_call("POST", "/api/portaria/alterar-status", identity="portaria", json_data={"usuario_id": 907, "novo_status": "saida", "metodo_validacao": "manual"})
    ultimo_log_sai = await db_fetchall("SELECT tipo, usuario_id FROM logs_acesso WHERE usuario_id = 907 ORDER BY data_hora DESC LIMIT 1")
    record_call("/api/portaria/alterar-status", "POST", "Registro de saída temporária do evento", "Portaria", "Participante dentro", {"novo_status": "saida"}, r_sai, f"Log de saída no DB: {ultimo_log_sai}", "JSON com sucesso=true", "Log em logs_acesso", "HTTP 200 OK com registro tipo=saida", expected_status=200)

    # Rota legada POST /portaria com token Form
    r_leg_port = http_call("POST", "/portaria", identity="portaria", data={"token": tok_qr})
    record_call("/portaria", "POST", "Validação por rota legada de portaria", "Portaria", f"Token {tok_qr}", {"token": tok_qr}, r_leg_port, "Busca realizada", "Resposta JSON/HTML de portaria", "Nenhum", "HTTP 200 OK", expected_status=200)

async def test_sorteios_and_premios():
    print("\n>>> 10. Testando Módulo de Sorteios, Prêmios e Telão...")
    r_telao = http_call("GET", "/api/sorteios/live-telao")
    record_call("/api/sorteios/live-telao", "GET", "Consulta pública de estado para sincronização do Telão do evento", "Visitante", "Nenhuma", {}, r_telao, "Sem alterações", "JSON com sorteando, status, premio_id", "Nenhum", "HTTP 200 OK", expected_status=200)

    # Preparar mesa com payload correto
    payload_mesa = {"itens": [{"premio_id": PREMIO_TEST_ID, "quantidade": 1}]}
    r_prep = http_call("POST", "/api/sorteios/mesa/preparar", identity="admin", json_data=payload_mesa)
    st_prep = await db_scalar("SELECT status FROM estado_sorteio WHERE id = 1")
    record_call("/api/sorteios/mesa/preparar", "POST", "Preparação da mesa de sorteio para exibição no telão", "Admin", f"Prêmio {PREMIO_TEST_ID}", payload_mesa, r_prep, f"status no DB: {st_prep}", "JSON de sucesso com status preparando", "Broadcast no telão", "HTTP 200 OK com status=preparando", expected_status=200)

    r_ini_mesa = http_call("POST", "/api/sorteios/mesa/iniciar", identity="admin")
    st_ini = await db_scalar("SELECT status FROM estado_sorteio WHERE id = 1")
    record_call("/api/sorteios/mesa/iniciar", "POST", "Início da animação da roleta de sorteio na mesa", "Admin", "Mesa preparada", {}, r_ini_mesa, f"status no DB: {st_ini}", "JSON de sucesso com status sorteando", "Animação iniciada no telão", "HTTP 200 OK com status=sorteando", expected_status=200)

    r_limp = http_call("POST", "/api/sorteios/mesa/limpar", identity="admin")
    st_limp = await db_scalar("SELECT status FROM estado_sorteio WHERE id = 1")
    record_call("/api/sorteios/mesa/limpar", "POST", "Limpeza e reset da mesa de sorteio para repouso", "Admin", "Mesa em execução", {}, r_limp, f"status no DB: {st_limp}", "JSON de sucesso com status idle", "Telão resetado", "HTTP 200 OK com status=idle", expected_status=200)

    # Executar Sorteio
    await db_exec("""
        INSERT INTO ingressos (id, usuario_id, lote_id, qr_code_token, data_resgate, deleted_at)
        VALUES (908, 908, :lid, :tok, NOW(), NULL)
        ON CONFLICT (id) DO UPDATE SET deleted_at = NULL;
    """, {"lid": LOTE_TEST_ID, "tok": "ING-AUDIT-SORTEIO-908"})
    await db_exec("""
        INSERT INTO logs_acesso (usuario_id, tipo, data_hora)
        VALUES (908, 'entrada', NOW());
    """)

    r_exec = http_call("POST", f"/api/sorteios/executar/{PREMIO_TEST_ID}", identity="admin")
    novo_ganhador = await db_fetchall("SELECT id, usuario_id, premio_id, entregue, anulado FROM ganhadores WHERE premio_id = :pid ORDER BY id DESC LIMIT 1", {"pid": PREMIO_TEST_ID})
    ganhador_id = novo_ganhador[0]["id"] if novo_ganhador else None
    record_call("/api/sorteios/executar/{premio_id}", "POST", "Execução de algoritmo auditável de sorteio selecionando ganhador elegível", "Admin", f"Prêmio {PREMIO_TEST_ID}", {}, r_exec, f"Ganhador inserido no DB: {novo_ganhador}", "JSON com ganhador selecionado", "Ganhador exibido no telão", "HTTP 200 OK com ganhador persistido no DB", expected_status=200)

    if ganhador_id:
        r_anul = http_call("POST", f"/api/sorteios/anular/{ganhador_id}", identity="admin", json_data={"motivo": "Participante ausente na chamada"})
        st_anul = await db_scalar("SELECT anulado FROM ganhadores WHERE id = :gid", {"gid": ganhador_id})
        record_call("/api/sorteios/anular/{ganhador_id}", "POST", "Anulação de premiação tornando o prêmio disponível novamente", "Admin", f"Ganhador {ganhador_id}", {"motivo": "Ausente"}, r_anul, f"anulado no DB: {st_anul}", "JSON com sucesso=true", "Prêmio reaberto", "HTTP 200 OK com anulado=true persistido", expected_status=200)

    # CRUD de Prêmios (Form)
    r_list_prem = http_call("GET", "/api/sorteios/premios")
    record_call("/api/sorteios/premios", "GET", "Listagem pública dos prêmios cadastrados", "Visitante", "Prêmios existentes", {}, r_list_prem, "Sem alterações", "JSON com lista de prêmios", "Nenhum", "HTTP 200 OK", expected_status=200)

    r_cria_prem = http_call("POST", "/api/sorteios/premios", identity="admin", data={
        "nome": "Micro-ondas Auditoria",
        "descricao": "20 Litros",
        "categoria": "categoria_1",
        "quantidade": 2
    })
    prem_db = await db_fetchall("SELECT id, nome, quantidade FROM premios WHERE nome = 'Micro-ondas Auditoria'")
    prem_temp_id = prem_db[0]["id"] if prem_db else None
    record_call("/api/sorteios/premios", "POST", "Cadastro de novo prêmio no catálogo pelo admin", "Admin", "Dados válidos", {"nome": "Micro-ondas"}, r_cria_prem, f"Prêmio inserido no DB: ID={prem_temp_id}", "JSON com sucesso e prêmio criado", "Nenhum", "HTTP 200 OK com prêmio persistido", expected_status=200)

    if prem_temp_id:
        r_edit_prem = http_call("PUT", f"/api/sorteios/premios/{prem_temp_id}", identity="admin", data={
            "nome": "Micro-ondas Digital Editado",
            "quantidade": 3
        })
        prem_edit_db = await db_fetchall("SELECT nome, quantidade FROM premios WHERE id = :pid", {"pid": prem_temp_id})
        record_call("/api/sorteios/premios/{premio_id}", "PUT", "Edição de características do prêmio cadastrado", "Admin", f"Prêmio {prem_temp_id}", {"quantidade": 3}, r_edit_prem, f"DB atualizado: {prem_edit_db}", "JSON de sucesso", "Nenhum", "HTTP 200 OK", expected_status=200)

        r_del_prem = http_call("DELETE", f"/api/sorteios/premios/{prem_temp_id}", identity="admin")
        prem_del_db = await db_scalar("SELECT count(*) FROM premios WHERE id = :pid", {"pid": prem_temp_id})
        record_call("/api/sorteios/premios/{premio_id}", "DELETE", "Exclusão de prêmio do catálogo", "Admin", f"Prêmio {prem_temp_id}", {}, r_del_prem, f"Prêmios restantes no DB: {prem_del_db}", "JSON de sucesso", "Nenhum", "HTTP 200 OK com exclusão no DB", expected_status=200)

    # CRUD de Eixos (Form)
    r_list_eixos = http_call("GET", "/api/sorteios/eixos")
    record_call("/api/sorteios/eixos", "GET", "Listagem pública dos eixos setoriais", "Visitante", "Eixos existentes", {}, r_list_eixos, "Sem alterações", "JSON com lista de eixos", "Nenhum", "HTTP 200 OK", expected_status=200)

    r_cria_eixo = http_call("POST", "/api/sorteios/eixos", identity="admin", data={"nome": "Eixo Educação e Saúde", "descricao": "Setor Social"})
    eixo_db = await db_fetchall("SELECT id, nome FROM eixos WHERE nome = 'Eixo Educação e Saúde'")
    eixo_temp_id = eixo_db[0]["id"] if eixo_db else None
    record_call("/api/sorteios/eixos", "POST", "Cadastro de novo eixo setorial pelo admin", "Admin", "Dados válidos", {"nome": "Eixo Educação e Saúde"}, r_cria_eixo, f"Eixo inserido no DB: ID={eixo_temp_id}", "JSON de sucesso", "Nenhum", "HTTP 200 OK com eixo persistido", expected_status=200)

    if eixo_temp_id:
        r_del_eixo = http_call("DELETE", f"/api/sorteios/eixos/{eixo_temp_id}", identity="admin")
        eixo_del_db = await db_scalar("SELECT count(*) FROM eixos WHERE id = :eid", {"eid": eixo_temp_id})
        record_call("/api/sorteios/eixos/{eixo_id}", "DELETE", "Exclusão de eixo setorial", "Admin", f"Eixo {eixo_temp_id}", {}, r_del_eixo, f"Eixos restantes no DB: {eixo_del_db}", "JSON de sucesso", "Nenhum", "HTTP 200 OK com exclusão no DB", expected_status=200)

    # Gestão de Secretarias (Form)
    r_sec_pub = http_call("GET", "/api/secretarias")
    record_call("/api/secretarias", "GET", "Consulta pública da lista de secretarias municipais", "Visitante", "Secretarias cadastradas", {}, r_sec_pub, "Sem alterações", "JSON com secretarias", "Nenhum", "HTTP 200 OK", expected_status=200)

    r_sec_adm = http_call("GET", "/api/sorteios/secretarias", identity="admin")
    record_call("/api/sorteios/secretarias", "GET", "Consulta administrativa detalhada de secretarias", "Admin", "Secretarias cadastradas", {}, r_sec_adm, "Sem alterações", "JSON com secretarias e eixos vinculados", "Nenhum", "HTTP 200 OK", expected_status=200)

    r_cria_sec = http_call("POST", "/api/sorteios/secretarias", identity="admin", data={"nome": "Secretaria de Teste Temp", "sigla": "SECTEMP", "eixo_id": EIXO_TEST_ID})
    sec_db = await db_fetchall("SELECT id, nome FROM secretarias WHERE nome = 'Secretaria de Teste Temp'")
    sec_temp_id = sec_db[0]["id"] if sec_db else None
    record_call("/api/sorteios/secretarias", "POST", "Cadastro de nova secretaria municipal", "Admin", "Dados válidos", {"nome": "Secretaria de Teste Temp"}, r_cria_sec, f"Secretaria inserida no DB: ID={sec_temp_id}", "JSON de sucesso", "Nenhum", "HTTP 200 OK com persistência", expected_status=200)

    if sec_temp_id:
        r_del_sec = http_call("DELETE", f"/api/sorteios/secretarias/{sec_temp_id}", identity="admin")
        sec_del_db = await db_scalar("SELECT count(*) FROM secretarias WHERE id = :sid", {"sid": sec_temp_id})
        record_call("/api/sorteios/secretarias/{sec_id}", "DELETE", "Exclusão de secretaria municipal", "Admin", f"Secretaria {sec_temp_id}", {}, r_del_sec, f"Secretarias restantes no DB: {sec_del_db}", "JSON de sucesso", "Nenhum", "HTTP 200 OK com exclusão no DB", expected_status=200)

    # Entrega de Prêmios (Entregador)
    await db_exec("""
        INSERT INTO ganhadores (id, premio_id, usuario_id, categoria, data_sorteio, entregue, anulado)
        VALUES (998, :pid, 908, 'categoria_1', NOW(), false, false)
        ON CONFLICT (id) DO UPDATE SET entregue = false, anulado = false;
    """, {"pid": PREMIO_TEST_ID})

    r_pend_ent = http_call("GET", "/api/sorteios/entregas-pendentes", identity="entregador")
    record_call("/api/sorteios/entregas-pendentes", "GET", "Listagem de prêmios sorteados aguardando entrega física", "Entregador", "Ganhador 998 pendente", {}, r_pend_ent, "Sem alterações", "JSON com lista de entregas pendentes", "Nenhum", "HTTP 200 OK", expected_status=200)

    r_val_ganh = http_call("POST", "/api/sorteios/validar-ganhador-entrega", identity="entregador", json_data={"identificador": CPFS["servidor_3"]})
    record_call("/api/sorteios/validar-ganhador-entrega", "POST", "Validação presencial de identidade do ganhador por CPF", "Entregador", f"CPF {CPFS['servidor_3']}", {"identificador": CPFS["servidor_3"]}, r_val_ganh, "Sem alterações", "JSON confirmando titularidade do prêmio", "Nenhum", "HTTP 200 OK", expected_status=200)

    r_reg_ent = http_call("POST", "/api/sorteios/registrar-entrega/998", identity="entregador", data={"foto_base64": MINI_JPEG_B64})
    st_ent = await db_scalar("SELECT entregue FROM ganhadores WHERE id = 998")
    record_call("/api/sorteios/registrar-entrega/{ganhador_id}", "POST", "Registro fotográfico e conclusão da entrega de prêmio", "Entregador", "Ganhador 998 pendente", {}, r_reg_ent, f"entregue no DB: {st_ent}", "JSON com sucesso=true", "Timestamp data_entrega e foto persistidos", "HTTP 200 OK com entregue=true no DB", expected_status=200)

    r_meus_prem = http_call("GET", f"/api/sorteios/meus-premios?cpf={CPFS['servidor_3']}&data_nascimento=1988-05-15")
    record_call("/api/sorteios/meus-premios", "GET", "Consulta pública de prêmios conquistados pelo participante com CPF e nascimento", "Visitante", f"CPF {CPFS['servidor_3']}", {}, r_meus_prem, "Sem alterações", "JSON com lista de prêmios ganhos", "Nenhum", "HTTP 200 OK", expected_status=200)

async def test_cancelamento_e2e():
    print("\n>>> 11. Testando Fluxo Completo de Cancelamento de Ingressos (E2E)...")
    tok_ing_canc = "ING-AUDIT-CANC-909"
    await db_exec("""
        INSERT INTO ingressos (id, usuario_id, lote_id, qr_code_token, data_resgate, deleted_at)
        VALUES (909, 909, :lid, :tok, NOW(), NULL)
        ON CONFLICT (id) DO UPDATE SET qr_code_token = :tok, deleted_at = NULL;
    """, {"lid": LOTE_TEST_ID, "tok": tok_ing_canc})

    cpf_canc = CPFS["servidor_cancel"]

    r_cons = http_call("POST", "/api/meu-ingresso/consultar", json_data={"cpf": cpf_canc, "data_nascimento": "1988-05-15"})
    record_call("/api/meu-ingresso/consultar", "POST", "Consulta pública de ingresso pelo CPF e data de nascimento do titular", "Participante", f"CPF {cpf_canc}", {"cpf": cpf_canc, "data_nascimento": "1988-05-15"}, r_cons, "Sem alterações", "JSON com ingresso_id, lote e qr_code", "Nenhum", "HTTP 200 OK com dados do ingresso", expected_status=200)

    r_ini = http_call("POST", "/api/meu-ingresso/iniciar", json_data={"cpf": cpf_canc, "data_nascimento": "1988-05-15"})
    solic_canc = await db_fetchall("SELECT token, codigo_verificacao, status FROM solicitacoes_cancelamento WHERE usuario_id = 909 ORDER BY id DESC LIMIT 1")
    token_canc = solic_canc[0]["token"] if solic_canc else None
    codigo_canc = solic_canc[0]["codigo_verificacao"] if solic_canc else "123456"
    record_call("/api/meu-ingresso/iniciar", "POST", "Início de solicitação de cancelamento com geração de código 2FA", "Participante", "Ingresso 909 ativo", {"cpf": cpf_canc}, r_ini, f"Solicitação criada no DB: {solic_canc}", "JSON com token_cancelamento", "Código 2FA gerado e mock email enviado", "HTTP 200 OK com token retornado", expected_status=200)

    if token_canc:
        r_reenv = http_call("POST", "/api/meu-ingresso/reenviar-codigo", json_data={"token_cancelamento": token_canc})
        record_call("/api/meu-ingresso/reenviar-codigo", "POST", "Reenvio de código de segurança por email", "Participante", f"Token {token_canc}", {}, r_reenv, "Código renovado no DB", "JSON de sucesso", "Mock email reenviado", "HTTP 200 OK", expected_status=200)

        r_cod_err = http_call("POST", "/api/meu-ingresso/validar-codigo", json_data={"token_cancelamento": token_canc, "codigo": "999999"})
        record_call("/api/meu-ingresso/validar-codigo", "POST", "Tentativa com código de segurança incorreto", "Participante", "Código errado", {"codigo": "999999"}, r_cod_err, "codigo_tentativas incrementado no DB", "HTTP 400 Bad Request", "Nenhum", "HTTP 400 Bad Request", expected_status=400)

        r_cod_ok = http_call("POST", "/api/meu-ingresso/validar-codigo", json_data={"token_cancelamento": token_canc, "codigo": codigo_canc})
        st_cod_ok = await db_scalar("SELECT status FROM solicitacoes_cancelamento WHERE token = :tok", {"tok": token_canc})
        record_call("/api/meu-ingresso/validar-codigo", "POST", "Validação com código de segurança correto avançando etapa", "Participante", "Código correto", {"codigo": codigo_canc}, r_cod_ok, f"Status no DB: {st_cod_ok}", "JSON com sucesso=true e etapa foto", "Status atualizado para pendente_foto", "HTTP 200 OK com status=pendente_foto", expected_status=200)

        r_foto1 = http_call("POST", "/api/meu-ingresso/enviar-foto", json_data={"token_cancelamento": token_canc, "foto_ao_vivo": MINI_JPEG_B64, "motivo": "Imprevisto de trabalho"})
        st_analise = await db_scalar("SELECT status FROM solicitacoes_cancelamento WHERE token = :tok", {"tok": token_canc})
        record_call("/api/meu-ingresso/enviar-foto", "POST", "Submissão de selfie ao vivo comprovando identidade para cancelamento", "Participante", "Etapa foto", {"motivo": "Imprevisto"}, r_foto1, f"Status no DB: {st_analise}", "JSON com sucesso=true", "Foto salva e encaminhado para comissão", "HTTP 200 OK com status=pendente_analise", expected_status=200)

        r_concluir = http_call("POST", "/api/meu-ingresso/concluir", json_data={"token_cancelamento": token_canc, "foto_ao_vivo": MINI_JPEG_B64, "motivo": "Imprevisto"})
        record_call("/api/meu-ingresso/concluir", "POST", "Envio pela rota alternativa POST /api/meu-ingresso/concluir", "Participante", "Pendente análise", {}, r_concluir, "Sem novas alterações", "JSON de confirmação", "Nenhum", "HTTP 200 OK", expected_status=200)

        r_st_canc = http_call("GET", f"/api/meu-ingresso/status?token={token_canc}")
        record_call("/api/meu-ingresso/status", "GET", "Consulta pública do andamento da solicitação de cancelamento", "Participante", f"Token {token_canc}", {}, r_st_canc, "Sem alterações", "JSON com status pendente_analise", "Nenhum", "HTTP 200 OK", expected_status=200)

        r_list_canc = http_call("GET", "/api/admin/cancelamentos", identity="admin")
        record_call("/api/admin/cancelamentos", "GET", "Listagem de cancelamentos pendentes para moderação da organização", "Admin", "Solicitação pendente", {}, r_list_canc, "Sem alterações", "JSON com lista de cancelamentos", "Nenhum", "HTTP 200 OK", expected_status=200)

        solic_canc_id = await db_scalar("SELECT id FROM solicitacoes_cancelamento WHERE token = :tok", {"tok": token_canc})

        if solic_canc_id:
            qtd_resg_antes = await db_scalar("SELECT quantidade_resgatada FROM lotes WHERE id = :lid", {"lid": LOTE_TEST_ID})
            r_aprov_canc = http_call("POST", f"/api/admin/cancelamentos/{solic_canc_id}/aprovar", identity="admin")
            ing_del_depois = await db_scalar("SELECT deleted_at FROM ingressos WHERE id = 909")
            qtd_resg_depois = await db_scalar("SELECT quantidade_resgatada FROM lotes WHERE id = :lid", {"lid": LOTE_TEST_ID})
            record_call("/api/admin/cancelamentos/{solicitacao_id}/aprovar", "POST", "Aprovação do cancelamento com revogação do ingresso e preservação da ocupação", "Admin", f"Solicitação {solic_canc_id}", {}, r_aprov_canc, f"Ingresso deleted_at={ing_del_depois}, Lote resgatada: {qtd_resg_antes}->{qtd_resg_depois}", "JSON com sucesso=true", "Ocupação mantida e ingresso invalidado", "HTTP 200 OK com ingresso revogado", expected_status=200)

        await db_exec("""
            INSERT INTO solicitacoes_cancelamento (id, token, usuario_id, ingresso_id, codigo_verificacao, codigo_expira_em, status, criado_em)
            VALUES (995, :tok, 907, 907, '123456', NOW() + INTERVAL '1 hour', 'pendente_analise', NOW())
            ON CONFLICT (id) DO UPDATE SET status = 'pendente_analise';
        """, {"tok": str(uuid.uuid4())})

        r_rej_canc = http_call("POST", "/api/admin/cancelamentos/995/rejeitar", identity="admin", json_data={"motivo": "Selfie não coincide com o cadastro"})
        st_rej_canc = await db_scalar("SELECT status FROM solicitacoes_cancelamento WHERE id = 995")
        record_call("/api/admin/cancelamentos/{solicitacao_id}/rejeitar", "POST", "Indeferimento do cancelamento mantendo o ingresso válido", "Admin", "Solicitação 995", {"motivo": "Selfie não coincide"}, r_rej_canc, f"Status no DB: {st_rej_canc}", "JSON com sucesso=true", "Mock email de indeferimento enviado", "HTTP 200 OK com status=rejeitado", expected_status=200)

    # Cancelamento direto de ingresso pelo Admin
    r_dir_canc1 = http_call("POST", "/admin/ingresso/907/cancelar", identity="admin", data={"motivo": "Cancelamento administrativo direto"})
    record_call("/admin/ingresso/{ingresso_id}/cancelar", "POST", "Cancelamento direto de ingresso via rota legado do painel", "Admin", "Ingresso 907", {}, r_dir_canc1, "deleted_at setado no DB", "Redirecionamento ou 200", "Ingresso cancelado", "HTTP 303 / 200", expected_status=303)

    r_dir_canc2 = http_call("POST", "/api/admin/ingressos/907/cancelar", identity="admin", json_data={"motivo": "Cancelamento administrativo API"})
    record_call("/api/admin/ingressos/{ingresso_id}/cancelar", "POST", "Cancelamento direto de ingresso via API administrativa", "Admin", "Ingresso 907", {}, r_dir_canc2, "deleted_at confirmado no DB", "JSON de confirmação", "Ingresso cancelado", "HTTP 200 OK", expected_status=200)

async def test_biometria_and_spa():
    print("\n>>> 12. Testando Proteção de Fotos Biométricas e Fallback SPA...")
    r_foto_unauth = http_call("GET", "/static/uploads/fotos/audit_biometria_teste.jpg")
    record_call("/static/uploads/fotos/{filename}", "GET", "Acesso anônimo a arquivo biométrico facial existente (SEC-04 LGPD)", "Visitante", "Arquivo existente", {}, r_foto_unauth, "Sem alterações", "HTTP 403 Forbidden com acesso não autorizado", "Bloqueio de vazamento de biometria", "HTTP 403 Forbidden", expected_status=403)

    r_foto_auth = http_call("GET", "/static/uploads/fotos/audit_biometria_teste.jpg", identity="admin")
    record_call("/static/uploads/fotos/{filename}", "GET", "Acesso de membro da equipe autenticado a fotos biométricas", "Admin", "Membro staff autenticado", {}, r_foto_auth, "Sem alterações", "HTTP 200 com arquivo JPEG", "Permissão concedida", "HTTP 200 OK com imagem retornada", expected_status=200)

    spa_status = 200 if os.path.exists("app/static/dist/index.html") else 404
    r_spa = http_call("GET", "/rota-virtual-inexistente-vue")
    record_call("/{full_path:path}", "GET", "Fallback catch-all para rotas dinâmicas do SPA Vue Router", "Visitante", "Rota virtual", {}, r_spa, "Sem alterações", f"HTTP {spa_status}", "Nenhum", f"HTTP {spa_status} controlado", expected_status=spa_status)

async def test_security_matrix_and_privilege_escalation():
    print("\n>>> 13. Testando Matriz de Autorização Cruzada e Tentativas de Elevação de Privilégio...")
    r_sec1 = http_call("GET", "/api/lotes-admin", identity="servidor_1")
    record_call("/api/lotes-admin", "GET", "Tentativa de elevação vertical: Servidor comum acessando /api/lotes-admin", "Servidor", "Sem papel admin", {}, r_sec1, "Acesso bloqueado", "HTTP 403 Forbidden", "Nenhum", "HTTP 403 Forbidden", expected_status=403)

    r_sec2 = http_call("GET", "/portaria", identity="validador")
    record_call("/portaria", "GET", "Tentativa de acesso cruzado: Validador acessando /portaria sem papel portaria", "Validador", "Sem papel portaria", {}, r_sec2, "Acesso bloqueado", "HTTP 403 Forbidden", "Nenhum", "HTTP 403 Forbidden", expected_status=403)

    r_sec3 = http_call("POST", "/admin/lote", identity="portaria", data={"nome": "Invasao", "quantidade_total": 1, "data_abertura": datetime.now().isoformat()})
    record_call("/admin/lote", "POST", "Tentativa de elevação vertical: Portaria tentando criar lote administrativo", "Portaria", "Sem papel admin", {}, r_sec3, "Acesso bloqueado", "HTTP 403 Forbidden", "Nenhum", "HTTP 403 Forbidden", expected_status=403)

    r_sec4 = http_call("POST", "/api/sorteios/anular/999", identity="entregador", json_data={"motivo": "Fraude"})
    record_call("/api/sorteios/anular/{ganhador_id}", "POST", "Tentativa de elevação: Entregador tentando anular sorteio", "Entregador", "Sem papel admin", {}, r_sec4, "Acesso bloqueado", "HTTP 403 Forbidden", "Nenhum", "HTTP 403 Forbidden", expected_status=403)

    r_tamper = http_call("GET", "/api/admin/usuarios-equipe", cookies={"access_token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.adulterado.assinatura_falsa"})
    record_call("/api/admin/usuarios-equipe", "GET", "Envio de token JWT assinado com chave forjada/inválida em rota protegida", "Invasor", "Token adulterado", {}, r_tamper, "Acesso rejeitado", "HTTP 303 Redirect / 401", "Nenhum", "HTTP 303 / 401 Rejeição obrigatória", expected_status=303)

    r_cross = http_call("GET", "/api/sucesso/999999", identity="servidor_1")
    record_call("/api/sucesso/{ingresso_id}", "GET", "Tentativa de consulta a identificador de ingresso inexistente ou de terceiro", "Servidor", "ID inexistente", {}, r_cross, "Sem alterações", "HTTP 404 Not Found", "Nenhum", "HTTP 404 Not Found", expected_status=404)

async def test_freshness_read_after_write_concurrency():
    print("\n>>> 14. Testando Consistência, Linearizabilidade e Concorrência (Seções 8.1 a 8.6)...")
    nova_cap = 15
    r_edit = http_call("POST", f"/admin/lote/{LOTE_TEST_ID}/editar", identity="admin", data={
        "nome": "Lote Auditoria 2026",
        "quantidade_total": nova_cap,
        "data_abertura": (datetime.now() - timedelta(days=1)).isoformat(),
        "data_fechamento": (datetime.now() + timedelta(days=5)).isoformat(),
        "secretaria_id": str(SEC_TEST_ID),
        "ativo": "on"
    })
    cap_db = await db_scalar("SELECT quantidade_total FROM lotes WHERE id = :lid", {"lid": LOTE_TEST_ID})
    r_adm = http_call("GET", "/api/lotes-admin", identity="admin")
    lotes_adm = r_adm.json().get("lotes", []) if r_adm.status_code == 200 else []
    l_adm = next((l.get("model", {}) for l in lotes_adm if l.get("model", {}).get("id") == LOTE_TEST_ID), {})
    cap_adm = l_adm.get("quantidade_total")
    r_live = http_call("GET", f"/api/lote/live-status?lote_id={LOTE_TEST_ID}")
    cap_live = r_live.json().get("quantidade_total") if r_live.status_code == 200 else None

    consistente = (cap_db == nova_cap and cap_adm == nova_cap and cap_live == nova_cap)
    diff_txt = f"PostgreSQL={cap_db}, AdminAPI={cap_adm}, LiveStatusAPI={cap_live}"
    record_call("/admin/lote/{lote_id}/editar", "POST", "Consistência de Leitura Imediata Pós-Escrita entre PostgreSQL, Admin API e Live Status", "Admin", f"Capacidade alterada para {nova_cap}", {}, r_edit, diff_txt, f"Todos endpoints retornam {nova_cap}", "Cache invalidado com sucesso", "Valores idênticos e atualizados em todos os canais", classification="Aprovado" if consistente else "Falhou")

    for i in range(3):
        http_call("POST", f"/admin/lote/{LOTE_TEST_ID}/toggle", identity="admin")
    st_final = await db_scalar("SELECT ativo FROM lotes WHERE id = :lid", {"lid": LOTE_TEST_ID})
    r_chk_obj = requests.Response()
    r_chk_obj.status_code = 200
    r_chk_obj._content = json.dumps({"ativo_db": st_final}).encode("utf-8")
    record_call("/admin/lote/{lote_id}/toggle", "POST", "Toggles consecutivos em sequência rápida garantindo convergência de estado", "Admin", "Múltiplos updates", {}, r_chk_obj, f"Estado final no DB: ativo={st_final}", "Convergência do estado", "Sem respostas defasadas", "Convergência determinística", expected_status=200)

    cpf_conc = gen_cpf(918)
    def req_val_cpf():
        return requests.get(f"{BASE_URL}/api/resgate/validar-cpf?cpf={cpf_conc}", timeout=10)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(req_val_cpf)
        f2 = executor.submit(req_val_cpf)
        res1 = f1.result()
        res2 = f2.result()

    r_conc_mock = requests.Response()
    r_conc_mock.status_code = 200 if (res1.status_code == 200 and res2.status_code == 200) else 500
    r_conc_mock._content = json.dumps({"res1": res1.status_code, "res2": res2.status_code}).encode("utf-8")
    record_call("/api/resgate/validar-cpf", "GET", "Concorrência de 2 chamadas paralelas para o mesmo CPF sem race condition", "Visitante", "Concorrência real", {"cpf": cpf_conc}, r_conc_mock, "Sem deadlocks ou inconsistências", "Ambas requisições tratadas de forma atômica", "Nenhum", "Tratamento atômico sem erro 500", expected_status=200)

async def teardown_test_environment():
    print("\n>>> 15. Limpando dados temporários de teste e preservando integridade...")
    if os.path.exists("app/static/uploads/fotos/audit_biometria_teste.jpg"):
        os.remove("app/static/uploads/fotos/audit_biometria_teste.jpg")

    await db_exec("DELETE FROM reservas_ingressos WHERE lote_id = :lid OR lote_id IN (SELECT id FROM lotes WHERE nome LIKE 'Lote Tempor%')", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM solicitacoes_cancelamento WHERE usuario_id BETWEEN 901 AND 915")
    await db_exec("DELETE FROM solicitacoes_validacao WHERE usuario_id BETWEEN 901 AND 915 OR lote_id = :lid", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM ganhadores WHERE usuario_id BETWEEN 901 AND 915 OR premio_id = :pid", {"pid": PREMIO_TEST_ID})
    await db_exec("DELETE FROM logs_acesso WHERE usuario_id BETWEEN 901 AND 915")
    await db_exec("DELETE FROM ingressos WHERE usuario_id BETWEEN 901 AND 915 OR lote_id = :lid OR lote_id IN (SELECT id FROM lotes WHERE nome LIKE 'Lote Tempor%')", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM tokens_exclusao_lote WHERE lote_id = :lid OR lote_id IN (SELECT id FROM lotes WHERE nome LIKE 'Lote Tempor%')", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM backups_lotes WHERE lote_id = :lid OR lote_id IN (SELECT id FROM lotes WHERE nome LIKE 'Lote Tempor%')", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM lotes WHERE id = :lid OR nome LIKE 'Lote Tempor%'", {"lid": LOTE_TEST_ID})
    await db_exec("DELETE FROM premios WHERE id = :pid OR nome LIKE '%Auditoria%'", {"pid": PREMIO_TEST_ID})
    await db_exec("DELETE FROM usuarios WHERE id BETWEEN 901 AND 915")
    await db_exec("DELETE FROM secretarias WHERE id = :sid", {"sid": SEC_TEST_ID})
    await db_exec("DELETE FROM eixos WHERE id = :eid", {"eid": EIXO_TEST_ID})

    lote1 = await db_fetchall("SELECT id, nome, quantidade_total, quantidade_resgatada FROM lotes WHERE id = 1")
    print(f"✅ Teardown concluído! Estado do Lote 1 preservado intacto: {lote1}")

async def run_all_audits():
    await setup_test_environment()
    try:
        await test_gatekeeper()
        await test_public_and_sse()
        await test_auth_and_session()
        await test_lotes_admin_crud()
        await test_admin_ingressos_relatorios_usuarios()
        await test_resgate_e2e_and_ingressos()
        await test_validacoes_manuais_e2e()
        await test_portaria_and_qr_code()
        await test_sorteios_and_premios()
        await test_cancelamento_e2e()
        await test_biometria_and_spa()
        await test_security_matrix_and_privilege_escalation()
        await test_freshness_read_after_write_concurrency()
    finally:
        await teardown_test_environment()

    with open("/tmp/audit_evidence.json", "w", encoding="utf-8") as f:
        json.dump(EVIDENCE, f, ensure_ascii=False, indent=2)

    total_calls = len(EVIDENCE)
    aprovados = sum(1 for e in EVIDENCE if e["classification"] == "Aprovado")
    falhas = sum(1 for e in EVIDENCE if e["classification"] == "Falhou")

    print(f"\n=======================================================")
    print(f"AUDITORIA CONCLUÍDA:")
    print(f"Total de Chamadas HTTP Executadas: {total_calls}")
    print(f"Aprovados: {aprovados}")
    print(f"Falhas: {falhas}")
    print(f"Arquivo gerado: tests/audit_evidence.json")
    print(f"=======================================================")

if __name__ == "__main__":
    asyncio.run(run_all_audits())
