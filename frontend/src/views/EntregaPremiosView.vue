<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { Html5Qrcode } from 'html5-qrcode'
import Modal from '../components/Modal.vue'
import WebcamCapture from '../components/WebcamCapture.vue'

// ============================================================================
// ESTADOS GERAIS
// ============================================================================
const loading = ref(true)
const entregas = ref([])
const filtroStatus = ref('pendentes') // 'pendentes' | 'entregues' | 'todos'
const busca = ref('')

// Modo de Identificação do Posto: 'qrcode' | 'cpf'
const modoIdentificacao = ref('qrcode')
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
      { facingMode: 'environment' },
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
    console.warn('Erro ao ligar câmera do scanner QR:', err)
    cameraError.value = 'Permissão de câmera negada ou dispositivo indisponível.'
  }
}

async function stopQRScanner() {
  if (!qrScanner || !scannerActive.value) return
  try {
    await qrScanner.stop()
    scannerActive.value = false
  } catch (err) {
    console.error('Erro parando scanner:', err)
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
    console.error('Erro na validação do participante:', e)
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
    alert('A foto ao vivo do ganhador segurando o prêmio é obrigatória.')
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
      alert(d.detail || 'Erro ao registrar entrega.')
    }
  } catch (err) {
    console.error('Erro registrando entrega:', err)
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
    if (!silent) console.error('Erro ao carregar entregas:', e)
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
  <div class="entrega-premios-page">
    <div class="app-container">
      
      <!-- TOAST DE SUCESSO -->
      <div v-if="mensagemSucessoToast" class="toast-floating-success font-outfit">
        <i class="bi bi-check-circle-fill text-success fs-4 me-2"></i>
        <span>{{ mensagemSucessoToast }}</span>
      </div>

      <!-- HEADER DA PÁGINA -->
      <div class="page-header-row mb-4">
        <div>
          <span class="vip-badge bg-warning mb-2">
            <i class="bi bi-shield-check me-1"></i> Posto de Entrega Oficial
          </span>
          <h1 class="page-title font-outfit">Registro de Entrega de Prêmios</h1>
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
            
            <div v-if="cameraError" class="alert-camera-err font-outfit">
              <i class="bi bi-exclamation-triangle-fill me-1"></i> {{ cameraError }}
              <button type="button" class="btn-retry-cam" @click="startQRScanner">Tentar Novamente</button>
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
      <div class="section-sub-header mb-3">
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
          <h3 class="font-outfit text-white fw-bold mb-0">
            <i class="bi bi-gift-fill text-warning me-2"></i> Relação Geral de Premiações
          </h3>

          <div class="btn-group-filters font-outfit">
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
            placeholder="Filtrar por Nome do Servidor, CPF, Secretaria ou Prêmio..."
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
<style scoped>
.entrega-premios-page { padding: 32px 0 60px; }
.page-header-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }
.page-title { font-size: 2.2rem; font-weight: 800; color: #ffffff; margin-bottom: 4px; }
.page-subtitle { color: var(--text-muted); font-size: 0.95rem; }

/* TOAST FLUTUANTE */
.toast-floating-success {
  position: fixed;
  top: 24px;
  right: 24px;
  background: rgba(16, 185, 129, 0.95);
  backdrop-filter: blur(10px);
  color: #ffffff;
  padding: 16px 24px;
  border-radius: 14px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5), 0 0 20px rgba(16, 185, 129, 0.4);
  z-index: 9999;
  display: flex;
  align-items: center;
  font-weight: 700;
  animation: slideInToast 0.3s ease;
}
@keyframes slideInToast {
  from { transform: translateY(-30px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

/* TERMINAL DE VALIDAÇÃO POSTO DE ENTREGA */
.validation-terminal-card {
  background: rgba(15, 23, 42, 0.85);
  backdrop-filter: blur(20px);
  border: 2px solid rgba(56, 189, 248, 0.3);
  border-radius: 24px;
  padding: 28px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5), 0 0 30px rgba(56, 189, 248, 0.1);
}
.terminal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.terminal-title { font-size: 1.4rem; font-weight: 800; color: #ffffff; }
.terminal-desc { color: var(--text-muted); font-size: 0.85rem; }

.mode-pills-nav {
  display: flex;
  background: rgba(11, 15, 25, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  padding: 4px;
  gap: 6px;
}
.btn-mode-pill {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-weight: 700;
  font-size: 0.88rem;
  padding: 8px 18px;
  border-radius: 9px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-mode-pill.active {
  background: #0284c7;
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(2, 132, 199, 0.4);
}

/* SCANNER QR CODE */
.scanner-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px 0 10px;
}
.scanner-viewfinder {
  width: 100%;
  max-width: 380px;
  border-radius: 20px;
  overflow: hidden;
  border: 2px solid rgba(56, 189, 248, 0.4);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.6);
  background: #000;
}
.scanner-guide-text {
  margin-top: 14px;
  color: var(--text-muted);
  font-size: 0.88rem;
  text-align: center;
}
.alert-camera-err {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #f87171;
  padding: 10px 16px;
  border-radius: 10px;
  margin-top: 12px;
  font-size: 0.85rem;
}
.btn-retry-cam {
  background: transparent;
  border: 1px solid #f87171;
  color: #f87171;
  padding: 2px 8px;
  border-radius: 6px;
  margin-left: 8px;
  font-size: 0.78rem;
  cursor: pointer;
}

/* CPF WRAPPER */
.cpf-wrapper {
  padding: 24px 0 10px;
  max-width: 600px;
  margin: 0 auto;
}
.cpf-input-group {
  display: flex;
  gap: 12px;
  align-items: center;
}
.cpf-input-box {
  flex: 1;
  display: flex;
  align-items: center;
  background: rgba(11, 15, 25, 0.9);
  border: 2px solid rgba(255, 255, 255, 0.15);
  border-radius: 14px;
  transition: all 0.2s ease;
}
.cpf-input-box:focus-within {
  border-color: #38bdf8;
  box-shadow: 0 0 18px rgba(56, 189, 248, 0.25);
}
.input-cpf-terminal {
  width: 100%;
  background: transparent;
  border: none;
  color: #ffffff;
  font-size: 1.35rem;
  font-weight: 800;
  padding: 14px 16px;
  outline: none;
  letter-spacing: 1.5px;
}
.btn-validar-cpf {
  background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
  border: 1px solid rgba(56, 189, 248, 0.4);
  color: #ffffff;
  font-weight: 800;
  padding: 16px 24px;
  border-radius: 14px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}
.btn-validar-cpf:hover:not(:disabled) {
  transform: translateY(-2px);
  filter: brightness(1.1);
  box-shadow: 0 6px 20px rgba(2, 132, 199, 0.5);
}
.btn-validar-cpf:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.cpf-hint {
  text-align: center;
  color: var(--text-muted);
  font-size: 0.85rem;
  margin-top: 10px;
}

/* FEEDBACK CARDS */
.validation-alert-card {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  padding: 20px;
  border-radius: 18px;
  margin-top: 20px;
  animation: fadeIn 0.25s ease;
}
.alert-not-winner {
  background: rgba(239, 68, 68, 0.08);
  border: 2px solid rgba(239, 68, 68, 0.4);
}
.alert-already-delivered {
  background: rgba(245, 158, 11, 0.08);
  border: 2px solid rgba(245, 158, 11, 0.4);
}
.alert-not-found {
  background: rgba(255, 255, 255, 0.04);
  border: 1px dashed rgba(255, 255, 255, 0.2);
}
.alert-icon-box { flex-shrink: 0; padding-top: 4px; }
.alert-content { flex: 1; min-width: 0; }
.badge-status-tag {
  display: inline-block;
  font-size: 0.7rem;
  font-weight: 800;
  padding: 3px 10px;
  border-radius: 999px;
  margin-bottom: 6px;
}
.tag-danger { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }
.tag-warning { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
.tag-neutral { background: rgba(255, 255, 255, 0.1); color: #cbd5e1; }
.alert-title { font-size: 1.25rem; }
.alert-msg-box {
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 0.9rem;
}
.bg-danger-soft { background: rgba(239, 68, 68, 0.15); color: #fca5a5; }
.entregas-anteriores-list { display: flex; flex-direction: column; gap: 8px; }
.entrega-ant-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(0, 0, 0, 0.4);
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.thumb-foto-ant {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  object-fit: cover;
  border: 1px solid #fbbf24;
  cursor: pointer;
}
.btn-clear-alert {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #ffffff;
  padding: 10px 18px;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.85rem;
  cursor: pointer;
  white-space: nowrap;
}

/* MODAL VERIFICAÇÃO */
.winner-verification-card {
  background: rgba(11, 15, 25, 0.9);
  border: 2px solid #38bdf8;
  border-radius: 18px;
  padding: 16px 20px;
  box-shadow: 0 0 20px rgba(56, 189, 248, 0.2);
}
.official-selfie-box {
  position: relative;
  width: 84px;
  height: 84px;
  border-radius: 16px;
  overflow: hidden;
  border: 2px solid #38bdf8;
  background: #000;
  flex-shrink: 0;
}
.official-selfie-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.selfie-badge-tag {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(2, 132, 199, 0.9);
  color: #fff;
  font-size: 0.6rem;
  font-weight: 800;
  text-align: center;
  padding: 2px 0;
}
.winner-pill-tag {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 800;
  color: #34d399;
  letter-spacing: 0.5px;
}
.winner-name-title { font-size: 1.3rem; margin: 0; }
.winner-sub-info { font-size: 0.85rem; }

.prize-badge-card {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 14px;
  padding: 14px 18px;
}
.prize-photo-box {
  width: 58px;
  height: 58px;
  border-radius: 10px;
  overflow: hidden;
  background: #050811;
  border: 1px solid rgba(255, 255, 255, 0.2);
  flex-shrink: 0;
}
.prize-img { width: 100%; height: 100%; object-fit: cover; }
.prize-cat-pill {
  font-size: 0.68rem;
  font-weight: 800;
  color: #f59e0b;
  display: block;
}
.prize-title-name { font-size: 1.15rem; }

.camera-step-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.live-only-tag {
  font-size: 0.72rem;
  font-weight: 800;
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  padding: 3px 10px;
  border-radius: 999px;
}

/* CARDS LISTAGEM */
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
.zoom-img { max-width: 100%; max-height: 70vh; border-radius: 12px; }
.empty-box { text-align: center; padding: 60px 20px; background: rgba(255, 255, 255, 0.02); border: 1px dashed rgba(255, 255, 255, 0.1); border-radius: 20px; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.mb-0 { margin-bottom: 0; }
.mb-1 { margin-bottom: 4px; }
.mb-2 { margin-bottom: 8px; }
.mb-3 { margin-bottom: 16px; }
.mb-4 { margin-bottom: 24px; }
.mb-5 { margin-bottom: 36px; }
.mt-2 { margin-top: 8px; }
.mt-3 { margin-top: 16px; }
.text-cyan { color: #38bdf8 !important; }
.text-warning { color: var(--warning-color); }
.text-white { color: #ffffff; }
.flex-1 { flex: 1; }
</style>