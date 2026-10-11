<script setup>
import { useToast } from '../composables/useToast'
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { Html5Qrcode } from 'html5-qrcode'
import Modal from '../components/Modal.vue'
import WebcamCapture from '../components/WebcamCapture.vue'

const { toast } = useToast()

// ============================================================================
// ESTADOS GERAIS
// ============================================================================
const loading = ref(true)
const entregas = ref([])
const filtroStatus = ref('pendentes') // 'pendentes' | 'entregues' | 'todos'
const busca = ref('')

// Modo de Identificação do Posto: 'qrcode' | 'cpf'
const modoIdentificacao = ref('qrcode')
const currentQrFacingMode = ref('environment')
const cpfBusca = ref('')
const validando = ref(false)
const scannerActive = ref(false)
const cameraError = ref(null)

// Resultado da Validação Prévia
const statusValidacao = ref(null) // null | 'nao_encontrado' | 'nao_ganhador' | 'ja_entregue'
const feedbackValidacao = ref(null)

// Modal de Entrega Oficial com Foto ao Vivo
const showModalEntrega = ref(false)
const showModalZoomFoto = ref(false)
const ganhadorValidado = ref(null)
const fotoZoomUrl = ref('')
const fotoComprovacaoBase64 = ref('')
const enviando = ref(false)
const mensagemSucessoToast = ref(null)

let qrScanner = null
let isProcessingScanner = false

// Formatação do CPF
function formatCPF(val) {
  if (!val) return ''
  const digits = val.replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 3) return digits
  if (digits.length <= 6) return `${digits.slice(0, 3)}.${digits.slice(3)}`
  if (digits.length <= 9) return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6)}`
  return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`
}

function onCpfInput(e) {
  cpfBusca.value = formatCPF(e.target.value)
  const digits = cpfBusca.value.replace(/\D/g, '')
  if (digits.length === 11 && !validando.value) {
    executarValidacao(digits)
  }
}
// ============================================================================
// SCANNER QR CODE COM HTML5-QRCODE
// ============================================================================
async function startQRScanner() {
  if (scannerActive.value) return
  cameraError.value = null

  try {
    const devices = await Html5Qrcode.getCameras()
    if (!devices || !devices.length) {
      cameraError.value = 'Nenhuma câmera encontrada no dispositivo.'
      return
    }

    if (!qrScanner) {
      qrScanner = new Html5Qrcode('qr-reader-entrega')
    }

    await qrScanner.start(
      { facingMode: currentQrFacingMode.value },
      {
        fps: 20,
        aspectRatio: 1.0,
        qrbox: (w, h) => {
          const edge = Math.floor(Math.min(w, h) * 0.75)
          return { width: edge, height: edge }
        }
      },
      (decodedText) => {
        if (!isProcessingScanner && decodedText) {
          executarValidacao(decodedText)
        }
      },
      () => {}
    )
    scannerActive.value = true
  } catch (err) {
    // Falha ao ligar câmera do scanner QR
    cameraError.value = 'Permissão de câmera negada ou dispositivo indisponível.'
  }
}

async function stopQRScanner() {
  if (!qrScanner || !scannerActive.value) return
  try {
    await qrScanner.stop()
    scannerActive.value = false
  } catch (err) {
    // Falha ao parar scanner
  }
}

watch(modoIdentificacao, async (novoModo) => {
  statusValidacao.value = null
  feedbackValidacao.value = null
  if (novoModo === 'qrcode') {
    await nextTick()
    await startQRScanner()
  } else {
    await stopQRScanner()
  }
})

// ============================================================================
// VALIDAÇÃO PRÉVIA DO GANHADOR (BACKEND)
// ============================================================================
async function executarValidacao(identificador) {
  if (!identificador || !identificador.trim() || validando.value) return
  validando.value = true
  isProcessingScanner = true
  statusValidacao.value = null
  feedbackValidacao.value = null

  try {
    const res = await fetch('/api/sorteios/validar-ganhador-entrega', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ identificador: identificador.trim() })
    })

    const data = await res.json()

    if (!res.ok) {
      statusValidacao.value = 'nao_encontrado'
      feedbackValidacao.value = { mensagem: data.mensagem || 'Participante não localizado no sistema.' }
      await stopQRScanner()
      return
    }

    if (data.sucesso && data.status === 'pendente') {
      ganhadorValidado.value = data
      fotoComprovacaoBase64.value = ''
      showModalEntrega.value = true
      await stopQRScanner()
    } else if (data.status === 'ja_entregue') {
      statusValidacao.value = 'ja_entregue'
      feedbackValidacao.value = data
      await stopQRScanner()
    } else if (data.status === 'nao_ganhador') {
      statusValidacao.value = 'nao_ganhador'
      feedbackValidacao.value = data
      await stopQRScanner()
    }
  } catch (e) {
    toast.error('Erro na validação do participante.')
    statusValidacao.value = 'nao_encontrado'
    feedbackValidacao.value = { mensagem: 'Falha de comunicação com o servidor.' }
  } finally {
    validando.value = false
    setTimeout(() => {
      isProcessingScanner = false
    }, 1500)
  }
}

function resetarValidacao() {
  statusValidacao.value = null
  feedbackValidacao.value = null
  cpfBusca.value = ''
  if (modoIdentificacao.value === 'qrcode') {
    startQRScanner()
  }
}

function abrirModalEntregaDireto(item) {
  ganhadorValidado.value = {
    ganhador_id: item.id,
    servidor: {
      nome: item.servidor_nome,
      cpf: item.servidor_cpf,
      secretaria: item.secretaria_nome,
      setor: item.setor,
      telefone: item.telefone,
      foto_rosto: item.servidor_foto
    },
    premio: {
      nome: item.premio_nome,
      foto: item.premio_foto,
      categoria: item.categoria === 'categoria_1' ? 'Categoria 1 (Geral)' : 'Categoria 2 (Eixo)'
    }
  }
  fotoComprovacaoBase64.value = ''
  showModalEntrega.value = true
}

async function confirmarEntrega() {
  if (!fotoComprovacaoBase64.value) {
    toast.warning('A foto ao vivo do ganhador segurando o prêmio é obrigatória.')
    return
  }

  enviando.value = true
  try {
    const formData = new FormData()
    formData.append('foto_base64', fotoComprovacaoBase64.value)

    const res = await fetch('/api/sorteios/registrar-entrega/' + ganhadorValidado.value.ganhador_id, {
      method: 'POST',
      body: formData
    })

    if (res.ok) {
      showModalEntrega.value = false
      mensagemSucessoToast.value = `Entrega de "${ganhadorValidado.value.premio.nome}" registrada com sucesso para ${ganhadorValidado.value.servidor.nome}!`
      setTimeout(() => {
        mensagemSucessoToast.value = null
      }, 5000)
      resetarValidacao()
      await carregarEntregas()
    } else {
      const d = await res.json()
      toast.error(d.detail || 'Erro ao registrar entrega.')
    }
  } catch (err) {
    // Erro registrando entrega
  } finally {
    enviando.value = false
  }
}

function fecharModalEntrega() {
  showModalEntrega.value = false
  resetarValidacao()
}

async function carregarEntregas(silent = false) {
  try {
    if (!silent) loading.value = true
    const res = await fetch('/api/sorteios/entregas-pendentes')
    if (res.ok) {
      const data = await res.json()
      entregas.value = data.entregas || []
    }
  } catch (e) {
    if (!silent) toast.error('Erro ao carregar entregas.')
  } finally {
    if (!silent) loading.value = false
  }
}

const entregasFiltradas = computed(() => {
  return entregas.value.filter(item => {
    if (filtroStatus.value === 'pendentes' && item.entregue) return false
    if (filtroStatus.value === 'entregues' && !item.entregue) return false

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

function abrirZoomFoto(url) {
  fotoZoomUrl.value = url
  showModalZoomFoto.value = true
}

onMounted(async () => {
  await carregarEntregas()
  if (modoIdentificacao.value === 'qrcode') {
    await nextTick()
    await startQRScanner()
  }
})

onUnmounted(async () => {
  await stopQRScanner()
})
</script>

<template>
  <div class="admin-page">
    <div class="app-container">
      
      <!-- TOAST DE SUCESSO -->
      <div v-if="mensagemSucessoToast" class="toast-floating-success font-outfit">
        <i class="bi bi-check-circle-fill text-success fs-4 me-2"></i>
        <span>{{ mensagemSucessoToast }}</span>
      </div>

      <!-- HEADER DA PÁGINA -->
      <div class="admin-header-row mb-4">
        <div>
          <span class="admin-eyebrow">
            <i class="bi bi-shield-check me-1"></i> Posto de Entrega Oficial
          </span>
          <h1 class="page-title font-quattrocento">Registro de Entrega de Prêmios</h1>
          <p class="page-subtitle">Validação biométrica e fotográfica dos contemplados no evento.</p>
        </div>
      </div>

      <!-- PAINEL SUPERIOR: POSTO DE VALIDAÇÃO DE GANHADOR -->
      <div class="vip-glass-card validation-terminal-card mb-5">
        <div class="terminal-header">
          <div class="d-flex align-items-center gap-2">
            <i class="bi bi-qr-code-scan text-cyan fs-4"></i>
            <div>
              <h2 class="terminal-title font-outfit mb-0">Identificação & Validação do Ganhador</h2>
              <span class="terminal-desc">Escaneie o ingresso ou digite o CPF para consultar se a pessoa tem prêmio a retirar.</span>
            </div>
          </div>

          <!-- SELETOR DE MODO DE ENTRADA -->
          <div class="mode-pills-nav font-outfit">
            <button
              type="button"
              :class="['btn-mode-pill', { active: modoIdentificacao === 'qrcode' }]"
              @click="modoIdentificacao = 'qrcode'"
            >
              <i class="bi bi-camera-fill me-1"></i> Escanear Ingresso (QR Code)
            </button>
            <button
              type="button"
              :class="['btn-mode-pill', { active: modoIdentificacao === 'cpf' }]"
              @click="modoIdentificacao = 'cpf'"
            >
              <i class="bi bi-person-vcard-fill me-1"></i> Digitar CPF
            </button>
          </div>
        </div>

        <div class="terminal-body mt-3">
          
          <!-- MODO 1: SCANNER QR CODE -->
          <div v-show="modoIdentificacao === 'qrcode'" class="scanner-wrapper">
            <div id="qr-reader-entrega" class="scanner-viewfinder"></div>

            <div v-if="scannerActive" class="text-center my-2">
              <button
                type="button"
                class="btn btn-secondary-sm"
                title="Alternar entre câmera traseira e frontal"
                @click="toggleQrCamera"
              >
                <i class="bi bi-camera-reverse me-1 text-cyan"></i>
                {{ currentQrFacingMode === 'environment' ? 'Usar Câmera Frontal' : 'Usar Câmera Traseira' }}
              </button>
            </div>
            
            <div v-if="cameraError" class="alert-camera-err font-outfit">
              <i class="bi bi-camera-video-off me-1 fs-5"></i>
              <span>{{ cameraError }}</span>
              <button type="button" class="btn-retry-cam ms-auto" @click="startQRScanner">Solicitar Permissão</button>
            </div>

            <p class="scanner-guide-text font-outfit">
              <i class="bi bi-upc-scan text-cyan me-1"></i> Aponte a câmera para o QR Code no ingresso impresso ou na tela do celular do participante.
            </p>
          </div>

          <!-- MODO 2: DIGITAR CPF -->
          <div v-show="modoIdentificacao === 'cpf'" class="cpf-wrapper">
            <div class="cpf-input-group">
              <div class="cpf-input-box">
                <i class="bi bi-person-badge text-muted fs-4 ms-3"></i>
                <input
                  :value="cpfBusca"
                  type="text"
                  class="input-cpf-terminal font-outfit"
                  placeholder="000.000.000-00"
                  maxlength="14"
                  @input="onCpfInput"
                  @keyup.enter="executarValidacao(cpfBusca.replace(/\D/g, ''))"
                />
              </div>
              <button
                type="button"
                class="btn-validar-cpf font-outfit"
                :disabled="validando || cpfBusca.replace(/\D/g, '').length !== 11"
                @click="executarValidacao(cpfBusca.replace(/\D/g, ''))"
              >
                <span v-if="validando"><i class="spinner-border spinner-border-sm me-1"></i> Validando...</span>
                <span v-else><i class="bi bi-search me-1"></i> Validar Ganhador</span>
              </button>
            </div>
            <p class="cpf-hint font-outfit">Digite os 11 dígitos do CPF do participante para validar no sistema.</p>
          </div>

          <!-- FEEDBACK: NÃO É GANHADOR -->
          <div v-if="statusValidacao === 'nao_ganhador'" class="validation-alert-card alert-not-winner font-outfit">
            <div class="alert-icon-box text-danger">
              <i class="bi bi-x-circle-fill fs-1"></i>
            </div>
            <div class="alert-content">
              <span class="badge-status-tag tag-danger">NÃO CONTEMPLADO</span>
              <h3 class="alert-title text-white fw-bold mb-1">{{ feedbackValidacao.servidor.nome }}</h3>
              <p class="alert-meta text-muted mb-2">{{ feedbackValidacao.servidor.secretaria }} &bull; CPF: {{ feedbackValidacao.servidor.cpf }}</p>
              <div class="alert-msg-box bg-danger-soft">
                <i class="bi bi-info-circle me-1"></i> Este participante <strong>NÃO foi sorteado</strong> em nenhum prêmio do evento.
              </div>
            </div>
            <button type="button" class="btn-clear-alert" @click="resetarValidacao">
              <i class="bi bi-arrow-repeat me-1"></i> Novo Atendimento
            </button>
          </div>

          <!-- FEEDBACK: PRÊMIO JÁ ENTREGUE ANTERIORMENTE -->
          <div v-if="statusValidacao === 'ja_entregue'" class="validation-alert-card alert-already-delivered font-outfit">
            <div class="alert-icon-box text-warning">
              <i class="bi bi-exclamation-triangle-fill fs-1"></i>
            </div>
            <div class="alert-content">
              <span class="badge-status-tag tag-warning">PRÊMIO JÁ ENTREGUE ANTERIORMENTE</span>
              <h3 class="alert-title text-white fw-bold mb-1">{{ feedbackValidacao.servidor.nome }}</h3>
              <p class="alert-meta text-muted mb-2">CPF: {{ feedbackValidacao.servidor.cpf }} &bull; {{ feedbackValidacao.servidor.secretaria }}</p>
              
              <div class="entregas-anteriores-list mt-2">
                <div v-for="(e, idx) in feedbackValidacao.entregas" :key="idx" class="entrega-ant-item">
                  <div>
                    <strong class="text-warning d-block">{{ e.premio_nome }}</strong>
                    <span class="small text-muted">Retirado em {{ e.data_entrega }} (Responsável: {{ e.responsavel }})</span>
                  </div>
                  <img
                    v-if="e.foto_entrega_url"
                    :src="e.foto_entrega_url"
                    alt="Foto anterior"
                    class="thumb-foto-ant"
                    @click="abrirZoomFoto(e.foto_entrega_url)"
                  />
                </div>
              </div>
            </div>
            <button type="button" class="btn-clear-alert" @click="resetarValidacao">
              <i class="bi bi-arrow-repeat me-1"></i> Novo Atendimento
            </button>
          </div>

          <!-- FEEDBACK: NÃO LOCALIZADO -->
          <div v-if="statusValidacao === 'nao_encontrado'" class="validation-alert-card alert-not-found font-outfit">
            <div class="alert-icon-box text-subtle">
              <i class="bi bi-search fs-1"></i>
            </div>
            <div class="alert-content">
              <span class="badge-status-tag tag-neutral">NÃO LOCALIZADO</span>
              <h4 class="text-white fw-bold mb-1">Participante ou Ingresso Não Encontrado</h4>
              <p class="text-muted small mb-0">{{ feedbackValidacao.mensagem }}</p>
            </div>
            <button type="button" class="btn-clear-alert" @click="resetarValidacao">
              <i class="bi bi-arrow-repeat me-1"></i> Tentar Novamente
            </button>
          </div>

        </div>
      </div>

      <!-- PAINEL INFERIOR: HISTÓRICO DE ENTREGAS -->
      <div class="admin-header-row mt-5 mb-3">
        <div>
          <h2 class="section-title font-quattrocento mb-1">
            <i class="bi bi-gift-fill text-warning me-2"></i> Relação Geral de Premiações
          </h2>
          <p class="admin-subtitle mb-0">Relação completa de servidores contemplados e registro de entregas.</p>
        </div>
      </div>

      <!-- Filtros e Barra de Busca Canônicos -->
      <div class="filter-card mb-4">
        <div class="filter-grid filter-grid--search-two">
          <div class="search-box">
            <i class="bi bi-search search-icon"></i>
            <input
              v-model="busca"
              type="text"
              class="form-control"
              placeholder="Filtrar por Nome do Servidor, CPF, Secretaria ou Prêmio..."
            />
          </div>

          <div class="d-flex align-items-center justify-content-end gap-1">
            <button
              type="button"
              class="btn btn-sm"
              :class="filtroStatus === 'pendentes' ? 'btn-primary' : 'btn-secondary'"
              @click="filtroStatus = 'pendentes'"
            >
              Pendentes
            </button>
            <button
              type="button"
              class="btn btn-sm"
              :class="filtroStatus === 'entregues' ? 'btn-primary' : 'btn-secondary'"
              @click="filtroStatus = 'entregues'"
            >
              Entregues
            </button>
            <button
              type="button"
              class="btn btn-sm"
              :class="filtroStatus === 'todos' ? 'btn-primary' : 'btn-secondary'"
              @click="filtroStatus = 'todos'"
            >
              Todos
            </button>
          </div>
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
                <span class="premio-tag font-outfit">{{ item.categoria === 'categoria_1' ? 'CATEGORIA GERAL' : 'EIXO SETORIAL' }}</span>
                <strong class="premio-nome font-outfit">{{ item.premio_nome }}</strong>
                <span class="sorteio-data">Sorteado em: {{ item.data_sorteio }}</span>
              </div>
            </div>

            <!-- Dados da Entrega Já Realizada -->
            <div v-if="item.entregue" class="comprovacao-box">
              <div class="comprovacao-info">
                <span class="comp-label font-outfit">Comprovação Oficial de Entrega:</span>
                <span class="comp-date"><i class="bi bi-calendar-check me-1"></i>{{ item.data_entrega }}</span>
                <span v-if="item.responsavel_entrega" class="comp-resp">Por: {{ item.responsavel_entrega }}</span>
              </div>
              <div
                v-if="item.foto_entrega_url"
                class="comprovacao-thumb"
                title="Clique para ampliar foto da entrega"
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
                @click="abrirModalEntregaDireto(item)"
              >
                <i class="bi bi-camera-fill me-1"></i> Registrar Entrega com Foto ao Vivo
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

    <!-- MODAL OFICIAL DE REGISTRO DE ENTREGA COM FOTO AO VIVO -->
    <Modal
      :show="showModalEntrega"
      title="Registrar Entrega Oficial de Prêmio"
      icon="bi-shield-check"
      icon-color="text-success"
      @close="fecharModalEntrega"
    >
      <div v-if="ganhadorValidado" class="modal-entrega-body">
        
        <!-- BLOCO 1: CONFERÊNCIA DE IDENTIDADE (SELFIE ORIGINAL DO CADASTRO) -->
        <div class="winner-verification-card mb-3">
          <div class="d-flex align-items-center gap-3">
            <div class="official-selfie-box">
              <img
                v-if="ganhadorValidado.servidor.foto_rosto"
                :src="ganhadorValidado.servidor.foto_rosto"
                alt="Selfie do Cadastro"
                class="official-selfie-img"
              />
              <div v-else class="avatar-ph"><i class="bi bi-person-fill fs-2"></i></div>
              <span class="selfie-badge-tag font-outfit">Foto do Ingresso</span>
            </div>

            <div class="winner-details-box flex-1">
              <span class="winner-pill-tag font-outfit mb-1">
                <i class="bi bi-check-circle-fill text-success me-1"></i> GANHADOR LEGÍTIMO VALIDADO
              </span>
              <h3 class="winner-name-title font-outfit text-white fw-bold mb-1">
                {{ ganhadorValidado.servidor.nome }}
              </h3>
              <p class="winner-sub-info font-outfit text-muted mb-0">
                CPF: <strong class="text-white">{{ ganhadorValidado.servidor.cpf }}</strong> &bull; {{ ganhadorValidado.servidor.secretaria }}
              </p>
              <span v-if="ganhadorValidado.servidor.setor" class="winner-setor font-outfit text-subtle small d-block">
                Setor: {{ ganhadorValidado.servidor.setor }}
              </span>
            </div>
          </div>
        </div>

        <!-- BLOCO 2: PRÊMIO CONQUISTADO -->
        <div class="prize-badge-card mb-3">
          <div class="d-flex align-items-center gap-3">
            <div class="prize-photo-box">
              <img v-if="ganhadorValidado.premio.foto" :src="ganhadorValidado.premio.foto" alt="Prêmio" class="prize-img" />
              <div v-else class="thumb-ph"><i class="bi bi-gift-fill text-warning fs-3"></i></div>
            </div>
            <div>
              <span class="prize-cat-pill font-outfit">{{ ganhadorValidado.premio.categoria || 'Prêmio Oficial' }}</span>
              <h4 class="prize-title-name font-outfit text-warning fw-bold mb-0">
                {{ ganhadorValidado.premio.nome }}
              </h4>
            </div>
          </div>
        </div>

        <!-- BLOCO 3: FOTO AO VIVO OBRIGATÓRIA (SEM ANEXO DE ARQUIVO) -->
        <div class="photo-capture-section">
          <div class="camera-step-header mb-2">
            <label class="form-label font-outfit text-white fw-bold mb-0">
              <i class="bi bi-camera-fill text-warning me-1"></i> Foto de Comprovação: Ganhador Segurando o Prêmio *
            </label>
            <span class="live-only-tag font-outfit">
              <i class="bi bi-broadcast me-1"></i> Câmera ao Vivo Obrigatória
            </span>
          </div>

          <!-- CÂMERA AO VIVO -->
          <div class="camera-wrapper">
            <WebcamCapture v-model="fotoComprovacaoBase64" />
          </div>
        </div>

      </div>

      <template #footer>
        <button type="button" class="btn-secondary font-outfit" @click="fecharModalEntrega">Cancelar</button>
        <button
          type="button"
          class="btn-primary font-outfit"
          :disabled="!fotoComprovacaoBase64 || enviando"
          @click="confirmarEntrega"
        >
          <span v-if="enviando"><i class="spinner-border spinner-border-sm me-1"></i> Gravando Entrega Oficial...</span>
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
