<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useCamera } from '../composables/useCamera'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue'])

const videoRef = ref(null)

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
  if (videoRef.value) {
    await startCamera(videoRef.value)
  }
})

onUnmounted(() => {
  stopCamera()
})

async function onCameraChange(e) {
  const newDeviceId = e.target.value
  if (videoRef.value && newDeviceId) {
    await switchCamera(videoRef.value, newDeviceId)
  }
}

async function handleTirarFoto() {
  const base64 = capturePhoto(videoRef.value)
  if (base64) {
    emit('update:modelValue', base64)
  }
}

async function handleAlternarCamera() {
  if (videoRef.value) {
    await toggleFacingMode(videoRef.value)
  }
}

async function handleSolicitarPermissao() {
  if (videoRef.value) {
    await startCamera(videoRef.value)
  }
}

async function handleRefazerFoto() {
  resetPhoto()
  emit('update:modelValue', '')
  if (videoRef.value) {
    await startCamera(videoRef.value, selectedDeviceId.value)
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
        @change="onCameraChange"
      >
        <option v-for="cam in availableCameras" :key="cam.deviceId" :value="cam.deviceId">
          {{ cam.label }}
        </option>
      </select>
    </div>

    <div class="video-viewport">
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
        alt="Foto Capturada"
        class="photo-preview"
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
        <button type="button" class="btn btn-sm btn-primary" @click="handleSolicitarPermissao">
          <i class="bi bi-shield-check me-1"></i> Solicitar Permissão Novamente
        </button>
      </div>
    </div>

    <!-- Ações de Captura -->
    <div class="camera-actions">
      <template v-if="!capturedPhoto && !modelValue">
        <button
          type="button"
          class="btn-snap font-outfit"
          :disabled="!isStreaming"
          @click="handleTirarFoto"
        >
          <i class="bi bi-camera-fill me-2"></i> Tirar Foto ao Vivo
        </button>

        <button
          v-if="isStreaming"
          type="button"
          class="btn btn-secondary btn-sm font-outfit"
          title="Alternar entre câmera frontal e traseira"
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
        @click="handleRefazerFoto"
      >
        <i class="bi bi-arrow-counterclockwise me-1"></i> Tirar Outra Foto
      </button>
    </div>

    <p v-if="isStreaming && !capturedPhoto && !modelValue" class="camera-hint">
      <i class="bi bi-shield-check text-cyan me-1"></i>
      {{ isMobile ? 'Utilizando a câmera frontal do seu aparelho.' : 'Posicione-se em frente à câmera e clique no botão acima.' }}
    </p>
    <p v-else-if="capturedPhoto || modelValue" class="camera-success-hint">
      <i class="bi bi-check-circle-fill text-success me-1"></i> Foto facial ao vivo capturada com sucesso!
    </p>
  </div>
</template>
