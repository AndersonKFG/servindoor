<script setup>
import { onMounted, ref } from 'vue'
const documents = ref([])
onMounted(async () => {
  try {
    const res = await fetch('/api/legal/current', { cache: 'no-store' })
    if (res.ok) documents.value = (await res.json()).documents
  } catch { /* Sem documento publicado, o rodapé mantém seu comportamento. */ }
})
</script>

<template>
  <nav v-if="documents.length" class="document-links footer-links" aria-label="Documentos legais">
    <router-link v-if="documents.some(doc => doc.kind === 'terms')" class="text-link" to="/termos-de-uso">Termos de Uso</router-link>
    <router-link v-if="documents.some(doc => doc.kind === 'privacy')" class="text-link" to="/politica-de-privacidade">Política de Privacidade</router-link>
  </nav>
</template>
