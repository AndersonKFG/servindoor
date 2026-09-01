<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Html5Qrcode } from 'html5-qrcode'

const router = useRouter()

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

    if (res.status === 401 || res.status === 403) {
      router.push('/login')
      return
    }

    const data = await res.json()

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

    if (res.status === 401 || res.status === 403) {
      router.push('/login')
      return
    }

    const data = await res.json()

    if (!res.ok || !data.sucesso) {
      mensagemErro.value = data.detail || 'Erro ao alterar status.'
      alterandoStatus.value = false
      return
    }

    participante.value.status = data.status
    mensagemSucesso.value = data.mensagem

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

  try {
    const devices = await Html5Qrcode.getCameras()
    if (!devices || !devices.length) {
      console.warn('Nenhuma câmera encontrada no dispositivo.')
      return
    }

    if (!qrScanner) {
      qrScanner = new Html5Qrcode('qr-reader-container')
    }

    await qrScanner.start(
      { facingMode: 'environment' },
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
    scannerActive.value = false
  }
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
          <h1 class="portaria-title">Presença no Evento</h1>
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

.portaria-wrapper {
  width: 100%;
  max-width: 480px;
  margin: 0 auto;
}

.portaria-header {
  text-align: center;
  margin-bottom: 14px;
}

.badge-role {
  display: inline-flex;
  align-items: center;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.3);
  padding: 4px 12px;
  border-radius: 999px;
  margin-bottom: 6px;
}

.portaria-title {
  font-size: clamp(1.3rem, 4vw, 1.6rem);
  font-weight: 800;
  color: #ffffff;
  margin: 0;
}

/* ALERTAS */
.alert-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-radius: 12px;
  margin-bottom: 14px;
  font-size: 0.88rem;
}

.error-alert {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #fca5a5;
}

.success-alert {
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: #6ee7b7;
}

.btn-close-alert {
  background: transparent;
  border: none;
  color: inherit;
  font-size: 1.25rem;
  cursor: pointer;
}

/* SCANNER CARD */
.scanner-card {
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  padding: 16px 14px 12px;
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.5);
}

/* ======================================================== */
/* VIEWPORT DA CÂMERA COM CENTRALIZAÇÃO TOTAL               */
/* ======================================================== */
.scanner-viewport-wrapper {
  position: relative;
  width: 100%;
  max-width: 360px;
  aspect-ratio: 1 / 1;
  margin: 0 auto;
  border-radius: 18px;
  overflow: hidden;
  background: #000000;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 25px rgba(0, 0, 0, 0.8), 0 4px 20px rgba(0, 0, 0, 0.4);
}

/* Elemento container do html5-qrcode */
.qr-viewport,
:deep(#qr-reader-container) {
  width: 100% !important;
  height: 100% !important;
  border: none !important;
  padding: 0 !important;
  margin: 0 !important;
  position: absolute !important;
  top: 0 !important;
  left: 0 !important;
  right: 0 !important;
  bottom: 0 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  overflow: hidden !important;
}

/* Forçar o vídeo inserido dinamicamente a ocupar 100% e centralizar com object-fit: cover */
:deep(#qr-reader-container video) {
  width: 100% !important;
  height: 100% !important;
  object-fit: cover !important;
  object-position: center center !important;
  display: block !important;
  margin: 0 auto !important;
  border-radius: 18px !important;
}

/* Esconde elementos nativos do html5-qrcode para dar lugar ao nosso design */
:deep(#qr-shaded-region) {
  display: none !important;
}

:deep(#qr-reader-container__scan_region) {
  width: 100% !important;
  height: 100% !important;
  min-height: 100% !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}

:deep(#qr-reader-container__dashboard) {
  display: none !important;
}

/* Overlay do Retículo Perfeitamente Centralizado */
.scanner-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}

.scanner-target-box {
  width: 72%;
  height: 72%;
  max-width: 250px;
  max-height: 250px;
  position: relative;
  border: 2px dashed rgba(255, 255, 255, 0.28);
  border-radius: 18px;
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.32);
}

.corner {
  position: absolute;
  width: 24px;
  height: 24px;
}

.corner-tl {
  top: -2px;
  left: -2px;
  border-top: 4px solid #38bdf8;
  border-left: 4px solid #38bdf8;
  border-top-left-radius: 10px;
}

.corner-tr {
  top: -2px;
  right: -2px;
  border-top: 4px solid #38bdf8;
  border-right: 4px solid #38bdf8;
  border-top-right-radius: 10px;
}

.corner-bl {
  bottom: -2px;
  left: -2px;
  border-bottom: 4px solid #38bdf8;
  border-left: 4px solid #38bdf8;
  border-bottom-left-radius: 10px;
}

.corner-br {
  bottom: -2px;
  right: -2px;
  border-bottom: 4px solid #38bdf8;
  border-right: 4px solid #38bdf8;
  border-bottom-right-radius: 10px;
}

.scan-laser-bar {
  position: absolute;
  left: 5%;
  width: 90%;
  height: 3px;
  background: linear-gradient(90deg, transparent, #38bdf8, #818cf8, transparent);
  box-shadow: 0 0 10px #38bdf8;
  animation: scanLaser 2.2s ease-in-out infinite alternate;
}

@keyframes scanLaser {
  0% { top: 6%; opacity: 0.4; }
  50% { opacity: 1; }
  100% { top: 90%; opacity: 0.4; }
}

.scanner-fallback {
  text-align: center;
  padding: 24px;
}

.scanner-hint {
  text-align: center;
  margin: 10px 0 2px;
  font-size: 0.8rem;
  color: #94a3b8;
}

/* SEPARADOR */
.or-separator {
  display: flex;
  align-items: center;
  text-align: center;
  margin: 14px 0;
}

.or-separator::before,
.or-separator::after {
  content: '';
  flex: 1;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
}

.or-separator span {
  padding: 0 12px;
  color: #64748b;
  font-size: 0.78rem;
  font-weight: 700;
}

/* CPF CARD */
.cpf-card {
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 18px;
  padding: 16px;
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.4);
}

.cpf-label {
  display: block;
  font-size: 0.85rem;
  font-weight: 700;
  color: #f1f5f9;
  margin-bottom: 8px;
}

.cpf-input-group {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 14px;
  color: #64748b;
  font-size: 1.1rem;
}

.cpf-input {
  width: 100%;
  padding: 14px 54px 14px 44px;
  background: #090d16;
  border: 2px solid #1e293b;
  border-radius: 12px;
  color: #ffffff;
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  font-family: monospace, sans-serif;
  transition: all 0.2s ease;
}

.cpf-input:focus {
  outline: none;
  border-color: #38bdf8;
  box-shadow: 0 0 15px rgba(56, 189, 248, 0.3);
}

.cpf-counter {
  position: absolute;
  right: 12px;
  font-size: 0.78rem;
  font-weight: 700;
  color: #64748b;
  background: #1e293b;
  padding: 3px 8px;
  border-radius: 6px;
}

.cpf-counter.ready {
  background: #10b981;
  color: #ffffff;
}

.cpf-subtext {
  margin: 8px 0 0;
  font-size: 0.74rem;
  color: #64748b;
  text-align: center;
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 14px;
  color: #38bdf8;
  font-weight: 600;
}

/* ============================================== */
/* TELA 2: CARD DE DECISÃO RÁPIDA                 */
/* ============================================== */
.participant-card {
  background: #0f172a;
  border-radius: 22px;
  overflow: hidden;
  border: 2px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
}

.card-inside {
  border-color: rgba(16, 185, 129, 0.6);
  box-shadow: 0 15px 40px rgba(16, 185, 129, 0.25);
}

.card-outside {
  border-color: rgba(239, 68, 68, 0.6);
  box-shadow: 0 15px 40px rgba(239, 68, 68, 0.25);
}

/* BANNER DE STATUS */
.status-banner {
  padding: 14px 10px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
}

.banner-inside {
  background: linear-gradient(135deg, #059669 0%, #10b981 100%);
  color: #ffffff;
}

.banner-outside {
  background: linear-gradient(135deg, #dc2626 0%, #ef4444 100%);
  color: #ffffff;
}

.status-title {
  font-size: clamp(1.15rem, 4vw, 1.35rem);
  font-weight: 900;
  letter-spacing: 0.03em;
}

.status-subtitle {
  font-size: 0.78rem;
  opacity: 0.9;
  font-weight: 600;
}

/* PERFIL DO SERVIDOR */
.profile-box {
  padding: 18px 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 12px;
}

.photo-container {
  width: 130px;
  height: 130px;
  border-radius: 18px;
  overflow: hidden;
  border: 3px solid rgba(255, 255, 255, 0.25);
  background: #000000;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.5);
  flex-shrink: 0;
}

.servant-photo {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.photo-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 3.5rem;
  color: #475569;
}

.details-container {
  width: 100%;
}

.servant-name {
  font-size: clamp(1.2rem, 3.5vw, 1.35rem);
  font-weight: 900;
  color: #ffffff;
  margin: 0 0 6px;
  line-height: 1.25;
  word-break: break-word;
}

/* CPF COMPLETO */
.cpf-badge-box {
  display: inline-block;
  background: #000000;
  border: 1px solid rgba(255, 255, 255, 0.15);
  padding: 6px 12px;
  border-radius: 10px;
  margin-bottom: 6px;
  max-width: 100%;
}

.cpf-label-mini {
  display: block;
  font-size: 0.62rem;
  font-weight: 800;
  color: #94a3b8;
  letter-spacing: 0.06em;
}

.cpf-value-raw {
  font-size: clamp(0.9rem, 3vw, 1.05rem);
  font-weight: 900;
  color: #38bdf8;
  font-family: monospace;
}

.servant-meta {
  font-size: 0.85rem;
  color: #cbd5e1;
  margin: 4px 0;
  word-break: break-word;
}

.servant-vinculo {
  margin: 4px 0 8px;
}

.vinculo-chip {
  background: rgba(59, 130, 246, 0.15);
  color: #93c5fd;
  border: 1px solid rgba(59, 130, 246, 0.3);
  font-size: 0.75rem;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 6px;
  display: inline-block;
}

.last-seen-box {
  display: inline-flex;
  align-items: center;
  font-size: 0.76rem;
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.05);
  padding: 4px 10px;
  border-radius: 6px;
}

/* BOTÕES DE AÇÃO */
.action-buttons-group {
  padding: 0 14px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.btn-toggle-status {
  width: 100%;
  min-height: 54px;
  padding: 16px;
  border-radius: 16px;
  border: none;
  font-size: 1.15rem;
  font-weight: 900;
  letter-spacing: 0.02em;
  cursor: pointer;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.4);
  transition: all 0.2s ease;
}

.btn-toggle-status:active {
  transform: scale(0.98);
}

.btn-mark-entry {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: #ffffff;
  box-shadow: 0 10px 25px rgba(16, 185, 129, 0.35);
}

.btn-mark-exit {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: #ffffff;
  box-shadow: 0 10px 25px rgba(239, 68, 68, 0.35);
}

.btn-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.btn-cancel-return {
  width: 100%;
  min-height: 48px;
  padding: 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #94a3b8;
  font-size: 0.92rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-cancel-return:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.animate-scale-up {
  animation: scaleUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes scaleUp {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}

.fs-1 { font-size: 2rem; }
.fs-4 { font-size: 1.3rem; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.m-0 { margin: 0; }
.text-muted { color: #64748b; }
.text-primary { color: #38bdf8; }
.btn-action {
  background: #2563eb;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
}
.btn-sm { padding: 6px 14px; font-size: 0.8rem; }
</style>
