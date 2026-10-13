<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import WebcamCapture from '../components/WebcamCapture.vue'

const route = useRoute()
const token = computed(() => route.hash.slice(1))
const solicitacao = ref(null)
const foto = ref('')
const carregando = ref(true)
const salvando = ref(false)
const concluido = ref(false)
const erro = ref('')
const linkIndisponivel = ref(false)

function mensagemErro(data, fallback) {
  return typeof data.detail === 'string' ? data.detail : fallback
}

async function carregar() {
  const tokenAtual = token.value
  carregando.value = true
  erro.value = ''
  try {
    if (!/^[A-Za-z0-9_-]{43}$/.test(tokenAtual)) {
      linkIndisponivel.value = true
      erro.value = 'Link de correção inválido. Abra o link completo recebido por e-mail.'
      return
    }
    const response = await fetch(`/api/correcao-foto/${tokenAtual}`, { cache: 'no-store', referrerPolicy: 'no-referrer' })
    const data = await response.json()
    if (tokenAtual !== token.value) return
    if (!response.ok) {
      linkIndisponivel.value = [404, 410].includes(response.status)
      erro.value = mensagemErro(data, 'Não foi possível carregar a solicitação.')
      return
    }
    solicitacao.value = data
  } catch {
    if (tokenAtual === token.value) erro.value = 'Falha de comunicação. Verifique sua conexão e tente novamente.'
  } finally {
    if (tokenAtual === token.value) carregando.value = false
  }
}

async function salvar() {
  if (!foto.value || salvando.value || concluido.value) return
  salvando.value = true
  const tokenAtual = token.value
  erro.value = ''
  try {
    const response = await fetch(`/api/correcao-foto/${tokenAtual}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      referrerPolicy: 'no-referrer',
      body: JSON.stringify({ foto_base64: foto.value })
    })
    const data = await response.json()
    if (tokenAtual !== token.value) return
    if (!response.ok) {
      linkIndisponivel.value = [404, 410].includes(response.status)
      erro.value = mensagemErro(data, 'Não foi possível salvar sua foto. Tente novamente.')
      return
    }
    concluido.value = true
    foto.value = ''
  } catch {
    if (tokenAtual === token.value) erro.value = 'Falha de comunicação. Verifique sua conexão e tente novamente.'
  } finally {
    if (tokenAtual === token.value) salvando.value = false
  }
}

watch(() => route.hash, () => {
  solicitacao.value = null
  foto.value = ''
  concluido.value = false
  linkIndisponivel.value = false
  salvando.value = false
  return carregar()
}, { immediate: true })
</script>

<template>
  <div class="public-query-page">
    <div class="app-container public-query-container">
      <section class="public-query-card" :aria-busy="carregando || salvando">
        <header class="public-query-header">
          <span class="public-query-badge">Serv indoor</span>
          <h1 class="public-query-title">Correção de foto</h1>
          <p class="public-query-description">Atualize sua foto de identificação a pedido da organização.</p>
        </header>
        <p v-if="carregando" role="status" class="text-center">Carregando solicitação...</p>
        <div v-else-if="concluido" class="modal-alert-card modal-alert-card--success" role="status">
          <div>
            <strong>Foto atualizada com sucesso!</strong>
            <p class="mb-0">A organização já pode consultar sua nova foto. Você pode fechar esta página.</p>
          </div>
        </div>
        <template v-else>
          <div v-if="erro" class="modal-alert-card modal-alert-card--danger mb-3" role="alert">{{ erro }}</div>
          <p v-if="linkIndisponivel" class="text-muted">Entre em contato com a organização para solicitar um novo link.</p>
          <form v-else-if="solicitacao" class="public-query-form" @submit.prevent="salvar">
            <p class="mb-0">Olá, <strong>{{ solicitacao.nome }}</strong>!</p>
            <div v-if="solicitacao.motivo" class="modal-field-card">
              <strong>Mensagem da organização</strong>
              <p class="text-pre-wrap mb-0">{{ solicitacao.motivo }}</p>
            </div>
            <p class="text-muted mb-0">Envie uma foto nítida, com boa iluminação e o rosto visível. Você pode usar a câmera ou escolher uma foto do dispositivo.</p>
            <fieldset :disabled="salvando" class="form-fieldset">
              <WebcamCapture v-model="foto" allow-upload />
            </fieldset>
            <button type="submit" class="btn btn-primary public-query-submit" :disabled="!foto || salvando">
              {{ salvando ? 'Salvando foto...' : 'Salvar nova foto' }}
            </button>
          </form>
          <button v-else type="button" class="btn btn-primary w-100" @click="carregar">Tentar novamente</button>
        </template>
      </section>
    </div>
  </div>
</template>
