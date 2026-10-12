<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useAuth } from '../composables/useAuth'
import Modal from './Modal.vue'

const { isAdminGeral } = useAuth()
const logos = ref([])
const showManager = ref(false)
const selectedFile = ref(null)
const sourceImage = ref(null)
const cropCanvas = ref(null)
const zoom = ref(1)
const centerX = ref(0.5)
const centerY = ref(0.5)
const dragging = ref(false)
const pointerStart = ref(null)
const saving = ref(false)
const deletingId = ref(null)
const errorMessage = ref('')
const repeatedLogos = computed(() => {
  if (!logos.value.length) return []
  const copies = Math.max(2, Math.ceil(5 / logos.value.length) * 2)
  return Array.from({ length: copies }, () => logos.value).flat()
})

async function loadLogos() {
  try {
    const response = await fetch('/api/sponsor-logos', { cache: 'no-store' })
    if (response.ok) logos.value = (await response.json()).itens || []
  } catch (error) {
    console.error('Não foi possível carregar as logos.', error)
  }
}

function drawCrop() {
  const canvas = cropCanvas.value
  const image = sourceImage.value
  if (!canvas || !image) return
  const context = canvas.getContext('2d')
  const aspect = canvas.width / canvas.height
  const baseWidth = Math.min(image.naturalWidth, image.naturalHeight * aspect)
  const baseHeight = baseWidth / aspect
  const cropWidth = baseWidth / zoom.value
  const cropHeight = baseHeight / zoom.value
  const left = (image.naturalWidth - cropWidth) * centerX.value
  const top = (image.naturalHeight - cropHeight) * centerY.value
  context.clearRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, left, top, cropWidth, cropHeight, 0, 0, canvas.width, canvas.height)
}

watch([zoom, centerX, centerY, sourceImage], () => nextTick(drawCrop))

async function chooseFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    errorMessage.value = 'Selecione um arquivo de imagem.'
    return
  }
  if (file.size > 12 * 1024 * 1024) {
    errorMessage.value = 'A imagem original deve ter até 12 MB.'
    return
  }
  errorMessage.value = ''
  selectedFile.value = file
  zoom.value = 1
  centerX.value = 0.5
  centerY.value = 0.5
  const image = new Image()
  image.onload = async () => {
    sourceImage.value = image
    await nextTick()
    drawCrop()
  }
  image.onerror = () => { errorMessage.value = 'Não foi possível abrir essa imagem.' }
  image.src = URL.createObjectURL(file)
}

function startDrag(event) {
  if (!sourceImage.value) return
  dragging.value = true
  pointerStart.value = { x: event.clientX, y: event.clientY, centerX: centerX.value, centerY: centerY.value }
  event.currentTarget.setPointerCapture(event.pointerId)
}

function moveCrop(event) {
  if (!dragging.value || !pointerStart.value) return
  const image = sourceImage.value
  const canvas = cropCanvas.value
  const aspect = canvas.width / canvas.height
  const baseWidth = Math.min(image.naturalWidth, image.naturalHeight * aspect) / zoom.value
  const baseHeight = baseWidth / aspect
  centerX.value = Math.min(1, Math.max(0, pointerStart.value.centerX - (event.clientX - pointerStart.value.x) * zoom.value / (canvas.clientWidth || 1) * canvas.width / (image.naturalWidth - baseWidth || 1)))
  centerY.value = Math.min(1, Math.max(0, pointerStart.value.centerY - (event.clientY - pointerStart.value.y) * zoom.value / (canvas.clientHeight || 1) * canvas.height / (image.naturalHeight - baseHeight || 1)))
}

function stopDrag() {
  dragging.value = false
  pointerStart.value = null
}

async function saveLogo() {
  if (!cropCanvas.value) return
  saving.value = true
  errorMessage.value = ''
  try {
    const response = await fetch('/api/sponsor-logos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ imagem: cropCanvas.value.toDataURL('image/png') })
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || 'Não foi possível salvar a logo.')
    await loadLogos()
    selectedFile.value = null
    sourceImage.value = null
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    saving.value = false
  }
}

async function deleteLogo(logo) {
  if (!window.confirm('Remover esta logo da faixa?')) return
  deletingId.value = logo.id
  errorMessage.value = ''
  try {
    const response = await fetch(`/api/sponsor-logos/${logo.id}`, { method: 'DELETE' })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || 'Não foi possível remover a logo.')
    logos.value = logos.value.filter(item => item.id !== logo.id)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    deletingId.value = null
  }
}

function closeManager() {
  showManager.value = false
  selectedFile.value = null
  sourceImage.value = null
  errorMessage.value = ''
}

onMounted(loadLogos)
</script>

<template>
  <section v-if="logos.length || isAdminGeral" class="sponsor-strip" aria-label="Patrocinadores">
    <div v-if="logos.length" class="sponsor-strip-track-wrap">
      <div class="sponsor-strip-track" :class="{ 'sponsor-strip-track-static': logos.length < 2 }">
        <div v-for="(logo, index) in repeatedLogos" :key="`${logo.id}-${index}`" class="sponsor-strip-item">
          <img :src="logo.url" :alt="`Logo de patrocinador ${index % logos.length + 1}`" />
        </div>
      </div>
    </div>
    <p v-else class="sponsor-strip-empty">Logos dos patrocinadores aparecerão aqui.</p>
    <button v-if="isAdminGeral" type="button" class="btn-sponsor-manage" @click="showManager = true">
      <i class="bi bi-images"></i>
      <span>{{ logos.length ? 'Gerenciar logos' : 'Adicionar logos' }}</span>
    </button>

    <Modal :show="showManager" title="Logos dos patrocinadores" icon="bi-images" :max-width="'680px'" @close="closeManager">
      <p class="sponsor-manager-help">Adicione logos e arraste a imagem para ajustar o enquadramento; todas ficam no mesmo quadro horizontal.</p>
      <div class="sponsor-upload-area">
        <label class="sponsor-file-label">
          <i class="bi bi-upload"></i>
          <span>{{ selectedFile ? 'Escolher outra imagem' : 'Selecionar imagem' }}</span>
          <input type="file" accept="image/*" @change="chooseFile" />
        </label>
        <template v-if="selectedFile">
          <div class="sponsor-crop-viewport" @pointerdown="startDrag" @pointermove="moveCrop" @pointerup="stopDrag" @pointercancel="stopDrag" @lostpointercapture="stopDrag">
            <canvas ref="cropCanvas" width="900" height="600" aria-label="Prévia do recorte da logo"></canvas>
            <span class="sponsor-crop-hint"><i class="bi bi-arrows-move"></i> Arraste para enquadrar</span>
          </div>
          <label class="sponsor-zoom-control">Zoom <input v-model.number="zoom" type="range" min="1" max="3" step="0.05" /></label>
          <button type="button" class="btn-sponsor-save" :disabled="saving || !sourceImage" @click="saveLogo">
            <i class="bi bi-check2"></i>{{ saving ? 'Salvando...' : 'Salvar logo' }}
          </button>
        </template>
      </div>
      <p v-if="errorMessage" class="sponsor-error" role="alert">{{ errorMessage }}</p>
      <div v-if="logos.length" class="sponsor-manager-list">
        <div v-for="logo in logos" :key="logo.id" class="sponsor-manager-item">
          <img :src="logo.url" alt="Logo cadastrada" />
          <button type="button" class="btn-sponsor-delete" :disabled="deletingId === logo.id" :aria-label="`Remover logo ${logo.ordem + 1}`" @click="deleteLogo(logo)">
            <i class="bi bi-trash3"></i>
          </button>
        </div>
      </div>
    </Modal>
  </section>
</template>
