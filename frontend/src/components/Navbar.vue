<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { useToast } from '../composables/useToast'

const router = useRouter()
const route = useRoute()
const { currentUser, isAuthenticated, isStaff, isAdminGeral, isAdmin, isPortaria, isEntregador, isValidador, sessaoSubstituida, hasRole, checkAuth, clearAuth } = useAuth()
const mobileMenuOpen = ref(false)

const { toast } = useToast()
let authHeartbeat = null
let originalFetch = null
let isRedirecionandoPorRevogacao = false

const MENSAGEM_REVOGACAO = 'O seu acesso a esta tela foi revogado, você será redirecionada para a tela inicial, onde poderá ver através do menu onde poderá acessar. Sua conta também pode ter sido desativada.'

function isRotaRestrita(r) {
  if (!r) return false
  return (
    r.matched?.some(record => record.meta?.requiresAuth) ||
    r.meta?.requiresAuth ||
    r.path?.startsWith('/admin') ||
    r.path?.startsWith('/portaria')
  )
}

function getRequiredRoles(r) {
  if (!r) return []
  if (Array.isArray(r.meta?.roles) && r.meta.roles.length > 0) {
    return r.meta.roles
  }
  if (r.matched && r.matched.length > 0) {
    for (const record of r.matched) {
      if (Array.isArray(record.meta?.roles) && record.meta.roles.length > 0) {
        return record.meta.roles
      }
    }
  }
  return []
}

function verificarAcessoRotaAtual() {
  const currentRoute = router.currentRoute.value || route
  if (!isRotaRestrita(currentRoute)) return
  if (isRedirecionandoPorRevogacao) return

  // 1. Caso o usuário não esteja mais autenticado (desativado ou logout)
  if (!currentUser.value || !isAuthenticated.value) {
    executarRevogacao()
    return
  }

  // 2. Caso a rota exija roles específicas e o usuário não as possua mais
  const requiredRoles = getRequiredRoles(currentRoute)
  if (requiredRoles && requiredRoles.length > 0) {
    const permitida = hasRole(...requiredRoles)
    if (!permitida) {
      executarRevogacao()
    }
  }
}

function executarRevogacao() {
  if (isRedirecionandoPorRevogacao) return
  isRedirecionandoPorRevogacao = true
  toast.warning(MENSAGEM_REVOGACAO, 'Acesso Revogado', 10000)
  router.push('/').finally(() => {
    setTimeout(() => {
      isRedirecionandoPorRevogacao = false
    }, 1500)
  })
}

watch(sessaoSubstituida, (val) => {
  if (val) {
    clearAuth()
    window.location.href = '/login?motivo=sessao_substituida'
  }
})

function onFocusOrVisibility() {
  if (document.visibilityState === 'visible') {
    checkAuth(true).then(() => verificarAcessoRotaAtual()).catch(() => {})
  }
}

onMounted(async () => {
  await checkAuth()
  verificarAcessoRotaAtual()

  // Heartbeat para checagem ativa de permissões em rotas restritas (pausa quando aba oculta ou na Home pública)
  authHeartbeat = setInterval(async () => {
    try {
      if (typeof document !== 'undefined' && document.hidden) return
      const currentRoute = router.currentRoute.value || route
      if (isRotaRestrita(currentRoute)) {
        await checkAuth(true)
        verificarAcessoRotaAtual()
      }
    } catch {
      // Ignora falha de rede transitória
    }
  }, 10000)

  if (typeof window !== 'undefined') {
    window.addEventListener('visibilitychange', onFocusOrVisibility)
    window.addEventListener('focus', onFocusOrVisibility)

    // Interceptador global para resposta 401/403 imediata caso uma ação seja executada na tela restrita
    if (window.fetch) {
      originalFetch = window.fetch
      window.fetch = async (...args) => {
        const response = await originalFetch(...args)
        if (response.status === 401 || response.status === 403) {
          const currentRoute = router.currentRoute.value || route
          if (isRotaRestrita(currentRoute)) {
            try {
              await checkAuth(true)
              verificarAcessoRotaAtual()
            } catch {
              // Ignora erro
            }
          }
        }
        return response
      }
    }
  }
})

onUnmounted(() => {
  if (authHeartbeat) {
    clearInterval(authHeartbeat)
  }
  if (typeof window !== 'undefined') {
    window.removeEventListener('visibilitychange', onFocusOrVisibility)
    window.removeEventListener('focus', onFocusOrVisibility)
    if (originalFetch) {
      window.fetch = originalFetch
    }
  }
})

watch(
  () => route.path,
  async () => {
    mobileMenuOpen.value = false
    await checkAuth(true)
    verificarAcessoRotaAtual()
  }
)

const showStaffNav = computed(() => {
  return isAuthenticated.value && isStaff.value
})

// Extrai PRIMEIRO e ÚLTIMO nome do usuário logado
const primeiroEUltimoNome = computed(() => {
  if (!currentUser.value?.nome) return 'Usuário'
  const partes = currentUser.value.nome.trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return 'Usuário'
  if (partes.length === 1) return partes[0]
  return `${partes[0]} ${partes[partes.length - 1]}`
})

// Identifica o rótulo da função principal do usuário
const rolePrincipalLabel = computed(() => {
  if (!currentUser.value) return ''
  const roles = Array.isArray(currentUser.value.roles) && currentUser.value.roles.length > 0
    ? currentUser.value.roles
    : [currentUser.value.role]
  
  if (roles.includes('admin_geral')) return 'Admin Geral'
  if (roles.includes('admin')) return 'Administrador'
  if (roles.includes('validador')) return 'Validador'
  if (roles.includes('portaria')) return 'Portaria'
  if (roles.includes('entregador')) return 'Entregador'
  return 'Staff'
})

async function handleLogout() {
  mobileMenuOpen.value = false
  clearAuth()
  window.location.href = '/logout'
}

function toggleMobileMenu() {
  mobileMenuOpen.value = !mobileMenuOpen.value
}
</script>

<template>
  <header class="navbar-wrapper">
    <!-- BARRA ÚNICA SUPERIOR -->
    <div class="navbar-main">
      <div class="app-container">
        <div class="navbar-main-inner">
          
          <!-- 1. ESQUERDA: Logo Oficial Serv indoor -->
          <router-link to="/" class="navbar-brand" @click="mobileMenuOpen = false">
            <img
              src="/images/logo_servindoor_sem-fundo.png"
              alt="Serv indoor • A Festa do Servidor 2026"
              class="navbar-logo-img"
            />
          </router-link>

          <!-- 2. CENTRO: Menus Dinâmicos (Entre a Logo e a div do Usuário) -->
          <nav class="navbar-center-menu" :class="showStaffNav ? 'staff-center-menu' : 'guest-center-menu'">
            
            <!-- LINKS PARA VISITANTE / NÃO LOGADO -->
            <ul v-if="!showStaffNav" class="navbar-center-list">
              <li>
                <router-link to="/" class="nav-center-link">
                  <i class="bi bi-house-door"></i>
                  <span>Início</span>
                </router-link>
              </li>

              <li>
                <router-link to="/meu-ingresso" class="nav-center-link">
                  <i class="bi bi-ticket-detailed text-cyan"></i>
                  <span>Meu Ingresso</span>
                </router-link>
              </li>

              <li v-if="!isAuthenticated">
                <router-link to="/meus-premios" class="nav-center-link nav-link-highlight">
                  <i class="bi bi-gift-fill text-gold"></i>
                  <span>Meus Prêmios</span>
                </router-link>
              </li>
            </ul>

            <!-- LINKS PARA EQUIPE / USUÁRIO LOGADO -->
            <ul v-else class="navbar-center-list staff-links">
              <!-- Consulta de Lotes (Admin e Admin Geral) -->
              <li v-if="isAdmin">
                <router-link to="/admin" class="nav-center-link" exact>
                  <i class="bi bi-speedometer2"></i>
                  <span>Lotes</span>
                </router-link>
              </li>

              <!-- Validações de Servidores (Validador, Admin, Admin Geral) -->
              <li v-if="isValidador">
                <router-link to="/admin/validacoes" class="nav-center-link">
                  <i class="bi bi-person-check-fill text-emerald"></i>
                  <span>Validações</span>
                </router-link>
              </li>

              <!-- Participantes (Admin & Admin Geral) -->
              <li v-if="isAdmin">
                <router-link to="/admin/participantes" class="nav-center-link">
                  <i class="bi bi-ticket-perforated-fill text-emerald"></i>
                  <span>Participantes</span>
                </router-link>
              </li>

              <!-- Cancelamentos (Admin & Admin Geral) -->
              <li v-if="isAdmin">
                <router-link to="/admin/cancelamentos" class="nav-center-link">
                  <i class="bi bi-person-x-fill text-danger"></i>
                  <span>Cancelamentos</span>
                </router-link>
              </li>

              <!-- Equipe & Acessos (Admin & Admin Geral) -->
              <li v-if="isAdminGeral">
                <router-link to="/admin/documentos-legais" class="nav-center-link">
                  <i class="bi bi-file-earmark-lock text-cyan"></i><span>Documentos Legais</span>
                </router-link>
              </li>
              <li v-if="isAdmin">
                <router-link to="/admin/usuarios" class="nav-center-link">
                  <i class="bi bi-person-gear text-purple"></i>
                  <span>Equipe</span>
                </router-link>
              </li>

              <!-- Mesa de Sorteios (Admin & Admin Geral) -->
              <li v-if="isAdmin">
                <router-link to="/admin/sorteios" class="nav-center-link">
                  <i class="bi bi-trophy-fill text-gold"></i>
                  <span>Sorteios</span>
                </router-link>
              </li>

              <!-- Portaria & Scanner (Portaria, Admin, Admin Geral) -->
              <li v-if="isPortaria">
                <router-link to="/portaria" class="nav-center-link">
                  <i class="bi bi-qr-code-scan text-cyan"></i>
                  <span>Portaria</span>
                </router-link>
              </li>

              <!-- Registro de Entregas (Entregador, Admin, Admin Geral) -->
              <li v-if="isEntregador">
                <router-link to="/admin/entregas" class="nav-center-link">
                  <i class="bi bi-camera-fill text-amber"></i>
                  <span>Entregas</span>
                </router-link>
              </li>
            </ul>

          </nav>

          <!-- 3. DIREITA: Botão de Acesso Staff ou Apresentação do Usuário -->
          <div class="navbar-right-actions">
            
            <!-- Visitante / Não Autenticado -->
            <router-link v-if="!showStaffNav" to="/login" class="btn-staff-access">
              <i class="bi bi-shield-lock-fill"></i>
              <span>Acesso Staff</span>
            </router-link>

            <!-- Usuário Equipe Autenticado: Avatar, Nome, Cargo e Logout -->
            <div v-else class="user-greeting-box">
              <div class="user-avatar-badge">
                <i class="bi bi-person-fill"></i>
              </div>

              <div class="user-info-text">
                <div class="greeting-line">
                  <span class="greeting-prefix">Olá,</span>
                  <strong class="user-full-name">{{ primeiroEUltimoNome }}</strong>
                </div>
                <span class="user-role-tag" :class="'badge-role-' + (currentUser?.roles?.[0] || currentUser?.role)">
                  <i class="bi bi-patch-check-fill me-1"></i>
                  {{ rolePrincipalLabel }}
                </span>
              </div>

              <button
                type="button"
                class="btn-logout-header"
                title="Encerrar Sessão"
                @click="handleLogout"
              >
                <i class="bi bi-box-arrow-right"></i>
                <span class="d-none-sm">Sair</span>
              </button>
            </div>



            <!-- Botão Hamburguer no Mobile/Tablet -->
            <button
              type="button"
              class="navbar-toggle-btn"
              :class="[{ 'active': mobileMenuOpen }, showStaffNav ? 'staff-toggle' : 'guest-toggle']"
              aria-label="Abrir Menu"
              @click="toggleMobileMenu"
            >
              <i :class="mobileMenuOpen ? 'bi bi-x-lg' : 'bi bi-list'"></i>
            </button>

          </div>

        </div>
      </div>
    </div>

    <!-- GAVETA MOBILE DROPDOWN -->
    <transition name="menu-slide">
      <nav v-show="mobileMenuOpen" class="mobile-nav-drawer">
        <div class="app-container">
          
          <!-- Apresentação do usuário no Mobile -->
          <div v-if="showStaffNav" class="mobile-user-greeting">
            <div class="mobile-avatar">
              <i class="bi bi-person-fill"></i>
            </div>
            <div>
              <div class="mobile-name">Olá, {{ primeiroEUltimoNome }}</div>
              <span class="user-role-tag" :class="'badge-role-' + (currentUser?.roles?.[0] || currentUser?.role)">
                <i class="bi bi-patch-check-fill me-1"></i>
                {{ rolePrincipalLabel }}
              </span>
            </div>
          </div>

          <ul class="mobile-nav-list">
            <li v-if="!showStaffNav">
              <router-link to="/" class="mobile-nav-link" @click="mobileMenuOpen = false">
                <i class="bi bi-house-door me-2 text-cyan"></i>
                <span>Início / Resgate de Ingressos</span>
              </router-link>
            </li>

            <li v-if="!showStaffNav">
              <router-link to="/meu-ingresso" class="mobile-nav-link" @click="mobileMenuOpen = false">
                <i class="bi bi-ticket-detailed me-2 text-cyan"></i>
                <span>Meu Ingresso / Consultar</span>
              </router-link>
            </li>

            <li v-if="!isAuthenticated">
              <router-link to="/meus-premios" class="mobile-nav-link" @click="mobileMenuOpen = false">
                <i class="bi bi-gift-fill me-2 text-gold"></i>
                <span>Consultar Meus Prêmios</span>
              </router-link>
            </li>

            <!-- Seção Operacional no Mobile -->
            <template v-if="showStaffNav">
              <li class="mobile-section-header">
                <span>PAINEL OPERACIONAL</span>
              </li>

              <li v-if="isAdmin">
                <router-link to="/admin" class="mobile-nav-link" exact @click="mobileMenuOpen = false">
                  <i class="bi bi-speedometer2 me-2 text-magenta"></i>
                  <span>Gestão de Lotes</span>
                </router-link>
              </li>

              <li v-if="isValidador">
                <router-link to="/admin/validacoes" class="mobile-nav-link" @click="mobileMenuOpen = false">
                  <i class="bi bi-person-check-fill me-2 text-emerald"></i>
                  <span>Validações de Servidores</span>
                </router-link>
              </li>

              <li v-if="isAdminGeral">
                <router-link to="/admin/documentos-legais" class="mobile-nav-link" @click="mobileMenuOpen = false">
                  <i class="bi bi-file-earmark-lock me-2 text-cyan"></i><span>Documentos Legais</span>
                </router-link>
              </li>

              <li v-if="isAdmin">
                <router-link to="/admin/participantes" class="mobile-nav-link" @click="mobileMenuOpen = false">
                  <i class="bi bi-ticket-perforated-fill me-2 text-emerald"></i>
                  <span>Participantes & Presença</span>
                </router-link>
              </li>

              <li v-if="isAdmin">
                <router-link to="/admin/cancelamentos" class="mobile-nav-link" @click="mobileMenuOpen = false">
                  <i class="bi bi-person-x-fill me-2 text-danger"></i>
                  <span>Cancelamentos de Ingressos</span>
                </router-link>
              </li>

              <li v-if="isAdmin">
                <router-link to="/admin/usuarios" class="mobile-nav-link" @click="mobileMenuOpen = false">
                  <i class="bi bi-person-gear me-2 text-purple"></i>
                  <span>Equipe & Permissões</span>
                </router-link>
              </li>

              <li v-if="isAdmin">
                <router-link to="/admin/sorteios" class="mobile-nav-link" @click="mobileMenuOpen = false">
                  <i class="bi bi-trophy-fill me-2 text-gold"></i>
                  <span>Mesa de Sorteios</span>
                </router-link>
              </li>

              <li v-if="isPortaria">
                <router-link to="/portaria" class="mobile-nav-link" @click="mobileMenuOpen = false">
                  <i class="bi bi-qr-code-scan me-2 text-cyan"></i>
                  <span>Portaria & Scanner</span>
                </router-link>
              </li>

              <li v-if="isEntregador">
                <router-link to="/admin/entregas" class="mobile-nav-link" @click="mobileMenuOpen = false">
                  <i class="bi bi-camera-fill me-2 text-amber"></i>
                  <span>Registro de Entregas</span>
                </router-link>
              </li>
            </template>



            <li class="mobile-divider"></li>

            <li>
              <router-link v-if="!showStaffNav" to="/login" class="mobile-nav-link text-cyan" @click="mobileMenuOpen = false">
                <i class="bi bi-shield-lock-fill me-2"></i>
                <span>Acesso Staff</span>
              </router-link>
              <a v-else href="/logout" class="mobile-nav-link text-danger" @click.prevent="handleLogout">
                <i class="bi bi-box-arrow-right me-2"></i>
                <span>Encerrar Sessão</span>
              </a>
            </li>
          </ul>

        </div>
      </nav>
    </transition>

  </header>
</template>
