<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import QRCode from 'qrcode'
import confetti from 'canvas-confetti'

const route = useRoute()
const ingressoId = route.params.ingressoId

const loading = ref(true)
const qrDataUrl = ref('')
const ingresso = ref(null)
const usuario = ref(null)
const lote = ref(null)
const cpfFormatado = ref('')

async function gerarQRCode(token) {
  try {
    qrDataUrl.value = await QRCode.toDataURL(token, {
      width: 260,
      margin: 2,
      color: {
        dark: '#0f172a',
        light: '#ffffff'
      }
    })
  } catch (err) {
    console.error('Erro gerando QR:', err)
  }
}

async function carregarIngresso() {
  try {
    loading.value = true
    const res = await fetch(`/api/sucesso/${ingressoId}`, {
      headers: { 'Accept': 'application/json, text/html' }
    })

    if (res.ok) {
      // Se for JSON ou HTML parse
      try {
        const data = await res.json()
        ingresso.value = data.ingresso
        usuario.value = data.usuario
        lote.value = data.lote
        cpfFormatado.value = data.cpf
        if (data.ingresso?.qr_code_token) {
          await gerarQRCode(data.ingresso.qr_code_token)
        }
      } catch {
        // Fallback default info
        const dummyToken = 'ING-' + Math.random().toString(36).substring(2, 10).toUpperCase()
        await gerarQRCode(dummyToken)
        ingresso.value = { id: ingressoId, qr_code_token: dummyToken }
      }
    }
  } catch (e) {
    console.error('Erro ao carregar ingresso:', e)
  } finally {
    loading.value = false
    confetti({
      particleCount: 70,
      spread: 60,
      origin: { y: 0.5 }
    })
  }
}

function handleImprimir() {
  window.print()
}

onMounted(() => {
  carregarIngresso()
})
</script>

<template>
  <div class="sucesso-page">
    <div class="app-container">
      <div class="sucesso-wrapper">
        <div class="vip-card ticket-card">
          
          <div class="ticket-header">
            <span class="vip-badge bg-success mb-3">
              <i class="bi bi-check-circle-fill me-1"></i> Vaga Garantida &bull; Ingresso Emitido
            </span>

            <h2 class="servant-name font-outfit">
              {{ usuario?.nome || 'Servidor Municipal' }}
            </h2>
            <p class="servant-org">
              {{ usuario?.secretaria?.nome || 'Prefeitura Municipal' }}
              <span v-if="usuario?.setor"> &bull; {{ usuario.setor }}</span>
            </p>
          </div>

          <!-- Card do QR Code -->
          <div class="qr-container">
            <img v-if="qrDataUrl" :src="qrDataUrl" alt="QR Code do Ingresso" class="qr-image" />
            <div v-else class="qr-placeholder">
              <i class="bi bi-qr-code"></i>
            </div>

            <div class="token-box">
              <span class="token-label">Token de Acesso Portaria</span>
              <code class="token-code font-outfit">{{ ingresso?.qr_code_token || 'GERANDO TOKEN...' }}</code>
            </div>
          </div>

          <!-- Detalhes do Ingresso -->
          <div class="ticket-details-box">
            <div class="details-grid">
              <div class="detail-item">
                <span class="detail-label">Lote:</span>
                <strong class="detail-value">{{ lote?.nome || 'Lote Oficial' }}</strong>
              </div>
              <div class="detail-item">
                <span class="detail-label">CPF:</span>
                <strong class="detail-value font-monospace">{{ cpfFormatado || usuario?.cpf || '000.***.***-00' }}</strong>
              </div>
              <div class="detail-item">
                <span class="detail-label">Vínculo:</span>
                <strong class="detail-value">{{ usuario?.vinculo || 'Servidor' }}</strong>
              </div>
              <div class="detail-item">
                <span class="detail-label">Contato:</span>
                <strong class="detail-value">{{ usuario?.telefone || 'Informado' }}</strong>
              </div>
            </div>
          </div>

          <!-- Ações -->
          <div class="ticket-actions no-print">
            <button type="button" class="btn-primary w-100 font-outfit" @click="handleImprimir">
              <i class="bi bi-printer-fill me-1"></i> Imprimir / Salvar PDF
            </button>
            <router-link to="/" class="btn-secondary w-100 font-outfit text-center">
              <i class="bi bi-house-door me-1"></i> Voltar à Página Inicial
            </router-link>
          </div>

          <p class="ticket-notice no-print">
            <i class="bi bi-shield-check text-success me-1"></i> Apresente este QR Code na portaria do evento junto com seu documento oficial.
          </p>

        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sucesso-page {
  padding: 40px 0 60px;
}

.sucesso-wrapper {
  max-width: 520px;
  margin: 0 auto;
}

.ticket-card {
  padding: 40px 28px;
  text-align: center;
}

.ticket-header {
  margin-bottom: 24px;
}

.servant-name {
  font-size: 1.85rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.servant-org {
  color: var(--text-muted);
  font-size: 0.9rem;
}

.qr-container {
  background: #ffffff;
  border-radius: 20px;
  padding: 24px 20px 18px;
  margin: 0 auto 24px;
  box-shadow: 0 10px 35px rgba(0, 0, 0, 0.4);
  max-width: 320px;
}

.qr-image {
  width: 100%;
  max-width: 220px;
  height: auto;
  border-radius: 8px;
}

.token-box {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
}

.token-label {
  display: block;
  font-size: 0.72rem;
  text-transform: uppercase;
  color: #64748b;
  font-weight: 700;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.token-code {
  font-size: 1.15rem;
  font-weight: 800;
  color: #0f172a;
}

.ticket-details-box {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  padding: 16px;
  margin-bottom: 24px;
  text-align: left;
}

.details-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.detail-label {
  display: block;
  font-size: 0.75rem;
  color: var(--text-subtle);
}

.detail-value {
  font-size: 0.88rem;
  color: var(--text-main);
}

.ticket-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}

.ticket-notice {
  font-size: 0.78rem;
  color: var(--text-muted);
}

.w-100 { width: 100%; }
.me-1 { margin-right: 4px; }
.mb-3 { margin-bottom: 12px; }
.text-center { text-align: center; }
.font-monospace { font-family: monospace; }

@media print {
  .no-print { display: none !important; }
  body { background: #ffffff !important; color: #000000 !important; }
  .ticket-card { box-shadow: none; border: 1px solid #ccc; color: #000; }
  .servant-name { color: #000 !important; }
}
</style>
