<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const mensagem = computed(() => {
  return route.query.msg || 'Ocorreu um imprevisto durante o processamento da sua solicitação.'
})
</script>


<template>
  <div class="erro-page">
    <div class="app-container">
      <div class="erro-wrapper">
        <div class="vip-glass-card erro-card">
          
          <div class="erro-icon-box">
            <i class="bi bi-exclamation-triangle-fill"></i>
          </div>

          <h2 class="erro-title font-quattrocento">Atenção</h2>
          <p class="erro-msg">{{ mensagem }}</p>

          <div class="erro-actions">
            <router-link to="/" class="btn-primary w-100 font-outfit">
              <i class="bi bi-arrow-left me-1"></i> Voltar à Página Inicial
            </router-link>
          </div>

        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.erro-page {
  min-height: 75vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
}
</style>
