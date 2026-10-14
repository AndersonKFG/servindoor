import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/src/views/AdminValidacoesView.vue', 'utf8')
  .split('<script setup>')[1].split('</script>')[0]
  .split('\n').filter(line => !line.startsWith('import ')).join('\n');
const settle = () => new Promise(setImmediate);
const reply = (page = 1, limit = 25, total = 61) => ({ ok: true, status: 200, json: async () => ({
  sucesso: true, solicitacoes: [{ id: page }], kpis: { total_geral: 90 },
  pagination: { page, limit, total, total_pages: Math.max(1, Math.ceil(total / limit)) },
  secretarias_disponiveis: [{ id: 1, nome: 'Secretaria 1' }, { id: 2, nome: 'Secretaria 2' }]
}) });

function component(fetch) {
  let mounted, unmounted, nextTimer = 0;
  const watchers = [];
  const timeouts = new Map();
  const intervals = new Map();
  const errors = [];
  const successes = [];
  const warnings = [];
  const context = vm.createContext({ URLSearchParams, AbortController,
    ref: value => ({ value }), computed: callback => ({ get value() { return callback(); } }),
    watch: (source, callback) => watchers.push({ source, callback }),
    useRouter: () => ({ push() {} }), useToast: () => ({ toast: {
      error: message => errors.push(message), success: message => successes.push(message),
      warning: message => warnings.push(message), info() {}
    } }),
    useConfirm: () => ({ confirmModal: async () => true }), useAuth: () => ({}), fetch,
    onMounted: callback => { mounted = callback; }, onUnmounted: callback => { unmounted = callback; },
    setTimeout: callback => { timeouts.set(++nextTimer, callback); return nextTimer; },
    clearTimeout: id => timeouts.delete(id),
    setInterval: callback => { intervals.set(++nextTimer, callback); return nextTimer; },
    clearInterval: id => intervals.delete(id)
  });
  vm.runInContext(source + '\nglobalThis.api = { carregarValidacoes, paginaAtual, itensPorPagina, totalPaginas, totalRegistrosServer, solicitacoesFiltradas, kpis, secretariasDisponiveis, busca, filtroStatus, filtroSecretaria, infoPaginacao, paginasVisiveis, irParaPagina, loading, dispararComunicacoesLote, dispararComunicacaoIndividual, processandoComunicacaoLote, comunicacoesEnfileiradas };', context);
  return { ...context.api, errors, successes, warnings, intervals, mount: () => mounted(), unmount: () => unmounted(),
    change: async (field, value) => {
      field.value = value;
      for (const watcher of watchers) {
        if (watcher.source === field || Array.isArray(watcher.source) && watcher.source.includes(field)) watcher.callback();
      }
      await settle();
    },
    flushSearch: async () => {
      const callbacks = [...timeouts.values()];
      timeouts.clear();
      for (const callback of callbacks) callback();
      await settle();
    }
  };
}

const requests = [];
const current = component(async (url, options) => {
  const params = new URL(url, 'http://test').searchParams;
  requests.push({ params, options });
  return reply(Number(params.get('page')), Number(params.get('limit')));
});
await current.mount();
assert.equal(requests[0].params.get('page'), '1');
assert.equal(requests[0].params.get('limit'), '25');
assert.equal(requests[0].params.get('status_filtro'), 'pendente_analise');
assert.equal(current.infoPaginacao.value, '1 - 25 de 61');
assert.equal(current.kpis.value.total_geral, 90, 'KPIs continuam contando todos os registros autorizados');
assert.equal(current.secretariasDisponiveis.value.length, 2);
await current.irParaPagina(3);
assert.equal(current.infoPaginacao.value, '51 - 61 de 61');
await current.carregarValidacoes(true);
assert.equal(requests.at(-1).params.get('page'), '3', 'Atualização automática mantém a página atual');
await current.change(current.filtroStatus, 'confirmados_api');
assert.equal(current.paginaAtual.value, 1);
assert.equal(requests.at(-1).params.get('status_filtro'), 'confirmados_api');
await current.irParaPagina(2);
await current.change(current.filtroSecretaria, 2);
assert.equal(current.paginaAtual.value, 1);
assert.equal(requests.at(-1).params.get('secretaria_id'), '2');
await current.change(current.itensPorPagina, 10);
assert.equal(requests.at(-1).params.get('limit'), '10');
await current.irParaPagina(2);
const beforeSearch = requests.length;
await current.change(current.busca, '  VAL-000002  ');
assert.equal(requests.length, beforeSearch, 'Busca aguarda o debounce');
await current.flushSearch();
assert.equal(current.paginaAtual.value, 1);
assert.equal(requests.at(-1).params.get('busca'), 'VAL-000002');
const beforeInvalid = requests.length;
for (const page of ['...', 0, 100, 1]) await current.irParaPagina(page);
assert.equal(requests.length, beforeInvalid, 'Não carrega páginas inválidas ou a página já selecionada');
current.totalRegistrosServer.value = 0;
assert.equal(current.infoPaginacao.value, '0 de 0');
current.unmount();
assert.equal(current.intervals.size, 0);

let resolveOld, resolveNew;
const pendingRequests = [];
const race = component((url, options) => new Promise(resolve => {
  pendingRequests.push(options);
  if (!resolveOld) resolveOld = resolve; else resolveNew = resolve;
}));
const oldLoad = race.carregarValidacoes();
const newLoad = race.carregarValidacoes();
assert.equal(pendingRequests[0].signal.aborted, true);
await race.carregarValidacoes(true);
assert.equal(pendingRequests.length, 2, 'Polling não interrompe a navegação em andamento');
resolveNew(reply(2));
await newLoad;
resolveOld(reply(1));
await oldLoad;
assert.equal(race.paginaAtual.value, 2, 'Resposta antiga não substitui a página mais recente');
assert.equal(race.loading.value, false);
assert.equal(race.errors.length, 0);

let resolveUnmount;
const leaving = component(() => new Promise(resolve => { resolveUnmount = resolve; }));
const mounting = leaving.mount();
leaving.unmount();
resolveUnmount(reply());
await mounting;
assert.equal(leaving.intervals.size, 0, 'Sair durante o carregamento não cria polling órfão');
assert.equal(leaving.solicitacoesFiltradas.value.length, 0);

const clamped = component(async () => reply(2, 25, 30));
clamped.paginaAtual.value = 3;
await clamped.carregarValidacoes();
assert.equal(clamped.paginaAtual.value, 2, 'Aceita a correção de página feita pela API após redução dos registros');
assert.equal(clamped.infoPaginacao.value, '26 - 30 de 30');

console.log('Paginação de validações: navegação, filtros, busca, atualização automática e respostas concorrentes OK');

const batchReply = data => ({ ok: true, status: 200, json: async () => ({ sucesso: true, ...data }) });
const cursors = [];
const batch = component(async (url, options) => {
  if (options?.method !== 'POST') return reply();
  const params = new URL(url, 'http://test').searchParams;
  assert.equal(params.get('limit'), '25');
  const cursor = Number(params.get('after_id'));
  cursors.push(cursor);
  return batchReply({ total_enfileirados: 25, falhas: 0, proximo_id: cursor + 25, tem_mais: cursor + 25 < 1200 });
});
batch.kpis.value.total_comunicacao_pendente = 1200;
await batch.dispararComunicacoesLote();
assert.equal(cursors.length, 48);
assert.equal(cursors.at(-1), 1175);
assert.equal(batch.comunicacoesEnfileiradas.value, 1200);
assert.equal(batch.successes.length, 1, 'Confirma conclusão apenas após percorrer todos os lotes');
assert.match(batch.successes[0], /1200.*fila/);
assert.equal(batch.processandoComunicacaoLote.value, false);

let failedCalls = 0, reloads = 0;
const interrupted = component(async (url, options) => {
  if (options?.method !== 'POST') { reloads++; return reply(); }
  if (++failedCalls === 1) return batchReply({ total_enfileirados: 25, proximo_id: 25, tem_mais: true });
  throw new Error('Conexão interrompida');
});
interrupted.kpis.value.total_comunicacao_pendente = 1200;
await interrupted.dispararComunicacoesLote();
assert.equal(interrupted.comunicacoesEnfileiradas.value, 25);
assert.equal(interrupted.successes.length, 0);
assert.match(interrupted.errors[0], /interrompido.*preservados/);
assert.equal(reloads, 1, 'Consulta pendências mesmo após perder a resposta do servidor');
assert.equal(interrupted.processandoComunicacaoLote.value, false);

const partial = component(async (url, options) => options?.method === 'POST'
  ? batchReply({ total_enfileirados: 23, falhas: 2, falhas_por_motivo: { sem_email: 1, sem_ingresso: 1 }, tem_mais: false })
  : reply());
partial.kpis.value.total_comunicacao_pendente = 25;
await partial.dispararComunicacoesLote();
assert.equal(partial.successes.length, 0);
assert.match(partial.warnings[0], /23.*2 pendência.*1 sem e-mail.*1 sem ingresso/);

let releaseBatch, duplicatePosts = 0;
const duplicate = component(async (url, options) => {
  if (options?.method !== 'POST') return reply();
  duplicatePosts++;
  return new Promise(resolve => { releaseBatch = resolve; });
});
duplicate.kpis.value.total_comunicacao_pendente = 25;
const running = duplicate.dispararComunicacoesLote();
await settle();
await duplicate.dispararComunicacoesLote();
await duplicate.dispararComunicacaoIndividual({ id: 1 });
assert.equal(duplicatePosts, 1, 'Bloqueia novo disparo em lote ou individual durante processamento');
releaseBatch(batchReply({ total_enfileirados: 25, tem_mais: false }));
await running;

let leaveRelease, leavePosts = 0;
const leavingBatch = component(async (url, options) => {
  if (options?.method !== 'POST') return reply();
  leavePosts++;
  return new Promise(resolve => { leaveRelease = resolve; });
});
leavingBatch.kpis.value.total_comunicacao_pendente = 1200;
const leavingRun = leavingBatch.dispararComunicacoesLote();
await settle();
leavingBatch.unmount();
leaveRelease(batchReply({ total_enfileirados: 25, proximo_id: 25, tem_mais: true }));
await leavingRun;
assert.equal(leavePosts, 1, 'Não inicia outro lote depois de sair da tela');
assert.equal(leavingBatch.successes.length, 0);

console.log('Comunicações: 1200 registros, falhas parciais, interrupção, bloqueio de disparos concorrentes e saída da tela OK');
