// Exercita o Proxy reativo real do Vue e isola toda gravação via API interceptada.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
const page = await browser.newPage();
const erros = [];
page.on('pageerror', error => erros.push(error.message));
const config = { temporizado: false, exige_validacao: true, campos: {
  secretaria_id: { modo: 'fixo', valor: '1' }, setor: { modo: 'preenchido', valor: 'Gabinete' },
  vinculo: { modo: 'fixo', valor: 'Efetivo' }
} };
const lotes = [true, false].map((oculto, index) => ({ model: {
  id: 10003 + index, nome: oculto ? 'Oculto para edição' : 'Público para edição',
  oculto, ativo: true, quantidade_total: 2, quantidade_resgatada: 0, secretaria_id: null,
  data_abertura: '2026-10-23T00:00:00-03:00', data_abertura_input: '2026-10-23T00:00',
  data_fechamento: null, data_fechamento_input: '', avulso_config: oculto ? config : null,
  tem_senha: oculto
}, status: { key: 'aberto', label: 'Aberto', badge_class: '', icon: '', pode_toggle: true }, pct: 0 }));
const json = (route, value) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) });
let salvo;
await page.addInitScript(() => localStorage.setItem('servindoor_gate_token', 'autorizado'));
await page.route('**/api/**', route => {
  const path = new URL(route.request().url()).pathname;
  if (path === '/api/auth/me') return json(route, { autenticado: true, usuario: {
    id: 46, nome: 'Superadministrador teste', role: 'admin_geral', roles: ['admin_geral'], deve_trocar_senha: false
  } });
  if (path === '/api/lotes-admin') return json(route, { metricas: {}, lotes, secretarias: [{ id: 1, nome: 'Secretaria teste' }] });
  if (path === '/api/admin/lotes/backups') return json(route, { backups: [] });
  return json(route, {});
});
await page.route('**/admin', route => route.request().resourceType() === 'document' ? route.continue() : json(route, {}));
await page.route('**/admin/lote/*/editar', route => {
  salvo = route.request().postData();
  return json(route, { sucesso: true });
});
const campo = nome => salvo.match(new RegExp(`name="${nome}"\\r\\n\\r\\n([^]*?)\\r\\n--`))?.[1];
try {
  await page.goto((process.env.TEST_BASE_URL || 'http://127.0.0.1:5173') + '/admin');
  const editarOculto = page.locator('tr').filter({ hasText: 'Oculto para edição' }).getByTitle('Editar Lote', { exact: true });
  await editarOculto.click();
  await page.locator('#edit-nome').waitFor({ timeout: 5000 });
  assert.equal(await page.locator('#edit-abertura').inputValue(), '2026-10-23T00:00');
  await page.getByRole('button', { name: 'Configurações adicionais', exact: true }).click();
  assert.equal(await page.getByLabel('Reservar vaga por cinco minutos').isChecked(), false);
  assert.equal(await page.getByLabel('Exigir análise do superadministrador').isChecked(), true);
  assert.equal(await page.locator('#avulso-modo-secretaria_id').inputValue(), 'fixo');
  assert.equal(await page.locator('#avulso-valor-secretaria_id').inputValue(), '1');
  assert.equal(await page.locator('#avulso-valor-setor').inputValue(), 'Gabinete');
  assert.equal(await page.locator('#avulso-valor-vinculo').inputValue(), 'Efetivo');
  await page.locator('#avulso-valor-setor').fill('Rascunho descartado');
  await page.getByRole('button', { name: 'Concluir configurações', exact: true }).click();
  await page.getByRole('button', { name: 'Cancelar', exact: true }).click();
  await editarOculto.click();
  await page.getByRole('button', { name: 'Configurações adicionais', exact: true }).click();
  assert.equal(await page.locator('#avulso-valor-setor').inputValue(), 'Gabinete', 'Cancelar não deve alterar a configuração original.');
  await page.locator('#avulso-valor-setor').fill('Gabinete editado');
  await page.getByRole('button', { name: 'Concluir configurações', exact: true }).click();
  await page.getByRole('button', { name: 'Salvar Alterações', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('#edit-nome'));
  assert.equal(campo('data_abertura'), '2026-10-23T00:00');
  const enviado = JSON.parse(campo('avulso_config'));
  assert.equal(enviado.campos.setor.valor, 'Gabinete editado');
  assert.deepEqual(enviado.campos.secretaria_id, config.campos.secretaria_id);
  assert.deepEqual(enviado.campos.vinculo, config.campos.vinculo);
  assert.equal(enviado.temporizado, false);
  assert.equal(enviado.exige_validacao, true);
  assert.equal(campo('acesso_senha'), undefined, 'Senha em branco deve preservar a atual.');
  assert.equal(campo('oculto'), undefined, 'A edição mantém a visibilidade imutável.');
  await page.locator('tr').filter({ hasText: 'Público para edição' }).getByTitle('Editar Lote', { exact: true }).click();
  await page.locator('#edit-nome').waitFor();
  assert.equal(await page.locator('#edit-nome').inputValue(), 'Público para edição');
  assert.equal(await page.getByRole('button', { name: 'Configurações adicionais', exact: true }).count(), 0);
  assert.deepEqual(erros, []);
  console.log('Edição no Vue real: lotes oculto/público, configuração carregada, cancelamento isolado e envio preservando senha/visibilidade OK.');
} finally {
  await browser.close();
}
