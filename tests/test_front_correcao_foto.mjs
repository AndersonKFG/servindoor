import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = file => fs.readFileSync(file, 'utf8').split('<script setup>')[1].split('</script>')[0]
  .split('\n').filter(line => !line.startsWith('import ')).join('\n');
const ref = value => ({ value });
const token = 'a'.repeat(43);
const info = { nome: 'Participante', motivo: 'Foto escura.\nEnvie outra.' };
const reply = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data });

function page({ hash = `#${token}`, fetch = async () => reply(200, info) } = {}) {
  let mount;
  const route = { hash };
  const context = vm.createContext({ ref, useRoute: () => route, fetch,
    computed: callback => ({ get value() { return callback(); } }),
    watch: (source, callback) => { mount = callback; } });
  vm.runInContext(source('frontend/src/views/CorrigirFotoView.vue') +
    '\nglobalThis.api = { carregar, salvar, foto, solicitacao, carregando, salvando, concluido, erro, linkIndisponivel };', context);
  return { ...context.api, mount: () => mount(), navigate: newHash => { route.hash = newHash; return mount(); } };
}

let calls = [];
const valid = page({ fetch: async (...args) => { calls.push(args); return reply(200, args[1]?.method === 'POST' ? { sucesso: true } : info); } });
await valid.mount();
assert.equal(valid.carregando.value, false);
assert.equal(valid.solicitacao.value.motivo, info.motivo);
assert.equal(calls[0][0], `/api/correcao-foto/${token}`);
await valid.salvar();
assert.equal(calls.length, 1, 'Não envia uma foto vazia');
valid.foto.value = 'data:image/jpeg;base64,Zm90bw==';
await valid.salvar();
assert.equal(JSON.parse(calls[1][1].body).foto_base64, 'data:image/jpeg;base64,Zm90bw==');
assert.equal(valid.concluido.value, true);
assert.equal(valid.foto.value, '');
await valid.salvar();
assert.equal(calls.length, 2, 'Conclusão impede reenvio');

const invalid = page({ hash: '', fetch: () => { throw Error('Link inválido não deve consultar a API'); } });
await invalid.mount();
assert.equal(invalid.linkIndisponivel.value, true);
assert.match(invalid.erro.value, /Link de correção inválido/);
for (const status of [404, 410]) {
  const unavailable = page({ fetch: async () => reply(status, { detail: 'Link indisponível.' }) });
  await unavailable.mount();
  assert.equal(unavailable.linkIndisponivel.value, true);
  assert.equal(unavailable.erro.value, 'Link indisponível.');
}

let attempt = 0;
const retry = page({ fetch: async () => {
  attempt++;
  if (attempt === 1) throw Error('offline');
  if (attempt === 2) return reply(200, info);
  return reply(400, { detail: 'Foto inválida.' });
} });
await retry.mount();
assert.equal(retry.linkIndisponivel.value, false);
assert.match(retry.erro.value, /comunicação/);
await retry.carregar();
assert.equal(retry.erro.value, '');
assert.equal(retry.solicitacao.value.nome, info.nome);
retry.foto.value = 'foto';
await retry.salvar();
assert.equal(retry.foto.value, 'foto', 'Erro de foto preserva a seleção para tentar novamente');
assert.equal(retry.erro.value, 'Foto inválida.');
assert.equal(retry.salvando.value, false);

let release;
const pending = page({ fetch: () => new Promise(resolve => { release = resolve; }) });
pending.foto.value = 'foto';
const submitting = pending.salvar();
assert.equal(pending.salvando.value, true);
await pending.salvar();
release(reply(200, { sucesso: true }));
await submitting;
assert.equal(pending.salvando.value, false);
assert.equal(pending.concluido.value, true);

let oldResponse;
const navigating = page({ fetch: async url => {
  if (url.endsWith(token)) return new Promise(resolve => { oldResponse = resolve; });
  return reply(200, { nome: 'Outro participante', motivo: 'Nova solicitação' });
} });
const oldLoad = navigating.mount();
navigating.foto.value = 'foto anterior';
await navigating.navigate(`#${'b'.repeat(43)}`);
oldResponse(reply(200, info));
await oldLoad;
assert.equal(navigating.solicitacao.value.nome, 'Outro participante', 'Resposta do link anterior não substitui a solicitação atual');
assert.equal(navigating.foto.value, '', 'Mudar de link limpa a foto selecionada anteriormente');

function modal(fetch) {
  const emitted = [];
  const props = { show: true, participante: { id: 2, email: 'pessoa@example.invalid' } };
  const context = vm.createContext({ ref, fetch, watch() {}, defineProps: () => props,
    defineEmits: () => event => emitted.push(event) });
  vm.runInContext(source('frontend/src/components/PhotoCorrectionRequestModal.vue') +
    '\nglobalThis.api = { motivo, enviando, resultado, enviar, fechar };', context);
  return { ...context.api, emitted, props };
}

calls = [];
const optional = modal(async (...args) => { calls.push(args); return reply(200, { mensagem: 'Enfileirada.' }); });
await optional.enviar();
assert.deepEqual(JSON.parse(calls[0][1].body), { motivo: '' }, 'Mensagem opcional permite o envio sem motivo');
assert.equal(optional.resultado.value.sucesso, true);
await optional.enviar();
assert.equal(calls.length, 1, 'Evita uma segunda solicitação após o sucesso');
optional.fechar();
assert.deepEqual(optional.emitted, ['close']);

const failed = modal(async () => reply(503, { detail: 'Fila indisponível.' }));
failed.motivo.value = '  Foto desfocada.  ';
await failed.enviar();
assert.equal(failed.resultado.value.sucesso, false);
assert.equal(failed.resultado.value.mensagem, 'Fila indisponível.');
assert.equal(failed.enviando.value, false);

const missingEmail = modal(() => { throw Error('Sem destinatário não deve enviar'); });
missingEmail.props.participante.email = '';
await missingEmail.enviar();
assert.equal(missingEmail.resultado.value, null);

let guard;
const storage = { getItem: () => null, setItem() {} };
const guardContext = vm.createContext({
  router: { beforeEach: callback => { guard = callback; } },
  sessionStorage: storage, localStorage: storage,
  fetch: async () => reply(200, { gatekeeper_enabled: true, autorizado: false })
});
const routerSource = fs.readFileSync('frontend/src/router/index.js', 'utf8')
  .split('// Interceptador Global do Gatekeeper e Proteção de Autenticação / RBAC')[1]
  .split('export default router')[0];
vm.runInContext(routerSource, guardContext);
let destination = 'unset';
await guard({ name: 'corrigir-foto', path: '/corrigir-foto' }, {}, value => { destination = value; });
assert.equal(destination, undefined, 'Link pessoal abre sem solicitar PIN ou login');
await guard({ name: 'admin', path: '/admin', fullPath: '/admin' }, {}, value => { destination = value; });
assert.equal(destination.path, '/acesso', 'As demais rotas continuam protegidas pelo PIN');

console.log('Correção de foto: carregamento, envio, erros, uso único, mensagem opcional e acesso sem PIN OK');
