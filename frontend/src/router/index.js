import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { useToast } from '../composables/useToast'

import AcessoPinView from '../views/AcessoPinView.vue'
import HomeView from '../views/HomeView.vue'
import ResgateView from '../views/ResgateView.vue'
import SucessoView from '../views/SucessoView.vue'
import LoginView from '../views/LoginView.vue'
import AdminView from '../views/AdminView.vue'
import AdminParticipantesView from '../views/AdminParticipantesView.vue'
import AdminUsuariosView from '../views/AdminUsuariosView.vue'
import LoteIngressosView from '../views/LoteIngressosView.vue'
import PortariaView from '../views/PortariaView.vue'
import ErroView from '../views/ErroView.vue'

// Views do Sistema de Sorteios
import TelaoView from '../views/TelaoView.vue'
import AdminSorteiosView from '../views/AdminSorteiosView.vue'
import EntregaPremiosView from '../views/EntregaPremiosView.vue'
import MeusPremiosView from '../views/MeusPremiosView.vue'
import MeuIngressoView from '../views/MeuIngressoView.vue'
import AdminCancelamentosView from '../views/AdminCancelamentosView.vue'
import AdminValidacoesView from '../views/AdminValidacoesView.vue'
import CorrigirFotoView from '../views/CorrigirFotoView.vue'

const routes = [
  // Rotas Públicas (Sem necessidade de Login)
  {
    path: '/corrigir-foto',
    name: 'corrigir-foto',
    component: CorrigirFotoView,
    meta: { hideNav: true }
  },
  {
    path: '/acesso',
    name: 'acesso',
    component: AcessoPinView,
    meta: { publicoGatekeeper: true, hideNav: true }
  },
  { path: '/', name: 'home', component: HomeView },
  { path: '/resgate/:loteId', name: 'resgate', component: ResgateView },
  { path: '/sucesso/analise', name: 'sucesso-analise', component: SucessoView },
  { path: '/sucesso/:ingressoId', name: 'sucesso', component: SucessoView },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/meu-ingresso', name: 'meu-ingresso', component: MeuIngressoView },
  { path: '/meus-premios', name: 'meus-premios', component: MeusPremiosView },
  { path: '/erro', name: 'erro', component: ErroView },
  { path: '/telao', name: 'telao', component: TelaoView, meta: { hideNav: true } },

  // Rotas Restritas - Equipe e Administradores (Exigem Login e Validação de Cargo)
  {
    path: '/admin',
    name: 'admin',
    component: AdminView,
    meta: { requiresAuth: true, roles: ['admin_geral'] }
  },
  {
    path: '/admin/participantes',
    name: 'admin-participantes',
    component: AdminParticipantesView,
    meta: { requiresAuth: true, roles: ['admin_geral', 'admin'] }
  },
  {
    path: '/admin/usuarios',
    name: 'admin-usuarios',
    component: AdminUsuariosView,
    meta: { requiresAuth: true, roles: ['admin_geral', 'admin'] }
  },
  {
    path: '/admin/lote/:loteId/ingressos',
    name: 'admin-lote-ingressos',
    component: LoteIngressosView,
    meta: { requiresAuth: true, roles: ['admin_geral', 'admin'] }
  },
  {
    path: '/admin/sorteios',
    name: 'admin-sorteios',
    component: AdminSorteiosView,
    meta: { requiresAuth: true, roles: ['admin_geral', 'admin'] }
  },
  {
    path: '/admin/cancelamentos',
    name: 'admin-cancelamentos',
    component: AdminCancelamentosView,
    meta: { requiresAuth: true, roles: ['admin_geral', 'admin'] }
  },
  {
    path: '/admin/validacoes',
    name: 'admin-validacoes',
    component: AdminValidacoesView,
    meta: { requiresAuth: true, roles: ['admin_geral', 'admin', 'validador'] }
  },
  {
    path: '/admin/entregas',
    name: 'admin-entregas',
    component: EntregaPremiosView,
    meta: { requiresAuth: true, roles: ['admin_geral', 'admin', 'entregador'] }
  },
  {
    path: '/portaria',
    name: 'portaria',
    component: PortariaView,
    meta: { requiresAuth: true, roles: ['admin_geral', 'admin', 'portaria'] }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Interceptador Global do Gatekeeper e Proteção de Autenticação / RBAC
let gatekeeperChecked = false
let gatekeeperEnabled = true

router.beforeEach(async (to, from, next) => {
  // O token pessoal recebido por e-mail autoriza exclusivamente a troca de foto.
  if (to.name === 'corrigir-foto') return next()

  // 1. REGRA ESTRITA DO TELÃO: sempre exige autenticação pelo SITE_ACCESS_PIN
  if (to.path === '/telao') {
    const telaoAuth = sessionStorage.getItem('servindoor_telao_pin_autorizado') || localStorage.getItem('servindoor_telao_pin_autorizado')
    if (telaoAuth !== 'true') {
      return next({
        path: '/acesso',
        query: { redirect: '/telao' }
      })
    }
    return next()
  }

  // 2. Se o usuário está acessando a tela de código (/acesso)
  if (to.path === '/acesso') {
    if (to.query.redirect === '/telao') {
      const telaoAuth = sessionStorage.getItem('servindoor_telao_pin_autorizado') || localStorage.getItem('servindoor_telao_pin_autorizado')
      if (telaoAuth === 'true') {
        return next({ path: '/telao' })
      }
      return next()
    }

    const gateToken = localStorage.getItem('servindoor_gate_token')
    if (gateToken) {
      return next({ path: '/' })
    }
    return next()
  }

  let gateToken = localStorage.getItem('servindoor_gate_token')
  if (!gateToken && !gatekeeperChecked) {
    try {
      const res = await fetch('/api/gatekeeper/status')
      if (res.ok) {
        const data = await res.json()
        gatekeeperEnabled = data.gatekeeper_enabled !== false
        if (!gatekeeperEnabled || data.autorizado) {
          localStorage.setItem('servindoor_gate_token', 'autorizado')
          gateToken = 'autorizado'
        }
      }
    } catch {
      // Ignora falha de rede temporária
    } finally {
      gatekeeperChecked = true
    }
  }

  if (gatekeeperEnabled && !gateToken) {
    return next({
      path: '/acesso',
      query: { redirect: to.fullPath }
    })
  }

  // 3. PROTEÇÃO DE ROTAS ADMINISTRATIVAS E OPERACIONAIS (STAFF AUTH & ROLES)
  const isRestrictedRoute = to.matched.some(record => record.meta.requiresAuth) ||
    to.path.startsWith('/admin') ||
    to.path.startsWith('/portaria')

  if (isRestrictedRoute) {
    const { checkAuth, isAuthenticated, hasRole } = useAuth()
    const user = await checkAuth(true)

    if (!user || !isAuthenticated.value) {
      return next({
        path: '/login',
        query: { redirect: to.fullPath }
      })
    }

    if (user.deve_trocar_senha) {
      return next({
        path: '/login',
        query: { redirect: to.fullPath }
      })
    }

    // Validação estrita de papéis (Role-Based Access Control)
    const requiredRoles = to.meta.roles
    if (requiredRoles && requiredRoles.length > 0) {
      const permitida = hasRole(...requiredRoles)
      if (!permitida) {
        const { toast } = useToast()
        toast.warning(
          'O seu acesso a esta tela foi revogado, você será redirecionada para a tela inicial, onde poderá ver através do menu onde poderá acessar. Sua conta também pode ter sido desativada.',
          'Acesso Revogado',
          10000
        )
        return next({ path: '/' })
      }
    }

    return next()
  }

  // 4. Se usuário já autenticado tentar acessar a tela de login
  if (to.path === '/login') {
    const { checkAuth, isAuthenticated } = useAuth()
    const user = await checkAuth()
    if (user && isAuthenticated.value) {
      if (user.deve_trocar_senha) return next()
      const redirect = to.query.redirect
      if (redirect && typeof redirect === 'string' && redirect.startsWith('/') && redirect !== '/login') {
        return next({ path: redirect })
      }
      const roles = Array.isArray(user.roles) && user.roles.length > 0 ? user.roles : [user.role]
      if (roles.includes('admin_geral')) return next({ path: '/admin' })
      if (roles.includes('admin')) return next({ path: '/admin/participantes' })
      if (roles.includes('validador')) return next({ path: '/admin/validacoes' })
      if (roles.includes('portaria')) return next({ path: '/portaria' })
      if (roles.includes('entregador')) return next({ path: '/admin/entregas' })
      return next({ path: '/' })
    }
  }

  return next()
})

export default router
