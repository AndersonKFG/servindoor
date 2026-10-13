<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useCamera } from '../composables/useCamera'
import { preparePhotoUpload } from '../utils/photoUpload'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  allowUpload: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue'])

const videoRef = ref(null)
const fileInputRef = ref(null)
const uploading = ref(false)
const uploadError = ref('')
const startingCamera = ref(false)
let unmounted = false

const {
  isStreaming,
  cameraError,
  capturedPhoto,
  availableCameras,
  selectedDeviceId,
  isMobile,
  startCamera,
  switchCamera,
  capturePhoto,
  resetPhoto,
  currentFacingMode,
  toggleFacingMode,
  stopCamera
} = useCamera()

onMounted(async () => {
  if (videoRef.value && !props.modelValue && !props.allowUpload) {
    await handleSolicitarPermissao()
  }
})

onUnmounted(() => {
  unmounted = true
  stopCamera()
})

async function onCameraChange(e) {
  const newDeviceId = e.target.value
  if (videoRef.value && newDeviceId) {
    await runCameraAction(() => switchCamera(videoRef.value, newDeviceId))
  }
}

async function handleTirarFoto() {
  const base64 = capturePhoto(videoRef.value)
  if (base64) {
    uploadError.value = ''
    emit('update:modelValue', base64)
    stopCamera()
  }
}

async function handleAlternarCamera() {
  if (videoRef.value) {
    await runCameraAction(() => toggleFacingMode(videoRef.value))
  }
}

async function runCameraAction(action) {
  if (!unmounted && !startingCamera.value && !uploading.value) {
    startingCamera.value = true
    try {
      await action()
      if (unmounted || props.modelValue || capturedPhoto.value || uploading.value) {
        stopCamera()
        cameraError.value = null
      }
    } finally {
      startingCamera.value = false
    }
  }
}

async function handleSolicitarPermissao() {
  if (videoRef.value) {
    await runCameraAction(() => startCamera(videoRef.value))
  }
}

async function handleRefazerFoto() {
  uploadError.value = ''
  resetPhoto()
  emit('update:modelValue', '')
  if (videoRef.value) {
    await handleSolicitarPermissao()
  }
}

async function handleEnviarArquivo(event) {
  const input = event.target
  const file = input.files?.[0]
  if (!file || !props.allowUpload || uploading.value) return
  uploading.value = true
  uploadError.value = ''
  try {
    const photo = await preparePhotoUpload(file)
    if (unmounted) return
    stopCamera()
    resetPhoto()
    cameraError.value = null
    emit('update:modelValue', photo)
  } catch (error) {
    if (!unmounted) uploadError.value = error.message || 'Não foi possível enviar a foto. Tente novamente.'
  } finally {
    uploading.value = false
    // Permite selecionar o mesmo arquivo novamente após um erro.
    input.value = ''
  }
}
</script>

<template>
  <div class="camera-box-card" :class="{ 'has-photo': capturedPhoto || modelValue, 'has-error': !!cameraError, 'active': isStreaming }">
    
    <!-- Seletor de Câmeras para Computadores com Múltiplas Fontes de Vídeo -->
    <div v-if="!capturedPhoto && !modelValue && availableCameras.length > 1" class="camera-selector-container">
      <label class="camera-selector-label" for="camera-select">
        <i class="bi bi-camera-video text-cyan me-1"></i> Selecionar Câmera:
      </label>
      <select
        id="camera-select"
        v-model="selectedDeviceId"
        class="form-select camera-select-input"
        :disabled="startingCamera || uploading"
        @change="onCameraChange"
      >
        <option v-for="cam in availableCameras" :key="cam.deviceId" :value="cam.deviceId">
          {{ cam.label }}
        </option>
      </select>
    </div>

    <div v-show="!allowUpload || isStreaming || capturedPhoto || modelValue" class="video-viewport">
      <video
        v-show="!capturedPhoto && !modelValue"
        ref="videoRef"
        autoplay
        playsinline
        muted
        class="video-element"
      ></video>

      <img
        v-if="capturedPhoto || modelValue"
        :src="capturedPhoto || modelValue"
        alt="Prévia da foto de identificação"
        class="photo-preview"
        :class="{ 'photo-preview--contain': allowUpload }"
      />

      <div v-if="isStreaming && !capturedPhoto && !modelValue" class="face-guide-overlay">
        <span class="face-guide-text">Enquadre seu rosto</span>
      </div>
    </div>

    <!-- Mensagens de Erro e Re-solicitação de Permissão -->
    <div v-if="cameraError" class="camera-error-msg">
      <i class="bi bi-camera-video-off fs-4 me-2 text-warning"></i>
      <div>
        <strong>Acesso à câmera bloqueado ou indisponível.</strong>
        <p class="small mb-2">{{ cameraError }}</p>
        <p v-if="allowUpload" class="small mb-2">Você também pode enviar uma foto pelo botão abaixo.</p>
        <button type="button" class="btn btn-sm btn-primary" :disabled="startingCamera || uploading" @click="handleSolicitarPermissao">
          <i class="bi bi-shield-check me-1"></i> Solicitar Permissão Novamente
        </button>
      </div>
    </div>

    <!-- Ações de Captura -->
    <div class="camera-actions flex-wrap gap-2">
      <template v-if="!capturedPhoto && !modelValue">
        <button
          v-if="allowUpload && !isStreaming && !cameraError"
          type="button"
          class="btn-snap font-outfit"
          :disabled="startingCamera || uploading"
          @click="handleSolicitarPermissao"
        >
          <i class="bi bi-camera-video me-2"></i> {{ startingCamera ? 'Abrindo câmera...' : 'Usar câmera' }}
        </button>
        <button
          v-show="!allowUpload || isStreaming"
          type="button"
          class="btn-snap font-outfit"
          :disabled="!isStreaming || startingCamera || uploading"
          @click="handleTirarFoto"
        >
          <i class="bi bi-camera-fill me-2"></i> Tirar Foto ao Vivo
        </button>

        <button
          v-if="isStreaming"
          type="button"
          class="btn btn-secondary btn-sm font-outfit"
          title="Alternar entre câmera frontal e traseira"
          :disabled="startingCamera || uploading"
          @click="handleAlternarCamera"
        >
          <i class="bi bi-camera-reverse me-1 text-cyan"></i>
          {{ currentFacingMode === 'user' ? 'Usar Traseira' : 'Usar Frontal' }}
        </button>
      </template>

      <button
        v-else
        type="button"
        class="btn-retake font-outfit"
        :disabled="uploading || startingCamera"
        @click="handleRefazerFoto"
      >
        <i class="bi bi-arrow-counterclockwise me-1"></i> Tirar Outra Foto
      </button>

      <button
        v-if="allowUpload"
        type="button"
        class="btn-retake font-outfit"
        :disabled="uploading"
        @click="fileInputRef?.click()"
      >
        <i class="bi bi-upload me-1"></i>
        {{ uploading ? 'Preparando foto...' : (capturedPhoto || modelValue ? 'Enviar outra foto' : 'Enviar foto do dispositivo') }}
      </button>
      <input
        v-if="allowUpload"
        ref="fileInputRef"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        aria-label="Selecionar foto de identificação"
        hidden
        @change="handleEnviarArquivo"
      />
    </div>

    <p v-if="uploadError" class="camera-error-msg" role="alert">{{ uploadError }}</p>
    <p v-if="allowUpload" class="camera-hint" role="status">
      {{ uploading ? 'Aguarde enquanto sua foto é preparada.' : 'Envie uma foto sua, nítida e com o rosto visível. JPG, PNG ou WebP, até 10 MB.' }}
    </p>

    <p v-if="isStreaming && !capturedPhoto && !modelValue" class="camera-hint">
      <i class="bi bi-shield-check text-cyan me-1"></i>
      {{ isMobile ? 'Utilizando a câmera frontal do seu aparelho.' : 'Posicione-se em frente à câmera e clique no botão acima.' }}
    </p>
    <p v-else-if="capturedPhoto || modelValue" class="camera-success-hint">
      <i class="bi bi-check-circle-fill text-success me-1"></i>
      {{ allowUpload ? 'Foto de identificação pronta para envio!' : 'Foto facial ao vivo capturada com sucesso!' }}
    </p>
  </div>
</template>
