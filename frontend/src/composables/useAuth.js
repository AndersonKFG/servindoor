import { ref, computed } from 'vue'

const currentUser = ref(null)
const isCheckingAuth = ref(false)
const hasCheckedAuth = ref(false)
const sessaoSubstituida = ref(false)
let authPromise = null

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
  const isValidador = computed(() => hasRole('admin_geral', 'admin', 'validador'))
  const isStaff = computed(() => {
    return userRoles.value.some(r => ['admin_geral', 'admin', 'portaria', 'entregador', 'validador'].includes(r))
  })

  async function checkAuth(force = false) {
    if (authPromise) return authPromise
    if (hasCheckedAuth.value && !force) return currentUser.value

    authPromise = (async () => {
      try {
        isCheckingAuth.value = true
        const res = await fetch('/api/auth/me', { credentials: 'same-origin', cache: 'no-store' })
        if (res.ok) {
          const data = await res.json()
          if (data.autenticado && data.usuario) {
            currentUser.value = data.usuario
            sessaoSubstituida.value = false
          } else {
            currentUser.value = null
          }
        } else {
          const errData = await res.json().catch(() => ({}))
          if (errData.sessao_substituida) {
            sessaoSubstituida.value = true
          }
          currentUser.value = null
        }
      } catch {
        currentUser.value = null
      } finally {
        isCheckingAuth.value = false
        hasCheckedAuth.value = true
        authPromise = null
      }

      return currentUser.value
    })()

    return authPromise
  }

  function clearAuth() {
    currentUser.value = null
    hasCheckedAuth.value = false
    sessaoSubstituida.value = false
    authPromise = null
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
    isValidador,
    sessaoSubstituida,
    hasRole,
    checkAuth,
    clearAuth
  }
}
