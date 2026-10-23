// Frontend compilado + APIs reais + PostgreSQL descartável. Nenhum worker SMTP é iniciado.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const baseURL = process.env.LEGAL_E2E_URL || 'http://127.0.0.1:8137';
assert.equal(new URL(baseURL).port, '8137');
const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge' });
try {
const context = await browser.newContext({ baseURL });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const info = await (await context.request.get('/__test/info')).json();
assert.match(info.schema, /^test_legal_/);
const file = await (await context.request.get('/__test/pdf')).body();
await page.goto('/admin/documentos-legais');
await page.getByRole('heading', { name: 'Documentos Legais', exact: true }).waitFor();
await page.getByRole('heading', { name: 'Cadastrar nova versão como rascunho' }).waitFor();
assert.equal(await page.getByLabel('Exigir aceite nos novos resgates').isChecked(), false);
assert.equal(await page.getByLabel('Disponibilizar confirmação voluntária para participantes anteriores').isChecked(), false);
assert.equal(await page.getByLabel('Habilitar envio de comunicados legais').isChecked(), false);

for (const [kind, name] of [['terms', 'Termos finais'], ['privacy', 'Política final']]) {
  await page.getByLabel('Tipo', { exact: true }).selectOption(kind);
  await page.getByLabel('Título', { exact: true }).fill(name);
  await page.getByLabel('Versão', { exact: true }).fill('1.0');
  await page.getByLabel('Arquivo PDF ou DOCX (até 5 MB)').setInputFiles({ name: 'documento.pdf', mimeType: 'application/pdf', buffer: file });
  await page.getByRole('button', { name: 'Salvar rascunho privado' }).click();
  const row = page.getByRole('row').filter({ hasText: name });
  await row.getByTitle('Visualizar documento').waitFor();
  await row.getByTitle('Visualizar documento').click();
  await page.getByRole('button', { name: 'Fechar revisão' }).click();
  await row.getByTitle('Publicar versão aprovada').click();
  await page.getByRole('button', { name: 'Publicar versão aprovada', exact: true }).click();
  await row.getByText('Publicado', { exact: true }).waitFor();
}
const settings = await (await context.request.get('/api/admin/legal/settings')).json();
assert.equal(settings.require_on_redemption, false);
assert.equal(settings.communications_enabled, false);
await page.getByLabel('Disponibilizar confirmação voluntária para participantes anteriores').check();
await page.getByLabel('Habilitar envio de comunicados legais').check();
await page.getByRole('button', { name: 'Salvar controles', exact: true }).click();
await page.getByRole('button', { name: 'Salvar configurações', exact: true }).click();
await page.getByText('Configurações salvas.', { exact: true }).waitFor();
await page.getByRole('button', { name: 'Pré-visualizar e-mail', exact: true }).click();
await page.getByRole('button', { name: 'Fechar pré-visualização', exact: true }).click();
await page.getByLabel('Para autorizar o disparo, digite AUTORIZAR ENVIO').fill('AUTORIZAR ENVIO');
await page.getByRole('button', { name: 'Autorizar campanha', exact: true }).click();
await page.getByRole('button', { name: 'Autorizar disparo', exact: true }).click();
await page.getByText('Campanha autorizada. Acompanhe o processamento na tabela de comunicações.', { exact: true }).waitFor();
const { token } = await (await context.request.post('/__test/prepare')).json();
assert.equal((await (await context.request.get('/__test/stats')).json()).acceptances, 0);

const anonymous = await browser.newContext({ baseURL });
const confirmation = await anonymous.newPage();
confirmation.on('pageerror', error => errors.push(error.message));
await confirmation.goto(`/confirmar_termos/${token}`);
await confirmation.getByRole('heading', { name: 'Olá, Ana!' }).waitFor();
const submit = confirmation.getByRole('button', { name: 'Confirmar concordância', exact: true });
assert.equal(await submit.isDisabled(), true);
assert.equal((await (await context.request.get('/__test/stats')).json()).acceptances, 0);
await confirmation.getByRole('checkbox').check();
await submit.click();
await confirmation.getByText('Confirmação registrada com sucesso. Seu ingresso permanece válido.', { exact: true }).first().waitFor();
const stats = await (await context.request.get('/__test/stats')).json();
assert.equal(stats.acceptances, 1);
assert.equal(stats.tickets, 1);
assert.equal(stats.sent, 0);

await context.addCookies([{ name: 'legal_e2e_role', value: 'admin', url: baseURL }]);
await page.goto('/admin/documentos-legais');
await page.waitForURL(url => url.pathname !== '/admin/documentos-legais');
assert.equal(await page.getByRole('link', { name: 'Documentos Legais', exact: true }).count(), 0);
assert.equal((await context.request.get('/api/admin/legal/documents')).status(), 403);
assert.deepEqual(errors, []);
console.log('Central legal: rascunhos, publicação, controles, campanha, prévia, confirmação voluntária e bloqueio do administrador comum passaram no browser.');
} finally {
  await browser.close();
}
