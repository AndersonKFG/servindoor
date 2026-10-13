import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const photoSource = fs.readFileSync('frontend/src/utils/photoUpload.js', 'utf8')
  .replace('export async function', 'async function');
const jpeg = 'data:image/jpeg;base64,/9j/Zm90bw==';

function converter({ width = 4000, height = 3000, corrupt = false, encoded = jpeg } = {}) {
  const revoked = [];
  const canvas = { getContext: () => ({ fillRect() {}, drawImage() {} }), toDataURL: () => encoded };
  class Image {
    naturalWidth = width;
    naturalHeight = height;
    set src(value) { queueMicrotask(() => corrupt ? this.onerror() : this.onload()); }
  }
  const context = vm.createContext({ Image, atob, document: { createElement: () => canvas },
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL: url => revoked.push(url) } });
  vm.runInContext(photoSource + '\nglobalThis.prepare = preparePhotoUpload;', context);
  return { prepare: context.prepare, revoked, canvas };
}

for (const type of ['image/jpeg', 'image/png', 'image/webp']) {
  const photo = converter();
  assert.equal(await photo.prepare({ type, size: 1000 }), jpeg);
  assert.equal(photo.canvas.width, 1600);
  assert.equal(photo.canvas.height, 1200);
  assert.deepEqual(photo.revoked, ['blob:test']);
}
const small = converter({ width: 300, height: 600 });
await small.prepare({ type: 'image/jpeg', size: 1000 });
assert.equal(small.canvas.width, 300);
assert.equal(small.canvas.height, 600);
await assert.rejects(converter().prepare({ type: 'application/pdf', size: 1000 }), /JPG, PNG ou WebP/);
await assert.rejects(converter().prepare({ type: 'image/svg+xml', size: 1000 }), /JPG, PNG ou WebP/);
await assert.rejects(converter().prepare({ type: 'image/png', size: 11 * 1024 * 1024 }), /10 MB/);
await assert.rejects(converter().prepare({ type: 'image/png', size: 0 }), /10 MB/);
const corrupt = converter({ corrupt: true });
await assert.rejects(corrupt.prepare({ type: 'image/jpeg', size: 1000 }), /abrir esta imagem/);
assert.deepEqual(corrupt.revoked, ['blob:test']);
const oversized = converter({ encoded: 'data:image/jpeg;base64,' + Buffer.alloc(4 * 1024 * 1024 + 1).toString('base64') });
await assert.rejects(oversized.prepare({ type: 'image/png', size: 1000 }), /imagem menor/);
assert.deepEqual(oversized.revoked, ['blob:test']);

const componentSource = fs.readFileSync('frontend/src/components/WebcamCapture.vue', 'utf8')
  .split('<script setup>')[1].split('</script>')[0]
  .split('\n').filter(line => !line.startsWith('import ')).join('\n');

function component({ allowUpload = true, modelValue = '', prepare = async () => jpeg, start } = {}) {
  const ref = value => ({ value });
  const props = { allowUpload, modelValue };
  const updates = [];
  let mounted, unmounted, starts = 0;
  const camera = { isStreaming: ref(false), cameraError: ref(null), capturedPhoto: ref(null),
    availableCameras: ref([]), selectedDeviceId: ref(''), isMobile: ref(false), currentFacingMode: ref('user'),
    startCamera: async () => { starts++; if (start) await start(); camera.isStreaming.value = true; },
    stopCamera: () => { camera.isStreaming.value = false; },
    resetPhoto: () => { camera.capturedPhoto.value = null; },
    capturePhoto: () => { camera.capturedPhoto.value = jpeg; return jpeg; } };
  const context = vm.createContext({ ref, defineProps: () => props,
    defineEmits: () => (name, value) => { updates.push({ name, value }); props.modelValue = value; },
    onMounted: fn => { mounted = fn; }, onUnmounted: fn => { unmounted = fn; },
    useCamera: () => camera, preparePhotoUpload: prepare });
  vm.runInContext(componentSource + '\nglobalThis.api = { videoRef, uploading, uploadError, handleEnviarArquivo, handleTirarFoto, handleRefazerFoto, handleSolicitarPermissao };', context);
  context.api.videoRef.value = {};
  return { api: context.api, camera, props, updates, mount: () => mounted(), unmount: () => unmounted(), get starts() { return starts; } };
}

const fileEvent = () => ({ target: { files: [{ type: 'image/png', size: 1000 }], value: 'foto.png' } });
const upload = component();
await upload.mount();
assert.equal(upload.starts, 0, 'Resgate não pede câmera antes da escolha do usuário');
upload.camera.cameraError.value = 'Sem câmera';
const event = fileEvent();
await upload.api.handleEnviarArquivo(event);
assert.equal(upload.props.modelValue, jpeg);
assert.equal(upload.camera.cameraError.value, null);
assert.equal(event.target.value, '');
assert.equal(upload.api.uploading.value, false);

const invalid = component({ modelValue: jpeg, prepare: async () => { throw new Error('Arquivo inválido'); } });
await invalid.api.handleEnviarArquivo(fileEvent());
assert.equal(invalid.props.modelValue, jpeg, 'Erro preserva a foto anterior');
assert.equal(invalid.updates.length, 0);
assert.equal(invalid.api.uploadError.value, 'Arquivo inválido');
await invalid.api.handleEnviarArquivo({ target: { files: [] } });
assert.equal(invalid.updates.length, 0, 'Cancelar seletor preserva a foto');

const liveOnly = component({ allowUpload: false });
await liveOnly.mount();
assert.equal(liveOnly.starts, 1, 'Cancelamento continua iniciando a câmera');
await liveOnly.api.handleEnviarArquivo(fileEvent());
assert.equal(liveOnly.updates.length, 0, 'Upload exige habilitação explícita');
await liveOnly.api.handleTirarFoto();
assert.equal(liveOnly.props.modelValue, jpeg);
assert.equal(liveOnly.camera.isStreaming.value, false);
await liveOnly.api.handleRefazerFoto();
assert.equal(liveOnly.props.modelValue, '');
assert.equal(liveOnly.camera.isStreaming.value, true);

let finishCamera;
const pendingCamera = component({ start: () => new Promise(resolve => { finishCamera = resolve; }) });
const opening = pendingCamera.api.handleSolicitarPermissao();
await pendingCamera.api.handleEnviarArquivo(fileEvent());
finishCamera();
await opening;
assert.equal(pendingCamera.camera.isStreaming.value, false, 'Permissão tardia não deixa câmera ligada após upload');
assert.equal(pendingCamera.props.modelValue, jpeg);

let finishPhoto;
const pendingPhoto = component({ prepare: () => new Promise(resolve => { finishPhoto = resolve; }) });
const preparing = pendingPhoto.api.handleEnviarArquivo(fileEvent());
pendingPhoto.unmount();
finishPhoto(jpeg);
await preparing;
assert.equal(pendingPhoto.updates.length, 0, 'Sair da tela cancela a atualização da foto');

console.log('Foto do resgate: formatos, tamanho, proporção, arquivo inválido, troca/cancelamento, câmera opcional, permissão tardia e saída da tela passaram.');
