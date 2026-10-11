<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useToast } from '../composables/useToast'
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

// Rate limit e bloqueio temporário por tentativas excessivas
const segundosBloqueio = ref(0)
let timerBloqueio = null

function iniciarTimerBloqueio(segundos) {
  if (timerBloqueio) clearInterval(timerBloqueio)
  segundosBloqueio.value = Number(segundos) || 0
  if (segundosBloqueio.value <= 0) return

  timerBloqueio = setInterval(() => {
    segundosBloqueio.value -= 1
    if (segundosBloqueio.value <= 0) {
      clearInterval(timerBloqueio)
      timerBloqueio = null
      errorMessage.value = ''
    }
  }, 1000)
}

onUnmounted(() => {
  if (timerBloqueio) clearInterval(timerBloqueio)
})

// Estados do modal de conflito de sessão
const showModalConflitoSessao = ref(false)

const showModalTrocarSenhaObrigatoria = ref(false)
const novaSenhaObrigatoria = ref('')
const confirmacaoSenhaObrigatoria = ref('')
const salvandoNovaSenha = ref(false)
const erroNovaSenha = ref('')

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
  } else if (roles.includes('validador')) {
    router.push('/admin/validacoes')
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


async function handleSalvarSenhaObrigatoria() {
  erroNovaSenha.value = ''
  if (novaSenhaObrigatoria.value.length < 6) {
    erroNovaSenha.value = 'A nova senha deve possuir pelo menos 6 caracteres.'
    return
  }
  if (novaSenhaObrigatoria.value !== confirmacaoSenhaObrigatoria.value) {
    erroNovaSenha.value = 'As senhas digitadas não conferem.'
    return
  }

  try {
    salvandoNovaSenha.value = true
    const res = await fetch('/api/auth/alterar-senha-obrigatoria', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nova_senha: novaSenhaObrigatoria.value,
        confirmacao_senha: confirmacaoSenhaObrigatoria.value
      })
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      toast.success('Senha definitiva cadastrada com sucesso!')
      showModalTrocarSenhaObrigatoria.value = false
      const user = await checkAuth(true)
      if (user) {
        redirecionarPorRoles(user.roles || [user.role])
      } else {
        router.push('/admin')
      }
    } else {
      erroNovaSenha.value = data.detail || 'Erro ao definir nova senha.'
    }
  } catch {
    erroNovaSenha.value = 'Erro de comunicação ao salvar nova senha.'
  } finally {
    salvandoNovaSenha.value = false
  }
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
      if (res.status >= 500) {
        errorMessage.value = 'Erro interno no servidor. Tente novamente mais tarde.'
      } else {
        const errData = await res.json().catch(() => ({}))
        errorMessage.value = errData.erro || errData.detail || 'CPF ou senha inválidos.'
        if (errData.bloqueado && errData.segundos_restantes) {
          iniciarTimerBloqueio(errData.segundos_restantes)
        }
      }
      loading.value = false
      return
    }

    if (timerBloqueio) {
      clearInterval(timerBloqueio)
      timerBloqueio = null
      segundosBloqueio.value = 0
    }

    showModalConflitoSessao.value = false
    const loginData = await res.json().catch(() => ({}))

    if (loginData.deve_trocar_senha) {
      showModalTrocarSenhaObrigatoria.value = true
      loading.value = false
      return
    }

    const user = await checkAuth(true)
    if (user) {
      const redirect = route.query.redirect
      if (redirect && typeof redirect === 'string' && redirect.startsWith('/')) {
        router.push(redirect)
        return
      }
      redirecionarPorRoles(user.roles || [user.role])
    } else {
      router.push('/admin')
    }
  } catch (err) {
    // Falha no login
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

          <!-- Alerta de Erro de Credenciais ou Bloqueio por Rate Limit -->
          <div v-if="errorMessage" class="alert-danger-box">
            <i class="bi bi-shield-exclamation me-2 fs-5 flex-shrink-0"></i>
            <div>
              <span>{{ errorMessage }}</span>
              <div v-if="segundosBloqueio > 0" class="small mt-1 opacity-75">
                Tentativas bloqueadas. Aguarde <strong>{{ segundosBloqueio }}s</strong> para nova tentativa.
              </div>
            </div>
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
                placeholder="Digite sua senha"
                required
              />
            </div>

            <div class="submit-btn-box">
              <button
                type="submit"
                class="btn-primary w-100 font-outfit"
                :disabled="loading || segundosBloqueio > 0"
              >
                <span v-if="segundosBloqueio > 0">
                  <i class="bi bi-clock-history me-1"></i> Aguarde {{ segundosBloqueio }}s
                </span>
                <span v-else-if="!loading">Entrar no Sistema</span>
                <span v-else>Autenticando...</span>
                <i v-if="segundosBloqueio === 0" class="bi bi-box-arrow-in-right ms-1"></i>
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
</style>
