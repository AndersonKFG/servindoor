<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Navbar from './components/Navbar.vue'

const route = useRoute()
const isTelao = computed(() => route.path === '/telao' || route.meta?.hideNav === true)
</script>

<template>
  <div class="app-root">
    <Navbar v-if="!isTelao" />
    <main :class="['main-content', { 'main-telao': isTelao }]">
      <router-view />
    </main>
    <footer v-if="!isTelao" class="app-footer">
      <div class="app-container footer-content-clean">
        <p class="footer-copy">
          &copy; 2026 <strong>Servindoor</strong> &bull; Todos os direitos reservados.
        </p>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.main-content {
  flex: 1;
}

.main-telao {
  padding: 0 !important;
  margin: 0 !important;
}

.app-footer {
  background: rgba(11, 15, 25, 0.98);
  border-top: 1px solid var(--border-glass);
  padding: 20px 0;
  margin-top: auto;
}

.footer-content-clean {
  text-align: center;
}

.footer-copy {
  color: var(--text-subtle);
  font-size: 0.85rem;
  margin: 0;
  letter-spacing: 0.3px;
}
</style>
