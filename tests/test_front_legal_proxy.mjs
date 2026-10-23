// Usa o proxy real do Vite e uma API HTTP descartável, sem banco ou e-mails.
import assert from 'node:assert/strict';
import http from 'node:http';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { createServer, loadConfigFromFile } = require('vite');
const { config: viteConfig } = await loadConfigFromFile(
  { command: 'serve', mode: 'development' },
  fileURLToPath(new URL('../frontend/vite.config.js', import.meta.url))
);
let received;
const backend = http.createServer(async (request, response) => {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  received = { headers: request.headers, body: Buffer.concat(chunks).toString() };
  response.setHeader('Content-Type', 'application/json');
  const sameOrigin = request.headers.origin === `http://${request.headers.host}`;
  response.writeHead(sameOrigin ? 201 : 403);
  response.end(JSON.stringify({ sameOrigin }));
});
await new Promise(resolve => backend.listen(0, '127.0.0.1', resolve));
const server = await createServer({
  ...viteConfig,
  configFile: false,
  root: fileURLToPath(new URL('../frontend', import.meta.url)),
  server: {
    ...viteConfig.server, host: '127.0.0.1', port: 0, open: false,
    proxy: { '/api': { ...viteConfig.server.proxy['/api'], target: `http://127.0.0.1:${backend.address().port}` } }
  }
});
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  const form = new FormData();
  form.set('kind', 'terms');
  form.set('title', 'Termos de Uso v1');
  form.set('version', '1.0');
  form.set('file', new Blob(['documento de teste'], { type: 'application/pdf' }), 'termos.pdf');
  const response = await fetch(`${origin}/api/admin/legal/documents`, {
    method: 'POST', body: form, headers: { Origin: origin, 'X-Legal-Action': '1' }
  });
  assert.equal(response.status, 201, await response.text());
  assert.equal(received.headers.host, new URL(origin).host);
  assert.equal(received.headers.origin, origin);
  assert.equal(received.headers['x-legal-action'], '1');
  assert.match(received.headers['content-type'], /^multipart\/form-data; boundary=/);
  assert.match(received.body, /Termos de Uso v1/);
  assert.match(received.body, /filename="termos.pdf"/);
  console.log('Proxy Vite: Host/Origin, header CSRF e upload multipart preservados.');
} finally {
  await server.close();
  await new Promise(resolve => backend.close(resolve));
}
