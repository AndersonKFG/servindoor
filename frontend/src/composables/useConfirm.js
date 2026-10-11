import { ref } from 'vue'

const confirmState = ref({
  isOpen: false,
  title: 'Confirmação',
  message: '',
  confirmText: 'Confirmar',
  cancelText: 'Cancelar',
  variant: 'danger',
  resolve: null
})

export function useConfirm() {
  function confirmModal({
    title = 'Confirmação',
    message = '',
    confirmText = 'Confirmar',
    cancelText = 'Cancelar',
    variant = 'danger'
  }) {
    return new Promise((resolve) => {
      confirmState.value = {
        isOpen: true,
        title,
        message,
        confirmText,
        cancelText,
        variant,
        resolve
      }
    })
  }

  function handleConfirm() {
    if (confirmState.value.resolve) {
      confirmState.value.resolve(true)
    }
    confirmState.value.isOpen = false
  }

  function handleCancel() {
    if (confirmState.value.resolve) {
      confirmState.value.resolve(false)
    }
    confirmState.value.isOpen = false
  }

  return {
    confirmState,
    confirmModal,
    handleConfirm,
    handleCancel
  }
}