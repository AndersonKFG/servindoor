import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { novaConfiguracaoAvulso } from '../frontend/src/utils/avulsoConfig.js';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const Vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { compile } = require('@vue/compiler-dom');
const { renderToString } = require('@vue/server-renderer');
const withoutImports = source => source.split('\n').filter(line => !line.startsWith('import ')).join('\n');

function component(path, geral) {
  const { descriptor } = parse(fs.readFileSync(path, 'utf8'));
  const bindings = Object.keys(compileScript(descriptor, { id: 'permissions-test' }).bindings);
  const requests = [];
  const mounted = [];
  const auth = {
    isAdmin: Vue.ref(true), isAdminGeral: Vue.ref(geral), isAuthenticated: Vue.ref(true),
    isStaff: Vue.ref(true), isPortaria: Vue.ref(false), isEntregador: Vue.ref(false),
    isValidador: Vue.ref(false), sessaoSubstituida: Vue.ref(false),
    currentUser: Vue.ref({ nome: 'Administrador Teste', roles: [geral ? 'admin_geral' : 'admin'] }),
    checkAuth: async () => {}, clearAuth() {}, hasRole: (...roles) => roles.includes(geral ? 'admin_geral' : 'admin')
  };
  const KpiCard = { props: ['title', 'value'], render() { return Vue.h('div', `${this.title}: ${this.value}`); } };
  const Modal = { props: ['show'], render() { return this.show ? Vue.h('div', this.$slots.default?.()) : null; } };
  const RouterLink = { props: ['to'], render() { return Vue.h('a', { href: this.to }, this.$slots.default?.()); } };
  const context = vm.createContext({
    ref: Vue.ref, computed: Vue.computed, watch() {},
    onMounted: callback => mounted.push(callback), onUnmounted() {},
    useAuth: () => auth, useToast: () => ({ toast: { error() {}, success() {} } }),
    useRouter: () => ({ push() {}, currentRoute: Vue.ref({ path: '/admin' }) }),
    useRoute: () => ({ path: '/admin' }),
    formatarDataHoraSp: value => value, paraDatetimeLocalSp: value => value,
    KpiCard, Modal, FormData, novaConfiguracaoAvulso,
    HiddenLotSettings: { render() { return null; } },
    window: { location: { origin: 'https://test' }, open() { requests.push('download'); } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, status: 200, json: async () => ({ metricas: {}, lotes: [], secretarias: [], backups: [] }) };
    }
  });
  vm.runInContext(withoutImports(descriptor.scriptSetup.content) + `\nglobalThis.api = { ${bindings.join(', ')} };`, context);
  const render = new Function('Vue', compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true }).code)(Vue);
  const options = { components: { KpiCard, Modal, RouterLink, HiddenLotSettings: context.HiddenLotSettings }, setup: () => context.api, render };
  return { api: context.api, requests, mounted, render: () => renderToString(Vue.createSSRApp(options)) };
}

const fixture = {
  model: { id: 1, nome: 'Lote de Teste', quantidade_resgatada: 25, quantidade_total: 100, secretaria: null },
  status: { label: 'Aberto', key: 'aberto', pode_toggle: true }, pct: 25
};
const backup = { id: 1, lote_nome: 'Lote Arquivado', lote_id: 2, total_ingressos: 10, horas_restantes: 72, restaurado: false };

for (const geral of [false, true]) {
  const view = component('frontend/src/views/AdminView.vue', geral);
  view.api.lotes.value = [fixture];
  view.api.backups.value = [backup];
  view.api.metricas.value.total_vagas = 100;
  const html = (await view.render()).replace(/<!--[\s\S]*?-->/g, '');
  assert.match(html, /Lote de Teste/);
  assert.match(html, /Lote Arquivado/);
  assert.match(html, /Vagas Totais: 100/);
  assert.equal(html.includes('<button'), geral, 'Somente Admin Geral vê botões de gestão');
  for (const label of ['Criar Novo Lote', 'Editar Lote', 'Pausar Lote', 'Excluir Lote', 'Importar Backup', 'Salvar Backup']) {
    assert.equal(html.includes(label), geral, `${label}: visibilidade por perfil`);
  }
  if (!geral) {
    for (const name of ['showModalNovo', 'showModalEditar', 'showModalExcluirLote', 'showModalRestaurarBackup', 'showModalImportarBackup']) {
      view.api[name].value = true;
    }
    assert.equal((await view.render()).includes('<button'), false, 'Modais de gestão não abrem para administrador');
    for (const [name, args] of [
      ['handleCriarLote', []], ['abrirEditarLote', [fixture]], ['handleSalvarEdicao', []],
      ['handleToggleLote', [1]], ['iniciarExclusaoLote', [fixture]],
      ['handleSolicitarCodigoExclusao', []], ['handleConfirmarExclusao', []],
      ['abrirModalRestaurar', [backup]], ['handleConfirmarRestauracao', []],
      ['handleExportarBackup', [backup]], ['abrirModalImportar', []], ['handleConfirmarImportacao', []]
    ]) await view.api[name](...args);
    assert.equal(view.requests.length, 0, 'Funções de gerenciamento não disparam requisições para administrador');
    await view.api.carregarDadosAdmin();
    await view.api.carregarBackups();
    assert.deepEqual(view.requests.map(request => request.url), ['/admin', '/api/lotes-admin', '/api/admin/lotes/backups']);
  }

  const navbar = component('frontend/src/components/Navbar.vue', geral);
  navbar.api.mobileMenuOpen.value = true;
  assert.equal((await navbar.render()).match(/href="\/admin"/g)?.length, 2, 'Menu desktop e móvel mostram Lotes para ambos os perfis');
}

const routeSource = fs.readFileSync('frontend/src/router/index.js', 'utf8');
let routeGuard, routeUser;
const routerContext = vm.createContext({
  createRouter: options => ({ ...options, beforeEach(callback) { routeGuard = callback; } }), createWebHistory() {},
  localStorage: { getItem: () => 'autorizado' },
  useToast: () => ({ toast: { warning() {} } }),
  useAuth: () => ({
    checkAuth: async () => routeUser, isAuthenticated: Vue.ref(Boolean(routeUser)),
    hasRole: (...roles) => routeUser?.roles.some(role => roles.includes(role))
  }),
});
for (const match of routeSource.matchAll(/^import (\w+) from /gm)) routerContext[match[1]] = {};
vm.runInContext(withoutImports(routeSource).replace('export default router', 'globalThis.router = router'), routerContext);
const adminRoute = routerContext.router.routes.find(route => route.path === '/admin');
assert.deepEqual([...adminRoute.meta.roles], ['admin_geral', 'admin']);
assert.equal(adminRoute.meta.requiresAuth, true);
for (const roles of [['admin'], ['admin_geral'], ['validador'], null]) {
  routeUser = roles ? { roles } : null;
  let result;
  await routeGuard({ path: '/admin', fullPath: '/admin', meta: adminRoute.meta, matched: [adminRoute] }, {}, value => { result = value; });
  if (roles?.some(role => ['admin', 'admin_geral'].includes(role))) assert.equal(result, undefined);
  else assert.equal(result.path, roles ? '/' : '/login');
}

console.log('Painel de lotes: consulta, menus desktop/móvel, botões, modais e bloqueio de ações por perfil OK');
