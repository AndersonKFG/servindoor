<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import Modal from '../components/Modal.vue'

const router = useRouter()
const route = useRoute()
const { currentUser, isStaff, checkAuth } = useAuth()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')
const sessaoSubstituidaAlerta = ref(false)

// Estados do modal de conflito de sessão
const showModalConflitoSessao = ref(false)
const conflitoInfo = ref({
  dispositivo: '',
  ultimoAcesso: '',
  mensagem: ''
})

onMounted(async () => {
  if (route.query.motivo === 'sessao_substituida') {
    sessaoSubstituidaAlerta.value = true
  }

  const user = await checkAuth()
  if (user && !sessaoSubstituidaAlerta.value) {
    redirecionarPorRoles(user.roles || [user.role])
  }
})

function redirecionarPorRoles(roles) {
  if (roles.includes('admin_geral')) {
    router.push('/admin')
  } else if (roles.includes('admin')) {
    router.push('/admin/participantes')
  } else if (roles.includes('portaria')) {
    router.push('/portaria')
  } else if (roles.includes('entregador')) {
    router.push('/admin/entregas')
  } else {
    router.push('/')
  }
}

function formatCPF(val) {
  const digits = val.replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 3) return digits
  if (digits.length <= 6) return `${digits.slice(0, 3)}.${digits.slice(3)}`
  if (digits.length <= 9) return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6)}`
  return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`
}

function onCpfInput(e) {
  username.value = formatCPF(e.target.value)
}

async function handleLogin(forcar = false) {
  loading.value = true
  errorMessage.value = ''
  sessaoSubstituidaAlerta.value = false

  try {
    const formData = new FormData()
    formData.append('username', username.value)
    formData.append('password', password.value)
    if (forcar) {
      formData.append('forcar_login', 'true')
    }

    const res = await fetch('/login', {
      method: 'POST',
      headers: {
        'Accept': 'application/json'
      },
      body: formData
    })

    // Caso 409 Conflict: Conta já logada em outro dispositivo
    if (res.status === 409) {
      const data = await res.json()
      conflitoInfo.value = {
        dispositivo: data.dispositivo_anterior || 'Outro dispositivo',
        ultimoAcesso: data.ultimo_acesso || 'Recentemente',
        mensagem: data.mensagem || 'Você já possui uma sessão ativa em outro dispositivo.'
      }
      showModalConflitoSessao.value = true
      loading.value = false
      return
    }

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}))
      errorMessage.value = errData.erro || errData.detail || 'CPF ou Senha incorretos.'
      loading.value = false
      return
    }

    showModalConflitoSessao.value = false
    const user = await checkAuth(true)
    if (user) {
      redirecionarPorRoles(user.roles || [user.role])
    } else {
      router.push('/admin')
    }
  } catch (err) {
    console.error('Erro no login:', err)
    errorMessage.value = 'Falha ao conectar com o servidor.'
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="app-container">
      <div class="login-wrapper">
        <div class="vip-card login-card">
          
          <div class="login-header">
            <div class="login-icon-box">
              <i class="bi bi-shield-lock-fill"></i>
            </div>
            <h2 class="login-title font-outfit">Painel de Acesso</h2>
            <p class="login-subtitle">Área restrita para a Equipe Operacional e Administradores.</p>
          </div>

          <!-- Alerta de Sessão Encerrada por Outro Dispositivo -->
          <div v-if="sessaoSubstituidaAlerta" class="alert-warning-box mb-3">
            <i class="bi bi-exclamation-triangle-fill me-2 fs-5"></i>
            <div>
              <strong>Sessão Desconectada</strong>
              <div class="small">Sua conta foi conectada em outro dispositivo. Por segurança, este acesso foi encerrado.</div>
            </div>
          </div>

          <!-- Alerta de Erro de Credenciais -->
          <div v-if="errorMessage" class="alert-danger-box">
            <i class="bi bi-exclamation-circle-fill me-2"></i>
            <span>{{ errorMessage }}</span>
          </div>

          <form @submit.prevent="handleLogin(false)">
            <div class="form-group">
              <label class="form-label" for="username">CPF do Usuário</label>
              <input
                id="username"
                v-model="username"
                type="tel"
                inputmode="numeric"
                class="form-control"
                placeholder="000.000.000-00"
                maxlength="14"
                required
                @input="onCpfInput"
              />
            </div>

            <div class="form-group">
              <label class="form-label" for="password">Senha de Acesso</label>
              <input
                id="password"
                v-model="password"
                type="password"
                class="form-control"
                placeholder="Digite sua senha segura"
                required
              />
            </div>

            <div class="submit-btn-box">
              <button type="submit" class="btn-primary w-100 font-outfit" :disabled="loading">
                <span v-if="!loading">Entrar no Sistema</span>
                <span v-else>Autenticando...</span>
                <i class="bi bi-box-arrow-in-right ms-1"></i>
              </button>
            </div>
          </form>

          <div class="login-footer-link">
            <router-link to="/" class="back-link">
              <i class="bi bi-arrow-left me-1"></i> Voltar à Página Inicial
            </router-link>
          </div>

        </div>
      </div>
    </div>

    <!-- Modal: Conflito de Sessão / Dispositivo Já Conectado -->
    <Modal
      :show="showModalConflitoSessao"
      title="Dispositivo Já Conectado"
      icon="bi-phone-flip"
      icon-color="text-warning"
      :max-width="'480px'"
      @close="showModalConflitoSessao = false"
    >
      <div class="text-center py-2">
        <p class="text-white mb-3" style="font-size: 0.98rem; line-height: 1.5;">
          Esta conta já possui uma sessão ativa no seguinte aparelho:
        </p>

        <div class="active-device-box mb-3">
          <div class="device-icon-circle">
            <i class="bi bi-display"></i>
          </div>
          <div class="device-info-text">
            <span class="device-name">{{ conflitoInfo.dispositivo }}</span>
            <small class="device-time">Último acesso: {{ conflitoInfo.ultimoAcesso }}</small>
          </div>
        </div>

        <p class="text-muted small mb-0" style="line-height: 1.4;">
          O sistema permite apenas <strong>1 dispositivo conectado por conta</strong>. Se você continuar, a sessão no outro aparelho será <strong>encerrada imediatamente</strong>.
        </p>
      </div>

      <template #footer>
        <div class="d-flex gap-2 w-100">
          <button
            type="button"
            class="btn-secondary flex-1"
            @click="showModalConflitoSessao = false"
          >
            Cancelar
          </button>
          <button
            type="button"
            class="btn-takeover flex-1 font-outfit"
            :disabled="loading"
            @click="handleLogin(true)"
          >
            <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
            <span>Desconectar Outro e Entrar</span>
          </button>
        </div>
      </template>
    </Modal>

  </div>
</template>

<style scoped>
.login-page {
  min-height: 80vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
}

.login-wrapper {
  width: 100%;
  max-width: 440px;
  margin: 0 auto;
}

.login-card {
  padding: 36px 30px;
}

.login-header {
  text-align: center;
  margin-bottom: 26px;
}

.login-icon-box {
  width: 58px;
  height: 58px;
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.35);
  border-radius: 50%;
  margin: 0 auto 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.6rem;
  color: var(--primary-accent);
}

.login-title {
  font-size: 1.65rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 6px;
}

.login-subtitle {
  color: var(--text-muted);
  font-size: 0.85rem;
}

.alert-danger-box {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.35);
  color: #fca5a5;
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 0.88rem;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
}

.alert-warning-box {
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #fde68a;
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 0.88rem;
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

/* Caixa de Informação do Dispositivo Anterior */
.active-device-box {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 14px;
  text-align: left;
}

.device-icon-circle {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.3rem;
  color: #fbbf24;
  flex-shrink: 0;
}

.device-info-text {
  display: flex;
  flex-direction: column;
}

.device-name {
  color: #ffffff;
  font-weight: 700;
  font-size: 0.95rem;
}

.device-time {
  color: #94a3b8;
  font-size: 0.8rem;
  margin-top: 2px;
}

/* Botão de Desconectar e Entrar */
.btn-takeover {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: #0f172a;
  font-weight: 800;
  border: none;
  border-radius: 10px;
  padding: 10px 16px;
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.3);
}

.btn-takeover:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(245, 158, 11, 0.45);
  background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
}

.btn-takeover:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.submit-btn-box {
  margin-top: 24px;
}

.login-footer-link {
  text-align: center;
  margin-top: 24px;
}

.back-link {
  color: var(--text-muted);
  font-size: 0.85rem;
  text-decoration: none;
  transition: color 0.2s ease;
}

.back-link:hover {
  color: #ffffff;
}

.flex-1 { flex: 1; }
.w-100 { width: 100%; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.ms-1 { margin-left: 4px; }
</style>
