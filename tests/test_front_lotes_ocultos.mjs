import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { novaConfiguracaoAvulso } from '../frontend/src/utils/avulsoConfig.js';

const source = fs.readFileSync('frontend/src/views/ResgateView.vue', 'utf8')
  .split('<script setup>')[1].split('</script>')[0].split('\n')
  .filter(line => !line.startsWith('import ')).join('\n');

const requests = [];
let config = novaConfiguracaoAvulso();
config.temporizado = false;
config.campos.setor = { modo: 'fixo', valor: 'Gabinete' };
let authorized = false;
let invalidated = false;
let reloads = 0;
let interval;
const sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
const response = (status, data) => ({ status, ok: status < 400, json: async () => data, text: async () => JSON.stringify(data) });
const context = vm.createContext({
  ref: value => ({ value }), computed: getter => ({ get value() { return getter(); } }),
  watch() {}, onMounted() {}, onUnmounted() {},
  useRoute: () => ({ params: { hiddenToken: 'x'.repeat(43) }, query: {} }),
  useRouter: () => ({ push() { throw new Error('Cadastro avulso deve permanecer no link do lote.'); } }),
  useServerTime: () => ({ calibrarComResposta() {}, getSynchronizedServerTime: () => Date.now() }),
  getDeviceFingerprint: () => 'fp', getDeviceId: () => 'device',
  getTabReservationToken: () => '', saveTabReservationToken() {}, clearTabReservationToken() {},
  sessionStorage, localStorage: sessionStorage, console, FormData, Headers, URL, Date,
  document: { cookie: '', getElementById() {} },
  window: { location: { origin: 'https://test', protocol: 'https:', reload() { reloads++; } } },
  setInterval: callback => { interval = callback; return 1; }, clearInterval() {}, setTimeout, clearTimeout,
  fetch: async (url, options = {}) => {
    requests.push({ url, options });
    if (url.endsWith('/acesso')) {
      if (JSON.parse(options.body).senha !== 'Ab#123') return response(403, { senha_necessaria: true, detail: 'Informe a senha.' });
      authorized = true;
      return response(200, { id: 1, nome: 'Oculto', config, autorizacao: 'grant' });
    }
    assert.ok(authorized);
    assert.equal(options.headers.get('X-Lote-Acesso'), 'grant');
    if (invalidated) return response(403, { detail: 'Invalidado' });
    if (url.includes('/iniciar')) return response(200, { id: 1, config, nome: 'Oculto', token_reserva: 'submission' });
    if (url.endsWith('/secretarias')) return response(200, [{ id: 1, nome: 'Secretaria' }]);
    if (url.endsWith('/resgatar')) return response(200, { sucesso: true, status: 'aprovado', solicitacao_id: 1, mensagem: 'Enviado', redirect_url: '/sucesso/analise' });
    return response(200, { config });
  }
});
vm.runInContext(source + '\nglobalThis.api = { carregarDadosResgate, senhaAvulso, senhaNecessaria, configAvulso, temporizado, form, campoTravado, tokenReserva, handleSubmit, confirmacaoAvulso, acessoInvalidado, requisicaoResgate, reiniciarAvulso };', context);
const api = context.api;

await api.carregarDadosResgate();
assert.equal(api.senhaNecessaria.value, true);
assert.equal(requests.length, 1);
api.senhaAvulso.value = 'Ab#123';
await api.carregarDadosResgate();
assert.equal(api.temporizado.value, false);
assert.equal(api.form.value.setor, 'Gabinete');
assert.equal(api.campoTravado('setor'), true);
assert.equal(api.campoTravado('nome'), false);
assert.equal(api.tokenReserva.value, 'submission');
assert.ok(requests.every(r => r.url.startsWith('/api/avulso/')));

api.form.value = { cpf: '52998224725', nome: 'Pessoa', data_nascimento: '1990-01-01', setor: 'Gabinete',
  secretaria_id: '1', vinculo: 'Efetivo', telefone: '81999990000', email: 'teste@example.invalid', foto_base64: 'foto' };
await api.handleSubmit();
assert.equal(api.confirmacaoAvulso.value.status, 'aprovado');
const submission = requests.find(r => r.url.endsWith('/resgatar'));
assert.equal(submission.options.body.get('setor'), 'Gabinete');
assert.equal(submission.options.body.get('token_reserva'), 'submission');

invalidated = true;
await api.requisicaoResgate('/status');
assert.equal(api.acessoInvalidado.value, true);
api.reiniciarAvulso();
assert.equal(reloads, 1);
console.log('Lotes ocultos: senha, API independente do PIN, campos travados, envio, confirmação e reinício OK.');
