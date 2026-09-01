<script setup>
import { ref } from 'vue'

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
    alert('Por favor, digite um CPF válido com 11 dígitos.')
    return
  }

  if (!dataNascInput.value) {
    alert('Por favor, informe a sua Data de Nascimento.')
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
    console.error('Erro buscando prêmios:', err)
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
        <h1 class="page-title font-outfit">Consultar Meus Prêmios</h1>
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

.page-title {
  font-size: clamp(1.8rem, 4vw, 2.4rem);
  font-weight: 900;
  color: #ffffff;
  margin-bottom: 6px;
}

.page-subtitle {
  color: var(--text-muted);
  font-size: 0.95rem;
  margin-bottom: 20px;
}

.query-box-card {
  padding: 24px;
  border-radius: 20px;
  text-align: left;
  box-shadow: 0 12px 35px rgba(0, 0, 0, 0.4);
}

.inputs-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 8px;
}

@media (max-width: 576px) {
  .inputs-grid {
    grid-template-columns: 1fr;
    gap: 10px;
  }
}

.form-label {
  display: block;
  font-size: 0.84rem;
  font-weight: 700;
  color: #e2e8f0;
  margin-bottom: 6px;
}

.query-input {
  min-height: 48px;
  font-size: 1.05rem;
  font-weight: 600;
}

.btn-buscar {
  margin-top: 14px;
}

.error-box {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.35);
  border-radius: 16px;
  padding: 30px 20px;
  max-width: 500px;
  margin: 0 auto;
}

.winner-congrats-banner {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.15) 0%, rgba(217, 119, 6, 0.1) 100%);
  border: 1px solid rgba(245, 158, 11, 0.4);
  border-radius: 18px;
  padding: 20px 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;
}

.winner-title {
  font-size: 1.6rem;
  font-weight: 800;
  color: #fbbf24;
  margin-bottom: 2px;
}

.winner-subtitle {
  color: #e2e8f0;
  font-size: 0.95rem;
  margin-bottom: 0;
}

.premios-won-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 20px;
}

.prize-won-card {
  padding: 22px;
  border-radius: 20px;
}

.prize-won-header {
  display: flex;
  gap: 16px;
  margin-bottom: 18px;
}

.prize-img-frame {
  width: 84px;
  height: 84px;
  border-radius: 14px;
  overflow: hidden;
  background: #000;
  border: 1px solid rgba(255, 255, 255, 0.15);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.p-img { width: 100%; height: 100%; object-fit: cover; }
.p-ph { font-size: 2.2rem; color: #fbbf24; }

.prize-title-meta { flex: 1; }

.cat-pill {
  display: inline-block;
  background: rgba(59, 130, 246, 0.2);
  border: 1px solid rgba(59, 130, 246, 0.4);
  color: #93c5fd;
  font-size: 0.72rem;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 999px;
  margin-bottom: 4px;
}

.p-name {
  font-size: 1.25rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.p-desc {
  font-size: 0.84rem;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.p-date {
  font-size: 0.75rem;
  color: var(--text-subtle);
  display: block;
}

.delivery-status-section {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding-top: 16px;
}

.delivered-box {
  background: rgba(16, 185, 129, 0.06);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 14px;
  padding: 14px;
}

.delivered-tag {
  font-weight: 800;
  font-size: 0.88rem;
  color: #34d399;
  margin-bottom: 10px;
}

.delivery-proof-card { margin-top: 8px; }
.proof-title { display: block; font-size: 0.74rem; color: var(--text-subtle); margin-bottom: 6px; }
.proof-photo { width: 100%; max-height: 240px; object-fit: cover; border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.2); }

.pending-box {
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.25);
  border-radius: 14px;
  padding: 14px;
  display: flex;
  align-items: center;
}

.no-prize-box {
  background: rgba(255, 255, 255, 0.02);
  border: 1px dashed rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  padding: 50px 20px;
  max-width: 540px;
  margin: 0 auto;
}

.animate-fade-in {
  animation: fadeIn 0.3s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.max-w-md { max-width: 450px; }
.mx-auto { margin-left: auto; margin-right: auto; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.mb-0 { margin-bottom: 0; }
.mb-1 { margin-bottom: 4px; }
.mb-2 { margin-bottom: 8px; }
.mb-3 { margin-bottom: 12px; }
.mb-4 { margin-bottom: 24px; }
.text-warning { color: var(--warning-color); }
.text-danger { color: #f87171; }
.font-monospace { font-family: monospace; }
</style>
