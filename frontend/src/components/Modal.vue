<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

// Gerenciamento global de travamento de tela e restauração de foco
function getOpenModalsCount() {
  return window.__servindoorOpenModals || 0
}

function setOpenModalsCount(val) {
  window.__servindoorOpenModals = val
}

const currentZIndex = ref(9999)

function lockBackground() {
  const current = getOpenModalsCount()
  setOpenModalsCount(current + 1)
  // Cada modal aberto recebe um z-index incremental garantindo empilhamento perfeito
  currentZIndex.value = 10000 + (current * 20)

  if (current === 0) {
    window.__servindoorPrevFocus = document.activeElement
    const appEl = document.getElementById('app')
    if (appEl) {
      appEl.setAttribute('inert', '')
      appEl.setAttribute('aria-hidden', 'true')
    }
    document.documentElement.classList.add('modal-open')
    document.body.classList.add('modal-open')
  }
}

function unlockBackground() {
  const current = Math.max(0, getOpenModalsCount() - 1)
  setOpenModalsCount(current)

  if (current === 0) {
    const appEl = document.getElementById('app')
    if (appEl) {
      appEl.removeAttribute('inert')
      appEl.removeAttribute('aria-hidden')
    }
    document.documentElement.classList.remove('modal-open')
    document.body.classList.remove('modal-open')

    const prevFocus = window.__servindoorPrevFocus
    if (prevFocus && typeof prevFocus.focus === 'function') {
      try {
        prevFocus.focus()
      } catch (err) {}
    }
  }
}

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  title: {
    type: String,
    default: ''
  },
  icon: {
    type: String,
    default: ''
  },
  iconColor: {
    type: String,
    default: 'text-primary'
  },
  maxWidth: {
    type: String,
    default: '540px'
  },
  dismissible: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['close'])
const modalContentRef = ref(null)

function handleBackdropClick(e) {
  if (props.dismissible && e.target === e.currentTarget) {
    emit('close')
  }
}

function handleKeyDown(e) {
  if (!props.show) return

  if (e.key === 'Escape') {
    // Apenas o modal mais ao topo da pilha responde ao Escape
    const topZIndex = 10000 + ((getOpenModalsCount() - 1) * 20)
    if (currentZIndex.value < topZIndex) {
      return
    }
    e.preventDefault()
    e.stopPropagation()
    if (props.dismissible) emit('close')
    return
  }

  // Focus Trap no Tab / Shift+Tab
  if (e.key === 'Tab') {
    const container = modalContentRef.value
    if (!container) return

    const focusableSelectors = [
      'a[href]',
      'button:not([disabled])',
      'textarea:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      '[tabindex]:not([tabindex="-1"])'
    ].join(',')

    const focusables = Array.from(container.querySelectorAll(focusableSelectors))
      .filter(el => el.offsetParent !== null && !el.hasAttribute('disabled'))

    if (focusables.length === 0) {
      e.preventDefault()
      container.focus()
      return
    }

    const firstEl = focusables[0]
    const lastEl = focusables[focusables.length - 1]

    if (e.shiftKey) {
      if (document.activeElement === firstEl || !container.contains(document.activeElement)) {
        e.preventDefault()
        lastEl.focus()
      }
    } else {
      if (document.activeElement === lastEl || !container.contains(document.activeElement)) {
        e.preventDefault()
        firstEl.focus()
      }
    }
  }
}

watch(() => props.show, (newVal) => {
  if (newVal) {
    lockBackground()
    window.addEventListener('keydown', handleKeyDown)
    nextTick(() => {
      if (!modalContentRef.value) return
      const focusables = modalContentRef.value.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      if (focusables.length > 0) {
        focusables[0].focus()
      } else {
        modalContentRef.value.focus()
      }
    })
  } else {
   window.removeEventListener('keydown', handleKeyDown)
    unlockBackground()
  }
})

onMounted(() => {
  if (props.show) {
    lockBackground()
    window.addEventListener('keydown', handleKeyDown)
    nextTick(() => {
      modalContentRef.value?.focus()
    })
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
  if (props.show) {
    unlockBackground()
  }
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="modal-backdrop-custom"
      :style="{ zIndex: currentZIndex }"
      @click="handleBackdropClick"
      @wheel.stop.prevent
      @touchmove.stop.prevent
    >
      <div
        ref="modalContentRef"
        class="modal-content-custom"
        :style="{ maxWidth }"
        tabindex="-1"
        role="dialog"
        aria-modal="true"
        @click.stop
        @wheel.stop
        @touchmove.stop
      >
        <div class="modal-header-custom">
          <h3 class="modal-title font-outfit">
            <i v-if="icon" :class="[ icon, iconColor, 'me-2' ]"></i>
            <span>{{ title }}</span>
          </h3>
          <button v-if="dismissible" type="button" class="btn-close-custom" aria-label="Fechar" @click="emit('close')">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>

        <div class="modal-body-custom">
          <slot></slot>
        </div>

        <div v-if="$slots.footer" class="modal-footer-custom">
          <slot name="footer"></slot>
        </div>
      </div>
    </div>
  </Teleport>
</template>
