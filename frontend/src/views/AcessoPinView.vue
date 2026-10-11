<template>
  <div class="gate-container">
    <div class="ambient-glow glow-1"></div>
    <div class="ambient-glow glow-2"></div>

    <div class="gate-card" :class="{ 'shake-anim': shaking }">
      <!-- Marca Serv indoor -->
      <div class="brand-header">
        <img
          src="/images/logo_servindoor_sem-fundo.png"
          alt="Serv indoor Logo"
          class="brand-logo"
          @error="onImageError"
        />
        <div class="badge-lock">
          <span class="lock-icon">🔒</span>
          <span>ACESSO RESTRITO</span>
        </div>
      </div>

      <!-- Título e Instruções -->
      <h1 class="title font-outfit">{{ route.query.redirect === '/telao' ? 'Acesso ao Telão Oficial' : 'Autorização de Dispositivo' }}</h1>
      <p class="subtitle">
        <span v-if="route.query.redirect === '/telao'">
          O acesso a esta tela requer um código de acesso.
        </span>
        <span v-else>
          Insira o <strong>código de 6 dígitos</strong> (letras, números ou símbolos) para liberar o acesso neste aparelho.
        </span>
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
        <span>Proteção com 3 tentativas diárias. Limite de sessão de 7 dias.</span>
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

      sessionStorage.setItem('servindoor_telao_pin_autorizado', 'true')
      localStorage.setItem('servindoor_telao_pin_autorizado', 'true')

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
}
</style>
