import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const Vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { compile } = require('@vue/compiler-dom');
const { renderToString } = require('@vue/server-renderer');
const { descriptor } = parse(fs.readFileSync('frontend/src/views/AdminParticipantesView.vue', 'utf8'));
const source = descriptor.scriptSetup.content.split('\n').filter(line => !line.startsWith('import ')).join('\n');
const bindings = Object.keys(compileScript(descriptor, { id: 'export-test' }).bindings);
const render = new Function('Vue', compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true }).code)(Vue);
const Modal = { props: ['show'], render() { return this.show ? Vue.h('section', [this.$slots.default?.(), this.$slots.footer?.()]) : null; } };
const Empty = { render: () => null };

function component(responder) {
  const requests = [], downloads = [], successes = [], revoked = [];
  const context = vm.createContext({
    ref: Vue.ref, computed: Vue.computed, watch: Vue.watch, onMounted() {}, onUnmounted() {},
    useRouter: () => ({}), useAuth: () => ({ isAdminGeral: Vue.ref(true) }),
    useToast: () => ({ toast: { success: message => successes.push(message), error() {}, warning() {} } }),
    Modal, PhotoCorrectionRequestModal: Empty, KpiCard: Empty, DropdownSelect: Empty, QRCode: {},
    formatarCpf: value => value, formatarTelefone: value => value, formatarData: value => value, formatarDataNascimento: value => value,
    URLSearchParams,
    URL: { createObjectURL: () => 'blob:export-test', revokeObjectURL: url => revoked.push(url) },
    document: { createElement() { return { click() { downloads.push({ name: this.download, url: this.href }); }, remove() {} }; }, body: { appendChild() {} } },
    setTimeout: callback => callback(), clearTimeout() {},
    fetch: async url => {
      requests.push(url);
      return url.includes('exportar-planilha') ? responder(url) : {
        ok: true, json: async () => ({ participantes: [], kpis: {}, pagination: { page: 1, total: 0, total_pages: 1 } })
      };
    }
  });
  vm.runInContext(source + `\nglobalThis.api = { ${bindings.join(', ')} };`, context);
  return { api: context.api, requests, downloads, successes, revoked,
    render: () => renderToString(Vue.createSSRApp({ components: { Modal, PhotoCorrectionRequestModal: Empty, KpiCard: Empty, DropdownSelect: Empty }, setup: () => context.api, render })) };
}

const view = component(async () => ({ ok: true, blob: async () => new Blob(['xlsx']) }));
assert.match(await view.render(), /Exportar Planilha/);
view.api.abrirExportacaoPlanilha();
assert.match(await view.render(), /1 arquivo Excel, 1 aba com todos/);
assert.match(await view.render(), /Vários arquivos Excel, 1 aba cada/);
assert.doesNotMatch(await view.render(), /id="exportacao-agrupamento"/);
view.api.modoExportacao.value = 'abas';
assert.match(await view.render(), /id="exportacao-agrupamento"/);
for (const modo of ['unico', 'abas', 'arquivos']) {
  for (const agrupar of ['lote', 'secretaria']) {
    view.api.modoExportacao.value = modo;
    view.api.agrupamentoExportacao.value = agrupar;
    view.api.busca.value = 'Nome filtrado';
    view.api.filtroLote.value = '99';
    view.api.abrirExportacaoPlanilha();
    await view.api.exportarPlanilhaParticipantes();
    assert.equal(view.requests.filter(url => url.includes('exportar-planilha')).at(-1), `/api/admin/participantes/exportar-planilha?modo=${modo}&agrupar=${agrupar}`);
    assert.equal(view.downloads.at(-1).name, modo === 'unico' ? 'participantes.xlsx' : `participantes_por_${agrupar}.${modo === 'arquivos' ? 'zip' : 'xlsx'}`);
    assert.equal(view.api.showModalExportacao.value, false);
    assert.equal(view.api.exportandoPlanilha.value, false);
  }
}
assert.equal(view.successes.length, 6);
assert.equal(view.revoked.length, 6);

const failed = component(async () => ({ ok: false, json: async () => ({ detail: 'Acesso negado' }) }));
failed.api.abrirExportacaoPlanilha();
await failed.api.exportarPlanilhaParticipantes();
assert.equal(failed.downloads.length, 0);
assert.equal(failed.api.erroExportacao.value, 'Acesso negado');
assert.equal(failed.api.showModalExportacao.value, true);
assert.equal(failed.api.exportandoPlanilha.value, false);

let release;
const simultaneous = component(() => new Promise(resolve => { release = resolve; }));
const running = simultaneous.api.exportarPlanilhaParticipantes();
await simultaneous.api.exportarPlanilhaParticipantes();
assert.equal(simultaneous.requests.length, 1);
release({ ok: true, blob: async () => new Blob(['xlsx']) });
await running;
console.log('Exportação de participantes: opções, agrupamentos, downloads, filtros independentes, erros e cliques concorrentes OK');
