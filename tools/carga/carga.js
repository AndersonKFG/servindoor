import http from 'k6/http';
import sse from 'k6/x/sse';
import exec from 'k6/execution';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const base = (__ENV.TARGET_URL || '').replace(/\/$/, '');
const mode = __ENV.TEST_MODE || 'home';
const maximum = Number(__ENV.MAX_VISITORS || 10);
const lot = Number(__ENV.TEST_LOTE_ID || 0);
const run = __ENV.TEST_RUN_ID || '';
const forceHTTP1 = (__ENV.GODEBUG || '').split(',').includes('http2client=0');
const profile = __ENV.LOAD_PROFILE || 'normal';
if (!/^https?:\/\/[^/?#]+$/.test(base) || base.includes('@')) throw new Error('Informe uma URL sem caminho, query ou credenciais.');
if (!['home', 'reservas'].includes(mode)) throw new Error('Modo inválido.');
if (![10, 100, 500, 1000, 2000, 3000, 4000].includes(maximum)) throw new Error('Limite inválido.');
if (mode === 'reservas' && maximum > 2000) throw new Error('O teste de reservas aceita até 2000 visitantes.');
if (!['normal', 'diagnostico'].includes(profile)) throw new Error('Perfil inválido.');
if (profile === 'diagnostico' && (mode !== 'home' || maximum > 1000)) throw new Error('O diagnóstico curto permite somente home, até 1000 visitantes.');
if (!/^[a-zA-Z0-9_-]{1,50}$/.test(run)) throw new Error('Identificação do teste inválida.');
if (mode === 'reservas' && (!Number.isInteger(lot) || lot < 1 || !__ENV.LOAD_TEST_SECRET)) throw new Error('Reservas exigem lote de teste e chave temporária.');

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
let reservationDiagnostics = 0;

export const options = {
  scenarios: { visitantes: { executor: 'ramping-vus', startVUs: 0, stages, gracefulRampDown: '0s', gracefulStop: '0s' } },
  // Evita milhares de séries de métricas com fingerprints/URLs/tokens únicos.
  systemTags: ['name', 'method', 'status', 'scenario', 'expected_response', 'error_code', 'proto', 'check'],
  userAgent: 'Servindoor-LoadTest/1.0',
  setupTimeout: '40s',
  thresholds: {
    checks: [{ threshold: 'rate>0.99', abortOnFail: true, delayAbortEval: '30s' }],
    sse_falhas: [{ threshold: 'rate<0.01', abortOnFail: true, delayAbortEval: '30s' }],
    sse_estado_ms: ['p(95)<3000'],
    ...(mode === 'reservas' ? {
      reserva_continuidade_ok: ['rate==1'], reserva_resposta_ms: ['p(95)<3000'],
      reserva_token_f5_ok: ['rate==1'], reserva_prazo_sse_ok: ['rate==1'],
      reserva_desistencia_ok: ['rate==1'],
      reserva_falhas_tecnicas: [{ threshold: 'rate<0.01', abortOnFail: true, delayAbortEval: '30s' }],
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
  if (!preflight || (mode === 'reservas' && Number(preflight.id) !== lot)) throw new Error('O SSE não entregou o estado esperado. Confira o lote/Cloudflare antes da carga.');
  if (mode === 'reservas' && !preflight.pode_resgatar) throw new Error('O lote de teste não está aberto para resgates.');
  if (mode === 'reservas') { accepted.add(0); filling.add(0); soldOut.add(0); }
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
  const query = `device_fingerprint=${encodeURIComponent(fingerprint)}${mode === 'reservas' ? `&lote_id=${lot}` : ''}`;
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
  const url = `${base}/api/lote/${lot}/reservar?device_fingerprint=${encodeURIComponent(fingerprint)}&device_id=${encodeURIComponent(fingerprint)}`;
  const reserved = http.post(url, null, params('reservar', headers));
  reservationTime.add(reserved.timings.duration);
  let response = null;
  try { response = reserved.json(); } catch { /* Resposta não JSON também é falha. */ }
  const token = response?.token_reserva;
  const success = reserved.status === 200 && typeof token === 'string' && token.length > 0;
  const capacity = reserved.status === 400 && ['em_preenchimento', 'esgotado'].includes(response?.codigo);
  reservationFailures.add(!success && !capacity);
  if (!check(reserved, { 'reserva aceita ou sem vaga por lotação': () => success || capacity })) { sleep(5); return; }
  if (capacity) {
    if (response.codigo === 'em_preenchimento') filling.add(1);
    else soldOut.add(1);
    // Quem não conseguiu vaga continua acompanhando o SSE sem repetir o POST em loop.
    stream(fingerprint, data.gateToken);
    sleep(1 + Math.random() * 3);
    return;
  }
  accepted.add(1);
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
    verificacoes_ok: value('checks', 'rate'),
    limites: 'VUs são visitantes programados; não comprovam conexões saudáveis simultâneas. Veja métricas por tempo e o servidor. Não cobre foto, emissão de ingresso ou e-mail.',
  };
  return {
    '/resultados/resumo.json': JSON.stringify({ report, metrics: data.metrics }, null, 2),
    stdout: '\nRESUMO DO TESTE\n' + JSON.stringify(report, null, 2) + '\n',
  };
}
