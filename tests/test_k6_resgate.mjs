import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('tools/carga/carga.js', 'utf8').split('\n')
  .filter(line => !line.startsWith('import ')).join('\n')
  .replace('export default function (data)', 'function scenario(data)')
  .replaceAll('export function ', 'function ').replaceAll('export const ', 'const ');
const metrics = new Map();
class Metric {
  constructor(name) { this.name = name; metrics.set(name, []); }
  add(value) { metrics.get(this.name).push(value); }
}
const execution = { vu: { idInTest: 1 } };
let responder = () => { throw new Error('unexpected HTTP'); };
const calls = [];
const context = vm.createContext({
  __ENV: { TARGET_URL: 'http://127.0.0.1:1', TEST_MODE: 'resgate', MAX_VISITORS: '2000', TEST_LOTE_ID: '1',
    TEST_RUN_ID: 'isolated_mock', LOAD_TEST_SECRET: '0'.repeat(32), TEST_SECRETARIA_ID: '1',
    LOAD_TEST_EMAIL: 'test@example.invalid', LOAD_TEST_EMAIL_CONFIRMED: 'ENVIAR_EMAILS' },
  __ITER: 0, exec: execution, Counter: Metric, Rate: Metric, Trend: Metric,
  encoding: { b64encode: data => Buffer.from(data).toString('base64') },
  open: () => fs.readFileSync('tools/carga/foto_teste.jpg'),
  http: { post: (url, body, params) => { calls.push({ url, body, params }); return responder(url, body, params); } },
  sse: {}, check: (value, checks) => Object.values(checks).every(fn => fn(value)), sleep: () => {}, console: { warn() {}, log() {} },
  Date, Math, Number, String, Object, Array, JSON,
});
vm.runInContext(source + '\nglobalThis.api = { syntheticCPF, completeRedemption, options };', context);
const api = context.api;
assert.equal(api.options.scenarios.visitantes.executor, 'per-vu-iterations');
assert.equal(api.options.scenarios.visitantes.vus, 2000);

function validCPF(value) {
  if (!/^\d{11}$/.test(value) || /^(\d)\1{10}$/.test(value)) return false;
  const digits = value.split('').map(Number);
  for (const length of [9, 10]) {
    const sum = digits.slice(0, length).reduce((total, digit, index) => total + digit * (length + 1 - index), 0);
    const rest = sum % 11;
    if (digits[length] !== (rest < 2 ? 0 : 11 - rest)) return false;
  }
  return true;
}
const cpfs = [];
for (let visitor = 1; visitor <= 2000; visitor++) {
  execution.vu.idInTest = visitor;
  const cpf = api.syntheticCPF();
  assert.ok(validCPF(cpf));
  if (visitor % 10 === 0) assert.equal(cpf, cpfs[visitor - 2]);
  cpfs.push(cpf);
}
assert.equal(new Set(cpfs).size, 1800);
execution.vu.idInTest = 1;
const headers = { 'X-Load-Test-Key': '0'.repeat(32) };
const protocol = { sucesso: true, solicitacao_id: 1, token: 'same-protocol', redirect_url: '/sucesso/analise' };
const response = (status, body) => ({ status, json: () => body, timings: { duration: 10 }, headers: {} });

responder = () => response(200, protocol);
api.completeRedemption('same-reservation', headers);
assert.equal(calls.length, 2);
assert.equal(calls[0].body, calls[1].body);
assert.equal(calls[0].params.headers['X-Load-Test-Form'], '1');
assert.ok(calls[0].body.includes('data:image/jpeg;base64,'));
assert.equal(metrics.get('resgate_idempotencia_ok').at(-1), true);

calls.length = 0;
responder = url => url.endsWith('/desistir') ? response(200, { sucesso: true }) : response(409, { codigo: 'cpf_ja_atendido' });
api.completeRedemption('duplicate-reservation', headers);
assert.equal(calls.length, 2);
assert.ok(calls[1].url.endsWith('/desistir'));
assert.equal(metrics.get('resgate_falhas_tecnicas').at(-1), false);

calls.length = 0;
responder = () => calls.length === 1 ? response(503, null) : response(200, protocol);
api.completeRedemption('recover-reservation', headers);
assert.equal(calls.length, 3);
assert.ok(calls.every(call => call.body === calls[0].body));
assert.equal(metrics.get('resgate_falhas_tecnicas').at(-1), true);
assert.equal(metrics.get('resgate_recuperacao_ok').at(-1), true);
assert.equal(calls.some(call => call.url.endsWith('/desistir')), false);

calls.length = 0;
responder = () => response(503, null);
api.completeRedemption('uncertain-reservation', headers);
assert.equal(calls.length, 2);
assert.equal(calls.some(call => call.url.endsWith('/desistir')), false);
console.log('Full resgate mocks: 2000 valid CPFs / 1800 unique, 10% duplicate pairs, same-body idempotency, expected duplicate release, recovery and uncertain-result protection passed.');
