import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const Vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { compile } = require('@vue/compiler-dom');
const { renderToString } = require('@vue/server-renderer');
const { descriptor } = parse(fs.readFileSync('frontend/src/views/AdminValidacoesView.vue', 'utf8'));
const source = descriptor.scriptSetup.content.split('\n').filter(line => !line.startsWith('import ')).join('\n');
const bindings = Object.keys(compileScript(descriptor, { id: 'cpf-list-test' }).bindings);
const render = new Function('Vue', compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true }).code)(Vue);
const Modal = { props: ['show'], render() { return this.show ? Vue.h('section', [this.$slots.default?.(), this.$slots.footer?.()]) : null; } };
const KpiCard = { render: () => null };
const DropdownSelect = { render: () => null };
const preview = { sucesso: true, cpfs_validos: 1200, cpfs_com_pendencia: 1200, pendentes_encontrados: 1200, cpfs_sem_pendencia: 0, cpfs_invalidos: 1, cpfs_duplicados: 2,
  servidores_a_homologar: Array.from({ length: 1200 }, (_, i) => ({
    usuario_id: i + 1, nome: `Servidor ${String(i + 1).padStart(4, '0')}`,
    cpf: String(i + 1).padStart(11, '0'), cpf_formatado: `000.000.${String(i + 1).padStart(3, '0')}-00`
  })) };

function component(geral, responder) {
  const requests = [], successes = [];
  const context = vm.createContext({
    ref: Vue.ref, computed: Vue.computed, watch: Vue.watch, onMounted() {}, onUnmounted() {},
    useAuth: () => ({ isAdminGeral: Vue.ref(geral), isAdmin: Vue.ref(true), isValidador: Vue.ref(true) }),
    useRouter: () => ({ push() {} }), useConfirm: () => ({ confirmModal: async () => true }),
    useToast: () => ({ toast: { success: message => successes.push(message), error() {} } }),
    Modal, KpiCard, DropdownSelect, formatarDataNascimento: value => value, formatarData: value => value,
    URLSearchParams, AbortController, setTimeout, clearTimeout, clearInterval,
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (options?.method === 'POST') return responder(JSON.parse(options.body));
      return { ok: true, status: 200, json: async () => ({ sucesso: true, solicitacoes: [], kpis: {},
        pagination: { page: 1, limit: 25, total: 0, total_pages: 1 } }) };
    }
  });
  vm.runInContext(source + `\nglobalThis.api = { ${bindings.join(', ')} };`, context);
  const api = context.api;
  api.loading.value = false;
  return { api, requests, successes, render: () => renderToString(Vue.createSSRApp({
    components: { Modal, KpiCard, DropdownSelect }, setup: () => api, render
  })) };
}
const response = data => ({ ok: true, status: 200, json: async () => data });

const restricted = component(false, () => { throw new Error('Ação indevida'); });
assert.doesNotMatch(await restricted.render(), />Homologar por CPFs</);
restricted.api.showModalListaCpfs.value = true;
assert.doesNotMatch(await restricted.render(), /id="lista-cpfs-validacao"/);
restricted.api.listaCpfsTexto.value = '52998224725';
await restricted.api.processarListaCpfs();
assert.equal(restricted.requests.length, 0);

const view = component(true, body => response(body.confirmar
  ? { sucesso: true, aprovados: 1200, ingressos_emitidos: 1200, mensagem: '1200 homologados. Envio aguarda liberação.' }
  : preview));
assert.match(await view.render(), />Homologar por CPFs</);
view.api.abrirModalListaCpfs();
assert.match(await view.render(), /id="lista-cpfs-validacao"/);
await view.api.processarListaCpfs();
assert.match(view.api.erroListaCpfs.value, /Informe a lista/);
assert.equal(view.requests.length, 0);
view.api.listaCpfsTexto.value = ' 529.982.247-25\n11144477735 ';
await Vue.nextTick();
await view.api.processarListaCpfs(true);
assert.equal(view.requests.length, 0, 'Confirmação exige conferência prévia');
await view.api.processarListaCpfs();
assert.equal(JSON.parse(view.requests[0].options.body).confirmar, false);
assert.equal(view.api.conferenciaCpfs.value.pendentes_encontrados, 1200);
assert.match(await view.render(), /Solicitações a homologar/);
assert.match(await view.render(), /CPFs inválidos serão ignorados/);
assert.match(await view.render(), /CPFs que serão homologados/);
assert.match(await view.render(), /Servidor 0001/);
assert.doesNotMatch(await view.render(), /Servidor 0026/);
view.api.paginaConferenciaCpfs.value = 2;
assert.match(await view.render(), /Servidor 0026/);
view.api.buscaConferenciaCpfs.value = 'Servidor 1200';
await Vue.nextTick();
assert.equal(view.api.paginaConferenciaCpfs.value, 1);
assert.match(await view.render(), /Servidor 1200/);
assert.equal(view.api.servidoresConferenciaCpfs.value.length, 1);
view.api.buscaConferenciaCpfs.value = '00000001200';
await Vue.nextTick();
assert.equal(view.api.servidoresConferenciaCpfs.value[0].usuario_id, 1200);
view.api.buscaConferenciaCpfs.value = 'Inexistente';
await Vue.nextTick();
assert.match(await view.render(), /Nenhum servidor corresponde à busca/);
await view.api.processarListaCpfs(true);
assert.equal(JSON.parse(view.requests[1].options.body).confirmar, true);
assert.equal(JSON.parse(view.requests[1].options.body).lista_cpfs, '529.982.247-25\n11144477735', 'Busca não altera a lista enviada para homologação');
assert.equal(view.api.resultadoListaCpfs.value.aprovados, 1200);
assert.equal(view.successes.length, 1);
assert.ok(view.requests[2].url.startsWith('/api/admin/validacoes?'), 'Atualiza a tela após homologação');
await view.api.processarListaCpfs(true);
assert.equal(view.requests.length, 3, 'Não repete homologação após sucesso');
assert.ok(view.requests.every(({ url }) => !url.includes('comunicar')), 'Homologação não dispara e-mail');

view.api.listaCpfsTexto.value = '52998224725';
await Vue.nextTick();
assert.equal(view.api.conferenciaCpfs.value, null);
assert.equal(view.api.resultadoListaCpfs.value, null);
await view.api.processarListaCpfs();
view.api.listaCpfsTexto.value = '11144477735';
await view.api.processarListaCpfs(true);
assert.equal(view.requests.length, 4, 'Alterar o texto exige nova conferência mesmo antes do watcher rodar');
await Vue.nextTick();

const empty = component(true, () => response({ ...preview, pendentes_encontrados: 0 }));
empty.api.listaCpfsTexto.value = '52998224725';
await Vue.nextTick();
await empty.api.processarListaCpfs();
await empty.api.processarListaCpfs(true);
assert.equal(empty.requests.length, 1, 'Não confirma lista sem pendências correspondentes');

let release;
const simultaneous = component(true, () => new Promise(resolve => { release = resolve; }));
simultaneous.api.listaCpfsTexto.value = '52998224725';
await Vue.nextTick();
const running = simultaneous.api.processarListaCpfs();
await simultaneous.api.processarListaCpfs();
assert.equal(simultaneous.requests.length, 1, 'Bloqueia cliques concorrentes');
release(response(preview));
await running;

const failed = component(true, body => {
  if (body.confirmar) throw new Error('Resposta perdida');
  return response(preview);
});
failed.api.listaCpfsTexto.value = '52998224725';
await Vue.nextTick();
await failed.api.processarListaCpfs();
await failed.api.processarListaCpfs(true);
assert.equal(failed.api.conferenciaCpfs.value, null);
assert.match(failed.api.erroListaCpfs.value, /Confira as solicitações atualizadas/);
assert.ok(failed.requests.at(-1).url.startsWith('/api/admin/validacoes?'));
assert.equal(failed.successes.length, 0);

console.log('Lista de CPFs: acesso exclusivo, conferência, homologação, edição, cliques concorrentes e falhas OK');
