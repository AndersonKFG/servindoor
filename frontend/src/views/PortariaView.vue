<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import { useAuth } from '../composables/useAuth'
import { Html5Qrcode } from 'html5-qrcode'

const router = useRouter()
const { toast } = useToast()
const { isAdminGeral } = useAuth()
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
const presencaLiberada = ref(false)
const liberacaoCarregada = ref(false)
const carregandoLiberacao = ref(false)
const salvandoLiberacao = ref(false)
const erroLiberacao = ref(null)

let qrScanner = null
let isProcessing = false
let liberacaoInterval = null

async function carregarLiberacaoPresenca() {
  if (carregandoLiberacao.value || salvandoLiberacao.value) return
  carregandoLiberacao.value = true
  try {
    const res = await fetch('/api/portaria/liberacao-presenca', {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    })
    if (res.status === 401) {
      router.push('/login')
      throw new Error('Sua sessão expirou. Entre novamente.')
    }
    const data = await res.json()
    if (!res.ok || typeof data.liberada !== 'boolean') {
      throw new Error(data.detail || 'Não foi possível consultar a liberação de presença.')
    }
    presencaLiberada.value = data.liberada
    liberacaoCarregada.value = true
    erroLiberacao.value = null
  } catch (err) {
    liberacaoCarregada.value = false
    presencaLiberada.value = false
    erroLiberacao.value = err.message || 'Falha ao consultar a liberação de presença.'
  } finally {
    carregandoLiberacao.value = false
  }
}

async function alternarLiberacaoPresenca() {
  if (!isAdminGeral.value || !liberacaoCarregada.value || carregandoLiberacao.value || salvandoLiberacao.value || alterandoStatus.value) return
  salvandoLiberacao.value = true
  erroLiberacao.value = null
  try {
    const res = await fetch('/api/portaria/liberacao-presenca', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ liberada: !presencaLiberada.value })
    })
    if (res.status === 401) {
      router.push('/login')
      throw new Error('Sua sessão expirou. Entre novamente.')
    }
    const data = await res.json()
    if (!res.ok || !data.sucesso || typeof data.liberada !== 'boolean') {
      throw new Error(data.detail || 'Não foi possível salvar a liberação de presença.')
    }
    presencaLiberada.value = data.liberada
    toast.success(data.liberada ? 'Alterações de presença liberadas.' : 'Alterações de presença bloqueadas.', 'Portaria', 3000)
  } catch (err) {
    // A resposta pode ter sido perdida depois de o servidor salvar a mudança.
    // Exige nova consulta antes de permitir outra alteração.
    liberacaoCarregada.value = false
    presencaLiberada.value = false
    erroLiberacao.value = err.message || 'Falha ao salvar a liberação de presença.'
  } finally {
    salvandoLiberacao.value = false
  }
}

function atualizarLiberacaoAoVoltar() {
  if (document.visibilityState === 'visible') carregarLiberacaoPresenca()
}

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
  if (!liberacaoCarregada.value || !presencaLiberada.value || salvandoLiberacao.value) {
    mensagemErro.value = 'As alterações de presença estão bloqueadas. Aguarde a liberação do Administrador Geral.'
    return
  }
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
      if (data.codigo === 'presenca_bloqueada') presencaLiberada.value = false
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
  carregarLiberacaoPresenca()
  liberacaoInterval = setInterval(carregarLiberacaoPresenca, 15000)
  document.addEventListener('visibilitychange', atualizarLiberacaoAoVoltar)
  startQRScanner()
})

onUnmounted(() => {
  clearInterval(liberacaoInterval)
  document.removeEventListener('visibilitychange', atualizarLiberacaoAoVoltar)
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

        <section class="availability-control" aria-label="Liberação das alterações de presença" :aria-busy="salvandoLiberacao">
          <div class="availability-control__status" :class="presencaLiberada && liberacaoCarregada ? 'text-success' : 'text-warning'" role="status" aria-live="polite">
            <i class="bi" :class="presencaLiberada && liberacaoCarregada ? 'bi-unlock-fill' : 'bi-lock-fill'" aria-hidden="true"></i>
            <strong>{{ !liberacaoCarregada ? 'Liberação de presença não confirmada' : presencaLiberada ? 'Alterações de presença liberadas' : 'Alterações de presença bloqueadas' }}</strong>
          </div>
          <p class="availability-control__description">
            {{ presencaLiberada && liberacaoCarregada ? 'Entradas e saídas podem ser registradas pela equipe.' : 'A consulta por QR Code ou CPF continua disponível. Para registrar entradas e saídas, aguarde a liberação do Administrador Geral.' }}
          </p>
          <button
            v-if="isAdminGeral"
            type="button"
            class="btn"
            :class="presencaLiberada ? 'btn-danger' : 'btn-primary'"
            :disabled="!liberacaoCarregada || carregandoLiberacao || salvandoLiberacao || alterandoStatus"
            :aria-pressed="presencaLiberada && liberacaoCarregada"
            @click="alternarLiberacaoPresenca"
          >
            <i class="bi" :class="presencaLiberada ? 'bi-lock-fill' : 'bi-unlock-fill'" aria-hidden="true"></i>
            {{ salvandoLiberacao ? 'Salvando...' : presencaLiberada ? 'Bloquear alterações de presença' : 'Liberar alterações de presença' }}
          </button>
          <p v-if="erroLiberacao" class="availability-control__description text-danger" role="alert">{{ erroLiberacao }}</p>
          <button v-if="erroLiberacao" type="button" class="btn btn-secondary" :disabled="carregandoLiberacao || salvandoLiberacao" @click="carregarLiberacaoPresenca">
            Tentar novamente
          </button>
        </section>

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
                <button type="button" class="btn-action btn btn-secondary btn-sm" @click="startQRScanner">
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
                placeholder="00000000000"
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
          
          <div class="participant-card identity-card" :class="participante.status === 'dentro' ? 'card-inside identity-card--success' : 'card-outside identity-card--warning'">
            
            <!-- 1. STATUS GIGANTE E CLARO -->
            <div class="status-banner identity-card__status" :class="participante.status === 'dentro' ? 'banner-inside' : 'banner-outside'">
              <i :class="participante.status === 'dentro' ? 'bi bi-check-circle-fill' : 'bi bi-geo-alt-fill'"></i>
              <span class="status-title identity-card__status-title">
                {{ participante.status === 'dentro' ? 'DENTRO DO EVENTO' : 'FORA DO EVENTO' }}
              </span>
              <span class="status-subtitle identity-card__status-description">
                {{ participante.status === 'dentro' ? '(Participando do Sorteio)' : '(Não concorre ao sorteio)' }}
              </span>
            </div>

            <!-- 2. FOTO + DADOS DO SERVIDOR -->
            <div class="profile-box identity-card__body">
              <div class="photo-container identity-card__avatar">
                <img
                  v-if="participante.foto_url"
                  :src="participante.foto_url"
                  alt="Foto do Servidor"
                  class="servant-photo identity-card__photo"
                />
                <div v-else class="photo-fallback identity-card__placeholder">
                  <i class="bi bi-person-fill"></i>
                </div>
              </div>

              <div class="details-container identity-card__details">
                <!-- 3. NOME COMPLETO -->
                <h2 class="servant-name identity-card__name">{{ participante.nome }}</h2>

                <!-- 4. CPF COMPLETO (SEM MÁSCARA) -->
                <div class="cpf-badge-box identity-card__identifier">
                  <span class="cpf-label-mini identity-card__label">CPF COMPLETO:</span>
                  <span class="cpf-value-raw identity-card__identifier-value">
                    <span>{{ formatarCpfExibicao(participante.cpf) }}</span>
                    <span class="identity-card__identifier-raw">({{ participante.cpf }})</span>
                  </span>
                </div>

                <!-- SECRETARIA & SETOR -->
                <p class="servant-meta identity-card__metadata">
                  <i class="bi bi-building me-1"></i>
                  <strong>{{ participante.secretaria }}</strong>
                  <span v-if="participante.setor"> &bull; {{ participante.setor }}</span>
                </p>

                <!-- VÍNCULO -->
                <p class="servant-vinculo identity-card__affiliation">
                  <span class="vinculo-chip identity-card__badge">{{ participante.vinculo }}</span>
                </p>

                <!-- ÚLTIMO REGISTRO DE MOVIMENTO -->
                <div class="last-seen-box identity-card__activity">
                  <i class="bi bi-clock-history me-1"></i>
                  <span>{{ participante.ultimo_registro }}</span>
                </div>
              </div>
            </div>

            <!-- 5. BOTÃO PRINCIPAL DE ALTERAR ESTADO -->
            <div class="action-buttons-group identity-card__actions">
              <button
                type="button"
                class="btn-toggle-status btn btn-operation"
                :class="participante.status === 'dentro' ? 'btn-mark-exit btn-operation--danger' : 'btn-mark-entry btn-operation--success'"
                :disabled="alterandoStatus || !liberacaoCarregada || !presencaLiberada || salvandoLiberacao"
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
                class="btn-cancel-return btn btn-secondary"
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
