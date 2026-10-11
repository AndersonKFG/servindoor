<script setup>
import { useToast } from '../composables/useToast'
import { ref } from 'vue'

const { toast } = useToast()

const cpfInput = ref('')
const dataNascInput = ref('')
const buscado = ref(false)
const carregando = ref(false)
const mensagemErro = ref('')
const servidorNome = ref('')
const premiosGanhos = ref([])

function formatarCPF(e) {
  let v = e.target.value.replace(/\D/g, '')
  if (v.length > 11) v = v.slice(0, 11)
  if (v.length > 9) v = v.replace(/(\d{3})(\d{3})(\d{3})(\d{1,2})/, '$1.$2.$3-$4')
  else if (v.length > 6) v = v.replace(/(\d{3})(\d{3})(\d{1,3})/, '$1.$2.$3')
  else if (v.length > 3) v = v.replace(/(\d{3})(\d{1,3})/, '$1.$2')
  cpfInput.value = v
}

async function buscarPremios() {
  const limpo = cpfInput.value.replace(/\D/g, '')
  if (limpo.length !== 11) {
    toast.warning('Por favor, digite um CPF válido com 11 dígitos.')
    return
  }

  if (!dataNascInput.value) {
    toast.warning('Por favor, informe a sua Data de Nascimento.')
    return
  }

  carregando.value = true
  buscado.value = false
  mensagemErro.value = ''
  servidorNome.value = ''
  premiosGanhos.value = []

  try {
    const params = new URLSearchParams({
      cpf: limpo,
      data_nascimento: dataNascInput.value
    })
    const res = await fetch('/api/sorteios/meus-premios?' + params.toString())
    const data = await res.json()

    if (data.encontrado) {
      servidorNome.value = data.servidor_nome
      premiosGanhos.value = data.premios || []
    } else {
      mensagemErro.value = data.mensagem || 'Nenhum cadastro localizado para os dados informados.'
    }
    buscado.value = true
  } catch (err) {
    toast.error('Erro ao buscar prêmios.')
    mensagemErro.value = 'Falha de comunicação com o servidor. Tente novamente.'
    buscado.value = true
  } finally {
    carregando.value = false
  }
}
</script>


<template>
  <div class="meus-premios-page">
    <div class="app-container">
      
      <div class="header-card text-center mb-4">
        <span class="vip-badge bg-warning mb-2">
          <i class="bi bi-gift-fill me-1"></i> Área do Servidor
        </span>
        <h1 class="page-title font-quattrocento">Consultar Meus Prêmios</h1>
        <p class="page-subtitle">Informe seu CPF e Data de Nascimento para consultar seus prêmios sorteados.</p>

        <!-- Formulário de Consulta com CPF e Data de Nascimento -->
        <div class="vip-glass-card query-box-card">
          <form class="search-form" @submit.prevent="buscarPremios">
            <div class="inputs-grid">
              
              <div class="form-group text-start">
                <label class="form-label" for="cpf-query">
                  <i class="bi bi-person-badge me-1 text-primary"></i> CPF: *
                </label>
                <input
                  id="cpf-query"
                  :value="cpfInput"
                  type="tel"
                  inputmode="numeric"
                  class="form-control query-input font-monospace"
                  placeholder="000.000.000-00"
                  maxlength="14"
                  required
                  @input="formatarCPF"
                />
              </div>

              <div class="form-group text-start">
                <label class="form-label" for="nasc-query">
                  <i class="bi bi-calendar-event me-1 text-warning"></i> Data de Nascimento: *
                </label>
                <input
                  id="nasc-query"
                  v-model="dataNascInput"
                  type="date"
                  class="form-control query-input"
                  required
                />
              </div>

            </div>

            <button type="submit" class="btn-vip-mega btn-buscar font-outfit" :disabled="carregando">
              <span v-if="carregando"><i class="bi bi-hourglass-split me-1"></i> Consultando...</span>
              <span v-else><i class="bi bi-search me-1"></i> Consultar Meus Prêmios</span>
            </button>
          </form>
        </div>
      </div>

      <!-- MENSAGEM DE DADOS INCORRETOS -->
      <div v-if="buscado && mensagemErro" class="error-box text-center">
        <i class="bi bi-exclamation-triangle-fill text-danger fs-1 mb-2 d-block"></i>
        <h3 class="font-outfit text-white fw-bold mb-1">Atenção</h3>
        <p class="text-danger mb-0">{{ mensagemErro }}</p>
      </div>

      <!-- RESULTADO: GANHOU PRÊMIOS -->
      <div v-else-if="buscado && premiosGanhos.length > 0" class="results-container animate-fade-in">
        <div class="winner-congrats-banner">
          <i class="bi bi-stars text-warning fs-2 me-2"></i>
          <div>
            <h2 class="winner-title font-outfit">Parabéns, {{ servidorNome }}!</h2>
            <p class="winner-subtitle">Você foi contemplado(a) com {{ premiosGanhos.length }} prêmio(s) no sorteio oficial.</p>
          </div>
        </div>

        <div class="premios-won-grid">
          <div
            v-for="item in premiosGanhos"
            :key="item.id"
            class="vip-glass-card prize-won-card"
          >
            <div class="prize-won-header">
              <div class="prize-img-frame">
                <img v-if="item.premio_foto" :src="item.premio_foto" alt="Prêmio" class="p-img" />
                <div v-else class="p-ph"><i class="bi bi-gift-fill"></i></div>
              </div>
              
              <div class="prize-title-meta">
                <span class="cat-pill font-outfit">{{ item.categoria }}</span>
                <h3 class="p-name font-outfit">{{ item.premio_nome }}</h3>
                <p v-if="item.premio_descricao" class="p-desc">{{ item.premio_descricao }}</p>
                <span class="p-date"><i class="bi bi-clock me-1"></i> Sorteado em: {{ item.data_sorteio }}</span>
              </div>
            </div>

            <!-- STATUS DE ENTREGA & FOTO -->
            <div class="delivery-status-section">
              <div v-if="item.entregue" class="delivered-box">
                <div class="delivered-tag font-outfit">
                  <i class="bi bi-check-circle-fill text-success me-1"></i> Prêmio Entregue em {{ item.data_entrega }}
                </div>
                
                <div v-if="item.foto_entrega_url" class="delivery-proof-card">
                  <span class="proof-title font-outfit">Foto Oficial de Comprovação:</span>
                  <img :src="item.foto_entrega_url" alt="Foto da Entrega" class="proof-photo" />
                </div>
              </div>

              <div v-else class="pending-box">
                <i class="bi bi-info-circle-fill text-warning fs-4 me-2"></i>
                <div>
                  <strong class="font-outfit text-white">Aguardando Retirada</strong>
                  <p class="text-muted small mb-0">Dirija-se ao palco / balcão de entrega de premiações para retirar o seu prêmio!</p>
                </div>
              </div>
            </div>

          </div>
        </div>
      </div>

      <!-- RESULTADO: NÃO GANHOU AINDA -->
      <div v-else-if="buscado && premiosGanhos.length === 0 && !mensagemErro" class="no-prize-box text-center animate-fade-in">
        <i class="bi bi-emoji-smile text-muted display-4 mb-3"></i>
        <h3 class="font-outfit text-white fw-bold mb-2">Nenhum prêmio sorteado para este CPF até o momento</h3>
        <p class="text-muted max-w-md mx-auto">
          Fique atento ao telão do evento! Novos sorteios estão sendo realizados ao longo da festa para os servidores presentes.
        </p>
      </div>

    </div>
  </div>
</template>

<style scoped>
.meus-premios-page {
  padding: 32px 0 80px;
}

.header-card {
  max-width: 620px;
  margin: 0 auto 32px;
}
</style>
