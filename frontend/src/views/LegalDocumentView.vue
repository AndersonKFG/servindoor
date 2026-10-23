<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import DocumentPreview from '../components/DocumentPreview.vue'
const route = useRoute()
const document = ref(null)
const loading = ref(true)
const title = computed(() => route.path === '/termos-de-uso' ? 'Termos de Uso' : 'Política de Privacidade')
watch(() => route.path, async () => {
  loading.value = true
  document.value = null
  try {
    const res = await fetch('/api/legal/current', { cache: 'no-store' })
    if (res.ok) {
      const kind = route.path === '/termos-de-uso' ? 'terms' : 'privacy'
      document.value = (await res.json()).documents.find(doc => doc.kind === kind)
    }
  } finally { loading.value = false }
}, { immediate: true })
</script>

<template>
  <div class="app-container workspace-stack">
    <h1 class="page-title font-quattrocento">{{ title }}</h1>
    <p v-if="loading" role="status">Carregando documento…</p>
    <DocumentPreview v-else-if="document" :document="document" />
    <p v-else class="availability-control" role="status">Documento ainda não disponível para consulta pública.</p>
  </div>
</template>
