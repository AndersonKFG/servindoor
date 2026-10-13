<script setup>
import { ref, watch } from 'vue'
import Modal from './Modal.vue'

const props = defineProps({ show: Boolean, participante: Object })
const emit = defineEmits(['close'])
const motivo = ref('')
const enviando = ref(false)
const resultado = ref(null)

watch(() => props.show, (show) => {
  if (show) {
    motivo.value = ''
    resultado.value = null
  }
})

function fechar() {
  if (!enviando.value) emit('close')
}

async function enviar() {
  if (!props.participante?.email || enviando.value || resultado.value?.sucesso) return
  enviando.value = true
  resultado.value = null
  try {
    const response = await fetch(`/api/admin/participantes/${props.participante.id}/solicitar-correcao-foto`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ motivo: motivo.value.trim() })
    })
    const data = await response.json()
    resultado.value = {
      sucesso: response.ok,
      mensagem: response.ok ? data.mensagem : (typeof data.detail === 'string' ? data.detail : 'Não foi possível solicitar a correção.')
    }
  } catch {
    resultado.value = { sucesso: false, mensagem: 'Falha de comunicação. Tente novamente.' }
  } finally {
    enviando.value = false
  }
}
</script>

<template>
  <Modal :show="show" title="Solicitar correção de foto" icon="bi-camera" maxWidth="620px" @close="fechar">
    <form v-if="participante" id="photo-correction-request" @submit.prevent="enviar">
      <div class="modal-hero-card">
        <div>
          <strong>{{ participante.nome }}</strong>
          <p class="text-muted mb-0">{{ participante.email }}</p>
        </div>
      </div>
      <div class="modal-section">
        <div class="modal-info-grid">
          <div class="modal-field-card">
            <p class="mb-0">O participante receberá um e-mail com o botão <strong>Corrigir minha foto</strong>. O link permite uma única atualização e expira em 72 horas.</p>
          </div>
          <div class="modal-field-card">
            <p class="mb-0">Uma nova solicitação substitui os links anteriores. A foto atual será mantida até o envio da nova foto.</p>
          </div>
        </div>
      </div>
      <div class="modal-section form-group">
        <label for="photo-correction-reason" class="form-label">Mensagem ao participante (opcional)</label>
        <textarea id="photo-correction-reason" v-model="motivo" class="form-control" rows="5" maxlength="2000"
          :disabled="enviando || resultado?.sucesso" placeholder="Ex.: A foto está escura. Envie outra com boa iluminação e o rosto visível."></textarea>
        <p class="text-muted small mt-2">A mensagem aparecerá no e-mail e na página de correção.</p>
      </div>
      <div v-if="resultado" role="status" class="modal-alert-card"
        :class="resultado.sucesso ? 'modal-alert-card--success' : 'modal-alert-card--danger'">
        {{ resultado.mensagem }}
      </div>
    </form>
    <template #footer>
      <div class="modal-footer-grid w-100">
        <button type="button" class="btn btn-secondary" :disabled="enviando" @click="fechar">{{ resultado?.sucesso ? 'Fechar' : 'Cancelar' }}</button>
        <button v-if="!resultado?.sucesso" type="submit" form="photo-correction-request" class="btn btn-primary"
          :disabled="enviando || !participante?.email">
          {{ enviando ? 'Enfileirando...' : 'Enviar solicitação' }}
        </button>
      </div>
    </template>
  </Modal>
</template>
