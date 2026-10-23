// Banco/API locais reais. Somente senha, início/desistência e envios inválidos;
// não cria participantes. --regenerar do ensaio Python coordena a troca do link.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const arquivo = '.venv/lote-oculto-teste.json';
const dados = JSON.parse(fs.readFileSync(arquivo, 'utf8'));
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
const context = await browser.newContext();
const page = await context.newPage();
const erros = [];
page.on('pageerror', err => erros.push(err.message));
let inicio;
page.on('response', async response => {
  if (new URL(response.url()).pathname === `/api/avulso/${dados.token}/iniciar` && response.ok()) inicio = await response.json();
});
try {
  await page.goto(`${base}/${dados.token}`);
  await page.locator('#senha-acesso-lote').waitFor();
  assert.equal(new URL(page.url()).pathname, `/${dados.token}`);
  await page.locator('#senha-acesso-lote').fill('errada');
  const negado = page.waitForResponse(r => r.url().endsWith('/acesso') && r.status() === 403);
  await page.getByRole('button', { name: 'Liberar acesso', exact: true }).click();
  await negado;
  await page.locator('#senha-acesso-lote').fill(dados.senha);
  await page.getByRole('button', { name: 'Liberar acesso', exact: true }).click();
  await page.locator('#cpf').waitFor();
  await page.waitForFunction(nome => document.querySelector('#secretaria-selector-button')?.innerText.includes(nome)
    && document.querySelector('#setor')?.value === 'TESTE LOCAL - LOTE OCULTO', dados.secretaria_nome);
  assert.equal(await page.locator('#secretaria-selector-button').isDisabled(), true);
  assert.ok((await page.locator('#secretaria-selector-button').innerText()).includes(dados.secretaria_nome));
  assert.equal(await page.locator('#setor').inputValue(), 'TESTE LOCAL - LOTE OCULTO');
  assert.equal(await page.locator('#setor').getAttribute('readonly'), '');
  assert.equal(await page.locator('#vinculo').isDisabled(), true);
  assert.equal(await page.locator('#vinculo').inputValue(), 'Efetivo');
  for (const id of ['cpf', 'nome', 'telefone', 'email']) assert.equal(await page.locator(`#${id}`).getAttribute('required'), '');
  await page.waitForFunction(() => document.body.innerText.includes('04:') || document.body.innerText.includes('05:'));
  await page.screenshot({ path: '.venv/lote-oculto-formulario-local.png', fullPage: true });
  assert.ok(inicio?.token_reserva);
  fs.writeFileSync('.venv/lote-oculto-browser-pronto.json', JSON.stringify({ id: dados.id, pronto: true }));
  console.log('Senha real, ausência do PIN geral, cronômetro e três campos travados OK. Aguardando regeneração do link.');
  let novo;
  for (let tentativa = 0; tentativa < 120; tentativa++) {
    const atual = JSON.parse(fs.readFileSync(arquivo, 'utf8'));
    if (atual.token !== dados.token) { novo = atual; break; }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  assert.ok(novo, 'A regeneração deve ocorrer durante o formulário aberto.');
  await page.getByRole('button', { name: 'Reabrir link e reiniciar', exact: true }).waitFor({ timeout: 12000 });
  assert.equal(await page.locator('#cpf').count(), 0);
  const bloqueios = await page.evaluate(async ({ antigo, novo, senha, reserva, secretaria }) => {
    const old = await fetch(`/api/avulso/${antigo}/resgatar`, { method: 'POST', body: new URLSearchParams({ token_reserva: reserva }) });
    const acesso = await fetch(`/api/avulso/${novo}/acesso`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ senha }) });
    const grant = (await acesso.json()).autorizacao;
    const form = new URLSearchParams({ token_reserva: reserva, cpf: '52998224725', nome: 'TESTE INVALIDADO', data_nascimento: '1990-01-01',
      secretaria_id: String(secretaria), setor: 'TESTE LOCAL - LOTE OCULTO', vinculo: 'Efetivo', telefone: '81999990000',
      email: 'lote-oculto-teste@example.invalid', foto_base64: 'invalida' });
    const stale = await fetch(`/api/avulso/${novo}/resgatar`, { method: 'POST', headers: { 'X-Lote-Acesso': grant }, body: form });
    return { old: old.status, novo: acesso.status, stale: stale.status };
  }, { antigo: dados.token, novo: novo.token, senha: novo.senha, reserva: inicio.token_reserva, secretaria: dados.secretaria_id });
  assert.deepEqual(bloqueios, { old: 404, novo: 200, stale: 403 });
  await page.goto(`${base}/${novo.token}`);
  await page.locator('#senha-acesso-lote').fill(novo.senha);
  const novoInicio = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/iniciar') && r.ok());
  await page.getByRole('button', { name: 'Liberar acesso', exact: true }).click();
  const novaReserva = await (await novoInicio).json();
  assert.notEqual(novaReserva.token_reserva, inicio.token_reserva);
  const abandonada = await page.evaluate(async ({ token, senha, reserva }) => {
    const acesso = await fetch(`/api/avulso/${token}/acesso`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ senha }) });
    const grant = (await acesso.json()).autorizacao;
    return (await fetch(`/api/avulso/${token}/desistir`, { method: 'POST', headers: { 'X-Lote-Acesso': grant }, body: new URLSearchParams({ token_reserva: reserva }) })).status;
  }, { token: novo.token, senha: novo.senha, reserva: novaReserva.token_reserva });
  assert.equal(abandonada, 200);
  assert.deepEqual(erros, []);
  console.log('API real: URL anterior 404, formulário antigo 403 mesmo no link novo; reinício com novo token e desistência OK.');
} finally {
  await browser.close();
}
