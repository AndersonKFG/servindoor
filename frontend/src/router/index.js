import { createRouter, createWebHistory } from 'vue-router'

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

const routes = [
  {
    path: '/acesso',
    name: 'acesso',
    component: AcessoPinView,
    meta: { publicoGatekeeper: true, hideNav: true }
  },
  { path: '/', name: 'home', component: HomeView },
  { path: '/resgate/:loteId', name: 'resgate', component: ResgateView },
  { path: '/sucesso/:ingressoId', name: 'sucesso', component: SucessoView },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/admin', name: 'admin', component: AdminView },
  { path: '/admin/participantes', name: 'admin-participantes', component: AdminParticipantesView },
  { path: '/admin/usuarios', name: 'admin-usuarios', component: AdminUsuariosView },
  { path: '/admin/lote/:loteId/ingressos', name: 'admin-lote-ingressos', component: LoteIngressosView },
  { path: '/portaria', name: 'portaria', component: PortariaView },
  { path: '/erro', name: 'erro', component: ErroView },
  
  // Rotas do Sistema de Sorteios
  { path: '/telao', name: 'telao', component: TelaoView, meta: { hideNav: true } },
  { path: '/admin/sorteios', name: 'admin-sorteios', component: AdminSorteiosView },
  { path: '/admin/entregas', name: 'admin-entregas', component: EntregaPremiosView },
  { path: '/meus-premios', name: 'meus-premios', component: MeusPremiosView }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})


// Interceptador Global do Gatekeeper (Validação de Dispositivo por PIN)
router.beforeEach((to, from, next) => {
  const gateToken = localStorage.getItem('servindoor_gate_token')

  // Se o usuário está acessando a tela de código (/acesso)
  if (to.meta.publicoGatekeeper) {
    if (gateToken) {
      // Se o dispositivo já tem liberação, redireciona para a página principal
      return next({ path: '/' })
    }
    return next()
  }

  // Se o dispositivo ainda não foi liberado, redireciona imediatamente para /acesso
  // e memoriza a URL pretendida no parâmetro redirect
  if (!gateToken) {
    return next({
      path: '/acesso',
      query: { redirect: to.fullPath }
    })
  }

  next()
})

export default router
