<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const router = useRouter()
const route = useRoute()
const { currentUser, isAuthenticated, isStaff, isAdminGeral, isAdmin, isPortaria, isEntregador, checkAuth, clearAuth } = useAuth()
const mobileMenuOpen = ref(false)

onMounted(async () => {
  await checkAuth()
})

watch(
  () => route.path,
  async () => {
    mobileMenuOpen.value = false
    await checkAuth()
  }
)

const showStaffNav = computed(() => {
  return isStaff.value || ['/admin', '/portaria'].some(p => route.path.startsWith(p))
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
    
    <!-- 1. BARRA PRINCIPAL SUPERIOR (MAIN NAV) -->
    <div class="navbar-main">
      <div class="app-container">
        <div class="navbar-main-inner">
          
          <!-- Logo Oficial Servindoor -->
          <router-link to="/" class="navbar-brand" @click="mobileMenuOpen = false">
            <img
              src="/images/logo_servindoor_sem-fundo.png"
              alt="Servindoor • A Festa do Servidor 2026"
              class="navbar-logo-img"
            />
          </router-link>

          <!-- Botão Hamburger no Mobile -->
          <button
            type="button"
            class="navbar-toggle-btn"
            :class="{ 'active': mobileMenuOpen }"
            aria-label="Abrir Menu"
            @click="toggleMobileMenu"
          >
            <i :class="mobileMenuOpen ? 'bi bi-x-lg' : 'bi bi-list'"></i>
          </button>

          <!-- Área Direita Desktop -->
          <div class="desktop-main-actions">
            
            <!-- VISITANTE NÃO AUTENTICADO -->
            <ul v-if="!showStaffNav" class="navbar-nav-guest">
              <li>
                <router-link to="/" class="nav-link-guest">
                  <i class="bi bi-house-door"></i>
                  <span>Início</span>
                </router-link>
              </li>

              <li v-if="!isAuthenticated">
                <router-link to="/meus-premios" class="nav-link-guest nav-link-highlight">
                  <i class="bi bi-gift-fill text-gold"></i>
                  <span>Meus Prêmios</span>
                </router-link>
              </li>

              <li>
                <router-link to="/login" class="btn-staff-access">
                  <i class="bi bi-shield-lock-fill"></i>
                  <span>Acesso Staff</span>
                </router-link>
              </li>
            </ul>

            <!-- USUÁRIO EQUIPE AUTENTICADO: APRESENTAÇÃO E LOGOUT -->
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

          </div>

        </div>
      </div>
    </div>

    <!-- 2. SUBNAV OPERACIONAL (EXCLUSIVA PARA EQUIPE LOGADA) -->
    <nav v-if="showStaffNav" class="navbar-subnav">
      <div class="app-container">
        <ul class="subnav-list">
          
          <!-- Gestão de Lotes (Admin Geral) -->
          <li v-if="isAdminGeral">
            <router-link to="/admin" class="subnav-link link-lotes" exact>
              <i class="bi bi-speedometer2"></i>
              <span>Lotes</span>
            </router-link>
          </li>

          <!-- Participantes (Admin & Admin Geral) -->
          <li v-if="isAdmin">
            <router-link to="/admin/participantes" class="subnav-link link-participantes">
              <i class="bi bi-ticket-perforated-fill"></i>
              <span>Participantes</span>
            </router-link>
          </li>

          <!-- Equipe & Acessos (Admin & Admin Geral) -->
          <li v-if="isAdmin">
            <router-link to="/admin/usuarios" class="subnav-link link-equipe">
              <i class="bi bi-person-gear"></i>
              <span>Equipe</span>
            </router-link>
          </li>

          <!-- Mesa de Sorteios (Admin & Admin Geral) -->
          <li v-if="isAdmin">
            <router-link to="/admin/sorteios" class="subnav-link link-sorteios">
              <i class="bi bi-trophy-fill"></i>
              <span>Sorteios</span>
            </router-link>
          </li>

          <!-- Portaria & Scanner (Portaria, Admin, Admin Geral) -->
          <li v-if="isPortaria">
            <router-link to="/portaria" class="subnav-link link-portaria">
              <i class="bi bi-qr-code-scan"></i>
              <span>Portaria</span>
            </router-link>
          </li>

          <!-- Registro de Entregas (Entregador, Admin, Admin Geral) -->
          <li v-if="isEntregador">
            <router-link to="/admin/entregas" class="subnav-link link-entregas">
              <i class="bi bi-camera-fill"></i>
              <span>Entregas</span>
            </router-link>
          </li>

        </ul>
      </div>
    </nav>

    <!-- 3. GAVETA MOBILE DROPDOWN -->
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
              <span class="user-role-tag">{{ rolePrincipalLabel }}</span>
            </div>
          </div>

          <ul class="mobile-nav-list">
            
            <li v-if="!showStaffNav">
              <router-link to="/" class="mobile-nav-link" @click="mobileMenuOpen = false">
                <i class="bi bi-house-door me-2 text-cyan"></i>
                <span>Início / Resgate de Ingressos</span>
              </router-link>
            </li>

            <li v-if="!isAuthenticated">
              <router-link to="/meus-premios" class="mobile-nav-link" @click="mobileMenuOpen = false">
                <i class="bi bi-gift-fill me-2 text-gold"></i>
                <span>Consultar Meus Prêmios</span>
              </router-link>
            </li>

            <!-- Seção Subnav no Mobile -->
            <template v-if="showStaffNav">
              <li class="mobile-section-header">
                <span>PAINEL OPERACIONAL</span>
              </li>

              <li v-if="isAdminGeral">
                <router-link to="/admin" class="mobile-nav-link" exact @click="mobileMenuOpen = false">
                  <i class="bi bi-speedometer2 me-2 text-magenta"></i>
                  <span>Gestão de Lotes</span>
                </router-link>
              </li>

              <li v-if="isAdmin">
                <router-link to="/admin/participantes" class="mobile-nav-link" @click="mobileMenuOpen = false">
                  <i class="bi bi-ticket-perforated-fill me-2 text-emerald"></i>
                  <span>Participantes & Presença</span>
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
                  <i class="bi bi-camera-fill me-2 text-copper"></i>
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

<style scoped>
.navbar-wrapper {
  position: sticky;
  top: 0;
  z-index: 1000;
  background: rgba(7, 9, 14, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

/* 1. BARRA PRINCIPAL SUPERIOR */
.navbar-main {
  padding: 8px 0;
}

.navbar-main-inner {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.navbar-brand {
  display: flex;
  align-items: center;
  text-decoration: none;
  transition: transform 0.2s ease;
}

.navbar-brand:hover {
  transform: scale(1.02);
}

.navbar-logo-img {
  height: 52px;
  max-width: 180px;
  object-fit: contain;
  filter: drop-shadow(0 2px 8px rgba(217, 70, 239, 0.25));
}

@media (max-width: 576px) {
  .navbar-logo-img {
    height: 42px;
    max-width: 140px;
  }
}

/* ÁREA DIREITA DESKTOP */
.desktop-main-actions {
  display: flex;
  align-items: center;
}

.navbar-nav-guest {
  display: flex;
  align-items: center;
  gap: 10px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.nav-link-guest {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 0.88rem;
  padding: 7px 12px;
  border-radius: 10px;
  text-decoration: none;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.nav-link-guest:hover,
.nav-link-guest.router-link-active {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
}

.nav-link-highlight {
  color: #fde047;
}

.btn-staff-access {
  background: rgba(6, 182, 212, 0.12);
  border: 1px solid rgba(6, 182, 212, 0.35);
  color: #22d3ee;
  font-weight: 700;
  font-size: 0.84rem;
  padding: 7px 14px;
  border-radius: 10px;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}

.btn-staff-access:hover {
  background: rgba(6, 182, 212, 0.25);
  border-color: #22d3ee;
  color: #ffffff;
  transform: translateY(-1px);
}

/* APRESENTAÇÃO AO USUÁRIO LOGADO */
.user-greeting-box {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 14px;
  padding: 5px 12px 5px 6px;
}

.user-avatar-badge {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--serv-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 1.15rem;
  box-shadow: 0 4px 12px rgba(217, 70, 239, 0.35);
}

.user-info-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.greeting-line {
  font-size: 0.86rem;
  color: #ffffff;
}

.greeting-prefix {
  color: var(--text-muted);
  margin-right: 4px;
}

.user-full-name {
  font-weight: 800;
  background: var(--serv-text-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.user-role-tag {
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 1px 7px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  width: fit-content;
  margin-top: 2px;
  background: rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
}

.badge-role-admin_geral {
  background: rgba(239, 68, 68, 0.2);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.35);
}

.badge-role-admin {
  background: rgba(168, 85, 247, 0.2);
  color: #c084fc;
  border: 1px solid rgba(168, 85, 247, 0.35);
}

.badge-role-portaria {
  background: rgba(6, 182, 212, 0.2);
  color: #22d3ee;
  border: 1px solid rgba(6, 182, 212, 0.35);
}

.badge-role-entregador {
  background: rgba(245, 158, 11, 0.2);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.btn-logout-header {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #fca5a5;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: all 0.2s ease;
  margin-left: 4px;
}

.btn-logout-header:hover {
  background: #ef4444;
  color: #ffffff;
  transform: translateY(-1px);
}

/* 2. SUBNAV OPERACIONAL */
.navbar-subnav {
  background: rgba(11, 15, 25, 0.88);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  padding: 6px 0;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.subnav-list {
  display: flex;
  align-items: center;
  gap: 8px;
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.subnav-list::-webkit-scrollbar {
  display: none;
}

.subnav-link {
  color: var(--text-muted);
  font-weight: 700;
  font-size: 0.82rem;
  padding: 7px 14px;
  border-radius: 999px;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}

.subnav-link:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.06);
}

.subnav-link.router-link-active {
  background: var(--serv-gradient);
  color: #ffffff;
  box-shadow: 0 4px 14px rgba(217, 70, 239, 0.35);
  border-color: rgba(255, 255, 255, 0.2);
}

/* BOTÃO TOGGLE MOBILE */
.navbar-toggle-btn {
  display: none;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #ffffff;
  font-size: 1.35rem;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.navbar-toggle-btn:hover,
.navbar-toggle-btn.active {
  background: rgba(255, 255, 255, 0.15);
  border-color: #06b6d4;
  color: #06b6d4;
}

/* GAVETA MOBILE */
.mobile-nav-drawer {
  display: none;
  background: #07090e;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding: 16px 0 20px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8);
}

.mobile-user-greeting {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  margin-bottom: 14px;
}

.mobile-avatar {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--serv-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  color: #ffffff;
}

.mobile-name {
  font-weight: 800;
  font-size: 0.95rem;
  color: #ffffff;
}

.mobile-nav-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mobile-nav-link {
  display: flex;
  align-items: center;
  color: #cbd5e1;
  text-decoration: none;
  font-size: 0.92rem;
  font-weight: 600;
  padding: 11px 14px;
  border-radius: 12px;
  transition: all 0.15s ease;
}

.mobile-nav-link:hover,
.mobile-nav-link.router-link-active {
  background: rgba(255, 255, 255, 0.08);
  color: #06b6d4;
}

.mobile-section-header {
  margin-top: 10px;
  padding-left: 8px;
}

.mobile-section-header span {
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #64748b;
}

.mobile-divider {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  margin: 8px 0;
}

.menu-slide-enter-active,
.menu-slide-leave-active {
  transition: all 0.25s ease-out;
}

.menu-slide-enter-from,
.menu-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.text-gold { color: var(--serv-gold) !important; }
.text-cyan { color: var(--serv-cyan) !important; }
.text-magenta { color: var(--serv-magenta) !important; }
.text-emerald { color: var(--serv-emerald) !important; }
.text-purple { color: var(--serv-purple) !important; }
.text-copper { color: var(--serv-copper) !important; }
.text-danger { color: #f87171 !important; }

/* RESPONSIVIDADE */
@media (max-width: 900px) {
  .navbar-toggle-btn {
    display: flex;
  }
  .desktop-main-actions {
    display: none;
  }
  .mobile-nav-drawer {
    display: block;
  }
}
</style>
