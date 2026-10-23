<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import DocumentPreview from '../components/DocumentPreview.vue'
const route = useRoute()
const data = ref(null)
const error = ref('')
const message = ref('')
const accepted = ref(false)
const busy = ref(false)
const headers = { 'X-Legal-Token': route.params.token, 'X-Legal-Action': '1', 'Content-Type': 'application/json' }
async function load() {
  try {
    const res = await fetch('/api/legal/confirmation', { headers, cache: 'no-store', referrerPolicy: 'no-referrer' })
    const result = await res.json()
    if (!res.ok) throw new Error(result.detail || 'Link indisponível.')
    data.value = result
  } catch (err) { error.value = err.message }
}
async function action(renew = false) {
  if (busy.value || (!renew && !accepted.value)) return
  busy.value = true
  error.value = ''
  try {
    const body = renew ? {} : { accepted: true, terms_id: data.value.terms.id, privacy_id: data.value.privacy.id }
    const res = await fetch(`/api/legal/confirmation${renew ? '/renew' : ''}`, {
      method: 'POST', headers, body: JSON.stringify(body), referrerPolicy: 'no-referrer'
    })
    const result = await res.json()
    if (!res.ok) throw new Error(result.detail || 'Não foi possível registrar a operação.')
    message.value = result.message
    if (!renew) data.value = result
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
onMounted(load)
</script>

<template>
  <div class="app-container workspace-stack">
    <h1 class="page-title font-quattrocento">Documentos da Servindoor</h1>
    <p v-if="error" class="availability-control" role="alert">{{ error }}</p>
    <p v-if="message" class="availability-control" role="status">{{ message }}</p>
    <template v-if="data?.status === 'pending'">
      <h2>Olá, {{ data.first_name }}!</h2>
      <p>Publicamos nossos Termos de Uso e nossa Política de Privacidade para formalizar as regras já divulgadas e esclarecer como tratamos os dados dos participantes.</p>
      <p>Essa publicação não altera as condições anteriores nem a validade do seu ingresso.</p>
      <DocumentPreview :document="data.terms" />
      <DocumentPreview :document="data.privacy" />
      <form class="consent-panel" @submit.prevent="action()">
        <label class="choice-row"><input v-model="accepted" type="checkbox" required />
          <span>Declaro que li e concordo com os Termos de Uso da Servindoor, versão {{ data.terms.version }}.</span>
        </label>
        <button class="btn-primary" type="submit" :disabled="!accepted || busy">Confirmar concordância</button>
      </form>
    </template>
    <template v-else-if="data?.status === 'expired'">
      <p>{{ data.message }}</p>
      <button class="btn-primary" :disabled="busy || !!message" @click="action(true)">Solicitar novo link por e-mail</button>
    </template>
    <p v-else-if="data?.status === 'confirmed'" role="status">{{ data.message }}</p>
    <p v-if="!data && !error" role="status">Consultando link…</p>
    <p class="text-muted">A confirmação é voluntária. A ausência de confirmação não altera a validade de seu ingresso.</p>
    <router-link to="/">Voltar ao início</router-link>
  </div>
</template>
