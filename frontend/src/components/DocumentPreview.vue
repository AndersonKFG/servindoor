<script setup>
defineProps({ document: { type: Object, required: true }, embedded: { type: Boolean, default: false } })
</script>

<template>
  <article class="document-panel" :class="{ 'document-panel--embedded': embedded }">
    <header class="document-panel__header" :class="{ 'modal-hero-card': embedded }">
      <h2>{{ document.title }}</h2>
      <p class="text-muted">Versão {{ document.version }} · {{ document.published_at ? new Date(document.published_at).toLocaleString('pt-BR') : 'Rascunho privado' }}</p>
    </header>
    <div :class="{ 'modal-info-grid modal-info-grid--single': embedded }">
      <p class="document-fingerprint" :class="{ 'modal-field-card': embedded }"><span class="modal-field-label">SHA-256</span> {{ document.sha256 }}</p>
    </div>
    <div class="document-links">
      <a :href="document.file_url + '?download=true'" class="btn-secondary" rel="noreferrer"><i class="bi bi-download" aria-hidden="true"></i>Baixar {{ document.extension.toUpperCase() }}</a>
      <a :href="document.file_url" class="btn-secondary" target="_blank" rel="noopener noreferrer"><i class="bi bi-box-arrow-up-right" aria-hidden="true"></i>Abrir documento</a>
    </div>
    <iframe v-if="document.extension === 'pdf'" :src="document.file_url" class="document-preview" :title="document.title" referrerpolicy="no-referrer"></iframe>
    <p v-else>Baixe o DOCX para consultar em um leitor de documentos.</p>
  </article>
</template>
