import { ref } from 'vue'

const toasts = ref([])
let nextId = 1

export function useToast() {
  function addToast({ message, title = '', type = 'info', duration = 4500 }) {
    const id = nextId++
    const toast = { id, message, title, type, duration }
    toasts.value.push(toast)

    if (duration > 0) {
      setTimeout(() => {
        removeToast(id)
      }, duration)
    }

    return id
  }

  function removeToast(id) {
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx !== -1) {
      toasts.value.splice(idx, 1)
    }
  }

  const toast = {
    success(message, title = 'Sucesso', duration = 4000) {
      return addToast({ message, title, type: 'success', duration })
    },
    error(message, title = 'Atenção', duration = 6000) {
      return addToast({ message, title, type: 'error', duration })
    },
    warning(message, title = 'Aviso', duration = 5000) {
      return addToast({ message, title, type: 'warning', duration })
    },
    info(message, title = 'Informação', duration = 4500) {
      return addToast({ message, title, type: 'info', duration })
    }
  }

  return {
    toasts,
    addToast,
    removeToast,
    toast
  }
}