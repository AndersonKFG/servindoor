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

    <!-- Mensagens de Erro de Câmera -->
    <div v-if="cameraError" class="camera-error-msg">
      <i class="bi bi-exclamation-triangle-fill me-1"></i>
      {{ cameraError }}
      <button type="button" class="btn-retry" @click="startCamera(videoRef)">
        <i class="bi bi-arrow-clockwise me-1"></i> Tentar Novamente
      </button>
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

<style scoped>
.camera-box-card {
  background: rgba(15, 23, 42, 0.75);
  border: 2px dashed rgba(255, 255, 255, 0.15);
  border-radius: 20px;
  padding: 18px 14px;
  text-align: center;
  position: relative;
  transition: all 0.3s ease;
}

.camera-box-card.active {
  border-color: rgba(56, 189, 248, 0.5);
  box-shadow: 0 0 25px rgba(56, 189, 248, 0.15);
}

.camera-box-card.has-photo {
  border-color: rgba(16, 185, 129, 0.6);
  border-style: solid;
  box-shadow: 0 0 25px rgba(16, 185, 129, 0.25);
}

.camera-box-card.has-error {
  border-color: rgba(244, 63, 94, 0.7);
  border-style: solid;
  box-shadow: 0 0 25px rgba(244, 63, 94, 0.3);
}

/* SELETOR DE CÂMERA */
.camera-selector-container {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.camera-selector-label {
  font-size: 0.8rem;
  font-weight: 700;
  color: #cbd5e1;
  margin: 0;
}

.camera-select-input {
  max-width: 260px;
  height: 36px;
  background: rgba(0, 0, 0, 0.5) !important;
  border: 1px solid rgba(255, 255, 255, 0.18) !important;
  color: #ffffff !important;
  border-radius: 8px !important;
  font-size: 0.8rem !important;
  padding: 4px 10px !important;
  cursor: pointer;
}

.camera-select-input option {
  background: #0f172a;
  color: #ffffff;
}

.video-viewport {
  position: relative;
  width: 100%;
  max-width: 300px;
  aspect-ratio: 1 / 1;
  margin: 0 auto;
  border-radius: 18px;
  overflow: hidden;
  background: #000000;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.video-element {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  transform: scaleX(-1);
}

.photo-preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.face-guide-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 68%;
  height: 82%;
  border: 2px dashed rgba(255, 255, 255, 0.65);
  border-radius: 50%;
  pointer-events: none;
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.28);
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding-bottom: 12px;
}

.face-guide-text {
  font-size: 0.7rem;
  font-weight: 700;
  color: #ffffff;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.9);
  letter-spacing: 0.3px;
  text-align: center;
  padding: 0 8px;
}

.camera-actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}

.btn-snap {
  background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
  border: 1px solid rgba(56, 189, 248, 0.5);
  color: #ffffff;
  font-weight: 700;
  padding: 12px 28px;
  border-radius: 999px;
  font-size: 0.94rem;
  min-height: 48px;
  box-shadow: 0 6px 20px rgba(2, 132, 199, 0.4);
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
}

.btn-snap:hover:not(:disabled) {
  transform: scale(1.03);
  filter: brightness(1.1);
  box-shadow: 0 8px 25px rgba(2, 132, 199, 0.6);
}

.btn-snap:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-retake {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #ffffff;
  font-weight: 600;
  padding: 10px 22px;
  border-radius: 999px;
  font-size: 0.88rem;
  min-height: 42px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-retake:hover {
  background: rgba(255, 255, 255, 0.16);
}

.camera-hint {
  font-size: 0.76rem;
  color: var(--text-muted);
  margin-top: 10px;
}

.camera-success-hint {
  font-size: 0.85rem;
  font-weight: 600;
  color: #34d399;
  margin-top: 10px;
}

.camera-error-msg {
  color: #fb7185;
  font-size: 0.82rem;
  margin-top: 10px;
  padding: 8px 12px;
  background: rgba(244, 63, 94, 0.1);
  border-radius: 8px;
}

.btn-retry {
  margin-top: 6px;
  display: block;
  margin-left: auto;
  margin-right: auto;
  background: transparent;
  border: 1px solid rgba(244, 63, 94, 0.4);
  color: #fb7185;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 0.75rem;
  cursor: pointer;
}

.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.text-cyan { color: #38bdf8 !important; }
.text-success { color: var(--success-color); }
</style>
