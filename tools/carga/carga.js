import http from 'k6/http';
import sse from 'k6/x/sse';
import exec from 'k6/execution';
import encoding from 'k6/encoding';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const base = (__ENV.TARGET_URL || '').replace(/\/$/, '');
const mode = __ENV.TEST_MODE || 'home';
const maximum = Number(__ENV.MAX_VISITORS || 10);
const lot = Number(__ENV.TEST_LOTE_ID || 0);
const run = __ENV.TEST_RUN_ID || '';
const forceHTTP1 = (__ENV.GODEBUG || '').split(',').includes('http2client=0');
const profile = __ENV.LOAD_PROFILE || 'normal';
const secretary = Number(__ENV.TEST_SECRETARIA_ID || 0);
const controlledEmail = __ENV.LOAD_TEST_EMAIL || '';
const testsReservations = mode === 'reservas' || mode === 'resgate';
if (!/^https?:\/\/[^/?#]+$/.test(base) || base.includes('@')) throw new Error('Informe uma URL sem caminho, query ou credenciais.');
if (!['home', 'reservas', 'resgate'].includes(mode)) throw new Error('Modo inválido.');
if (![10, 100, 500, 1000, 2000, 3000, 4000].includes(maximum)) throw new Error('Limite inválido.');
if (testsReservations && maximum > 2000) throw new Error('Reservas e resgate aceitam até 2000 visitantes.');
if (!['normal', 'diagnostico'].includes(profile)) throw new Error('Perfil inválido.');
if (profile === 'diagnostico' && (mode !== 'home' || maximum > 1000)) throw new Error('O diagnóstico curto permite somente home, até 1000 visitantes.');
if (!/^[a-zA-Z0-9_-]{1,50}$/.test(run)) throw new Error('Identificação do teste inválida.');
if (testsReservations && (!Number.isInteger(lot) || lot < 1 || !__ENV.LOAD_TEST_SECRET)) throw new Error('Reservas e resgate exigem lote de teste e chave temporária.');
if (mode === 'resgate' && (!Number.isInteger(secretary) || secretary < 1
  || !/^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/.test(controlledEmail)
  || __ENV.LOAD_TEST_EMAIL_CONFIRMED !== 'ENVIAR_EMAILS')) {
  throw new Error('Resgate exige secretaria válida, e-mail controlado e confirmação ENVIAR_EMAILS.');
}
// JPEG sintético de 320x240, sem pessoa real: mede upload e gravação da foto.
const testPhoto = mode === 'resgate' ? 'data:image/jpeg;base64,' + encoding.b64encode(open('./foto_teste.jpg', 'b')) : '';

const stages = [];
if (profile === 'diagnostico') {
  stages.push({ duration: '60s', target: maximum }, { duration: '2m', target: maximum });
} else {
  const targets = maximum >= 500 ? [500, 1000, 2000, 3000, 4000] : [10, 100];
  for (const target of targets.filter(n => n <= maximum)) {
    stages.push({ duration: target <= 100 ? '30s' : '60s', target });
    stages.push({ duration: '2m', target });
  }
}
stages.push({ duration: '30s', target: 0 });

const connections = new Counter('sse_conexoes_abertas');
const snapshots = new Counter('sse_estados_recebidos');
const failures = new Rate('sse_falhas');
const openTime = new Trend('sse_abertura_ms', true);
const snapshotTime = new Trend('sse_estado_ms', true);
const reservationTime = new Trend('reserva_resposta_ms', true);
const resumeOK = new Rate('reserva_continuidade_ok');
const tokenF5OK = new Rate('reserva_token_f5_ok');
const deadlineSSEOK = new Rate('reserva_prazo_sse_ok');
const quitOK = new Rate('reserva_desistencia_ok');
const accepted = new Counter('reservas_aceitas');
const filling = new Counter('reservas_sem_vaga_em_preenchimento');
const soldOut = new Counter('reservas_sem_vaga_esgotado');
const reservationFailures = new Rate('reserva_falhas_tecnicas');
const homeFailures = new Rate('home_falhas');
const homeTime = new Trend('home_total_ms', true);
const formTime = new Trend('resgate_formulario_ms', true);
const formFailures = new Rate('resgate_falhas_tecnicas');
const idempotentOK = new Rate('resgate_idempotencia_ok');
const recoveredOK = new Rate('resgate_recuperacao_ok');
const confirmedForms = new Counter('resgates_confirmados');
const repeatedCPFs = new Counter('resgates_cpf_ja_atendido');
const submittedForms = new Counter('resgates_formularios_enviados');
let reservationDiagnostics = 0;

export const options = {
  scenarios: { visitantes: mode === 'resgate'
    ? { executor: 'per-vu-iterations', vus: maximum, iterations: 1, maxDuration: '10m', gracefulStop: '30s' }
    : { executor: 'ramping-vus', startVUs: 0, stages, gracefulRampDown: '0s', gracefulStop: '0s' } },
  // Evita milhares de séries de métricas com fingerprints/URLs/tokens únicos.
  systemTags: ['name', 'method', 'status', 'scenario', 'expected_response', 'error_code', 'proto', 'check'],
  userAgent: 'Servindoor-LoadTest/1.0',
  setupTimeout: '40s',
  thresholds: {
    checks: [{ threshold: 'rate>0.99', abortOnFail: true, delayAbortEval: '30s' }],
    sse_falhas: [{ threshold: 'rate<0.01', abortOnFail: true, delayAbortEval: '30s' }],
    sse_estado_ms: ['p(95)<3000'],
    ...(testsReservations ? {
      reserva_resposta_ms: ['p(95)<3000'],
      reserva_falhas_tecnicas: [{ threshold: 'rate<0.01', abortOnFail: true, delayAbortEval: '30s' }],
    } : {}),
    ...(mode === 'reservas' ? {
      reserva_continuidade_ok: ['rate==1'],
      reserva_token_f5_ok: ['rate==1'], reserva_prazo_sse_ok: ['rate==1'],
      reserva_desistencia_ok: ['rate==1'],
    } : {}),
    ...(mode === 'resgate' ? {
      resgate_formulario_ms: ['p(95)<3000'], resgate_idempotencia_ok: ['rate==1'],
      resgate_falhas_tecnicas: [{ threshold: 'rate<0.01', abortOnFail: true, delayAbortEval: '30s' }],
      resgates_confirmados: ['count>0'],
    } : {}),
  },
};

function params(name, headers = {}) {
  return { tags: { name }, timeout: '15s', redirects: 0, headers };
}

export function setup() {
  let gateToken = '';
  const status = http.get(`${base}/api/gatekeeper/status`, params('gate_status'));
  if (status.status !== 200) throw new Error(`Não foi possível consultar o acesso: HTTP ${status.status}.`);
  const gate = status.json();
  if (gate.gatekeeper_enabled && !gate.autorizado) {
    if (!__ENV.SITE_PIN) throw new Error('O site exige o PIN de acesso.');
    const access = http.post(`${base}/api/gatekeeper/verificar`, JSON.stringify({ pin: __ENV.SITE_PIN }),
      params('gate_verificar', { 'Content-Type': 'application/json' }));
    // Uma tentativa apenas: não repete PIN incorreto até bloquear o IP.
    if (access.status !== 200 || !access.json('token')) throw new Error(`PIN recusado: HTTP ${access.status}.`);
    gateToken = access.json('token');
  }
  const preflight = stream('loadtest_' + run + '_preflight', gateToken, { snapshotOnly: true, timeout: '10s' });
  if (!preflight || (testsReservations && Number(preflight.id) !== lot)) throw new Error('O SSE não entregou o estado esperado. Confira o lote/Cloudflare antes da carga.');
  if (testsReservations && !preflight.pode_resgatar) throw new Error('O lote de teste não está aberto para resgates.');
  if (testsReservations) { accepted.add(0); filling.add(0); soldOut.add(0); }
  if (mode === 'resgate') {
    const departments = http.get(`${base}/api/secretarias`, params('secretarias_setup', { 'X-Gatekeeper-Token': gateToken }));
    let available = null;
    try { available = departments.json(); } catch {}
    if (departments.status !== 200 || !Array.isArray(available) || !available.some(item => Number(item.id) === secretary)) {
      throw new Error('A secretaria escolhida não foi encontrada. Nenhum formulário foi enviado.');
    }
    confirmedForms.add(0); repeatedCPFs.add(0); submittedForms.add(0);
  }
  console.log(`Teste ${run}: ${mode}, perfil ${profile}, até ${maximum} visitantes, HTTP ${forceHTTP1 ? '1.1 forçado' : 'automático'}. Ctrl+C interrompe.`);
  return { gateToken };
}

function diagnosticReservation(stage, details) {
  // Limita a saída por VU; não imprime tokens, cookies ou a chave temporária.
  if (reservationDiagnostics >= 3) return;
  reservationDiagnostics += 1;
  console.warn('[diagnostico_reserva] ' + JSON.stringify({
    teste: run, utc: new Date().toISOString(), vu: exec.vu.idInTest, etapa: stage, ...details,
  }));
}

function stream(fingerprint, gateToken, config = {}) {
  const start = Date.now();
  const until = start + 90000;
  let state = null;
  let intentional = false;
  let failed = false;
  let ready = false;
  const headers = { 'X-Gatekeeper-Token': gateToken, 'X-Device-Fingerprint': fingerprint };
  const query = `device_fingerprint=${encodeURIComponent(fingerprint)}${testsReservations ? `&lote_id=${lot}` : ''}`;
  try {
    sse.open(`${base}/api/lote/stream?${query}`, {
      headers, timeout: config.timeout || '120s', tags: { name: 'lote_stream' },
    }, client => {
      client.on('open', () => { connections.add(1); openTime.add(Date.now() - start); });
      client.on('error', () => { failed = true; client.close(); });
      client.on('event', event => {
        if (event.name === 'ESTADO_CONSOLIDADO' && !ready) {
          try { state = JSON.parse(event.data); } catch { failed = true; client.close(); return; }
          ready = typeof state.server_time_ms === 'number' && typeof state.has_lote === 'boolean';
          snapshots.add(1);
          snapshotTime.add(Date.now() - start);
          if (!check(state, { 'SSE entrega estado e hora do servidor': () => ready })) { failed = true; client.close(); return; }
          if (config.expectedToken) {
            const expiry = state.minha_reserva_expira_em_ms;
            const remaining = expiry - state.server_time_ms;
            // O POST fornece o token. O SSE por fingerprint pode omiti-lo;
            // continua obrigatório entregar o prazo válido e preservar sua data.
            const tokenConsistent = state.minha_reserva_token == null || state.minha_reserva_token === config.expectedToken;
            const correct = typeof expiry === 'number' && Number.isFinite(expiry)
              && remaining > 0 && remaining <= 300000 && tokenConsistent
              && (config.expectedExpiry === undefined || expiry === config.expectedExpiry);
            deadlineSSEOK.add(correct);
            resumeOK.add(correct);
            if (!check(correct, { 'SSE entrega prazo válido e preserva expiração após F5': value => value })) {
              diagnosticReservation(config.expectedExpiry === undefined ? 'sse_apos_reservar' : 'sse_apos_f5', {
                server_time_ms: state.server_time_ms, expira_em_ms: expiry,
                expira_em_esperada_ms: config.expectedExpiry ?? null,
                restante_ms: remaining, token_sse_presente: state.minha_reserva_token != null,
                token_sse_coerente: tokenConsistent,
              });
            }
          }
          if (config.expectEmpty) {
            const empty = state.minha_reserva_token == null && state.minha_reserva_expira_em_ms == null
              && state.minha_reserva_segundos == null && state.minha_reserva_milissegundos == null;
            quitOK.add(empty);
            if (!check(empty, { 'desistência remove token e prazo da reserva do SSE': value => value })) {
              diagnosticReservation('sse_apos_desistir', {
                prazo_ainda_presente: state.minha_reserva_expira_em_ms != null,
                token_sse_presente: state.minha_reserva_token != null,
              });
            }
          }
          if (config.onSnapshot) config.onSnapshot(state);
          if (config.snapshotOnly) { intentional = true; client.close(); return; }
        }
        // A extensão entrega também os comentários (: ping), permitindo encerrar
        // a visita após ~90s sem tratar um timeout como fechamento normal.
        if (Date.now() >= until) { intentional = true; client.close(); }
      });
    });
  } catch { failed = true; }
  failures.add(failed || !ready || !intentional);
  return ready ? state : null;
}

function syntheticCPF() {
  // Cada décimo VU usa o CPF do VU anterior, com dispositivo diferente.
  const visitor = exec.vu.idInTest % 10 === 0 ? exec.vu.idInTest - 1 : exec.vu.idInTest;
  let seed = 2166136261;
  for (let index = 0; index < run.length; index++) seed = Math.imul(seed ^ run.charCodeAt(index), 16777619) >>> 0;
  const digits = String(100000000 + seed % 898990000 + visitor).split('').map(Number);
  for (const weight of [10, 11]) {
    const sum = digits.reduce((total, digit, index) => total + digit * (weight - index), 0);
    const remainder = sum % 11;
    digits.push(remainder < 2 ? 0 : 11 - remainder);
  }
  return digits.join('');
}

function completeRedemption(token, headers) {
  const boundary = `servindoor-${run}-${exec.vu.idInTest}`;
  const fields = {
    token_reserva: token, cpf: syntheticCPF(), nome: `TESTE CARGA ${run} VU ${exec.vu.idInTest}`,
    data_nascimento: '1990-01-01', setor: `TESTE_CARGA_${run}`, secretaria_id: String(secretary),
    vinculo: 'Efetivo', telefone: '81999999999', email: controlledEmail, foto_base64: testPhoto,
  };
  const body = Object.entries(fields).map(([key, value]) =>
    `--${boundary}\r\nContent-Disposition: form-data; name="${key}"\r\n\r\n${value}\r\n`).join('') + `--${boundary}--\r\n`;
  const requestHeaders = { ...headers, 'X-Load-Test-Form': '1', 'Content-Type': `multipart/form-data; boundary=${boundary}` };
  const send = name => http.post(`${base}/api/lote/${lot}/resgatar`, body, params(name, requestHeaders));
  const decode = response => { try { return response.json(); } catch { return null; } };
  const isConfirmed = (response, result) => response.status === 200 && result?.sucesso === true
    && Number.isInteger(result.solicitacao_id) && result.solicitacao_id > 0
    && typeof result.token === 'string' && result.token.length > 0 && typeof result.redirect_url === 'string';
  const isDuplicate = (response, result) => response.status === 409 && result?.codigo === 'cpf_ja_atendido';
  const diagnose = (stage, response, result) => diagnosticReservation(stage, {
    status: response.status, error_code: response.error_code || 0,
    codigo_api: typeof result?.codigo === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(result.codigo) ? result.codigo : null,
    total_ms: response.timings.duration, cf_ray: response.headers?.['Cf-Ray'] || null,
    resposta_json: result !== null,
  });

  // A conexão SSE permanece aberta enquanto esse callback envia o formulário.
  // Não reproduz digitação/câmera de navegador: a foto já está preparada.
  sleep(2 + Math.random() * 8);
  submittedForms.add(1);
  let response = send('resgatar_formulario');
  formTime.add(response.timings.duration);
  let result = decode(response);
  const firstConfirmed = isConfirmed(response, result);
  const firstDuplicate = isDuplicate(response, result);
  formFailures.add(!firstConfirmed && !firstDuplicate);
  if (!firstConfirmed && !firstDuplicate) {
    diagnose('post_resgatar', response, result);
    check(false, { 'formulário aceita cadastro ou informa CPF já atendido': value => value });
    // Resposta perdida pode esconder um commit concluído. Repete exatamente o
    // mesmo token/CPF/foto; não desiste de uma reserva com resultado incerto.
    if (response.status === 0 || response.status === 200 || response.status >= 500 || response.status === 408 || response.status === 429) {
      sleep(0.5);
      response = send('resgatar_recuperar');
      result = decode(response);
      recoveredOK.add(isConfirmed(response, result));
    }
  } else check(true, { 'formulário aceita cadastro ou informa CPF já atendido': value => value });

  if (isDuplicate(response, result)) {
    repeatedCPFs.add(1);
    const quit = http.post(`${base}/api/resgate/desistir`, { token_reserva: token }, params('desistir_cpf_ja_atendido', headers));
    let released = false;
    try { released = quit.status === 200 && quit.json('sucesso') === true; } catch {}
    if (!check(released, { 'CPF já atendido encerra ciclo e libera sua reserva': value => value })) diagnose('desistir_cpf_ja_atendido', quit, decode(quit));
    return;
  }
  if (!isConfirmed(response, result)) return;
  confirmedForms.add(1);
  const repeat = send('resgatar_repetir_confirmacao');
  const repeated = decode(repeat);
  const same = isConfirmed(repeat, repeated) && repeated.solicitacao_id === result.solicitacao_id
    && repeated.token === result.token && repeated.redirect_url === result.redirect_url;
  idempotentOK.add(same);
  if (!check(same, { 'repetir confirmação preserva protocolo e resultado': value => value })) diagnose('post_resgatar_repetir', repeat, repeated);
}

export default function (data) {
  const fingerprint = `loadtest_${run}_${exec.vu.idInTest}`;
  const headers = {
    'X-Gatekeeper-Token': data.gateToken, 'X-Device-Fingerprint': fingerprint,
    'X-Device-ID': fingerprint, 'X-Load-Test-Key': __ENV.LOAD_TEST_SECRET || '', Accept: 'application/json',
  };
  if (__ITER === 0) {
    const started = Date.now();
    const page = http.get(`${base}/`, params('home', { 'X-Gatekeeper-Token': data.gateToken }));
    const elapsed = Date.now() - started;
    homeFailures.add(page.status !== 200);
    homeTime.add(elapsed);
    if (page.status !== 200 || exec.vu.idInTest === 1) {
      // Somente campos de diagnóstico da GET /. Não registra cabeçalhos de
      // autenticação, cookies, corpos de resposta, PIN ou chave temporária.
      console.warn('[diagnostico_home] ' + JSON.stringify({
        teste: run, utc: new Date().toISOString(), vu: exec.vu.idInTest,
        status: page.status, error_code: page.error_code || 0,
        error: String(page.error || '').slice(0, 300),
        remote_ip: page.remote_ip || null, proto: page.proto || null,
        cf_ray: page.headers?.['Cf-Ray'] || null,
        total_ms: elapsed, timings: page.timings,
      }));
    }
    if (!check(page, { 'home responde HTTP 200': value => value.status === 200 })) { sleep(5); return; }
  }
  if (mode === 'home') { stream(fingerprint, data.gateToken); sleep(1 + Math.random() * 2); return; }

  // O estado é lido primeiro pelo SSE, como no site. Nunca usa live-status.
  if (!stream(fingerprint, data.gateToken, { snapshotOnly: true })) { sleep(5); return; }
  const loadKey = __ENV.LOAD_TEST_SECRET ? `&load_test_key=${encodeURIComponent(__ENV.LOAD_TEST_SECRET)}` : '';
  const url = `${base}/api/lote/${lot}/reservar?device_fingerprint=${encodeURIComponent(fingerprint)}&device_id=${encodeURIComponent(fingerprint)}${loadKey}`;
  const reserved = http.post(url, null, params('reservar', headers));
  reservationTime.add(reserved.timings.duration);
  let response = null;
  try { response = reserved.json(); } catch { /* Resposta não JSON também é falha. */ }
  const token = response?.token_reserva;
  const success = reserved.status === 200 && typeof token === 'string' && token.length > 0;
  const capacity = reserved.status === 400 && ['em_preenchimento', 'esgotado'].includes(response?.codigo);
  reservationFailures.add(!success && !capacity);
  if (!success && !capacity) {
    // Registra o primeiro POST que efetivamente falhou, antes de o aborto
    // cancelar F5/desistências em andamento. Nunca imprime corpo ou tokens.
    const apiCode = response?.codigo || response?.code || response?.detail?.codigo;
    diagnosticReservation('post_reservar', {
      status: reserved.status,
      codigo_api: typeof apiCode === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(apiCode) ? apiCode : null,
      error_code: reserved.error_code || 0,
      total_ms: reserved.timings.duration,
      espera_ms: reserved.timings.waiting,
      conexao_ms: reserved.timings.connecting,
      cf_ray: reserved.headers?.['Cf-Ray'] || null,
      resposta_json: response !== null,
      token_presente: typeof token === 'string' && token.length > 0,
    });
  }
  if (!check(reserved, { 'reserva aceita ou sem vaga por lotação': () => success || capacity })) { sleep(5); return; }
  if (capacity) {
    if (response.codigo === 'em_preenchimento') filling.add(1);
    else soldOut.add(1);
    if (mode === 'resgate') return;
    // Quem não conseguiu vaga continua acompanhando o SSE sem repetir o POST em loop.
    stream(fingerprint, data.gateToken);
    sleep(1 + Math.random() * 3);
    return;
  }
  accepted.add(1);
  if (mode === 'resgate') {
    let sent = false;
    stream(fingerprint, data.gateToken, {
      snapshotOnly: true, expectedToken: token,
      onSnapshot: () => { sent = true; completeRedemption(token, headers); },
    });
    check(sent, { 'reserva aceita alcança envio do formulário': value => value });
    return;
  }
  try {
    const before = stream(fingerprint, data.gateToken, { snapshotOnly: true, expectedToken: token });
    if (!before || typeof before.minha_reserva_expira_em_ms !== 'number') return;
    sleep(2);
    const refreshed = http.post(url, null, params('reservar_f5', headers));
    let sameToken = false;
    try { sameToken = refreshed.status === 200 && refreshed.json('token_reserva') === token; } catch { /* Contabilizada abaixo. */ }
    tokenF5OK.add(sameToken);
    resumeOK.add(sameToken);
    if (!check(sameToken, { 'POST do F5 preserva o token da reserva': value => value })) {
      diagnosticReservation('post_apos_f5', { status: refreshed.status, mesmo_token: sameToken });
    }
    stream(fingerprint, data.gateToken, { expectedToken: token, expectedExpiry: before.minha_reserva_expira_em_ms });
  } finally {
    const quit = http.post(`${base}/api/resgate/desistir`, { token_reserva: token }, params('desistir', headers));
    let released = false;
    try { released = quit.status === 200 && quit.json('sucesso') === true; } catch { /* Contabilizada abaixo. */ }
    quitOK.add(released);
    if (check(released, { 'desistência responde HTTP 200 e confirma sucesso': value => value })) {
      stream(fingerprint, data.gateToken, { snapshotOnly: true, expectEmpty: true });
    } else {
      diagnosticReservation('post_desistir', { status: quit.status, sucesso: released });
    }
  }
  sleep(1 + Math.random() * 3);
}

export function handleSummary(data) {
  const value = (name, key) => data.metrics[name]?.values?.[key] ?? null;
  const report = {
    teste: run, modo: mode, limite_planejado: maximum,
    perfil: profile,
    http1_forcado: forceHTTP1,
    vus_max_observado: value('vus', 'max'),
    conexoes_abertas_acumuladas: value('sse_conexoes_abertas', 'count'),
    estados_recebidos_acumulados: value('sse_estados_recebidos', 'count'),
    falhas_sse: value('sse_falhas', 'rate'), sse_estado_p95_ms: value('sse_estado_ms', 'p(95)'),
    falhas_home: value('home_falhas', 'rate'), home_total_p95_ms: value('home_total_ms', 'p(95)'),
    continuidade_reserva: value('reserva_continuidade_ok', 'rate'), reserva_p95_ms: value('reserva_resposta_ms', 'p(95)'),
    token_preservado_apos_f5: value('reserva_token_f5_ok', 'rate'),
    prazo_preservado_no_sse: value('reserva_prazo_sse_ok', 'rate'),
    desistencia_confirmada: value('reserva_desistencia_ok', 'rate'),
    reservas_aceitas_acumuladas: value('reservas_aceitas', 'count'),
    sem_vaga_em_preenchimento_acumuladas: value('reservas_sem_vaga_em_preenchimento', 'count'),
    sem_vaga_esgotado_acumuladas: value('reservas_sem_vaga_esgotado', 'count'),
    falhas_tecnicas_reserva: value('reserva_falhas_tecnicas', 'rate'),
    formularios_enviados: value('resgates_formularios_enviados', 'count'),
    resgates_confirmados: value('resgates_confirmados', 'count'),
    cpf_ja_atendido: value('resgates_cpf_ja_atendido', 'count'),
    formulario_p95_ms: value('resgate_formulario_ms', 'p(95)'),
    falhas_tecnicas_formulario: value('resgate_falhas_tecnicas', 'rate'),
    confirmacao_idempotente: value('resgate_idempotencia_ok', 'rate'),
    recuperacao_apos_falha: value('resgate_recuperacao_ok', 'rate'),
    verificacoes_ok: value('checks', 'rate'),
    limites: mode === 'resgate'
      ? 'Uma tentativa por VU, chegada direta. Foto JPEG sintética de 320x240; cadastra solicitação pendente e enfileira e-mail real no destino controlado. Não cobre câmera, aprovação, PDF do ingresso nem entrega SMTP. API externa é dispensada somente pela autorização temporária de teste.'
      : 'VUs são visitantes programados; não comprovam conexões saudáveis simultâneas. Veja métricas por tempo e o servidor. Não cobre foto, emissão de ingresso ou e-mail.',
  };
  return {
    '/resultados/resumo.json': JSON.stringify({ report, metrics: data.metrics }, null, 2),
    stdout: '\nRESUMO DO TESTE\n' + JSON.stringify(report, null, 2) + '\n',
  };
}
