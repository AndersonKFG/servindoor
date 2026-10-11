<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useConfirm } from '../composables/useConfirm'

const { confirmState, handleConfirm, handleCancel } = useConfirm()

const confirmCardRef = ref(null)
const confirmBtnRef = ref(null)

function handleKeyDown(e) {
  if (!confirmState.value.isOpen) return

  if (e.key === 'Escape') {
    e.stopPropagation()
    e.stopImmediatePropagation()
    handleCancel()
    return
  }

  if (e.key === 'Tab') {
    const container = confirmCardRef.value
    if (!container) return

    const focusables = Array.from(
      container.querySelectorAll('button:not([disabled])')
    )
    if (focusables.length === 0) return

    const firstEl = focusables[0]
    const lastEl = focusables[focusables.length - 1]

    if (e.shiftKey) {
      if (document.activeElement === firstEl || !container.contains(document.activeElement)) {
        e.preventDefault()
        e.stopPropagation()
        lastEl.focus()
      }
    } else {
      if (document.activeElement === lastEl || !container.contains(document.activeElement)) {
        e.preventDefault()
        e.stopPropagation()
        firstEl.focus()
      }
    }
  }
}

watch(() => confirmState.value.isOpen, (open) => {
  if (open) {
    nextTick(() => {
      confirmBtnRef.value?.focus()
    })
  }
})

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown, true)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown, true)
})
</script>

<template>
  <Teleport to="body">
    <transition name="confirm-fade">
      <div
        v-if="confirmState.isOpen"
        class="confirm-modal-overlay"
        @click.self="handleCancel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
      >
        <div ref="confirmCardRef" class="confirm-modal-card" :class="'confirm-' + confirmState.variant">
          <div class="confirm-modal-header">
            <div class="confirm-icon-box">
              <!-- DANGER -->
              <svg v-if="confirmState.variant === 'danger'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                <line x1="12" y1="9" x2="12" y2="13"></line>
                <line x1="12" y1="17" x2="12.01" y2="17"></line>
              </svg>
              <!-- WARNING -->
              <svg v-else-if="confirmState.variant === 'warning'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
              <!-- PRIMARY / INFO -->
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="16" x2="12" y2="12"></line>
                <line x1="12" y1="8" x2="12.01" y2="8"></line>
              </svg>
            </div>
            <div>
              <h3 id="confirm-modal-title" class="confirm-modal-title font-outfit">{{ confirmState.title }}</h3>
              <p class="confirm-modal-meta">Confirmação de ação</p>
            </div>
          </div>

          <div class="confirm-modal-body">
            <p class="confirm-modal-text">{{ confirmState.message }}</p>
          </div>

          <div class="confirm-modal-actions">
            <button
              type="button"
              class="btn-cancel font-outfit"
              @click="handleCancel"
            >
              {{ confirmState.cancelText || 'Cancelar' }}
            </button>
            <button
              ref="confirmBtnRef"
              type="button"
              :class="['btn-confirm font-outfit', 'btn-confirm-' + confirmState.variant]"
              @click="handleConfirm"
            >
              {{ confirmState.confirmText || 'Confirmar' }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>
