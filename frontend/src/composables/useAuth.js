import { ref, computed } from 'vue'

const currentUser = ref(null)
const isCheckingAuth = ref(false)
const hasCheckedAuth = ref(false)

export function useAuth() {
  const isAuthenticated = computed(() => currentUser.value !== null)

  const userRoles = computed(() => {
    if (!currentUser.value) return []
    if (Array.isArray(currentUser.value.roles) && currentUser.value.roles.length > 0) {
      return currentUser.value.roles
    }
    if (currentUser.value.role) {
      return [currentUser.value.role]
    }
    return []
  })

  function hasRole(...roles) {
    if (!currentUser.value) return false
    if (userRoles.value.includes('admin_geral')) return true
    return roles.some(r => userRoles.value.includes(r))
  }

  const isAdminGeral = computed(() => userRoles.value.includes('admin_geral'))
  const isAdmin = computed(() => hasRole('admin_geral', 'admin'))
  const isPortaria = computed(() => hasRole('admin_geral', 'admin', 'portaria'))
  const isEntregador = computed(() => hasRole('admin_geral', 'admin', 'entregador'))
  const isStaff = computed(() => {
    return userRoles.value.some(r => ['admin_geral', 'admin', 'portaria', 'entregador', 'validador'].includes(r))
  })

  async function checkAuth(force = false) {
    if (isCheckingAuth.value) return currentUser.value
    if (hasCheckedAuth.value && !force) return currentUser.value

    try {
      isCheckingAuth.value = true
      const res = await fetch('/api/auth/me', { credentials: 'same-origin', cache: 'no-store' })
      if (res.ok) {
        const data = await res.json()
        if (data.autenticado && data.usuario) {
          currentUser.value = data.usuario
        } else {
          currentUser.value = null
        }
      } else {
        currentUser.value = null
      }
    } catch (e) {
      console.warn('Erro ao checar autenticação:', e)
      currentUser.value = null
    } finally {
      isCheckingAuth.value = false
      hasCheckedAuth.value = true
    }

    return currentUser.value
  }

  function clearAuth() {
    currentUser.value = null
    hasCheckedAuth.value = false
  }

  return {
    currentUser,
    userRoles,
    isAuthenticated,
    isStaff,
    isAdminGeral,
    isAdmin,
    isPortaria,
    isEntregador,
    hasRole,
    checkAuth,
    clearAuth
  }
}
