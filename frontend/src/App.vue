<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Navbar from './components/Navbar.vue'
import ToastContainer from './components/ToastContainer.vue'
import ConfirmModal from './components/ConfirmModal.vue'
import LegalFooterLinks from './components/LegalFooterLinks.vue'

const route = useRoute()
const isTelao = computed(() => route.path === '/telao' || route.meta?.hideNav === true)
const isHome = computed(() => route.path === '/')
</script>

<template>
  <div :class="['app-root', { 'app-root-home': isHome }]">
    <Navbar v-if="!isTelao" />
    <main :class="['main-content', { 'main-telao': isTelao, 'main-home': isHome }]">
      <router-view />
    </main>
    <footer v-if="!isTelao" :class="['app-footer', { 'footer-home': isHome }]">
      <div class="app-container footer-content-clean">
        <p class="footer-copy">
          &copy; 2026 <strong>Serv indoor</strong> &bull; Todos os direitos reservados.
        </p>
        <LegalFooterLinks />
      </div>
    </footer>
    <ToastContainer />
    <ConfirmModal />
  </div>
</template>
