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

          <h2 class="erro-title font-outfit">Atenção</h2>
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

.erro-wrapper {
  width: 100%;
  max-width: 480px;
  margin: 0 auto;
}

.erro-card {
  padding: 40px 30px;
  text-align: center;
  border-color: rgba(239, 68, 68, 0.4);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5), 0 0 35px rgba(239, 68, 68, 0.2);
}

.erro-icon-box {
  width: 68px;
  height: 68px;
  background: rgba(239, 68, 68, 0.15);
  border: 2px solid rgba(239, 68, 68, 0.4);
  border-radius: 50%;
  margin: 0 auto 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  color: var(--danger-color);
}

.erro-title {
  font-size: 1.8rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 10px;
}

.erro-msg {
  color: #e2e8f0;
  font-size: 1.05rem;
  line-height: 1.5;
  margin-bottom: 28px;
}

.w-100 { width: 100%; }
.me-1 { margin-right: 4px; }
</style>
