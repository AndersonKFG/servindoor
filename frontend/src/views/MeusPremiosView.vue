<script setup>
import { useToast } from '../composables/useToast'
import { ref, computed } from 'vue'

const { toast } = useToast()

const cpfInput = ref('')
const dataNascInput = ref('')
const nascimentoDia = ref('')
const nascimentoMes = ref('')
const nascimentoAno = ref('')
const anoAtual = new Date().getFullYear()
const anosNascimento = computed(() => Array.from(
  { length: anoAtual - 1930 + 1 },
  (_, index) => String(anoAtual - index)
))
const mesesNascimento = [
  { valor: '01', nome: 'Janeiro' }, { valor: '02', nome: 'Fevereiro' },
  { valor: '03', nome: 'Março' }, { valor: '04', nome: 'Abril' },
  { valor: '05', nome: 'Maio' }, { valor: '06', nome: 'Junho' },
  { valor: '07', nome: 'Julho' }, { valor: '08', nome: 'Agosto' },
  { valor: '09', nome: 'Setembro' }, { valor: '10', nome: 'Outubro' },
  { valor: '11', nome: 'Novembro' }, { valor: '12', nome: 'Dezembro' }
]
const diasNascimento = computed(() => {
  const mes = Number(nascimentoMes.value)
  const ano = Number(nascimentoAno.value)
  const totalDias = mes && ano ? new Date(ano, mes, 0).getDate() : 31
  return Array.from({ length: totalDias }, (_, index) => String(index + 1).padStart(2, '0'))
})

function atualizarDataNascimento() {
  if (nascimentoDia.value && nascimentoMes.value && nascimentoAno.value) {
    const ultimoDia = diasNascimento.value[diasNascimento.value.length - 1]
    if (Number(nascimentoDia.value) > Number(ultimoDia)) nascimentoDia.value = ultimoDia
    dataNascInput.value = `${nascimentoAno.value}-${nascimentoMes.value}-${nascimentoDia.value}`
    return
  }
  dataNascInput.value = ''
}

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
  <div class="meus-premios-page public-query-page">
    <div class="app-container public-query-container">
      
      <div class="header-card text-center mb-4 public-query-card">
        <div class="public-query-header">
          <span class="vip-badge font-outfit public-query-badge">
            <i class="bi bi-gift-fill" aria-hidden="true"></i> CONSULTA OFICIAL
          </span>
          <h1 class="page-title font-quattrocento public-query-title">Meus Prêmios • Serv indoor</h1>
          <p class="page-subtitle public-query-description">Informe seu CPF e Data de Nascimento para consultar seus prêmios sorteados e acompanhar a retirada.</p>
        </div>

        <!-- Formulário de Consulta com CPF e Data de Nascimento -->
        <div class="public-query-body">
          <form class="search-form public-query-form" @submit.prevent="buscarPremios">
            <div class="inputs-grid public-query-fields">
              
              <div class="form-group text-start">
                <label class="form-label" for="cpf-query">
                  <i class="bi bi-person-badge me-1 text-primary" aria-hidden="true"></i> CPF do Servidor:
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
                  autocomplete="off"
                  @input="formatarCPF"
                />
              </div>

              <div class="form-group text-start">
                <label class="form-label" for="nasc-query-dia">
                  <i class="bi bi-calendar-event me-1 text-warning" aria-hidden="true"></i> Data de Nascimento:
                </label>
                <div class="date-select-grid">
                  <div class="select-col col-dia">
                    <select id="nasc-query-dia" v-model="nascimentoDia" class="form-select date-select" required aria-label="Dia de nascimento" @change="atualizarDataNascimento">
                      <option value="" disabled>Dia</option>
                      <option v-for="dia in diasNascimento" :key="dia" :value="dia">{{ dia }}</option>
                    </select>
                  </div>
                  <div class="select-col col-mes">
                    <select id="nasc-query-mes" v-model="nascimentoMes" class="form-select date-select" required aria-label="Mês de nascimento" @change="atualizarDataNascimento">
                      <option value="" disabled>Mês</option>
                      <option v-for="mes in mesesNascimento" :key="mes.valor" :value="mes.valor">{{ mes.nome }}</option>
                    </select>
                  </div>
                  <div class="select-col col-ano">
                    <select id="nasc-query-ano" v-model="nascimentoAno" class="form-select date-select" required aria-label="Ano de nascimento" @change="atualizarDataNascimento">
                      <option value="" disabled>Ano</option>
                      <option v-for="ano in anosNascimento" :key="ano" :value="ano">{{ ano }}</option>
                    </select>
                  </div>
                </div>
                <!-- Conserva o campo ISO usado pela consulta; os selects compõem seu valor. -->
                <input
                  id="nasc-query"
                  v-model="dataNascInput"
                  type="hidden"
                  class="form-control query-input"
                  required
                />
              </div>

            </div>

            <button type="submit" class="btn btn-primary w-100 font-outfit public-query-submit" :disabled="carregando">
              <span v-if="carregando"><i class="bi bi-hourglass-split me-1"></i> Consultando...</span>
              <span v-else><i class="bi bi-search me-1"></i> Consultar Prêmios</span>
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
