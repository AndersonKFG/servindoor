<template>
  <div class="gate-container">
    <div class="ambient-glow glow-1"></div>
    <div class="ambient-glow glow-2"></div>

    <div class="gate-card" :class="{ 'shake-anim': shaking }">
      <!-- Marca Servindoor -->
      <div class="brand-header">
        <img
          src="/images/logo_servindoor_sem-fundo.png"
          alt="Servindoor Logo"
          class="brand-logo"
          @error="onImageError"
        />
        <div class="badge-lock">
          <span class="lock-icon">🔒</span>
          <span>ACESSO RESTRITO</span>
        </div>
      </div>

      <!-- Título e Instruções -->
      <h1 class="title">Autorização de Dispositivo</h1>
      <p class="subtitle">
        Insira o <strong>código de 6 dígitos</strong> (letras, números ou símbolos) para liberar o acesso neste aparelho.
      </p>

      <!-- Badge de Tentativas Restantes -->
      <div class="tentativas-badge" :class="{ 'warning-tentativas': tentativasRestantes <= 1 }">
        <span v-if="tentativasRestantes > 0">
          ⚠️ Tentativas restantes hoje: <strong>{{ tentativasRestantes }} de 3</strong>
        </span>
        <span v-else class="bloqueado-tag">
          🚫 Limite diário de 3 tentativas atingido
        </span>
      </div>

      <!-- Campos dos 6 Caracteres (Letras, Números, Símbolos) -->
      <div class="pin-grid">
        <input
          v-for="(digit, idx) in digits"
          :key="idx"
          :ref="el => (inputRefs[idx] = el)"
          v-model="digits[idx]"
          type="text"
          maxlength="1"
          autocomplete="off"
          autocorrect="off"
          autocapitalize="off"
          spellcheck="false"
          :disabled="bloqueado || loading"
          class="pin-digit"
          :class="{
            'digit-filled': digits[idx] !== '',
            'digit-error': errorMessage,
            'digit-disabled': bloqueado
          }"
          @input="handleInput(idx, $event)"
          @keydown="handleKeyDown(idx, $event)"
          @paste="handlePaste($event)"
          @focus="$event.target.select()"
        />
      </div>

      <!-- Alerta de Erro / Informações -->
      <transition name="fade">
        <div v-if="errorMessage" class="error-banner" :class="{ 'error-banner-blocked': bloqueado }">
          <svg class="error-icon" viewBox="0 0 20 20" fill="currentColor">
            <path
              fill-rule="evenodd"
              d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
              clip-rule="evenodd"
            />
          </svg>
          <span>{{ errorMessage }}</span>
        </div>
      </transition>

      <!-- Botão de Ação -->
      <button
        type="button"
        class="btn-submit"
        :disabled="loading || pinCompleto.length < 6 || bloqueado"
        @click="validarPin"
      >
        <span v-if="!loading" class="btn-content">
          <span>{{ bloqueado ? 'Aparelho Bloqueado' : 'Liberar Acesso' }}</span>
          <svg v-if="!bloqueado" class="arrow-icon" viewBox="0 0 20 20" fill="currentColor">
            <path
              fill-rule="evenodd"
              d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z"
              clip-rule="evenodd"
            />
          </svg>
        </span>
        <span v-else class="loading-content">
          <span class="spinner"></span>
          <span>Validando...</span>
        </span>
      </button>

      <!-- Rodapé com Segurança -->
      <div class="footer-note">
        <span class="shield-icon">🛡️</span>
        <span>Proteção com Rate Limit (3x/dia). Acesso válido por 7 dias.</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const digits = ref(['', '', '', '', '', ''])
const inputRefs = ref([])
const loading = ref(false)
const errorMessage = ref('')
const shaking = ref(false)
const tentativasRestantes = ref(3)

const pinCompleto = computed(() => digits.value.join(''))
const bloqueado = computed(() => tentativasRestantes.value <= 0)

onMounted(async () => {
  await checarStatus()

  nextTick(() => {
    if (!bloqueado.value) {
      inputRefs.value[0]?.focus()
    }
  })
})

async function checarStatus() {
  try {
    const res = await fetch('/api/gatekeeper/status')
    if (res.ok) {
      const data = await res.json()
      tentativasRestantes.value = data.tentativas_restantes ?? 3
      if (data.autorizado) {
        localStorage.setItem('servindoor_gate_token', 'autorizado')
        const destino = route.query.redirect || '/'
        router.push(destino)
      }
    }
  } catch (e) {
    console.warn('Erro ao consultar status:', e)
  }
}

function onImageError(e) {
  e.target.style.display = 'none'
}

function handleInput(idx, e) {
  errorMessage.value = ''
  const val = e.target.value

  if (val && val.length > 0) {
    // Permite qualquer caractere (letras maiúsculas/minúsculas, números, símbolos)
    digits.value[idx] = val.slice(-1)
    if (idx < 5) {
      inputRefs.value[idx + 1]?.focus()
    }
  } else {
    digits.value[idx] = ''
  }

  if (pinCompleto.value.length === 6) {
    validarPin()
  }
}

function handleKeyDown(idx, e) {
  if (e.key === 'Backspace') {
    if (!digits.value[idx] && idx > 0) {
      digits.value[idx - 1] = ''
      inputRefs.value[idx - 1]?.focus()
      e.preventDefault()
    }
  } else if (e.key === 'ArrowLeft' && idx > 0) {
    inputRefs.value[idx - 1]?.focus()
  } else if (e.key === 'ArrowRight' && idx < 5) {
    inputRefs.value[idx + 1]?.focus()
  } else if (e.key === 'Enter' && pinCompleto.value.length === 6) {
    validarPin()
  }
}

function handlePaste(e) {
  e.preventDefault()
  const pasted = (e.clipboardData || window.clipboardData)
    .getData('text')
    .trim()
    .slice(0, 6)

  if (pasted.length > 0) {
    pasted.split('').forEach((char, i) => {
      if (i < 6) digits.value[i] = char
    })

    const nextIndex = Math.min(pasted.length, 5)
    inputRefs.value[nextIndex]?.focus()

    if (pasted.length === 6) {
      validarPin()
    }
  }
}

function triggerShake() {
  shaking.value = true
  setTimeout(() => {
    shaking.value = false
  }, 600)
}

async function validarPin() {
  if (pinCompleto.value.length < 6 || loading.value || bloqueado.value) return

  loading.value = true
  errorMessage.value = ''

  try {
    const res = await fetch('/api/gatekeeper/verificar', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        pin: pinCompleto.value
      })
    })

    const data = await res.json()

    if (res.ok && data.sucesso) {
      if (data.token) {
        localStorage.setItem('servindoor_gate_token', data.token)
      } else {
        localStorage.setItem('servindoor_gate_token', 'liberado')
      }

      const destino = route.query.redirect || '/'
      router.push(destino)
    } else {
      errorMessage.value = data.detail || 'Código incorreto. Tente novamente.'
      triggerShake()
      digits.value = ['', '', '', '', '', '']

      await checarStatus()

      nextTick(() => {
        if (!bloqueado.value) {
          inputRefs.value[0]?.focus()
        }
      })
    }
  } catch (err) {
    errorMessage.value = 'Erro de conexão com o servidor. Tente novamente.'
    triggerShake()
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.gate-container {
  min-height: 100vh;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bg-base, #07090e);
  padding: 1.5rem;
  position: relative;
  overflow: hidden;
  font-family: inherit;
}

.ambient-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(120px);
  pointer-events: none;
  opacity: 0.25;
}
.glow-1 {
  width: 400px;
  height: 400px;
  background: var(--serv-magenta, #d946ef);
  top: -80px;
  left: -80px;
}
.glow-2 {
  width: 450px;
  height: 450px;
  background: var(--serv-cyan, #06b6d4);
  bottom: -100px;
  right: -100px;
}

.gate-card {
  position: relative;
  z-index: 10;
  width: 100%;
  max-width: 470px;
  background: rgba(15, 23, 42, 0.82);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border-glass, rgba(255, 255, 255, 0.1));
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6), 0 0 30px rgba(6, 182, 212, 0.12);
  border-radius: 1.5rem;
  padding: 2.75rem 2.25rem;
  text-align: center;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.brand-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 1.5rem;
}

.brand-logo {
  max-height: 48px;
  object-fit: contain;
  margin-bottom: 1rem;
  filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.4));
}

.badge-lock {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.85rem;
  border-radius: 9999px;
  background: rgba(217, 70, 239, 0.12);
  border: 1px solid rgba(217, 70, 239, 0.3);
  color: var(--serv-magenta, #f0abfc);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.lock-icon {
  font-size: 0.85rem;
}

.title {
  color: var(--text-main, #f8fafc);
  font-size: 1.65rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin-bottom: 0.5rem;
}

.subtitle {
  color: var(--text-muted, #94a3b8);
  font-size: 0.92rem;
  line-height: 1.55;
  margin-bottom: 1.25rem;
}
.subtitle strong {
  color: var(--text-main, #f8fafc);
}

/* Badge de Tentativas */
.tentativas-badge {
  display: inline-block;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 0.4rem 1rem;
  border-radius: 9999px;
  font-size: 0.82rem;
  color: var(--text-muted, #94a3b8);
  margin-bottom: 1.5rem;
}
.tentativas-badge strong {
  color: var(--serv-cyan, #38bdf8);
}
.warning-tentativas {
  border-color: rgba(245, 158, 11, 0.5);
  background: rgba(245, 158, 11, 0.1);
  color: #fde047;
}
.warning-tentativas strong {
  color: #f59e0b;
}
.bloqueado-tag {
  color: #ef4444;
  font-weight: 700;
}

/* Grid com os 6 campos */
.pin-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0.55rem;
  margin-bottom: 1.5rem;
}

.pin-digit {
  width: 100%;
  height: 62px;
  background: rgba(11, 15, 25, 0.85);
  border: 2px solid rgba(255, 255, 255, 0.12);
  border-radius: 0.85rem;
  color: #ffffff;
  font-size: 1.75rem;
  font-weight: 800;
  text-align: center;
  outline: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.4);
  font-family: inherit;
}

.pin-digit:focus:not(:disabled) {
  border-color: var(--serv-cyan, #06b6d4);
  background: rgba(6, 182, 212, 0.08);
  box-shadow: 0 0 15px rgba(6, 182, 212, 0.35), inset 0 2px 4px rgba(0, 0, 0, 0.2);
  transform: translateY(-2px);
}

.digit-filled {
  border-color: rgba(6, 182, 212, 0.5);
  background: rgba(6, 182, 212, 0.04);
}

.digit-error {
  border-color: var(--danger-color, #ef4444) !important;
  background: rgba(239, 68, 68, 0.08) !important;
}

.digit-disabled {
  opacity: 0.4;
  cursor: not-allowed;
  background: rgba(0, 0, 0, 0.5);
}

/* Alerta de erro */
.error-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.35);
  color: #fca5a5;
  padding: 0.75rem 1rem;
  border-radius: 0.75rem;
  font-size: 0.85rem;
  margin-bottom: 1.5rem;
  font-weight: 500;
}
.error-banner-blocked {
  background: rgba(239, 68, 68, 0.25);
  border-color: #ef4444;
  font-weight: 700;
}

.error-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

/* Botão de envio */
.btn-submit {
  width: 100%;
  padding: 0.95rem 1.5rem;
  background: var(--serv-gradient, linear-gradient(135deg, #d946ef 0%, #f59e0b 50%, #06b6d4 100%));
  border: none;
  border-radius: 0.85rem;
  color: #ffffff;
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  cursor: pointer;
  box-shadow: 0 4px 15px rgba(217, 70, 239, 0.3);
  transition: all 0.25s ease;
  position: relative;
  overflow: hidden;
}

.btn-submit:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 22px rgba(217, 70, 239, 0.45);
  filter: brightness(1.08);
}

.btn-submit:active:not(:disabled) {
  transform: translateY(1px);
}

.btn-submit:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.btn-content,
.loading-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
}

.arrow-icon {
  width: 18px;
  height: 18px;
  transition: transform 0.2s ease;
}

.btn-submit:hover:not(:disabled) .arrow-icon {
  transform: translateX(4px);
}

.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* Rodapé */
.footer-note {
  margin-top: 1.8rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  color: var(--text-subtle, #64748b);
  font-size: 0.78rem;
}

.shield-icon {
  font-size: 0.9rem;
}

/* Animações */
.shake-anim {
  animation: shake 0.5s cubic-bezier(0.36, 0.07, 0.19, 0.97) both;
}

@keyframes shake {
  10%, 90% { transform: translate3d(-2px, 0, 0); }
  20%, 80% { transform: translate3d(4px, 0, 0); }
  30%, 50%, 70% { transform: translate3d(-6px, 0, 0); }
  40%, 60% { transform: translate3d(6px, 0, 0); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 480px) {
  .gate-card {
    padding: 2rem 1.25rem;
    border-radius: 1.25rem;
  }
  .pin-grid {
    gap: 0.35rem;
  }
  .pin-digit {
    height: 54px;
    font-size: 1.45rem;
    border-radius: 0.65rem;
  }
  .title {
    font-size: 1.4rem;
  }
}
</style>
