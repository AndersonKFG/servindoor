<script setup>
import { onMounted, ref } from 'vue'

defineProps({ modelValue: Object })
const emit = defineEmits(['update:modelValue'])
const documents = ref([])
const required = ref(false)
const error = ref('')
const loaded = ref(false)

function update() {
  emit('update:modelValue', {
    loaded: loaded.value, required: required.value,
    termsId: documents.value.find(doc => doc.kind === 'terms')?.id,
    privacyId: documents.value.find(doc => doc.kind === 'privacy')?.id
  })
}
onMounted(async () => {
  try {
    const res = await fetch('/api/legal/current', { cache: 'no-store' })
    if (!res.ok) throw new Error()
    const data = await res.json()
    documents.value = data.documents
    required.value = data.require_on_redemption
    loaded.value = true
    update()
  } catch {
    error.value = 'Não foi possível consultar os documentos. Recarregue a página antes de concluir.'
  }
})
</script>

<template>
  <section v-if="required || documents.length || error" class="consent-panel consent-panel--compact" aria-label="Documentos legais">
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="required">Ao enviar o formulário, concordo com os <a class="text-link" href="/termos-de-uso" target="_blank" rel="noopener noreferrer">Termos de Uso da Servindoor</a>.</p>
    <p v-if="documents.some(doc => doc.kind === 'privacy')">Os dados são tratados conforme a <a class="text-link" href="/politica-de-privacidade" target="_blank" rel="noopener noreferrer">Política de Privacidade</a>.</p>
    <a v-if="!required && documents.some(doc => doc.kind === 'terms')" class="text-link" href="/termos-de-uso" target="_blank" rel="noopener noreferrer">Consultar Termos de Uso</a>
  </section>
</template>
