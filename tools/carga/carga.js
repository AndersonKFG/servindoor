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
if (!/^https?:\/\/[^/?#]+$/.test(base) || base.includes('@')) throw new Error('Informe uma URL sem caminho, query ou credenciais.');
if (!['home', 'reservas'].includes(mode)) throw new Error('Modo inválido.');
if (![10, 100, 500, 1000, 2000, 3000, 4000].includes(maximum)) throw new Error('Limite inválido.');
if (!/^[a-zA-Z0-9_-]{1,50}$/.test(run)) throw new Error('Identificação do teste inválida.');
if (mode === 'reservas' && (!Number.isInteger(lot) || lot < 1 || !__ENV.LOAD_TEST_SECRET)) throw new Error('Reservas exigem lote de teste e chave temporária.');

const stages = [];
for (const target of [10, 100, 500, 1000, 2000, 3000, 4000].filter(n => n <= maximum)) {
  stages.push({ duration: target <= 100 ? '30s' : '60s', target });
  stages.push({ duration: '2m', target });
}
stages.push({ duration: '30s', target: 0 });

const connections = new Counter('sse_conexoes_abertas');
const snapshots = new Counter('sse_estados_recebidos');
const failures = new Rate('sse_falhas');
const openTime = new Trend('sse_abertura_ms', true);
const snapshotTime = new Trend('sse_estado_ms', true);
const reservationTime = new Trend('reserva_resposta_ms', true);
const resumeOK = new Rate('reserva_continuidade_ok');

export const options = {
  scenarios: { visitantes: { executor: 'ramping-vus', startVUs: 0, stages, gracefulRampDown: '0s', gracefulStop: '0s' } },
  // Evita milhares de séries de métricas com fingerprints/URLs/tokens únicos.
  systemTags: ['name', 'method', 'status', 'scenario', 'expected_response'],
  userAgent: 'Servindoor-LoadTest/1.0',
  setupTimeout: '40s',
  thresholds: {
    checks: [{ threshold: 'rate>0.99', abortOnFail: true, delayAbortEval: '30s' }],
    sse_falhas: [{ threshold: 'rate<0.01', abortOnFail: true, delayAbortEval: '30s' }],
    sse_estado_ms: ['p(95)<3000'],
    ...(mode === 'reservas' ? { reserva_continuidade_ok: ['rate==1'], reserva_resposta_ms: ['p(95)<3000'] } : {}),
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
  console.log(`Teste ${run}: ${mode}, até ${maximum} visitantes. Ctrl+C interrompe.`);
  return { gateToken };
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
            const remaining = Number(state.minha_reserva_expira_em_ms) - Number(state.server_time_ms);
            const correct = state.minha_reserva_token === config.expectedToken && remaining > 0 && remaining <= 300000
              && (!config.expectedExpiry || state.minha_reserva_expira_em_ms === config.expectedExpiry);
            resumeOK.add(correct);
            check(correct, { 'F5 preserva token e expiração da reserva': value => value });
          }
          if (config.expectEmpty) check(state, { 'desistência remove a reserva do SSE': value => value.minha_reserva_token == null });
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
    const page = http.get(`${base}/`, params('home', { 'X-Gatekeeper-Token': data.gateToken }));
    if (!check(page, { 'home responde HTTP 200': value => value.status === 200 })) { sleep(5); return; }
  }
  if (mode === 'home') { stream(fingerprint, data.gateToken); sleep(1 + Math.random() * 2); return; }

  // O estado é lido primeiro pelo SSE, como no site. Nunca usa live-status.
  if (!stream(fingerprint, data.gateToken, { snapshotOnly: true })) { sleep(5); return; }
  const url = `${base}/api/lote/${lot}/reservar?device_fingerprint=${encodeURIComponent(fingerprint)}&device_id=${encodeURIComponent(fingerprint)}`;
  const reserved = http.post(url, null, params('reservar', headers));
  reservationTime.add(reserved.timings.duration);
  let token = null;
  try { token = reserved.json('token_reserva'); } catch { /* Resposta não JSON também é falha. */ }
  if (!check(reserved, { 'reserva criada/recuperada': value => value.status === 200 && !!token })) { sleep(5); return; }
  try {
    const before = stream(fingerprint, data.gateToken, { snapshotOnly: true, expectedToken: token });
    if (!before) return;
    sleep(2);
    const refreshed = http.post(url, null, params('reservar_f5', headers));
    let sameToken = false;
    try { sameToken = refreshed.status === 200 && refreshed.json('token_reserva') === token; } catch { /* Contabilizada abaixo. */ }
    resumeOK.add(sameToken);
    check(sameToken, { 'POST do F5 não cria outra reserva': value => value });
    stream(fingerprint, data.gateToken, { expectedToken: token, expectedExpiry: before.minha_reserva_expira_em_ms });
  } finally {
    const quit = http.post(`${base}/api/resgate/desistir`, { token_reserva: token }, params('desistir', headers));
    if (check(quit, { 'desistência responde HTTP 200': value => value.status === 200 })) stream(fingerprint, data.gateToken, { snapshotOnly: true, expectEmpty: true });
  }
  sleep(1 + Math.random() * 3);
}

export function handleSummary(data) {
  const value = (name, key) => data.metrics[name]?.values?.[key] ?? null;
  const report = {
    teste: run, modo: mode, limite_planejado: maximum,
    vus_max_observado: value('vus', 'max'),
    conexoes_abertas_acumuladas: value('sse_conexoes_abertas', 'count'),
    estados_recebidos_acumulados: value('sse_estados_recebidos', 'count'),
    falhas_sse: value('sse_falhas', 'rate'), sse_estado_p95_ms: value('sse_estado_ms', 'p(95)'),
    continuidade_reserva: value('reserva_continuidade_ok', 'rate'), reserva_p95_ms: value('reserva_resposta_ms', 'p(95)'),
    verificacoes_ok: value('checks', 'rate'),
    limites: 'VUs são visitantes programados; não comprovam conexões saudáveis simultâneas. Veja métricas por tempo e o servidor. Não cobre foto, emissão de ingresso ou e-mail.',
  };
  return {
    '/resultados/resumo.json': JSON.stringify({ report, metrics: data.metrics }, null, 2),
    stdout: '\nRESUMO DO TESTE\n' + JSON.stringify(report, null, 2) + '\n',
  };
}
