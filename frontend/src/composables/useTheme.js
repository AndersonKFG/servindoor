import { ref, computed } from 'vue'

const THEME_STORAGE_KEY = 'festa_servidor_theme'

// Limpa qualquer configuração residual de tema claro do localStorage
if (typeof window !== 'undefined') {
  try {
    localStorage.removeItem(THEME_STORAGE_KEY)
  } catch {}

  // Garante a aplicação exclusiva do tema escuro no documento
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', 'dark')
    document.documentElement.classList.remove('theme-light')
    document.documentElement.classList.add('theme-dark')
    if (document.body) {
      document.body.classList.remove('theme-light')
      document.body.classList.add('theme-dark')
    }
  }
}

const currentTheme = ref('dark')

export function useTheme() {
  const isDark = computed(() => true)
  const isLight = computed(() => false)

  return {
    theme: currentTheme,
    isDark,
    isLight
  }
}
