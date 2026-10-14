import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/src/views/AdminParticipantesView.vue', 'utf8')
  .split('<script setup>')[1].split('</script>')[0]
  .split('\n').filter(line => !line.startsWith('import ')).join('\n');

function component(fetch) {
  const warnings = [], errors = [];
  const context = vm.createContext({
    ref: value => ({ value }), computed: callback => ({ get value() { return callback(); } }),
    watch() {}, onMounted() {}, onUnmounted() {},
    useRouter: () => ({}), useAuth: () => ({ isAdminGeral: { value: false } }),
    useToast: () => ({ toast: { success() {}, warning: message => warnings.push(message), error: message => errors.push(message) } }),
    fetch,
  });
  vm.runInContext(source + '\nglobalThis.api = { abrirModalEditar, salvarEdicaoParticipante, formEditar, participantes, participanteInfo, showModalEditar, salvandoEditar };', context);
  return { ...context.api, warnings, errors };
}

const participante = { id: 1, nome: 'Nome original', vinculo: 'Efetivo', cpf: '52998224725' };
let payload;
const page = component(async (url, options) => {
  assert.equal(url, '/api/admin/participantes/1');
  assert.equal(options.method, 'PUT');
  payload = JSON.parse(options.body);
  return { ok: true, json: async () => ({ participante: { nome: 'Maria da Conceição', vinculo: 'Comissionado' } }) };
});
page.participantes.value = [{ ...participante }];
page.participanteInfo.value = { ...participante };
page.abrirModalEditar(participante);
assert.equal(page.formEditar.value.nome, 'Nome original');
assert.equal(page.formEditar.value.vinculo, 'Efetivo');
page.formEditar.value.nome = '  Maria da Conceição  ';
page.formEditar.value.vinculo = 'Comissionado';
await page.salvarEdicaoParticipante();
assert.equal(payload.nome, 'Maria da Conceição');
assert.equal(payload.vinculo, 'Comissionado');
for (const updated of [page.participantes.value[0], page.participanteInfo.value]) {
  assert.equal(updated.nome, 'Maria da Conceição');
  assert.equal(updated.vinculo, 'Comissionado');
  assert.equal(updated.cpf, participante.cpf);
}
assert.equal(page.showModalEditar.value, false, 'Fecha o modal após salvar');
assert.equal(page.salvandoEditar.value, false);

const invalid = component(() => { throw Error('Nome vazio não deve chamar a API'); });
invalid.abrirModalEditar(participante);
invalid.formEditar.value.nome = '   ';
await invalid.salvarEdicaoParticipante();
assert.equal(invalid.warnings.length, 1);
assert.equal(invalid.errors.length, 0);
assert.equal(invalid.showModalEditar.value, true);

const failed = component(async () => ({ ok: false, json: async () => ({ detail: 'Edição negada.' }) }));
failed.participantes.value = [{ ...participante }];
failed.abrirModalEditar(participante);
failed.formEditar.value.nome = 'Novo nome';
await failed.salvarEdicaoParticipante();
assert.equal(failed.participantes.value[0].nome, 'Nome original');
assert.equal(failed.formEditar.value.nome, 'Novo nome', 'Preserva a edição para tentar novamente');
assert.equal(failed.errors[0], 'Edição negada.');
assert.equal(failed.showModalEditar.value, true);

const legacy = component(async (_url, options) => {
  assert.equal(JSON.parse(options.body).vinculo, null);
  return { ok: true, json: async () => ({ participante: { vinculo: null } }) };
});
legacy.participantes.value = [{ ...participante }];
legacy.abrirModalEditar({ ...participante, vinculo: 'Vínculo legado' });
assert.equal(legacy.formEditar.value.vinculo, 'Vínculo legado');
legacy.formEditar.value.vinculo = '';
await legacy.salvarEdicaoParticipante();
assert.equal(legacy.participantes.value[0].vinculo, null);

console.log('Edição de participantes: nome, vínculo, validação, atualização da tela e erros OK');
