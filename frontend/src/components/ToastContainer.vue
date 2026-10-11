<script setup>
import { useToast } from '../composables/useToast'

const { toasts, removeToast } = useToast()
</script>

<template>
  <Teleport to="body">
    <div class="toast-stack-container" aria-live="polite" aria-atomic="true">
      <transition-group name="toast-slide">
        <div
          v-for="t in toasts"
          :key="t.id"
          :class="['toast-card', 'toast-' + t.type]"
          role="alert"
        >
          <div class="toast-icon-wrapper">
            <!-- SUCCESS -->
            <svg v-if="t.type === 'success'" class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
              <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
            <!-- ERROR / DANGER -->
            <svg v-else-if="t.type === 'error'" class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="15" y1="9" x2="9" y2="15"></line>
              <line x1="9" y1="9" x2="15" y2="15"></line>
            </svg>
            <!-- WARNING -->
            <svg v-else-if="t.type === 'warning'" class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <!-- INFO -->
            <svg v-else class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
          </div>

          <div class="toast-body">
            <h4 v-if="t.title" class="toast-title font-outfit">{{ t.title }}</h4>
            <p class="toast-message">{{ t.message }}</p>
          </div>

          <button
            type="button"
            class="toast-close-btn"
            @click="removeToast(t.id)"
            aria-label="Fechar notificação"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>

          <div
            v-if="t.duration > 0"
            class="toast-progress-bar"
            :style="{ animationDuration: t.duration + 'ms' }"
          ></div>
        </div>
      </transition-group>
    </div>
  </Teleport>
</template>
