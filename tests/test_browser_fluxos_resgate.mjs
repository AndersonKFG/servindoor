// Frontend compilado + backend HTTP + PostgreSQL reais no servidor descartável.
// Iniciar flow_e2e_server.py explicitamente; nenhuma API é interceptada aqui.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium, request } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.FLOW_E2E_URL || 'http://127.0.0.1:8127';
assert.equal(new URL(base).port, '8127', 'Usar somente o servidor de ensaio.');
const probe = await request.newContext({ baseURL: base });
const infoResponse = await probe.get('/__test/info');
assert.equal(infoResponse.status(), 200);
const info = await infoResponse.json();
assert.match(info.schema, /^test_browser_flow_/);
const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge',
  args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
const context = await browser.newContext({ permissions: ['camera'] });
const page = await context.newPage();
const errors = [], failures = [];
const grants = new Map(), reservations = new Map();
page.on('pageerror', error => errors.push(error.message));
page.on('response', async response => {
  if (response.status() >= 500) failures.push({ path: new URL(response.url()).pathname, status: response.status() });
  const path = new URL(response.url()).pathname;
  if (path.startsWith('/api/avulso/') && response.ok()) {
    if (path.endsWith('/acesso')) grants.set(path.split('/')[3], (await response.json()).autorizacao);
    if (path.endsWith('/iniciar')) reservations.set(path.split('/')[3], (await response.json()).token_reserva);
  }
});

async function senha() {
  await page.getByLabel('Senha de acesso do lote', { exact: true }).fill(info.senha);
  await page.getByRole('button', { name: 'Liberar acesso', exact: true }).click();
  await page.locator('#cpf').waitFor();
  await page.waitForFunction(() => document.querySelector('#setor')?.value === 'Laboratorio local');
}

async function preencher(cpf, nome, publico = false) {
  await page.locator('#cpf').fill(cpf);
  await page.locator('#cpf.is-valid').waitFor();
  await page.locator('#nasc-ano').selectOption('1990');
  await page.locator('#nasc-mes').selectOption('01');
  await page.locator('#nasc-dia').selectOption('01');
  await page.locator('#nome').fill(nome);
  if (publico) {
    await page.locator('#secretaria-selector-button').click();
    await page.locator('.secretaria-result-option').filter({ hasText: 'Secretaria do ensaio' }).click();
    await page.locator('#setor').fill('Resgate publico');
    await page.locator('#vinculo').selectOption('Comissionado');
  } else {
    assert.equal(await page.locator('#secretaria-selector-button').isDisabled(), true);
    assert.equal(await page.locator('#setor').getAttribute('readonly'), '');
    assert.equal(await page.locator('#vinculo').isDisabled(), true);
  }
  await page.locator('#telefone').fill('81999990000');
  await page.locator('#email').fill(`${cpf}@example.invalid`);
  if (publico) {
    await page.getByRole('button', { name: /Usar câmera/ }).click();
    const tirar = page.getByRole('button', { name: /Tirar Foto ao Vivo/ });
    await tirar.waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.includes('Tirar Foto ao Vivo') && !b.disabled));
    await tirar.click();
  } else {
    const foto = await page.evaluate(() => {
      const c = document.createElement('canvas'); c.width = 128; c.height = 128;
      const ctx = c.getContext('2d'); ctx.fillStyle = 'gray'; ctx.fillRect(0, 0, 128, 128);
      return c.toDataURL('image/jpeg').split(',')[1];
    });
    await page.getByLabel('Selecionar foto de identificação', { exact: true }).setInputFiles({
      name: 'foto-ensaio.jpg', mimeType: 'image/jpeg', buffer: Buffer.from(foto, 'base64')
    });
  }
  await page.getByAltText('Prévia da foto de identificação').waitFor();
}

async function enviar(publico = false, status = 'pendente_analise') {
  const resposta = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/resgatar') && r.request().method() === 'POST');
  await page.getByRole('button', { name: /Concluir e Garantir Ingresso/ }).click();
  const r = await resposta;
  assert.equal(r.status(), 200, await r.text());
  const dados = await r.json();
  assert.equal(dados.status, status);
  if (publico) {
    await page.waitForURL('**/sucesso/analise?**');
    await page.getByText('Cadastro em Análise', { exact: false }).waitFor();
  } else {
    await page.getByRole('heading', { name: status === 'aprovado' ? 'Ingresso aprovado' : 'Cadastro recebido', exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, `/${status === 'aprovado' ? info.tokens['302'] : info.tokens['301']}`);
  }
  return dados;
}

try {
  assert.equal((await probe.post('/api/lote/201/reservar')).status(), 403);
  await page.goto(`${base}/${info.tokens['301']}`);
  await page.locator('#senha-acesso-lote').fill('errada');
  await page.getByRole('button', { name: 'Liberar acesso', exact: true }).click();
  await page.locator('.access-gate__error').waitFor();
  assert.equal(await page.locator('#cpf').count(), 0);
  await senha();
  assert.equal(await page.locator('.sticky-timer-bar').count(), 0);
  await preencher('52998224725', 'Ensaio oculto manual A');
  await enviar();
  await page.getByRole('button', { name: /Cadastrar outro participante/ }).click();
  await page.locator('#cpf').waitFor();
  assert.equal(await page.locator('#nome').inputValue(), '');
  await page.locator('#cpf').fill('52998224725');
  await page.locator('#cpf.is-invalid').waitFor();
  await page.getByRole('button', { name: /Cadastrar outro participante/ }).click();
  await page.locator('#cpf').waitFor();
  await preencher('11144477735', 'Ensaio oculto manual B');
  await enviar();
  console.log('Oculto manual: senha incorreta/correta, formulário completo, foto, campos travados, envio, novo participante e CPF duplicado OK.');

  assert.equal((await context.request.post(`${base}/api/lote/201/reservar`)).status(), 403);
  await page.goto(`${base}/resgate/201`);
  await page.waitForURL('**/acesso?**');
  const globalInputs = page.locator('.pin-digit');
  await globalInputs.first().waitFor();
  for (let i = 0; i < 6; i++) await globalInputs.nth(i).fill(info.gate_pin[i]);
  await page.waitForURL('**/resgate/201');
  await page.locator('#cpf').waitFor();
  assert.equal(await page.locator('.access-gate').count(), 0);
  assert.equal(await page.locator('.sticky-timer-bar').count(), 1);
  assert.equal(await page.locator('#nome').inputValue(), '', 'Rascunho oculto não pode vazar no público.');
  await preencher('93541134780', 'Ensaio publico', true);
  await enviar(true);
  console.log('Público: acesso oculto não libera o PIN geral; PIN real, reserva, câmera, cadastro e confirmação pública OK.');

  await page.goto(`${base}/${info.tokens['302']}`);
  await page.locator('#senha-acesso-lote').waitFor();
  assert.equal(await page.locator('#cpf').count(), 0, 'PIN geral não autoriza o lote oculto.');
  await senha();
  assert.equal(await page.locator('.sticky-timer-bar').count(), 1);
  await page.locator('#cpf').fill('93541134780');
  await page.locator('#cpf.is-invalid').waitFor();
  await page.getByRole('button', { name: /Cadastrar outro participante/ }).click();
  await page.locator('#cpf').waitFor();
  await preencher('12345678909', 'Ensaio oculto automatico');
  await enviar(false, 'aprovado');
  await page.screenshot({ path: '.venv/fluxo-real-confirmacao-oculto.png', fullPage: true });
  console.log('Oculto automático: PIN público não libera a senha do lote; cronômetro, CPF público duplicado e ingresso aprovado OK.');

  const cookieLess = await browser.newContext();
  const semSenha = await cookieLess.newPage();
  await semSenha.goto(`${base}/${info.tokens['303']}`);
  await semSenha.locator('#cpf').waitFor();
  assert.equal(await semSenha.locator('.access-gate').count(), 0);
  await cookieLess.close();

  const hiddenOnPublic = await context.request.post(`${base}/api/lote/301/reservar`);
  assert.equal(hiddenOnPublic.status(), 404, await hiddenOnPublic.text());
  const wrongLotGrant = await context.request.get(`${base}/api/avulso/${info.tokens['302']}/status`, {
    headers: { 'X-Lote-Acesso': grants.get(info.tokens['301']) }
  });
  assert.equal(wrongLotGrant.status(), 403);
  const hiddenGrantPublic = await probe.post('/api/lote/201/reservar', {
    headers: { 'X-Lote-Acesso': grants.get(info.tokens['302']) }
  });
  assert.equal(hiddenGrantPublic.status(), 403);
  for (const id of [301, 302, 303]) {
    const r = await probe.get(`/api/lote/live-status?lote_id=${id}`);
    assert.notEqual((await r.json()).id, id);
    assert.doesNotMatch(await r.text(), /Oculto E2E/);
  }
  const publicStatus = await probe.get('/api/lote/live-status');
  assert.equal((await publicStatus.json()).id, 201);

  const stats = await (await probe.get('/__test/stats')).json();
  assert.deepEqual(stats.solicitacoes, [
    { lote_id: 201, status: 'pendente_analise', total: 1 },
    { lote_id: 301, status: 'pendente_analise', total: 2 },
    { lote_id: 302, status: 'aprovado', total: 1 }
  ]);
  assert.equal(stats.ingressos, 1);
  assert.equal(stats.jobs, 3);
  assert.equal(stats.emails.find(e => e.sender_type === 'communications')?.total, 3);
  const ticket = stats.emails.find(e => e.sender_type === 'ticket');
  assert.equal(ticket?.total, 1);
  assert.equal(ticket.status, 'queued');
  assert.ok(ticket.imagem_bytes > 0);
  assert.equal(stats.lotes.find(l => l.id === 301).quantidade_resgatada, 2);
  assert.equal(stats.lotes.find(l => l.id === 201).quantidade_resgatada, 1);
  assert.deepEqual(errors, []);
  assert.deepEqual(failures, []);
  console.log('Isolamento: sem senha opcional, grant por lote, exclusão da API pública, ocupações separadas e filas reais (4 e-mails, 1 ingresso, 3 validações) OK. Nenhum SMTP/API externa executado.');
} catch (error) {
  console.error('Tela:', (await page.locator('body').innerText()).slice(0, 2000));
  console.error('Erros Vue:', errors, 'Falhas HTTP:', failures);
  await page.screenshot({ path: '.venv/fluxo-real-falha.png', fullPage: true });
  throw error;
} finally {
  await browser.close();
  await probe.dispose();
}
