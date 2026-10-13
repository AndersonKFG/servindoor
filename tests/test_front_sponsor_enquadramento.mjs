import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/src/components/SponsorLogos.vue', 'utf8')
  .split('<script setup>')[1].split('</script>')[0]
  .split('\n').filter(line => !line.startsWith('import ')).join('\n');
const requests = [];
const draws = [];
let exported;
const canvas = {
  width: 900, height: 600, clientWidth: 450, clientHeight: 300,
  getContext: () => ({ clearRect() {}, drawImage: (...args) => draws.push(args) }),
  toDataURL: type => { exported = { type, draw: draws.at(-1) }; return 'data:image/png;base64,bG9nbw=='; },
};
const context = vm.createContext({ ref: value => ({ value }), computed: getter => ({ get value() { return getter(); } }),
  watch() {}, onMounted() {}, nextTick: async fn => fn?.(), useAuth: () => ({ isAdminGeral: true }),
  fetch: async (url, options) => { requests.push({ url, options }); return { ok: true, json: async () => ({ itens: [] }) }; }, console,
});
vm.runInContext(source + '\nglobalThis.api = { cropCanvas, sourceImage, zoom, centerX, centerY, drawCrop, resetCrop, startDrag, moveCrop, stopDrag, saveLogo };', context);
const api = context.api;
api.cropCanvas.value = canvas;

function assertWholeLogo(draw, width, height) {
  const [image, left, top, drawnWidth, drawnHeight] = draw;
  assert.equal(draw.length, 5, 'Desenha toda a imagem de origem, sem recortar pixels');
  assert.equal(image.naturalWidth, width);
  assert.equal(image.naturalHeight, height);
  assert.ok(left >= -1e-8 && top >= -1e-8, 'Bordas iniciais da logo ficam no quadro');
  assert.ok(left + drawnWidth <= canvas.width + 1e-8, 'Borda direita fica no quadro');
  assert.ok(top + drawnHeight <= canvas.height + 1e-8, 'Borda inferior fica no quadro');
  assert.ok(Math.abs(drawnWidth / drawnHeight - width / height) < 1e-8, 'Preserva a proporção');
}

for (const [width, height] of [[11170, 11170], [4000, 500], [500, 4000], [900, 600], [24, 24]]) {
  api.sourceImage.value = { naturalWidth: width, naturalHeight: height };
  api.resetCrop();
  api.drawCrop();
  assertWholeLogo(draws.at(-1), width, height);
  api.zoom.value = 0.25;
  api.drawCrop();
  assertWholeLogo(draws.at(-1), width, height);
}

api.sourceImage.value = { naturalWidth: 11170, naturalHeight: 11170 };
api.resetCrop();
api.drawCrop();
const beforeDrag = draws.at(-1);
api.startDrag({ clientX: 0, clientY: 0, pointerId: 1, currentTarget: { setPointerCapture() {} } });
api.moveCrop({ clientX: 40, clientY: 40 });
api.drawCrop();
assert.ok(Math.abs(draws.at(-1)[1] - beforeDrag[1] - 80) < 1e-8, 'Posição acompanha o ponteiro na escala da prévia');
assertWholeLogo(draws.at(-1), 11170, 11170);
api.stopDrag();

api.zoom.value = 3;
api.centerX.value = 0;
api.centerY.value = 1;
api.drawCrop();
api.resetCrop();
await api.saveLogo();
assert.equal(exported.type, 'image/png', 'Mantém o formato com suporte a transparência');
assertWholeLogo(exported.draw, 11170, 11170);
assert.equal(requests[0].url, '/api/sponsor-logos');
assert.equal(requests[0].options.method, 'POST');
assert.equal(JSON.parse(requests[0].options.body).imagem, 'data:image/png;base64,bG9nbw==');

console.log('Logos: imagem inteira, proporção quadrada/horizontal/vertical, zoom para reduzir, arrastar, restaurar e exportar PNG passaram.');
