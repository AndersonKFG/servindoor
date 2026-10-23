<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  requiresPassword: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'submit'])
const passwordInput = ref(null)
const characters = computed(() => Array.from(props.modelValue))

watch(() => props.requiresPassword && !props.loading, async ready => {
  if (ready) {
    await nextTick()
    passwordInput.value?.focus()
  }
}, { immediate: true })
</script>

<template>
  <section class="access-gate" aria-labelledby="exclusive-access-title">
    <div class="access-gate__card" :aria-busy="loading">
      <div class="access-gate__brand">
        <img src="/images/logo_servindoor_sem-fundo.png" alt="Serv indoor 2026" class="access-gate__logo" />
        <span class="access-gate__badge"><i class="bi bi-lock-fill" aria-hidden="true"></i> Acesso restrito</span>
      </div>

      <h1 id="exclusive-access-title" class="access-gate__title">Acesso exclusivo ao lote</h1>
      <p id="exclusive-access-description" class="access-gate__description">
        Informe a senha recebida para acessar o cadastro de participantes deste lote.
      </p>

      <form class="access-gate__form" @submit.prevent="emit('submit')">
        <div v-if="requiresPassword" class="access-gate__password">
          <label for="senha-acesso-lote" class="access-gate__label">Senha de acesso do lote</label>
          <div class="access-gate__code">
            <div class="access-gate__slots" aria-hidden="true">
              <span v-for="position in 6" :key="position" class="access-gate__slot" :class="{
                'access-gate__slot--filled': !!characters[position - 1],
                'access-gate__slot--active': position === Math.min(characters.length + 1, 6),
                'access-gate__slot--error': !!errorMessage
              }">{{ characters[position - 1] ? '•' : '' }}</span>
            </div>
            <input
              id="senha-acesso-lote"
              ref="passwordInput"
              :value="modelValue"
              class="access-gate__input"
              name="password"
              type="password"
              inputmode="text"
              minlength="6"
              maxlength="6"
              required
              autocomplete="current-password"
              autocapitalize="off"
              :spellcheck="false"
              :disabled="loading"
              :aria-invalid="!!errorMessage"
              :aria-describedby="errorMessage ? 'exclusive-access-hint exclusive-access-error' : 'exclusive-access-hint'"
              @input="emit('update:modelValue', $event.target.value)"
            />
          </div>
          <p id="exclusive-access-hint" class="access-gate__hint">6 caracteres: letras, números ou símbolos.</p>
        </div>

        <p v-if="errorMessage" id="exclusive-access-error" class="access-gate__error" role="alert">
          <i class="bi bi-exclamation-circle" aria-hidden="true"></i><span>{{ errorMessage }}</span>
        </p>
        <button type="submit" class="access-gate__submit" :disabled="loading || (requiresPassword && characters.length !== 6)">
          <span>{{ loading ? 'Verificando acesso...' : requiresPassword ? 'Liberar acesso' : 'Tentar novamente' }}</span>
          <i :class="['bi', loading ? 'bi-hourglass-split' : 'bi-arrow-right']" aria-hidden="true"></i>
        </button>
      </form>

      <p class="access-gate__footer"><i class="bi bi-shield-lock" aria-hidden="true"></i> Acesso exclusivo para cadastro de participantes.</p>
    </div>
  </section>
</template>
