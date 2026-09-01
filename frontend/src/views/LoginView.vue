<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const router = useRouter()
const { currentUser, isStaff, checkAuth } = useAuth()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

onMounted(async () => {
  const user = await checkAuth()
  if (user) {
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

async function handleLogin() {
  loading.value = true
  errorMessage.value = ''

  try {
    const formData = new FormData()
    formData.append('username', username.value)
    formData.append('password', password.value)

    const res = await fetch('/login', {
      method: 'POST',
      body: formData
    })

    if (!res.ok) {
      errorMessage.value = 'CPF ou Senha incorretos.'
      loading.value = false
      return
    }

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

          <div v-if="errorMessage" class="alert-danger-box">
            <i class="bi bi-exclamation-circle-fill me-2"></i>
            <span>{{ errorMessage }}</span>
          </div>

          <form @submit.prevent="handleLogin">
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

.w-100 { width: 100%; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.ms-1 { margin-left: 4px; }
</style>
