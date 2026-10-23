// Executa a interface real no Vite; intercepta toda API para impedir gravações.
// PLAYWRIGHT_MODULE permite usar o runtime de browser disponibilizado pelo ambiente.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
const page = await browser.newPage();
let mode = 'atual';
const requests = [];
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(() => localStorage.setItem('servindoor_gate_token', 'autorizado'));
const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
await page.route('**/api/**', async route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (path === '/api/auth/me') return json(route, { autenticado: true, usuario: { id: 46, nome: 'Superadministrador teste', role: 'admin_geral', roles: ['admin_geral'], deve_trocar_senha: false } });
  if (path === '/api/lotes-admin') return json(route, { metricas: {}, lotes: [], secretarias: [{ id: 1, nome: 'Secretaria teste' }] });
  if (path === '/api/admin/lotes/backups') return json(route, { backups: [] });
  if (path === '/api/portaria/liberacao-presenca') return json(route, { liberada: true });
  if (path === '/api/admin/lotes' && request.method() === 'POST') {
    const body = request.postData() || '';
    requests.push({ path, body });
    if (mode === 'antigo') return json(route, { detail: 'Not Found' }, 404);
    return json(route, { sucesso: true, id: 12345, oculto: mode !== 'inconsistente' }, 201);
  }
  return json(route, {});
});
await page.route('**/admin', route => {
  if (route.request().resourceType() !== 'document') return json(route, {});
  return route.continue();
});
await page.route('**/admin/lote', route => {
  requests.push({ path: '/admin/lote', body: route.request().postData() });
  return json(route, { detail: 'A rota legada não deve ser usada pela interface.' }, 500);
});

try {
  await page.goto((process.env.TEST_BASE_URL || 'http://127.0.0.1:5173') + '/admin');
  await page.getByRole('button', { name: /Criar Novo Lote/ }).click();
  await page.getByLabel('Lote oculto para cadastros avulsos').check();
  await page.locator('#novo-nome').fill('Lote oculto teste de navegador');
  await page.locator('#novo-qtd').fill('8');
  await page.locator('#novo-abertura').fill('2026-10-22T19:30');
  await page.getByRole('button', { name: 'Configurações adicionais', exact: true }).click();
  await page.getByLabel('Reservar vaga por cinco minutos').uncheck();
  await page.getByLabel('Exigir análise do superadministrador').uncheck();
  await page.locator('#avulso-modo-secretaria_id').selectOption('fixo');
  await page.locator('#avulso-valor-secretaria_id').selectOption('1');
  await page.locator('#avulso-modo-setor').selectOption('preenchido');
  await page.locator('#avulso-valor-setor').fill('Setor teste');
  await page.locator('#avulso-modo-vinculo').selectOption('fixo');
  await page.locator('#avulso-valor-vinculo').selectOption('Efetivo');
  await page.locator('#avulso-senha').fill('Ab#123');
  if (process.env.TEST_SCREENSHOT_PATH) await page.screenshot({ path: process.env.TEST_SCREENSHOT_PATH, fullPage: true });
  await page.getByRole('button', { name: 'Concluir configurações', exact: true }).click();
  await page.getByRole('button', { name: 'Criar Lote', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('#novo-nome'));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].path, '/api/admin/lotes');
  const value = name => requests[0].body.match(new RegExp(`name="${name}"\\r\\n\\r\\n([^]*?)\\r\\n--`))?.[1];
  assert.equal(value('oculto'), 'true');
  assert.equal(value('data_abertura'), '2026-10-22T19:30');
  assert.equal(value('acesso_senha'), 'Ab#123');
  const config = JSON.parse(value('avulso_config'));
  assert.equal(config.temporizado, false);
  assert.equal(config.exige_validacao, false);
  assert.deepEqual(config.campos.secretaria_id, { modo: 'fixo', valor: '1' });
  assert.deepEqual(config.campos.setor, { modo: 'preenchido', valor: 'Setor teste' });
  assert.deepEqual(config.campos.vinculo, { modo: 'fixo', valor: 'Efetivo' });

  // Backend antigo não recebe uma criação legada com as opções ignoradas.
  mode = 'antigo';
  await page.getByRole('button', { name: /Criar Novo Lote/ }).click();
  await page.getByLabel('Lote oculto para cadastros avulsos').check();
  await page.locator('#novo-nome').fill('Tentativa sem backend atualizado');
  await page.locator('#novo-abertura').fill('2026-10-22T19:30');
  await page.getByRole('button', { name: 'Criar Lote', exact: true }).click();
  await page.getByText('O serviço de criação de lotes precisa ser atualizado.', { exact: false }).waitFor();
  assert.equal(await page.locator('#novo-nome').inputValue(), 'Tentativa sem backend atualizado');
  assert.equal(await page.getByLabel('Lote oculto para cadastros avulsos').isChecked(), true);
  assert.ok(requests.every(request => request.path === '/api/admin/lotes'));

  mode = 'inconsistente';
  await page.getByRole('button', { name: 'Criar Lote', exact: true }).click();
  await page.getByText('O servidor não confirmou as opções do lote.', { exact: false }).waitFor();
  assert.equal(await page.getByLabel('Lote oculto para cadastros avulsos').isChecked(), true);
  assert.deepEqual(errors, []);
  console.log('Browser: modal adicional, envio de todas as opções e bloqueio de backend antigo/inconsistente OK; nenhuma gravação real.');
} catch (error) {
  console.error('URL:', page.url());
  console.error('TELA:', (await page.locator('body').innerText()).slice(0, 1600));
  console.error('ERROS DE PAGINA:', errors);
  if (process.env.TEST_SCREENSHOT_PATH) await page.screenshot({ path: process.env.TEST_SCREENSHOT_PATH, fullPage: true });
  throw error;
} finally {
  await browser.close();
}
