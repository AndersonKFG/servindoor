<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Modal from '../components/Modal.vue'
import WebcamCapture from '../components/WebcamCapture.vue'

const loading = ref(true)
const entregas = ref([])
const filtroStatus = ref('pendentes') // 'pendentes' | 'entregues' | 'todos'
const busca = ref('')

const showModalEntrega = ref(false)
const showModalZoomFoto = ref(false)
const entregaSelecionada = ref(null)
const fotoZoomUrl = ref('')

const fotoComprovacaoBase64 = ref('')
const modoCaptura = ref('camera') // 'camera' | 'upload'
const enviando = ref(false)

let pollInterval = null

async function carregarEntregas(silent = false) {
  try {
    if (!silent) loading.value = true
    const res = await fetch('/api/sorteios/entregas-pendentes')
    if (res.ok) {
      const data = await res.json()
      entregas.value = data.entregas || []
    }
  } catch (e) {
    if (!silent) console.error('Erro ao carregar entregas:', e)
  } finally {
    if (!silent) loading.value = false
  }
}

const entregasFiltradas = computed(() => {
  return entregas.value.filter(item => {
    // Filtro por status
    if (filtroStatus.value === 'pendentes' && item.entregue) return false
    if (filtroStatus.value === 'entregues' && !item.entregue) return false

    // Filtro por busca
    if (!busca.value.trim()) return true
    const termo = busca.value.toLowerCase()
    return (
      item.servidor_nome.toLowerCase().includes(termo) ||
      item.servidor_cpf.toLowerCase().includes(termo) ||
      item.secretaria_nome.toLowerCase().includes(termo) ||
      item.premio_nome.toLowerCase().includes(termo)
    )
  })
})

function abrirModalEntrega(item) {
  entregaSelecionada.value = item
  fotoComprovacaoBase64.value = ''
  modoCaptura.value = 'camera'
  showModalEntrega.value = true
}

function onSelfieCaptured(base64Data) {
  fotoComprovacaoBase64.value = base64Data
}

function onUploadFotoChange(e) {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    fotoComprovacaoBase64.value = reader.result
  }
  reader.readAsDataURL(file)
}

async function confirmarEntrega() {
  if (!fotoComprovacaoBase64.value) {
    alert('A foto do ganhador segurando o prêmio é obrigatória.')
    return
  }

  enviando.value = true
  try {
    const formData = new FormData()
    formData.append('foto_base64', fotoComprovacaoBase64.value)

    const res = await fetch('/api/sorteios/registrar-entrega/' + entregaSelecionada.value.id, {
      method: 'POST',
      body: formData
    })

    if (res.ok) {
      showModalEntrega.value = false
      await carregarEntregas()
    } else {
      const d = await res.json()
      alert(d.detail || 'Erro ao registrar entrega.')
    }
  } catch (err) {
    console.error('Erro registrando entrega:', err)
  } finally {
    enviando.value = false
  }
}

function abrirZoomFoto(url) {
  fotoZoomUrl.value = url
  showModalZoomFoto.value = true
}

onMounted(() => {
  carregarEntregas()
})
</script>
<template>
  <div class="entrega-premios-page">
    <div class="app-container">
      
      <div class="page-header-row">
        <div>
          <span class="vip-badge bg-warning mb-2">
            <i class="bi bi-box2-heart-fill me-1"></i> Logística de Premiação
          </span>
          <h1 class="page-title font-outfit">Registro de Entrega de Prêmios</h1>
          <p class="page-subtitle">Valide e fotografe os ganhadores oficiais recebendo seus prêmios.</p>
        </div>

        <div class="filter-controls">
          <div class="btn-group-filters">
            <button
              type="button"
              :class="['btn-filter', { active: filtroStatus === 'pendentes' }]"
              @click="filtroStatus = 'pendentes'"
            >
              Pendentes
            </button>
            <button
              type="button"
              :class="['btn-filter', { active: filtroStatus === 'entregues' }]"
              @click="filtroStatus = 'entregues'"
            >
              Entregues
            </button>
            <button
              type="button"
              :class="['btn-filter', { active: filtroStatus === 'todos' }]"
              @click="filtroStatus = 'todos'"
            >
              Todos
            </button>
          </div>
        </div>
      </div>

      <!-- Barra de Busca -->
      <div class="search-bar-row mb-4">
        <div class="search-input-box">
          <i class="bi bi-search search-icon"></i>
          <input
            v-model="busca"
            type="text"
            class="search-input font-outfit"
            placeholder="Buscar por Nome do Servidor, CPF, Secretaria ou Prêmio..."
          />
          <button v-if="busca" type="button" class="btn-clear" @click="busca = ''">
            <i class="bi bi-x"></i>
          </button>
        </div>
      </div>

      <!-- Grid de Entregas -->
      <div class="entregas-grid">
        <div
          v-for="item in entregasFiltradas"
          :key="item.id"
          class="vip-glass-card entrega-card"
          :class="{ 'card-entregue': item.entregue }"
        >
          <div class="entrega-card-header">
            <div class="servidor-avatar-box">
              <img v-if="item.servidor_foto" :src="item.servidor_foto" alt="Foto" class="servidor-avatar" />
              <div v-else class="avatar-ph"><i class="bi bi-person"></i></div>
            </div>

            <div class="servidor-meta">
              <h3 class="servidor-nome font-outfit">{{ item.servidor_nome }}</h3>
              <span class="servidor-cpf font-monospace">{{ item.servidor_cpf }}</span>
              <span class="servidor-sec"><i class="bi bi-building me-1"></i>{{ item.secretaria_nome }}</span>
            </div>

            <span :class="['status-chip font-outfit', item.entregue ? 'chip-entregue' : 'chip-pendente']">
              <i :class="['bi me-1', item.entregue ? 'bi-check-circle-fill' : 'bi-hourglass-split']"></i>
              {{ item.entregue ? 'Entregue' : 'Pendente' }}
            </span>
          </div>

          <div class="entrega-card-body">
            <div class="premio-highlight-box">
              <div class="premio-thumb">
                <img v-if="item.premio_foto" :src="item.premio_foto" alt="Prêmio" class="thumb-img" />
                <div v-else class="thumb-ph"><i class="bi bi-gift-fill"></i></div>
              </div>
              <div>
                <span class="premio-tag font-outfit">PRÊMIO GANHO</span>
                <strong class="premio-nome font-outfit">{{ item.premio_nome }}</strong>
                <span class="sorteio-data">Sorteado em: {{ item.data_sorteio }}</span>
              </div>
            </div>

            <!-- Dados da Entrega Já Realizada -->
            <div v-if="item.entregue" class="comprovacao-box">
              <div class="comprovacao-info">
                <span class="comp-label font-outfit">Comprovação de Entrega:</span>
                <span class="comp-date"><i class="bi bi-calendar-check me-1"></i>{{ item.data_entrega }}</span>
                <span v-if="item.responsavel_entrega" class="comp-resp">Por: {{ item.responsavel_entrega }}</span>
              </div>
              <div
                v-if="item.foto_entrega_url"
                class="comprovacao-thumb"
                title="Clique para ampliar"
                @click="abrirZoomFoto(item.foto_entrega_url)"
              >
                <img :src="item.foto_entrega_url" alt="Comprovação" class="thumb-img" />
                <span class="zoom-hint"><i class="bi bi-zoom-in"></i></span>
              </div>
            </div>

            <!-- Ação de Registrar Entrega -->
            <div v-else class="action-footer">
              <button
                type="button"
                class="btn-registrar-entrega font-outfit"
                @click="abrirModalEntrega(item)"
              >
                <i class="bi bi-camera-fill me-1"></i> Registrar Entrega com Foto
              </button>
            </div>

          </div>
        </div>
      </div>

      <div v-if="entregasFiltradas.length === 0" class="empty-box">
        <i class="bi bi-inbox text-muted fs-1 mb-2"></i>
        <p class="text-muted">Nenhum registro de premiação encontrado com os filtros atuais.</p>
      </div>

    </div>

    <!-- MODAL REGISTRO DE ENTREGA -->
    <Modal
      :show="showModalEntrega"
      title="Registrar Entrega de Prêmio"
      icon="bi-camera-fill"
      icon-color="text-warning"
      @close="showModalEntrega = false"
    >
      <div v-if="entregaSelecionada" class="modal-entrega-body">
        
        <div class="modal-winner-summary">
          <div class="winner-sm-info">
            <h4 class="font-outfit text-white fw-bold mb-1">{{ entregaSelecionada.servidor_nome }}</h4>
            <p class="text-muted small mb-0">{{ entregaSelecionada.secretaria_nome }} &bull; {{ entregaSelecionada.servidor_cpf }}</p>
          </div>
          <div class="prize-sm-badge">
            <i class="bi bi-gift-fill text-warning me-1"></i>
            <strong>{{ entregaSelecionada.premio_nome }}</strong>
          </div>
        </div>

        <div class="photo-capture-section">
          <label class="form-label font-outfit text-warning">
            <i class="bi bi-camera me-1"></i> Foto de Comprovação (Ganhador segurando o prêmio) *
          </label>

          <div class="capture-toggle-btns mb-2">
            <button
              type="button"
              :class="['btn-toggle-cap', { active: modoCaptura === 'camera' }]"
              @click="modoCaptura = 'camera'"
            >
              <i class="bi bi-webcam me-1"></i> Câmera ao Vivo
            </button>
            <button
              type="button"
              :class="['btn-toggle-cap', { active: modoCaptura === 'upload' }]"
              @click="modoCaptura = 'upload'"
            >
              <i class="bi bi-upload me-1"></i> Enviar Arquivo
            </button>
          </div>

          <!-- MODO 1: CÂMERA -->
          <div v-if="modoCaptura === 'camera'" class="camera-wrapper">
            <WebcamCapture @captured="onSelfieCaptured" />
          </div>

          <!-- MODO 2: UPLOAD ARQUIVO -->
          <div v-else class="upload-wrapper">
            <input type="file" accept="image/*" class="form-control" @change="onUploadFotoChange" />
            <div v-if="fotoComprovacaoBase64" class="preview-upload-box mt-2">
              <img :src="fotoComprovacaoBase64" alt="Preview" class="preview-img" />
            </div>
          </div>
        </div>

      </div>

      <template #footer>
        <button type="button" class="btn-secondary" @click="showModalEntrega = false">Cancelar</button>
        <button
          type="button"
          class="btn-primary font-outfit"
          :disabled="!fotoComprovacaoBase64 || enviando"
          @click="confirmarEntrega"
        >
          <span v-if="enviando">Gravando...</span>
          <span v-else><i class="bi bi-check-circle-fill me-1"></i> Confirmar Entrega Oficial</span>
        </button>
      </template>
    </Modal>

    <!-- MODAL ZOOM FOTO -->
    <Modal
      :show="showModalZoomFoto"
      title="Foto de Comprovação da Entrega"
      icon="bi-image-fill"
      @close="showModalZoomFoto = false"
    >
      <div class="zoom-photo-box text-center">
        <img :src="fotoZoomUrl" alt="Foto Ampliada" class="zoom-img" />
      </div>
    </Modal>

  </div>
</template>

<style scoped>
.entrega-premios-page { padding: 32px 0 60px; }
.page-header-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }
.page-title { font-size: 2rem; font-weight: 800; color: #ffffff; margin-bottom: 4px; }
.page-subtitle { color: var(--text-muted); font-size: 0.9rem; }
.btn-group-filters { display: flex; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; padding: 4px; gap: 4px; }
.btn-filter { background: transparent; border: none; color: var(--text-muted); font-weight: 700; font-size: 0.85rem; padding: 6px 14px; border-radius: 8px; cursor: pointer; transition: all 0.2s ease; }
.btn-filter.active { background: var(--primary-accent); color: #ffffff; }
.search-bar-row { width: 100%; }
.search-input-box { position: relative; width: 100%; }
.search-icon { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); color: var(--text-subtle); font-size: 1.1rem; }
.search-input { width: 100%; background: var(--bg-card); border: 1px solid var(--border-glass); border-radius: 14px; padding: 12px 16px 12px 46px; color: #ffffff; font-size: 0.95rem; outline: none; }
.search-input:focus { border-color: var(--primary-accent); }
.btn-clear { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); background: none; border: none; color: var(--text-muted); font-size: 1.2rem; cursor: pointer; }
.entregas-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; }
.entrega-card { padding: 22px; display: flex; flex-direction: column; justify-content: space-between; border-radius: 20px; transition: all 0.2s ease; }
.entrega-card.card-entregue { border-color: rgba(16, 185, 129, 0.35); background: rgba(16, 185, 129, 0.03); }
.entrega-card-header { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; position: relative; }
.servidor-avatar-box { width: 52px; height: 52px; border-radius: 14px; overflow: hidden; background: #000; border: 1px solid rgba(255, 255, 255, 0.2); flex-shrink: 0; }
.servidor-avatar { width: 100%; height: 100%; object-fit: cover; }
.avatar-ph { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: #64748b; font-size: 1.5rem; }
.servidor-meta { flex: 1; min-width: 0; }
.servidor-nome { font-size: 1.1rem; font-weight: 800; color: #ffffff; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.servidor-cpf { font-size: 0.75rem; color: var(--text-subtle); display: block; }
.servidor-sec { font-size: 0.75rem; color: #94a3b8; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status-chip { font-size: 0.72rem; font-weight: 800; padding: 4px 10px; border-radius: 999px; }
.chip-pendente { background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); color: #fbbf24; }
.chip-entregue { background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #34d399; }
.premio-highlight-box { background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 12px; display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.premio-thumb { width: 44px; height: 44px; border-radius: 8px; overflow: hidden; background: #000; flex-shrink: 0; border: 1px solid rgba(255, 255, 255, 0.15); }
.thumb-img { width: 100%; height: 100%; object-fit: cover; }
.thumb-ph { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: #fbbf24; }
.premio-tag { display: block; font-size: 0.68rem; color: #fbbf24; font-weight: 800; letter-spacing: 0.5px; }
.premio-nome { font-size: 1rem; color: #ffffff; display: block; }
.sorteio-data { font-size: 0.72rem; color: var(--text-subtle); display: block; }
.comprovacao-box { display: flex; justify-content: space-between; align-items: center; background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 12px; padding: 10px 12px; }
.comprovacao-info { font-size: 0.75rem; }
.comp-label { display: block; font-weight: 800; color: #34d399; margin-bottom: 2px; }
.comp-date, .comp-resp { display: block; color: var(--text-muted); }
.comprovacao-thumb { width: 48px; height: 48px; border-radius: 8px; overflow: hidden; position: relative; cursor: pointer; border: 1px solid rgba(255, 255, 255, 0.3); }
.zoom-hint { position: absolute; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 0.9rem; opacity: 0; transition: opacity 0.2s ease; }
.comprovacao-thumb:hover .zoom-hint { opacity: 1; }
.btn-registrar-entrega { width: 100%; background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); border: none; color: #000000; font-weight: 800; padding: 10px; border-radius: 10px; cursor: pointer; transition: transform 0.15s ease; display: inline-flex; align-items: center; justify-content: center; }
.btn-registrar-entrega:hover { transform: translateY(-1px); filter: brightness(1.1); }
.modal-winner-summary { background: rgba(255, 255, 255, 0.04); border-radius: 12px; padding: 14px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.prize-sm-badge { background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.3); color: #fbbf24; padding: 6px 12px; border-radius: 8px; font-size: 0.85rem; }
.capture-toggle-btns { display: flex; gap: 8px; }
.btn-toggle-cap { flex: 1; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); color: var(--text-muted); font-size: 0.85rem; font-weight: 700; padding: 8px; border-radius: 8px; cursor: pointer; }
.btn-toggle-cap.active { background: var(--primary-accent); color: #ffffff; }
.preview-upload-box { width: 120px; height: 120px; border-radius: 12px; overflow: hidden; border: 2px solid var(--primary-accent); }
.preview-img { width: 100%; height: 100%; object-fit: cover; }
.zoom-img { max-width: 100%; max-height: 70vh; border-radius: 12px; }
.empty-box { text-align: center; padding: 60px 20px; background: rgba(255, 255, 255, 0.02); border: 1px dashed rgba(255, 255, 255, 0.1); border-radius: 20px; }
.me-1 { margin-right: 4px; }
.mb-0 { margin-bottom: 0; }
.mb-1 { margin-bottom: 4px; }
.mb-2 { margin-bottom: 8px; }
.mb-4 { margin-bottom: 24px; }
.mt-2 { margin-top: 8px; }
.text-warning { color: var(--warning-color); }
.text-white { color: #ffffff; }
</style>