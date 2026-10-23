<script setup>
import { computed } from 'vue'
const props = defineProps({ page: Number, total: Number, size: { type: Number, default: 25 } })
const emit = defineEmits(['change'])
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.size)))
</script>

<template>
  <div class="pagination-footer">
    <span class="pagination-info">{{ total }} registros · página {{ page }} de {{ pages }}</span>
    <div class="document-links">
      <button class="btn-page-nav" :disabled="page <= 1" aria-label="Página anterior" @click="emit('change', page - 1)"><i class="bi bi-chevron-left"></i></button>
      <button class="btn-page-number active" aria-current="page">{{ page }}</button>
      <button class="btn-page-nav" :disabled="page >= pages" aria-label="Próxima página" @click="emit('change', page + 1)"><i class="bi bi-chevron-right"></i></button>
    </div>
  </div>
</template>
