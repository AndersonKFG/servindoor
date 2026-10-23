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
    removeItem: key => values.delete(key), key: index => [...values.keys()][index], get length() { return values.size; } };
}

function create(local = storage(), session = storage()) {
  const calls = [];
  const routes = [];
  let responder = async () => { throw new TypeError('network interrupted'); };
  const context = vm.createContext({ ref: value => ({ value }), computed: getter => ({ get value() { return getter(); } }),
    watch: () => {}, onMounted: () => {}, onUnmounted: () => {},
    useRoute: () => ({ params: { loteId: 1 }, query: {} }), useRouter: () => ({ push: route => routes.push(route) }),
    useServerTime: () => ({ calibrarComResposta() {}, getSynchronizedServerTime: () => Date.now() }),
    getDeviceFingerprint: () => 'device-fp', getDeviceId: () => 'device-id',
    getTabReservationToken: id => reservationStorage.getTabReservationToken(id, session),
    saveTabReservationToken: (id, token) => reservationStorage.saveTabReservationToken(id, token, session),
    clearTabReservationToken: id => reservationStorage.clearTabReservationToken(id, session),
    localStorage: local, sessionStorage: session, document: { cookie: '', getElementById: () => null },
    window: { location: { protocol: 'https:' } }, console, FormData, URL, Date, Math, setTimeout, clearTimeout, setInterval, clearInterval,
    fetch: async (url, options) => { calls.push({ url, options }); return responder(url, options); },
  });
  // Este ensaio não monta componentes filhos; simula a consulta legal com controles desativados.
  vm.runInContext(source + '\nlegalConsent.value = { loaded: true, required: false };\nglobalThis.api = { form, tokenReserva, envioPendente, errorMessage, submitting, handleSubmit, carregarDadosResgate, updateCountdown, reservaExpiraEmMs, showModalExpirado, validarCpfNoServidor, showModalDesistidaOutroNavegador, limparEnvioPendente, legalConsent };', context);
  const api = context.api;
  api.form.value = { cpf: '529.982.247-25', nome: 'Original', data_nascimento: '1990-01-01', secretaria_id: '1', setor: 'Teste', vinculo: 'Efetivo', telefone: '81999999999', email: 'test@example.invalid', foto_base64: 'data:image/jpeg;base64,dGVzdA==' };
  api.tokenReserva.value = 'same-token';
  return { api, calls, routes, local, session, respond: fn => { responder = fn; } };
}

const success = () => ({ status: 200, ok: true, redirected: false, json: async () => ({ sucesso: true, redirect_url: '/sucesso/analise?solicitacao_id=1' }) });
const notConfirmed = () => ({ status: 200, ok: true, json: async () => ({ sucesso: false, status: 'nao_confirmado' }) });
const first = create();
await first.api.handleSubmit();
assert.ok(first.api.envioPendente.value);
assert.equal(first.api.submitting.value, false);
assert.equal(first.calls[0].options.body.get('token_reserva'), 'same-token');
first.api.form.value.nome = 'Edited after network failure';
first.respond(url => url.includes('/resgate-confirmado?') ? notConfirmed() : success());
await first.api.handleSubmit();
assert.ok(first.calls[1].url.includes('/resgate-confirmado?'));
assert.equal(first.calls[2].options.body.get('nome'), 'Original');
assert.equal(first.calls[2].options.body.get('token_reserva'), 'same-token');
assert.equal(first.api.envioPendente.value, null);
assert.equal(first.routes.length, 1);

const pending = create();
pending.respond(async () => ({ status: 500, ok: false }));
await pending.api.handleSubmit();
assert.ok(pending.api.envioPendente.value);
pending.api.reservaExpiraEmMs.value = Date.now() - 1000;
pending.api.updateCountdown();
assert.equal(pending.api.showModalExpirado.value, false);
const beforeValidationCalls = pending.calls.length;
await pending.api.validarCpfNoServidor('52998224725');
assert.equal(pending.calls.length, beforeValidationCalls);

const reloaded = create(pending.local, pending.session);
reloaded.respond(async url => {
  if (url.includes('/resgate-confirmado?')) return notConfirmed();
  assert.equal(url, '/api/secretarias');
  return { ok: true, json: async () => [{ id: 1, nome: 'Teste' }] };
});
await reloaded.api.carregarDadosResgate();
assert.equal(reloaded.api.envioPendente.value.token, 'same-token');
assert.equal(reloaded.api.envioPendente.value.payload.nome, 'Original');
assert.equal(reloaded.calls.some(call => call.url.includes('/reservar')), false);
reloaded.respond(url => url.includes('/resgate-confirmado?') ? notConfirmed() : success());
await reloaded.api.handleSubmit();
assert.equal(reloaded.calls[3].options.body.get('token_reserva'), 'same-token');
assert.equal(reloaded.api.envioPendente.value, null);

const validationRace = create();
let finishValidation;
validationRace.respond(async url => {
  if (url.startsWith('/api/resgate/validar-cpf')) return await new Promise(resolve => { finishValidation = resolve; });
  throw new TypeError('network interrupted');
});
const validationPromise = validationRace.api.validarCpfNoServidor('52998224725');
await validationRace.api.handleSubmit();
finishValidation({ json: async () => ({ valido: false, tipo_erro: 'solicitacao_existente', mensagem: 'Já foi realizado um resgate' }) });
await validationPromise;
assert.ok(validationRace.api.envioPendente.value);
assert.equal(validationRace.calls.some(call => call.url.includes('/desistir')), false);
assert.equal(validationRace.api.form.value.cpf, '529.982.247-25');

// Um commit já confirmado é recuperado mesmo sem rascunho/foto no navegador.
const lostDraft = create();
await lostDraft.api.handleSubmit();
lostDraft.session.removeItem('festa_resgate_draft_1');
const reloadWithoutPhoto = create(lostDraft.local, lostDraft.session);
reloadWithoutPhoto.api.form.value = { cpf: '', nome: '', data_nascimento: '', secretaria_id: '', setor: '', vinculo: 'Efetivo', telefone: '', email: '', foto_base64: '' };
reloadWithoutPhoto.respond(success);
await reloadWithoutPhoto.api.carregarDadosResgate();
assert.equal(reloadWithoutPhoto.calls.length, 1);
assert.ok(reloadWithoutPhoto.calls[0].url.includes('/resgate-confirmado?'));
assert.equal(reloadWithoutPhoto.routes.length, 1);
assert.equal(reloadWithoutPhoto.api.envioPendente.value, null);

// No resgate, a ação de enviar registra a concordância e preserva as versões no retry.
const legal = create();
legal.api.legalConsent.value = { loaded: true, required: true, termsId: 11, privacyId: 12 };
assert.equal(legal.calls.length, 0);
await legal.api.handleSubmit();
assert.equal(legal.calls[0].options.body.get('legal_accepted'), 'true');
assert.equal(legal.calls[0].options.body.get('legal_terms_id'), '11');
assert.equal(legal.calls[0].options.body.get('legal_privacy_id'), '12');
legal.api.legalConsent.value = { loaded: true, required: true, termsId: 21, privacyId: 22 };
legal.respond(url => url.includes('/resgate-confirmado?') ? notConfirmed() : success());
await legal.api.handleSubmit();
assert.equal(legal.calls[2].options.body.get('legal_terms_id'), '11');
assert.equal(legal.calls[2].options.body.get('legal_privacy_id'), '12');
assert.equal(first.calls[0].options.body.get('legal_accepted'), null);
const unavailableLegal = create();
unavailableLegal.api.legalConsent.value = { loaded: true, required: true };
await unavailableLegal.api.handleSubmit();
assert.equal(unavailableLegal.calls.length, 0);
assert.match(unavailableLegal.api.errorMessage.value, /consultar os documentos/);

console.log('Front recovery: retries, frozen payload/versions, 500, expiry, CPF guard, F5, photo recovery and legal agreement on form submission passed.');
