<script setup>
defineProps({
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
  }
})

const emit = defineEmits(['close'])

function handleBackdropClick(e) {
  if (e.target === e.currentTarget) {
    emit('close')
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="modal-backdrop-custom" @click="handleBackdropClick">
      <div class="modal-content-custom" :style="{ maxWidth }">
        <div class="modal-header-custom">
          <h3 class="modal-title font-outfit">
            <i v-if="icon" :class="[icon, iconColor, 'me-2']"></i>
            <span>{{ title }}</span>
          </h3>
          <button type="button" class="btn-close-custom" @click="emit('close')">
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

<style scoped>
.modal-title {
  font-size: 1.15rem;
  font-weight: 700;
  color: #ffffff;
  display: flex;
  align-items: center;
}

.btn-close-custom {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 1rem;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close-custom:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.1);
}

.me-2 {
  margin-right: 8px;
}
.text-primary { color: var(--primary-accent); }
.text-warning { color: var(--warning-color); }
.text-danger { color: var(--danger-color); }
.text-success { color: var(--success-color); }
</style>
