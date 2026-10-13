import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const loginFile = fs.readFileSync('frontend/src/views/LoginView.vue', 'utf8');
const script = file => file.split('<script setup>')[1].split('</script>')[0]
  .split('\n').filter(line => !line.startsWith('import ')).join('\n');
const response = data => ({ status: 200, ok: true, json: async () => data });
const user = pending => ({ role: 'portaria', roles: ['portaria'], deve_trocar_senha: pending });

function login(initialUser = null) {
  let currentUser = initialUser;
  let responder = async () => response({ sucesso: true, deve_trocar_senha: true });
  let mounted;
  const calls = [], routes = [], notices = [];
  const context = vm.createContext({
    ref: value => ({ value }), onMounted: fn => { mounted = fn; }, onUnmounted() {},
    useRouter: () => ({ push: path => routes.push(path) }), useRoute: () => ({ query: {} }),
    useAuth: () => ({ checkAuth: async () => currentUser }),
    useToast: () => ({ toast: { success: message => notices.push(message) } }),
    FormData, setInterval, clearInterval,
    fetch: async (url, options) => { calls.push({ url, options }); return responder(url, options); },
  });
  vm.runInContext(script(loginFile) + `
    globalThis.api = { handleLogin, handleSalvarSenhaObrigatoria,
      showModalTrocarSenhaObrigatoria, novaSenhaObrigatoria, confirmacaoSenhaObrigatoria,
      erroNovaSenha, salvandoNovaSenha, loading };
  `, context);
  return { api: context.api, calls, routes, notices, mount: () => mounted(),
    setUser: value => { currentUser = value; }, respond: fn => { responder = fn; } };
}

test('senha provisória abre o modal antes de entrar no painel', async () => {
  const state = login();
  await state.api.handleLogin();
  assert.equal(state.api.showModalTrocarSenhaObrigatoria.value, true);
  assert.equal(state.api.loading.value, false);
  assert.equal(state.routes.length, 0);
  // O formulário precisa estar presente na interface, além do estado no script.
  assert.match(loginFile, /:show="showModalTrocarSenhaObrigatoria"/);
  assert.match(loginFile, /@submit.prevent="handleSalvarSenhaObrigatoria"/);
  assert.match(loginFile, /v-model="novaSenhaObrigatoria"/);
  assert.match(loginFile, /v-model="confirmacaoSenhaObrigatoria"/);
  assert.match(loginFile, /:dismissible="false"/);
});

test('recarregar login com pendência reabre o modal sem redirecionar', async () => {
  const state = login(user(true));
  await state.mount();
  assert.equal(state.api.showModalTrocarSenhaObrigatoria.value, true);
  assert.equal(state.routes.length, 0);
});

test('pendência em auth/me também exige troca se login omitir o campo', async () => {
  const state = login(user(true));
  state.respond(async () => response({ sucesso: true }));
  await state.api.handleLogin();
  assert.equal(state.api.showModalTrocarSenhaObrigatoria.value, true);
  assert.equal(state.routes.length, 0);
});

test('senha curta ou confirmação diferente não envia a alteração', async () => {
  const state = login(user(true));
  await state.mount();
  state.api.novaSenhaObrigatoria.value = '123';
  await state.api.handleSalvarSenhaObrigatoria();
  assert.match(state.api.erroNovaSenha.value, /6 caracteres/);
  state.api.novaSenhaObrigatoria.value = 'NovaSenha';
  state.api.confirmacaoSenhaObrigatoria.value = 'OutraSenha';
  await state.api.handleSalvarSenhaObrigatoria();
  assert.match(state.api.erroNovaSenha.value, /não conferem/);
  assert.equal(state.calls.length, 0);
  assert.equal(state.api.showModalTrocarSenhaObrigatoria.value, true);
});

test('falha ao salvar mantém modal e mostra erro', async () => {
  const state = login(user(true));
  await state.mount();
  state.api.novaSenhaObrigatoria.value = state.api.confirmacaoSenhaObrigatoria.value = 'NovaSenha';
  state.respond(async () => ({ ok: false, json: async () => ({ detail: 'Falha de gravação' }) }));
  await state.api.handleSalvarSenhaObrigatoria();
  assert.equal(state.api.erroNovaSenha.value, 'Falha de gravação');
  assert.equal(state.api.showModalTrocarSenhaObrigatoria.value, true);
  assert.equal(state.api.salvandoNovaSenha.value, false);
  assert.equal(state.routes.length, 0);
});

test('nova senha salva atualiza autenticação e libera o painel', async () => {
  const state = login(user(true));
  await state.mount();
  state.api.novaSenhaObrigatoria.value = state.api.confirmacaoSenhaObrigatoria.value = 'NovaSenha';
  state.respond(async () => { state.setUser(user(false)); return response({ sucesso: true }); });
  await state.api.handleSalvarSenhaObrigatoria();
  assert.equal(state.calls[0].url, '/api/auth/alterar-senha-obrigatoria');
  assert.deepEqual(JSON.parse(state.calls[0].options.body), {
    nova_senha: 'NovaSenha', confirmacao_senha: 'NovaSenha',
  });
  assert.equal(state.api.showModalTrocarSenhaObrigatoria.value, false);
  assert.equal(state.api.novaSenhaObrigatoria.value, '');
  assert.deepEqual(state.routes, ['/portaria']);
  assert.equal(state.notices.length, 1);
});

test('login sem pendência continua normalmente', async () => {
  const state = login(user(false));
  state.respond(async () => response({ sucesso: true, deve_trocar_senha: false }));
  await state.api.handleLogin();
  assert.equal(state.api.showModalTrocarSenhaObrigatoria.value, false);
  assert.deepEqual(state.routes, ['/portaria']);
});

function routerGuard(currentUser) {
  const source = fs.readFileSync('frontend/src/router/index.js', 'utf8');
  let guard;
  const views = Object.fromEntries([...source.matchAll(/import (\w+View) from/g)].map(match => [match[1], {}]));
  const context = vm.createContext({ ...views,
    createRouter: () => ({ beforeEach: fn => { guard = fn; } }), createWebHistory() {},
    localStorage: { getItem: () => 'autorizado' },
    useAuth: () => ({ checkAuth: async () => currentUser,
      isAuthenticated: { value: !!currentUser }, hasRole: () => true }),
  });
  vm.runInContext(source.split('\n').filter(line => !line.startsWith('import ') && !line.startsWith('export default')).join('\n'), context);
  return async (path, query = {}) => {
    let decision;
    await guard({ path, fullPath: path, query, matched: [], meta: {} }, {}, value => { decision = value; });
    return decision;
  };
}

test('acesso direto ao painel exige troca e login não redireciona em loop', async () => {
  const guard = routerGuard(user(true));
  const decision = await guard('/portaria');
  assert.equal(decision.path, '/login');
  assert.equal(decision.query.redirect, '/portaria');
  assert.equal(await guard('/login', { redirect: '/portaria' }), undefined);
  assert.equal(await routerGuard(user(false))('/portaria'), undefined);
  assert.equal((await routerGuard(null)('/portaria')).path, '/login');
});

test('modal obrigatório ignora Escape e backdrop; demais modais continuam fechando', () => {
  let closings = 0;
  const props = { show: true, dismissible: false };
  const context = vm.createContext({
    ref: value => ({ value }), defineProps: () => props, defineEmits: () => () => { closings++; },
    watch() {}, onMounted() {}, onUnmounted() {},
    window: { __servindoorOpenModals: 1 },
  });
  vm.runInContext(script(fs.readFileSync('frontend/src/components/Modal.vue', 'utf8')) +
    '\ncurrentZIndex.value = 10000; globalThis.api = { handleBackdropClick, handleKeyDown };', context);
  const element = {};
  const backdrop = { target: element, currentTarget: element };
  const escape = { key: 'Escape', preventDefault() {}, stopPropagation() {} };
  context.api.handleBackdropClick(backdrop);
  context.api.handleKeyDown(escape);
  assert.equal(closings, 0);
  props.dismissible = true;
  context.api.handleBackdropClick(backdrop);
  context.api.handleKeyDown(escape);
  assert.equal(closings, 2);
});
