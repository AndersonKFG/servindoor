<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import { Html5Qrcode } from 'html5-qrcode'

const router = useRouter()
const { toast } = useToast()
const currentFacingMode = ref('environment')
const cameraPermissaoErro = ref(false)

// Estados
const cpfInput = ref('')
const loading = ref(false)
const participante = ref(null)
const mensagemErro = ref(null)
const mensagemSucesso = ref(null)
const scannerActive = ref(false)
const alterandoStatus = ref(false)
const cpfInputRef = ref(null)

let qrScanner = null
let isProcessing = false

// Formatação do CPF para exibição limpa
function formatarCpfExibicao(cpf) {
  if (!cpf) return ''
  const c = cpf.replace(/\D/g, '').padStart(11, '0')
  return `${c.slice(0, 3)}.${c.slice(3, 6)}.${c.slice(6, 9)}-${c.slice(9, 11)}`
}

// Busca participante por QR Code Token ou CPF de 11 dígitos
async function buscarParticipante(identificador) {
  if (!identificador || !identificador.trim() || isProcessing) return
  isProcessing = true
  loading.value = true
  mensagemErro.value = null
  mensagemSucesso.value = null

  try {
    const res = await fetch('/api/portaria/buscar', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({ identificador: identificador.trim() })
    })

    if (res.status === 401) {
      router.push('/login')
      return
    }

    const data = await res.json()

    if (res.status === 403 && data.cancelado) {
      mensagemErro.value = data.mensagem || 'Ingresso CANCELADO. Entrada não permitida!'
      setTimeout(() => {
        isProcessing = false
      }, 3000)
      return
    }

    if (res.status === 403 && !data.cancelado) {
      mensagemErro.value = data.mensagem || data.detail || 'Acesso negado para esta operação.'
      setTimeout(() => {
        isProcessing = false
      }, 2000)
      return
    }

    if (!res.ok || !data.sucesso) {
      mensagemErro.value = data.mensagem || 'Participante não encontrado.'
      setTimeout(() => {
        isProcessing = false
      }, 1500)
      return
    }

    participante.value = data
    // Pausa a câmera enquanto a decisão está na tela
    await stopQRScanner()
  } catch (err) {
    console.error('Erro ao buscar participante:', err)
    mensagemErro.value = 'Falha de comunicação com o servidor.'
    setTimeout(() => {
      isProcessing = false
    }, 1500)
  } finally {
    loading.value = false
  }
}

// Alternar status (se dentro -> marca saida; se fora -> marca entrada)
async function alternarStatus() {
  if (!participante.value || alterandoStatus.value) return
  alterandoStatus.value = true
  mensagemErro.value = null

  const novoStatus = participante.value.status === 'dentro' ? 'saida' : 'entrada'

  try {
    const res = await fetch('/api/portaria/alterar-status', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({
        usuario_id: participante.value.usuario_id,
        novo_status: novoStatus
      })
    })

    if (res.status === 401) {
      router.push('/login')
      return
    }

    const data = await res.json()

    if (!res.ok || !data.sucesso) {
      mensagemErro.value = data.detail || data.mensagem || 'Erro ao alterar status.'
      alterandoStatus.value = false
      return
    }

    participante.value.status = data.status
    mensagemSucesso.value = data.mensagem
    const msgToast = novoStatus === 'saida' ? 'Saída registrada' : 'Entrada registrada'
    toast.success(msgToast, 'Portaria', 3000)

    // Retorna automaticamente para o scanner após 1.2 segundos
    setTimeout(() => {
      resetarPortaria()
    }, 1200)
  } catch (err) {
    console.error('Erro alterando status:', err)
    mensagemErro.value = 'Erro de conexão ao salvar movimentação.'
    alterandoStatus.value = false
  }
}

// Resetar para novo escaneamento
async function resetarPortaria() {
  participante.value = null
  mensagemErro.value = null
  mensagemSucesso.value = null
  cpfInput.value = ''
  alterandoStatus.value = false
  isProcessing = false

  await nextTick()
  await startQRScanner()
  if (cpfInputRef.value) {
    cpfInputRef.value.focus()
  }
}

// Monitora digitação do CPF: ao atingir 11 números, busca na hora
watch(cpfInput, (novoValor) => {
  const numeros = novoValor.replace(/\D/g, '')
  if (numeros.length === 11 && !participante.value && !loading.value) {
    buscarParticipante(numeros)
  }
})

// Inicialização da Câmera contínua com enquadramento perfeito
async function startQRScanner() {
  if (scannerActive.value) return
  cameraPermissaoErro.value = false

  try {
    const devices = await Html5Qrcode.getCameras()
    if (!devices || !devices.length) {
      console.warn('Nenhuma câmera encontrada no dispositivo.')
      cameraPermissaoErro.value = true
      return
    }

    if (!qrScanner) {
      qrScanner = new Html5Qrcode('qr-reader-container')
    }

    await qrScanner.start(
      { facingMode: currentFacingMode.value },
      {
        fps: 20,
        aspectRatio: 1.0,
        qrbox: (viewfinderWidth, viewfinderHeight) => {
          const edge = Math.floor(Math.min(viewfinderWidth, viewfinderHeight) * 0.75)
          return { width: edge, height: edge }
        }
      },
      (decodedText) => {
        if (!isProcessing && decodedText) {
          buscarParticipante(decodedText)
        }
      },
      () => {}
    )
    scannerActive.value = true
  } catch (err) {
    console.warn('Câmera não pôde ser iniciada:', err)
    cameraPermissaoErro.value = true
    scannerActive.value = false
  }
}

async function toggleCamera() {
  currentFacingMode.value = currentFacingMode.value === 'environment' ? 'user' : 'environment'
  await stopQRScanner()
  await startQRScanner()
}

async function stopQRScanner() {
  if (qrScanner && scannerActive.value) {
    try {
      await qrScanner.stop()
      qrScanner.clear()
    } catch (e) {
      console.warn('Erro ao pausar scanner:', e)
    }
    scannerActive.value = false
  }
}

onMounted(() => {
  startQRScanner()
})

onUnmounted(() => {
  stopQRScanner()
})
</script>


<template>
  <div class="portaria-page">
    <div class="app-container">
      <div class="portaria-wrapper">

        <!-- CABEÇALHO COMPACTO -->
        <header class="portaria-header">
          <div class="badge-role">
            <i class="bi bi-shield-check me-1"></i> PORTARIA & CONTROLE DE ACESSO
          </div>
          <h1 class="portaria-title font-quattrocento">Presença no Evento</h1>
        </header>

        <!-- ALERTA DE ERRO TEMPORÁRIO -->
        <div v-if="mensagemErro" class="alert-box error-alert animate-bounce">
          <i class="bi bi-exclamation-triangle-fill fs-4 me-2"></i>
          <div>
            <strong>Atenção:</strong>
            <p class="m-0">{{ mensagemErro }}</p>
          </div>
          <button type="button" class="btn-close-alert" @click="mensagemErro = null">
            <i class="bi bi-x"></i>
          </button>
        </div>

        <!-- ALERTA DE SUCESSO TEMPORÁRIO -->
        <div v-if="mensagemSucesso" class="alert-box success-alert animate-bounce">
          <i class="bi bi-check-circle-fill fs-4 me-2"></i>
          <div>
            <strong>Sucesso:</strong>
            <p class="m-0">{{ mensagemSucesso }}</p>
          </div>
        </div>

        <!-- ============================================== -->
        <!-- TELA 1: SCANNER CONTÍNUO E INPUT DE CPF       -->
        <!-- ============================================== -->
        <div v-show="!participante" class="scanner-section">
          
          <!-- Card do Scanner com Viewport Centralizado -->
          <div class="scanner-card">
            
            <div class="scanner-viewport-wrapper">
              <div id="qr-reader-container" class="qr-viewport"></div>
              
              <!-- Retículo Visual Perfeitamente Centralizado -->
              <div class="scanner-overlay">
                <div class="scanner-target-box">
                  <div class="corner corner-tl"></div>
                  <div class="corner corner-tr"></div>
                  <div class="corner corner-bl"></div>
                  <div class="corner corner-br"></div>
                  <div class="scan-laser-bar"></div>
                </div>
              </div>

              <!-- Fallback quando câmera em espera -->
              <div v-if="!scannerActive" class="scanner-fallback">
                <i class="bi bi-camera-fill fs-1 text-muted"></i>
                <p class="mt-2 mb-3 text-muted">Câmera em espera ou sem permissão</p>
                <button type="button" class="btn-action btn-sm" @click="startQRScanner">
                  <i class="bi bi-camera-video-fill me-1"></i> Ligar Câmera
                </button>
              </div>
            </div>

            <div v-if="scannerActive" class="text-center mt-2">
              <button
                type="button"
                class="btn btn-secondary-sm"
                :title="currentFacingMode === 'environment' ? 'Alternar para a câmera frontal' : 'Alternar para a câmera traseira'"
                @click="toggleCamera"
              >
                <i class="bi bi-camera-reverse me-1 text-cyan"></i>
                {{ currentFacingMode === 'environment' ? 'Usar Câmera Frontal' : 'Usar Câmera Traseira' }}
              </button>
            </div>
            
            <p class="scanner-hint">
              <i class="bi bi-qr-code-scan me-1 text-primary"></i> Aponte a câmera para o QR Code do ingresso
            </p>
          </div>

          <!-- Divisor Visual -->
          <div class="or-separator">
            <span>OU</span>
          </div>

          <!-- Caixa de Entrada de CPF Numérico -->
          <div class="cpf-card">
            <label class="cpf-label" for="cpf-portaria">
              <i class="bi bi-person-badge me-1 text-primary"></i> Digite o CPF do Servidor
            </label>
            <div class="cpf-input-group">
              <i class="bi bi-search search-icon"></i>
              <input
                id="cpf-portaria"
                ref="cpfInputRef"
                v-model="cpfInput"
                type="tel"
                inputmode="numeric"
                pattern="[0-9]*"
                maxlength="11"
                placeholder="000.000.000-00 (11 números)"
                class="cpf-input"
                autocomplete="off"
                :disabled="loading"
              />
              <span v-if="cpfInput.length > 0" class="cpf-counter" :class="{ 'ready': cpfInput.length === 11 }">
                {{ cpfInput.length }}/11
              </span>
            </div>
            <p class="cpf-subtext">
              A busca acontece automaticamente assim que você digitar os 11 dígitos.
            </p>
          </div>

          <!-- Loading Overlay -->
          <div v-if="loading" class="loading-state">
            <div class="spinner-border text-primary"></div>
            <span>Buscando participante...</span>
          </div>

        </div>

        <!-- ============================================== -->
        <!-- TELA 2: DECISÃO RÁPIDA - STATUS DENTRO / FORA -->
        <!-- ============================================== -->
        <div v-if="participante" class="decision-section animate-scale-up">
          
          <div class="participant-card" :class="participante.status === 'dentro' ? 'card-inside' : 'card-outside'">
            
            <!-- 1. STATUS GIGANTE E CLARO -->
            <div class="status-banner" :class="participante.status === 'dentro' ? 'banner-inside' : 'banner-outside'">
              <i :class="participante.status === 'dentro' ? 'bi bi-check-circle-fill' : 'bi bi-geo-alt-fill'"></i>
              <span class="status-title">
                {{ participante.status === 'dentro' ? 'DENTRO DO EVENTO' : 'FORA DO EVENTO' }}
              </span>
              <span class="status-subtitle">
                {{ participante.status === 'dentro' ? '(Participando do Sorteio)' : '(Não concorre ao sorteio)' }}
              </span>
            </div>

            <!-- 2. FOTO + DADOS DO SERVIDOR -->
            <div class="profile-box">
              <div class="photo-container">
                <img
                  v-if="participante.foto_url"
                  :src="participante.foto_url"
                  alt="Foto do Servidor"
                  class="servant-photo"
                />
                <div v-else class="photo-fallback">
                  <i class="bi bi-person-fill"></i>
                </div>
              </div>

              <div class="details-container">
                <!-- 3. NOME COMPLETO -->
                <h2 class="servant-name">{{ participante.nome }}</h2>

                <!-- 4. CPF COMPLETO (SEM MÁSCARA) -->
                <div class="cpf-badge-box">
                  <span class="cpf-label-mini">CPF COMPLETO:</span>
                  <span class="cpf-value-raw">{{ formatarCpfExibicao(participante.cpf) }} ({{ participante.cpf }})</span>
                </div>

                <!-- SECRETARIA & SETOR -->
                <p class="servant-meta">
                  <i class="bi bi-building me-1"></i>
                  <strong>{{ participante.secretaria }}</strong>
                  <span v-if="participante.setor"> &bull; {{ participante.setor }}</span>
                </p>

                <!-- VÍNCULO -->
                <p class="servant-vinculo">
                  <span class="vinculo-chip">{{ participante.vinculo }}</span>
                </p>

                <!-- ÚLTIMO REGISTRO DE MOVIMENTO -->
                <div class="last-seen-box">
                  <i class="bi bi-clock-history me-1"></i>
                  <span>{{ participante.ultimo_registro }}</span>
                </div>
              </div>
            </div>

            <!-- 5. BOTÃO PRINCIPAL DE ALTERAR ESTADO -->
            <div class="action-buttons-group">
              <button
                type="button"
                class="btn-toggle-status"
                :class="participante.status === 'dentro' ? 'btn-mark-exit' : 'btn-mark-entry'"
                :disabled="alterandoStatus"
                @click="alternarStatus"
              >
                <div v-if="!alterandoStatus" class="btn-content">
                  <i :class="participante.status === 'dentro' ? 'bi bi-box-arrow-right' : 'bi bi-box-arrow-in-right'"></i>
                  <span>{{ participante.status === 'dentro' ? 'MARCAR SAÍDA' : 'MARCAR ENTRADA' }}</span>
                </div>
                <div v-else class="btn-content">
                  <div class="spinner-border spinner-border-sm me-2"></div>
                  <span>Atualizando...</span>
                </div>
              </button>

              <!-- 6. BOTÃO CANCELAR E VOLTAR -->
              <button
                type="button"
                class="btn-cancel-return"
                :disabled="alterandoStatus"
                @click="resetarPortaria"
              >
                <i class="bi bi-arrow-left-circle me-2"></i> Cancelar e Voltar
              </button>
            </div>

          </div>

        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
.portaria-page {
  min-height: calc(100vh - 120px);
  padding: 16px 8px 40px;
  display: flex;
  justify-content: center;
}
</style>
