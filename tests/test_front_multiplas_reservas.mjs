import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as reservationStorage from '../frontend/src/utils/reservationStorage.js';

const source = fs.readFileSync('frontend/src/views/ResgateView.vue', 'utf8')
  .split('<script setup>')[1].split('</script>')[0]
  .split('\n').filter(line => !line.startsWith('import ')).join('\n');

function storage() {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key) };
}

const sharedLocal = storage();
let sequence = 0;
function tab(session = storage(), query = {}) {
  const calls = [], streams = [];
  function ref(initial) {
    let value = initial;
    const callbacks = [];
    return { get value() { return value; }, set value(next) { value = next; callbacks.forEach(fn => fn(next)); }, callbacks };
  }
  class EventSource {
    constructor(url) { this.url = url; this.listeners = {}; streams.push(this); }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    close() {}
    emit(type, data) { this.listeners[type]?.({ type, data: JSON.stringify(data) }); }
  }
  const route = { params: { loteId: 1 }, path: '/resgate/1', query };
  const context = vm.createContext({ ref, computed: getter => ({ get value() { return getter(); } }),
    watch: (target, fn, options) => { target?.callbacks?.push(fn); if (options?.immediate) fn(target.value); }, onMounted() {}, onUnmounted() {},
    useRoute: () => route, useRouter: () => ({ push() {}, replace: async next => { route.query = next.query; } }),
    useServerTime: () => ({ calibrarComResposta() {}, getSynchronizedServerTime: () => Date.now() }),
    getDeviceFingerprint: () => 'same-fp', getDeviceId: () => 'same-device',
    getTabReservationToken: id => reservationStorage.getTabReservationToken(id, session),
    saveTabReservationToken: (id, token) => reservationStorage.saveTabReservationToken(id, token, session),
    clearTabReservationToken: id => reservationStorage.clearTabReservationToken(id, session),
    localStorage: sharedLocal, sessionStorage: session, document: { cookie: '' },
    window: { EventSource, location: { protocol: 'https:' } }, EventSource,
    console, FormData, URL, Date, Math, setTimeout, clearTimeout, setInterval: () => 1, clearInterval() {},
    fetch: async (url, options) => {
      calls.push({ url, options });
      const data = url.includes('/reservar')
        ? { token_reserva: options.headers['X-Reserva-Token'] || `token-${++sequence}` }
        : [];
      return { ok: true, json: async () => data };
    },
  });
  vm.runInContext(source + '\nglobalThis.api = { carregarDadosResgate, tokenReserva, reservaExpiraEmMs, form, salvarRascunhoFormulario, limparRascunhoFormulario, showModalDesistidaOutroNavegador };', context);
  return { api: context.api, session, calls, streams };
}

const first = tab(), second = tab();
await first.api.carregarDadosResgate();
await second.api.carregarDadosResgate();
assert.notEqual(first.api.tokenReserva.value, second.api.tokenReserva.value);
assert.ok(first.streams[0].url.includes(`token_reserva=${first.api.tokenReserva.value}`));
first.api.form.value.nome = 'Primeira aba';
first.api.salvarRascunhoFormulario();
second.api.form.value.nome = 'Segunda aba';
second.api.salvarRascunhoFormulario();
assert.equal(sharedLocal.getItem('festa_resgate_draft_1'), null);

const reloaded = tab(first.session);
await reloaded.api.carregarDadosResgate();
assert.equal(reloaded.calls[0].options.headers['X-Reserva-Token'], first.api.tokenReserva.value);
assert.equal(reloaded.api.form.value.nome, 'Primeira aba');

const ownToken = first.api.tokenReserva.value;
const stream = first.streams[0];
const deadline = Date.now() + 200000;
stream.emit('ESTADO_CONSOLIDADO', { minha_reserva_token: ownToken, minha_reserva_expira_em_ms: deadline, server_time_ms: Date.now() });
const originalDeadline = first.api.reservaExpiraEmMs.value;
stream.emit('ESTADO_CONSOLIDADO', { minha_reserva_token: second.api.tokenReserva.value, minha_reserva_expira_em_ms: deadline + 60000, server_time_ms: Date.now() });
stream.emit('RESERVA_ATUALIZADA', { tipo: 'reserva_criada', lote_id: 1, device_fingerprint: 'same-fp', device_id: 'same-device', token_reserva: second.api.tokenReserva.value, expira_em_ms: deadline + 60000, server_time_ms: Date.now() });
stream.emit('RESERVA_ATUALIZADA', { tipo: 'reserva_liberada', motivo: 'desistencia', lote_id: 1, device_fingerprint: 'same-fp', token_reserva: second.api.tokenReserva.value });
assert.equal(first.api.tokenReserva.value, ownToken);
assert.equal(first.api.reservaExpiraEmMs.value, originalDeadline);
assert.equal(first.api.showModalDesistidaOutroNavegador.value, false);
stream.emit('RESERVA_ATUALIZADA', { tipo: 'reserva_liberada', motivo: 'desistencia', lote_id: 1, token_reserva: ownToken });
assert.equal(first.api.showModalDesistidaOutroNavegador.value, true);

first.api.limparRascunhoFormulario();
assert.ok(second.session.getItem('festa_resgate_draft_1'));
const another = tab(second.session, { nova: '1' });
await another.api.carregarDadosResgate();
assert.equal(another.calls[0].options.headers['X-Reserva-Token'], '');
assert.notEqual(another.api.tokenReserva.value, second.api.tokenReserva.value);
assert.equal(another.api.form.value.nome, '');
const continued = tab(storage(), { token_reserva: ownToken });
await continued.api.carregarDadosResgate();
assert.equal(continued.calls[0].options.headers['X-Reserva-Token'], ownToken);
assert.equal(continued.session.getItem('festa_reserva_token_1'), ownToken);

const statusSource = fs.readFileSync('frontend/src/composables/useLoteStatus.js', 'utf8')
  .split('\n').filter(line => !line.startsWith('import ')).join('\n').replace(/^export /gm, '');

function home(session) {
  const streams = [];
  class EventSource {
    constructor(url) { this.url = url; this.listeners = {}; streams.push(this); }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    close() {}
    emit(type, data) { this.listeners[type]?.({ type, data: JSON.stringify(data) }); }
  }
  sharedLocal.setItem('servindoor_device_fp', 'same-fp');
  sharedLocal.setItem('servindoor_device_id', 'same-device');
  const context = vm.createContext({ ref: value => ({ value }), onMounted() {}, onUnmounted() {},
    useServerTime: () => ({ calibrarComResposta() {}, getSynchronizedServerTime: () => Date.now() }),
    getTabReservationToken: id => reservationStorage.getTabReservationToken(id, session),
    clearTabReservationToken: id => reservationStorage.clearTabReservationToken(id, session),
    sessionStorage: session, localStorage: sharedLocal, EventSource, window: { EventSource },
    document: { addEventListener() {}, removeEventListener() {} }, Date, Math, console,
  });
  vm.runInContext(statusSource + '\nglobalThis.api = useLoteStatus();', context);
  context.api.startSSE();
  return { api: context.api, streams };
}

const homeSessionA = storage(), homeSessionB = storage();
reservationStorage.saveTabReservationToken(1, 'home-token-a', homeSessionA);
const homeA = home(homeSessionA), homeB = home(homeSessionB);
const snapshot = token => ({ has_lote: true, id: 1, nome: 'Lote 03', status_slug: 'aberto',
  minha_reserva_token: token, minha_reserva_milissegundos: 200000,
  minha_reserva_segundos: 200, minha_reserva_expira_em_ms: Date.now() + 200000, server_time_ms: Date.now() });
for (const visitor of [homeA, homeB]) {
  visitor.streams.at(-1).emit('ESTADO_CONSOLIDADO', snapshot('home-token-a'));
  visitor.streams.at(-1).emit('RESERVA_ATUALIZADA', { tipo: 'reserva_criada', lote_id: 1,
    token_reserva: 'home-token-a', device_fingerprint: 'same-fp', device_id: 'same-device',
    segundos_restantes: 200, milissegundos_restantes: 200000 });
}
assert.equal(homeA.api.minhaReservaToken.value, 'home-token-a');
assert.ok(homeA.streams[0].url.includes('token_reserva=home-token-a'));
assert.equal(homeB.api.minhaReservaToken.value, null, 'Nova guia deve exibir Resgatar Ingresso');
assert.equal(homeB.api.minhaReservaExpiraEmMs.value, null, 'Reserva da outra guia não deve ativar o aviso');
assert.equal(homeB.api.statusInfo.value.status_slug, 'aberto');

reservationStorage.saveTabReservationToken(1, 'home-token-b', homeSessionB);
const homeBReserved = home(homeSessionB);
homeBReserved.streams[0].emit('ESTADO_CONSOLIDADO', snapshot('home-token-b'));
const expiryB = homeBReserved.api.minhaReservaExpiraEmMs.value;
homeBReserved.streams[0].emit('RESERVA_ATUALIZADA', { tipo: 'reserva_liberada', lote_id: 1,
  token_reserva: 'home-token-a', device_fingerprint: 'same-fp', device_id: 'same-device' });
assert.equal(homeBReserved.api.minhaReservaToken.value, 'home-token-b');
assert.equal(homeBReserved.api.minhaReservaExpiraEmMs.value, expiryB);
assert.equal(reservationStorage.getTabReservationToken(1, homeSessionB), 'home-token-b');
homeBReserved.streams[0].emit('RESERVA_ATUALIZADA', { tipo: 'reserva_liberada', lote_id: 1, token_reserva: 'home-token-b' });
assert.equal(homeBReserved.api.minhaReservaToken.value, null);
assert.equal(reservationStorage.getTabReservationToken(1, homeSessionB), '');

// Abas existentes, com token por lote mas sem o ponteiro novo, retomam o token correto.
const previousSession = storage();
previousSession.setItem('festa_reserva_token_1', 'previous-token');
const previousHome = home(previousSession);
previousHome.streams[0].emit('ESTADO_CONSOLIDADO', snapshot('home-token-a'));
assert.equal(previousHome.api.minhaReservaToken.value, null);
assert.equal(previousHome.streams.length, 2);
assert.ok(previousHome.streams[1].url.includes('token_reserva=previous-token'));
previousHome.streams[1].emit('ESTADO_CONSOLIDADO', snapshot('previous-token'));
assert.equal(previousHome.api.minhaReservaToken.value, 'previous-token');
console.log('Múltiplas reservas: tokens, prazos SSE, rascunhos, F5, cancelamento e nova reserva independentes OK.');
