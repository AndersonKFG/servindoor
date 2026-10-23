import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const Vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { compile } = require('@vue/compiler-dom');
const { renderToString } = require('@vue/server-renderer');
const { descriptor } = parse(fs.readFileSync('frontend/src/views/PortariaView.vue', 'utf8'));
const bindings = Object.keys(compileScript(descriptor, { id: 'portaria-test' }).bindings);
const render = new Function('Vue', compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true }).code)(Vue);

function view(geral) {
  const requests = [], mounted = [], unmounted = [], intervals = [], cleared = [];
  const listeners = new Map();
  let response = { status: 200, data: { liberada: false } };
  const context = vm.createContext({
    ref: Vue.ref, watch() {}, nextTick: Vue.nextTick,
    onMounted: callback => mounted.push(callback), onUnmounted: callback => unmounted.push(callback),
    useAuth: () => ({ isAdminGeral: Vue.ref(geral) }),
    useToast: () => ({ toast: { success() {} } }),
    useRouter: () => ({ push() {} }),
    Html5Qrcode: { getCameras: async () => [] },
    console: { warn() {}, error() {} },
    setInterval(callback, delay) { intervals.push({ callback, delay }); return 123; },
    clearInterval(id) { cleared.push(id); },
    setTimeout() {},
    document: {
      visibilityState: 'visible',
      addEventListener(event, callback) { listeners.set(event, callback); },
      removeEventListener(event) { listeners.delete(event); },
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const result = typeof response === 'function' ? await response() : response;
      return { ok: result.status < 400, status: result.status, json: async () => result.data };
    },
  });
  const script = descriptor.scriptSetup.content.split('\n').filter(line => !line.startsWith('import ')).join('\n');
  vm.runInContext(script + `\nglobalThis.api = { ${bindings.join(', ')} };`, context);
  return {
    api: context.api, requests, mounted, unmounted, intervals, cleared, listeners,
    respond(value) { response = value; },
    render: () => renderToString(Vue.createSSRApp({ setup: () => context.api, render })),
  };
}

for (const geral of [false, true]) {
  const fixture = view(geral);
  const { api } = fixture;
  api.participante.value = { usuario_id: 2, nome: 'Participante', cpf: '12345678909', status: 'fora' };
  await api.alternarStatus();
  assert.equal(fixture.requests.length, 0, 'Não registra presença antes de consultar a liberação');
  await api.carregarLiberacaoPresenca();
  let html = await fixture.render();
  assert.equal(html.includes('Liberar alterações de presença'), geral, 'Somente administrador geral tem o controle');
  assert.match(html, /Alterações de presença bloqueadas/);
  assert.match(html, /<button[^>]*class="[^"]*\bbtn-toggle-status\b[^"]*"[^>]*\bdisabled\b/);
  await api.alternarStatus();
  assert.equal(fixture.requests.length, 1, 'Não envia movimento quando bloqueada');

  fixture.respond({ status: 200, data: { sucesso: true, liberada: true } });
  await api.alternarLiberacaoPresenca();
  assert.equal(fixture.requests.length, geral ? 2 : 1, 'Função de gestão também verifica o perfil');
  if (geral) {
    assert.equal(fixture.requests[1].options.method, 'PUT');
    assert.deepEqual(JSON.parse(fixture.requests[1].options.body), { liberada: true });
  }

  await api.carregarLiberacaoPresenca();
  html = await fixture.render();
  assert.match(html, /Alterações de presença liberadas/);
  assert.doesNotMatch(html, /<button[^>]*class="[^"]*\bbtn-toggle-status\b[^"]*"[^>]*\bdisabled\b/);
  assert.equal(html.includes('Bloquear alterações de presença'), geral);

  fixture.respond({ status: 403, data: { codigo: 'presenca_bloqueada', mensagem: 'Bloqueado pelo administrador.' } });
  await api.alternarStatus();
  assert.equal(api.presencaLiberada.value, false, 'Atualiza o estado quando outra sessão bloqueia a presença');
  assert.equal(api.mensagemErro.value, 'Bloqueado pelo administrador.');
  assert.equal(api.alterandoStatus.value, false);
}

const fixture = view(true);
fixture.respond({ status: 200, data: { liberada: true } });
await fixture.api.carregarLiberacaoPresenca();
let finish;
fixture.respond(() => new Promise(resolve => { finish = resolve; }));
const saving = fixture.api.alternarLiberacaoPresenca();
await fixture.api.alternarLiberacaoPresenca();
await fixture.api.carregarLiberacaoPresenca();
assert.equal(fixture.requests.length, 2, 'Evita salvamento duplicado e consulta concorrente');
assert.deepEqual(JSON.parse(fixture.requests[1].options.body), { liberada: false });
finish({ status: 200, data: { sucesso: true, liberada: false } });
await saving;
assert.equal(fixture.api.presencaLiberada.value, false);

fixture.respond(() => { throw new Error('Sem conexão'); });
await fixture.api.alternarLiberacaoPresenca();
assert.equal(fixture.api.liberacaoCarregada.value, false, 'Falha ao salvar exige nova consulta');
assert.equal(fixture.api.presencaLiberada.value, false);
assert.match(await fixture.render(), /Tentar novamente/);

fixture.respond({ status: 200, data: { liberada: true } });
await fixture.api.carregarLiberacaoPresenca();
assert.equal(fixture.api.erroLiberacao.value, null);
assert.equal(fixture.api.presencaLiberada.value, true);
fixture.respond(() => { throw new Error('Consulta indisponível'); });
await fixture.api.carregarLiberacaoPresenca();
assert.equal(fixture.api.presencaLiberada.value, false, 'Falha na consulta impede movimentos com estado desatualizado');

fixture.respond({ status: 200, data: { liberada: false } });
fixture.mounted.forEach(callback => callback());
await Vue.nextTick();
assert.equal(fixture.intervals[0].delay, 15000);
assert.ok(fixture.listeners.has('visibilitychange'));
fixture.unmounted.forEach(callback => callback());
assert.deepEqual(fixture.cleared, [123]);
assert.equal(fixture.listeners.size, 0);
console.log('Portaria: permissões, bloqueio, liberação, erros e atualização automática OK');
