<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import Modal from '../components/Modal.vue'

const router = useRouter()
const activeTab = ref('mesa')

const loading = ref(true)
const premios = ref([])
const totalPresentes = ref(0)
const eixos = ref([])
const todasSecretarias = ref([])
const historicoGanhadores = ref([])

// Estados da Mesa de Rodada do Telão
const mesaStatus = ref('idle') // idle, preparando, sorteando, finalizado
const premiosRodada = ref([])
const quantidadesAdicionar = ref({})
const imgErrors = ref({})
const isDisparandoMesa = ref(false)
const filtroCategoriaMesa = ref('todos')

const showModalNovoPremio = ref(false)
const showModalEditarPremio = ref(false)
const showModalEixo = ref(false)
const showModalAnular = ref(false)
const showModalSucessoSorteio = ref(false)
const showModalConfirmarInicio = ref(false)

// Sistema de Toast Moderno (In-App, sem alert que rouba foco e fecha fullscreen)
const toast = ref(null)
let toastTimer = null
function showToast(message, type = 'error') {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { message, type }
  toastTimer = setTimeout(() => {
    toast.value = null
  }, 4500)
}

const sorteioResultado = ref(null)
const sorteandoId = ref(null)
const ganhadorAnulando = ref(null)
const motivoAnulacao = ref('Servidor ausente no momento do sorteio')

const premioForm = ref({
  id: null,
  nome: '',
  descricao: '',
  categoria: 'categoria_1',
  eixo_id: '0',
  quantidade: 1,
  foto_base64: '',
  foto_preview: ''
})

const eixoForm = ref({
  id: null,
  nome: '',
  descricao: '',
  secretarias_selecionadas: []
})

let pollInterval = null

async function carregarDados(silent = false) {
  try {
    if (!silent) loading.value = true
    const resPremios = await fetch('/api/sorteios/premios')
    if (resPremios.ok) {
      const dataP = await resPremios.json()
      premios.value = dataP.premios || []
      totalPresentes.value = dataP.total_presentes || 0
    }

    const resEixos = await fetch('/api/sorteios/eixos')
    if (resEixos.ok) {
      const dataE = await resEixos.json()
      eixos.value = dataE.eixos || []
      todasSecretarias.value = dataE.todas_secretarias || []
    }

    const resTelao = await fetch('/api/sorteios/live-telao')
    if (resTelao.ok) {
      const dataT = await resTelao.json()
      mesaStatus.value = dataT.status || 'idle'
      premiosRodada.value = dataT.premios_rodada || []
      historicoGanhadores.value = dataT.ultimos_ganhadores || []
    }

    if (!silent) loading.value = false
  } catch (err) {
    if (!silent) console.error('Erro carregando dados:', err)
    if (!silent) loading.value = false
  }
}

function getQtdNaMesa(pId) {
  return premiosRodada.value.filter(it => it.premio_id === pId).length
}

function getDisponivelRestante(p) {
  return Math.max(0, p.disponiveis - getQtdNaMesa(p.id))
}

function getQtdSelecionada(pId, maxReal) {
  if (maxReal <= 0) return 0
  const v = quantidadesAdicionar.value[pId] || 1
  return Math.max(1, Math.min(maxReal, v))
}

function setQtdSelecionada(pId, val, maxReal) {
  if (maxReal <= 0) {
    quantidadesAdicionar.value[pId] = 0
    return
  }
  const v = Math.max(1, Math.min(maxReal, parseInt(val) || 1))
  quantidadesAdicionar.value[pId] = v
}

async function handleAdicionarARodada(p) {
  const restante = getDisponivelRestante(p)
  if (restante <= 0) {
    showToast(`Todas as ${p.disponiveis} unidade(s) disponíveis de '${p.nome}' já estão na mesa do Telão!`, 'warning')
    return
  }

  const qtd = getQtdSelecionada(p.id, restante)
  if (qtd <= 0 || qtd > restante) {
    showToast(`Quantidade máxima que pode ser adicionada agora é ${restante}.`, 'warning')
    return
  }

  // Agrupa itens já na mesa + novos
  const contagem = {}
  premiosRodada.value.forEach(item => {
    contagem[item.premio_id] = (contagem[item.premio_id] || 0) + 1
  })
  contagem[p.id] = (contagem[p.id] || 0) + qtd

  // Clamping de segurança
  if (contagem[p.id] > p.disponiveis) {
    contagem[p.id] = p.disponiveis
  }

  const payloadItens = Object.keys(contagem).map(pid => ({
    premio_id: parseInt(pid),
    quantidade: contagem[pid]
  }))

  try {
    const res = await fetch('/api/sorteios/mesa/preparar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ itens: payloadItens })
    })
    const data = await res.json()
    if (!res.ok) {
      showToast(data.detail || 'Erro ao preparar item na mesa.', 'error')
      return
    }
    mesaStatus.value = data.status
    premiosRodada.value = data.premios_rodada
    quantidadesAdicionar.value[p.id] = 1
    showToast(`+${qtd}x '${p.nome}' adicionado ao Telão!`, 'success')
  } catch (err) {
    showToast('Erro de comunicação ao adicionar prêmio.', 'error')
  }
}

async function handleRemoverItemMesa(premioId) {
  const contagem = {}
  premiosRodada.value.forEach(item => {
    if (item.premio_id !== premioId) {
      contagem[item.premio_id] = (contagem[item.premio_id] || 0) + 1
    }
  })

  const payloadItens = Object.keys(contagem).map(pid => ({
    premio_id: parseInt(pid),
    quantidade: contagem[pid]
  }))

  if (payloadItens.length === 0) {
    await handleLimparMesa()
    return
  }

  try {
    const res = await fetch('/api/sorteios/mesa/preparar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ itens: payloadItens })
    })
    const data = await res.json()
    if (res.ok) {
      mesaStatus.value = data.status
      premiosRodada.value = data.premios_rodada
    }
  } catch (err) {
    console.error('Erro ao remover item:', err)
  }
}

function handleIniciarSorteioMesa() {
  if (premiosRodada.value.length === 0) {
    showToast('Adicione pelo menos um prêmio à mesa antes de iniciar o sorteio.', 'warning')
    return
  }
  // Abre o modal in-app elegante (não bloqueia nem fecha tela cheia do telão)
  showModalConfirmarInicio.value = true
}

async function confirmarEIniciarSorteio() {
  showModalConfirmarInicio.value = false
  isDisparandoMesa.value = true
  try {
    const res = await fetch('/api/sorteios/mesa/iniciar', { method: 'POST' })
    const data = await res.json()
    if (!res.ok) {
      showToast(data.detail || 'Erro ao iniciar sorteio da mesa.', 'error')
      isDisparandoMesa.value = false
      return
    }
    mesaStatus.value = 'sorteando'
    premiosRodada.value = data.premios_rodada
    showToast('Sorteio iniciado no Telão! Animação de 10s em andamento...', 'success')

    // Monitora a finalização dos 10 segundos
    setTimeout(async () => {
      isDisparandoMesa.value = false
      await carregarDados()
      showToast('Sorteio concluído com sucesso!', 'success')
    }, 10500)
  } catch (err) {
    showToast('Erro de conexão ao iniciar sorteio.', 'error')
    isDisparandoMesa.value = false
  }
}

async function handleLimparMesa() {
  try {
    const res = await fetch('/api/sorteios/mesa/limpar', { method: 'POST' })
    if (res.ok) {
      mesaStatus.value = 'idle'
      premiosRodada.value = []
      await carregarDados()
    }
  } catch (err) {
    console.error('Erro ao limpar mesa:', err)
  }
}

function abrirTelao() {
  window.open('/telao', '_blank')
}

async function handleSortear(p) {
  if (p.disponiveis <= 0) return
  if (!confirm('Deseja realizar o sorteio de "' + p.nome + '" agora? O telão será sincronizado instantaneamente!')) return

  sorteandoId.value = p.id
  try {
    const res = await fetch('/api/sorteios/executar/' + p.id, { method: 'POST' })
    const data = await res.json()

    if (!res.ok) {
      showToast(data.detail || 'Erro ao realizar sorteio.', 'error')
      sorteandoId.value = null
      return
    }

    sorteioResultado.value = data
    showModalSucessoSorteio.value = true
    await carregarDados()
  } catch (e) {
    console.error('Erro ao sortear:', e)
  } finally {
    sorteandoId.value = null
  }
}

function abrirAnulacao(g) {
  ganhadorAnulando.value = g
  motivoAnulacao.value = 'Servidor ausente no momento do sorteio'
  showModalAnular.value = true
}

async function confirmarAnulacao() {
  if (!ganhadorAnulando.value) return
  try {
    const formData = new FormData()
    formData.append('motivo', motivoAnulacao.value)

    const res = await fetch('/api/sorteios/anular/' + ganhadorAnulando.value.id, {
      method: 'POST',
      body: formData
    })

    if (res.ok) {
      showModalAnular.value = false
      await carregarDados()
    } else {
      const d = await res.json()
      showToast(d.detail || 'Erro ao anular.', 'error')
    }
  } catch (e) {
    console.error('Erro anulando:', e)
  }
}

function abrirNovoPremio() {
  premioForm.value = {
    id: null,
    nome: '',
    descricao: '',
    categoria: 'categoria_1',
    eixo_id: eixos.value.length > 0 ? String(eixos.value[0].id) : '0',
    quantidade: 1,
    foto_base64: '',
    foto_preview: ''
  }
  showModalNovoPremio.value = true
}

function abrirEditarPremio(p) {
  premioForm.value = {
    id: p.id,
    nome: p.nome,
    descricao: p.descricao || '',
    categoria: p.categoria,
    eixo_id: p.eixo_id ? String(p.eixo_id) : '0',
    quantidade: p.quantidade,
    foto_base64: '',
    foto_preview: p.foto_url || ''
  }
  showModalEditarPremio.value = true
}

function onFotoPremioChange(e) {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    premioForm.value.foto_base64 = reader.result
    premioForm.value.foto_preview = reader.result
  }
  reader.readAsDataURL(file)
}

async function handleSalvarPremio(isEdit = false) {
  try {
    const formData = new FormData()
    formData.append('nome', premioForm.value.nome)
    formData.append('descricao', premioForm.value.descricao)
    formData.append('categoria', premioForm.value.categoria)
    formData.append('eixo_id', premioForm.value.eixo_id)
    formData.append('quantidade', premioForm.value.quantidade)
    if (premioForm.value.foto_base64) {
      formData.append('foto_base64', premioForm.value.foto_base64)
    }

    const url = isEdit ? '/api/sorteios/premios/' + premioForm.value.id : '/api/sorteios/premios'
    const method = isEdit ? 'PUT' : 'POST'

    const res = await fetch(url, { method, body: formData })
    if (res.ok) {
      showModalNovoPremio.value = false
      showModalEditarPremio.value = false
      await carregarDados()
    } else {
      const d = await res.json()
      showToast(d.detail || 'Erro ao salvar prêmio.', 'error')
    }
  } catch (e) {
    console.error('Erro salvando premio:', e)
  }
}

async function handleExcluirPremio(pId) {
  if (!confirm('Deseja realmente excluir este prêmio?')) return
  try {
    const res = await fetch('/api/sorteios/premios/' + pId, { method: 'DELETE' })
    if (res.ok) {
      await carregarDados()
    } else {
      const d = await res.json()
      showToast(d.detail || 'Não foi possível excluir.', 'error')
    }
  } catch (e) {
    console.error('Erro excluindo:', e)
  }
}

function abrirNovoEixo() {
  eixoForm.value = {
    id: null,
    nome: '',
    descricao: '',
    secretarias_selecionadas: []
  }
  showModalEixo.value = true
}

function abrirEditarEixo(e) {
  eixoForm.value = {
    id: e.id,
    nome: e.nome,
    descricao: e.descricao || '',
    secretarias_selecionadas: e.secretarias.map(s => s.id)
  }
  showModalEixo.value = true
}

function toggleSecretariaNoEixo(secId) {
  const idx = eixoForm.value.secretarias_selecionadas.indexOf(secId)
  if (idx > -1) {
    eixoForm.value.secretarias_selecionadas.splice(idx, 1)
  } else {
    eixoForm.value.secretarias_selecionadas.push(secId)
  }
}

async function handleSalvarEixo() {
  try {
    const formData = new FormData()
    formData.append('nome', eixoForm.value.nome)
    formData.append('descricao', eixoForm.value.descricao)
    formData.append('secretaria_ids', eixoForm.value.secretarias_selecionadas.join(','))
    if (eixoForm.value.id) {
      formData.append('eixo_id', eixoForm.value.id)
    }

    const res = await fetch('/api/sorteios/eixos', { method: 'POST', body: formData })
    if (res.ok) {
      showModalEixo.value = false
      await carregarDados()
    } else {
      const d = await res.json()
      showToast(d.detail || 'Erro ao salvar eixo.', 'error')
    }
  } catch (e) {
    console.error('Erro salvando eixo:', e)
  }
}

async function handleExcluirEixo(eixoId) {
  if (!confirm('Deseja realmente excluir este eixo?')) return
  try {
    const res = await fetch('/api/sorteios/eixos/' + eixoId, { method: 'DELETE' })
    if (res.ok) {
      await carregarDados()
    }
  } catch (e) {
    console.error('Erro excluindo eixo:', e)
  }
}

function abrirTelaoEmNovaJanela() {
  window.open('/telao', '_blank')
}

onMounted(() => {
  carregarDados()
})
</script>
<template>
  <div class="admin-sorteios-page">
    <div class="app-container">
      
      <div class="page-header-row">
        <div>
          <span class="vip-badge bg-primary mb-2">
            <i class="bi bi-trophy-fill me-1"></i> Central de Sorteios
          </span>
          <h1 class="page-title font-outfit">Gestão e Mesa de Sorteios</h1>
          <p class="page-subtitle">Controle de prêmios, eixos temáticos e execução em tempo real.</p>
        </div>

        <div class="header-btns">
          <button type="button" class="btn-telao-pop font-outfit" @click="abrirTelaoEmNovaJanela">
            <i class="bi bi-display-fill me-1"></i> Abrir Telão de Projeção
          </button>
        </div>
      </div>

      <div class="tabs-nav-bar">
        <button
          type="button"
          :class="['tab-btn font-outfit', { active: activeTab === 'mesa' }]"
          @click="activeTab = 'mesa'"
        >
          <i class="bi bi-dice-5-fill me-1"></i> Mesa de Sorteio ao Vivo
        </button>

        <button
          type="button"
          :class="['tab-btn font-outfit', { active: activeTab === 'premios' }]"
          @click="activeTab = 'premios'"
        >
          <i class="bi bi-gift-fill me-1"></i> Gestão de Prêmios ({{ premios.length }})
        </button>

        <button
          type="button"
          :class="['tab-btn font-outfit', { active: activeTab === 'eixos' }]"
          @click="activeTab = 'eixos'"
        >
          <i class="bi bi-diagram-3-fill me-1"></i> Eixos & Secretarias ({{ eixos.length }})
        </button>

        <button
          type="button"
          :class="['tab-btn font-outfit', { active: activeTab === 'historico' }]"
          @click="activeTab = 'historico'"
        >
          <i class="bi bi-clock-history me-1"></i> Histórico de Ganhadores
        </button>
      </div>

      <!-- ABA 1: MESA DE SORTEIO (PREPARAÇÃO DE RODADA E CONTROLE DO TELÃO) -->
      <div v-if="activeTab === 'mesa'" class="tab-pane">
        
        <!-- PAINEL 1: CONTROLE DA RODADA AO VIVO NO TELÃO -->
        <div class="mesa-stage-control-panel">
          
          <div class="mesa-panel-header">
            <div class="mesa-title-box">
              <span class="mesa-badge-tag font-outfit">
                <i class="bi bi-broadcast me-1"></i> SINCRONIZAÇÃO EM TEMPO REAL
              </span>
              <h2 class="mesa-panel-title font-outfit">
                Mesa de Rodada do Telão
              </h2>
              <p class="mesa-panel-subtitle">
                Selecione os prêmios abaixo para exibi-los no Telão. Quando estiver pronto, clique em <strong>Iniciar Sorteio</strong> para rodar a animação de 10s.
              </p>
            </div>

            <!-- BOTÕES DE AÇÃO DO TELÃO -->
            <div class="mesa-header-actions">
              <button
                type="button"
                class="btn-telao-view font-outfit"
                @click="abrirTelao"
                title="Abrir a tela de projeção em tela cheia"
              >
                <i class="bi bi-display me-1"></i> Abrir Telão (/telao)
              </button>

              <button
                v-if="premiosRodada.length > 0 && mesaStatus !== 'sorteando'"
                type="button"
                class="btn-danger-soft font-outfit"
                @click="handleLimparMesa"
              >
                <i class="bi bi-trash3 me-1"></i> Limpar Mesa
              </button>

              <button
                type="button"
                class="btn-iniciar-mesa font-outfit"
                :disabled="premiosRodada.length === 0 || isDisparandoMesa || mesaStatus === 'sorteando'"
                @click="handleIniciarSorteioMesa"
              >
                <i class="bi bi-stars me-2"></i>
                <span v-if="isDisparandoMesa || mesaStatus === 'sorteando'">SORTEANDO NO TELÃO (10s)...</span>
                <span v-else-if="premiosRodada.length === 0">SELECIONE OS PRÊMIOS ABAIXO</span>
                <span v-else>INICIAR SORTEIO NO TELÃO ({{ premiosRodada.length }} PRÊMIOS)</span>
              </button>
            </div>
          </div>

          <!-- STATUS BAR DA MESA -->
          <div class="mesa-status-bar font-outfit">
            <span v-if="mesaStatus === 'sorteando'" class="status-chip chip-sorteando">
              <span class="chip-pulse"></span> Animação em andamento no Telão (10 segundos)
            </span>
            <span v-else-if="mesaStatus === 'finalizado'" class="status-chip chip-finalizado">
              <i class="bi bi-check-circle-fill me-1"></i> Rodada finalizada! Ganhadores revelados no Telão
            </span>
            <span v-else-if="premiosRodada.length > 0" class="status-chip chip-preparando">
              <i class="bi bi-layers-fill me-1"></i> {{ premiosRodada.length }} prêmio(s) preparado(s) no Telão • Aguardando início
            </span>
            <span v-else class="status-chip chip-idle">
              <i class="bi bi-info-circle me-1"></i> Nenhum prêmio colocado na mesa ainda
            </span>

            <span class="badge-presentes-chip">
              <i class="bi bi-person-check-fill text-success me-1"></i> {{ totalPresentes }} presentes no evento
            </span>
          </div>

          <!-- CARDS DOS PRÊMIOS COLOCADOS NA MESA (VISUALIZAÇÃO AO VIVO DO TELÃO) -->
          <div v-if="premiosRodada.length > 0" class="mesa-items-deck">
            <div
              v-for="item in premiosRodada"
              :key="item.item_id"
              class="mesa-item-card"
              :class="{ 'item-sorteado': item.ganhador, 'item-anulado': item.ganhador?.anulado }"
            >
              <div class="mesa-item-photo">
                <img v-if="item.premio_foto && !imgErrors[item.item_id]" :src="item.premio_foto" alt="Prêmio" class="item-img" @error="imgErrors[item.item_id] = true" />
                <div v-else class="item-placeholder"><i class="bi bi-gift-fill"></i></div>
              </div>

              <div class="mesa-item-info">
                <span class="mesa-item-cat font-outfit">
                  {{ item.categoria === 'categoria_1' ? 'CATEGORIA GERAL' : 'EIXO: ' + (item.eixo_nome || 'Setorial') }}
                </span>
                <h4 class="mesa-item-nome font-outfit">{{ item.premio_nome }}</h4>

                <!-- GANHADOR SE FINALIZADO -->
                <div v-if="item.ganhador" class="mesa-item-winner">
                  <div class="winner-label font-outfit">
                    <i class="bi bi-trophy-fill text-warning me-1"></i> CONTEMPLADO:
                  </div>
                  <strong class="winner-name">{{ item.ganhador.nome }}</strong>
                  <span class="winner-details">{{ item.ganhador.cpf }} &bull; {{ item.ganhador.secretaria }}</span>

                  <div v-if="item.ganhador.anulado" class="text-danger fw-bold mt-1">
                    <i class="bi bi-x-circle me-1"></i> ANULADO
                  </div>
                  <button
                    v-else
                    type="button"
                    class="btn-anular-mesa-link font-outfit"
                    @click="abrirAnulacao(item.ganhador)"
                  >
                    <i class="bi bi-x-circle me-1"></i> Anular (Ausente)
                  </button>
                </div>
                <div v-else class="mesa-item-pending font-outfit">
                  <i class="bi bi-hourglass-split me-1"></i> Aguardando sorteio
                </div>
              </div>

              <!-- BOTÃO DE REMOVER ANTES DO SORTEIO -->
              <button
                v-if="mesaStatus === 'preparando'"
                type="button"
                class="btn-remover-mesa"
                title="Remover este item da mesa"
                @click="handleRemoverItemMesa(item.premio_id)"
              >
                <i class="bi bi-x"></i>
              </button>
            </div>
          </div>

          <div v-else class="mesa-deck-empty">
            <i class="bi bi-diagram-3 fs-2 text-muted mb-2"></i>
            <p class="text-muted mb-0 font-outfit">
              A mesa de sorteio está vazia. Escolha os prêmios no catálogo abaixo e clique em <strong>"+ Adicionar à Rodada"</strong>.
            </p>
          </div>

        </div>

        <!-- PAINEL 2: CATÁLOGO DE PRÊMIOS DISPONÍVEIS PARA ADICIONAR À MESA -->
        <div class="catalogo-section mt-4">
          <div class="catalogo-header">
            <h3 class="font-outfit text-white fw-bold mb-0">
              <i class="bi bi-gift-fill me-2 text-primary"></i> Catálogo de Prêmios Disponíveis
            </h3>
            <span class="text-muted font-outfit fs-6">
              Defina a quantidade de cada item e adicione à rodada do telão
            </span>
          </div>

          <div class="prizes-grid mt-3">
            <div
              v-for="p in premios"
              :key="p.id"
              class="prize-card-live"
              :class="{ 'prize-completed': p.disponiveis === 0 }"
            >
              <div class="prize-card-photo-box">
                <img v-if="p.foto_url && !imgErrors[p.id]" :src="p.foto_url" alt="Prêmio" class="prize-card-img" @error="imgErrors[p.id] = true" />
                <div v-else class="prize-placeholder"><i class="bi bi-gift-fill"></i></div>
                
                <span :class="['cat-badge font-outfit', p.categoria === 'categoria_1' ? 'cat-1' : 'cat-2']">
                  {{ p.categoria === 'categoria_1' ? 'Cat 1 (Geral)' : 'Cat 2 (' + (p.eixo_nome || 'Eixo') + ')' }}
                </span>
              </div>

              <div class="prize-card-content">
                <h3 class="prize-card-title font-outfit">{{ p.nome }}</h3>
                <p v-if="p.descricao" class="prize-card-desc">{{ p.descricao }}</p>

                <div class="prize-metrics-row">
                  <div class="metric-pill">
                    <span class="m-k">Sorteados:</span>
                    <strong class="m-v">{{ p.quantidade_sorteada }} / {{ p.quantidade }}</strong>
                  </div>
                  <div class="metric-pill">
                    <span class="m-k">Disponíveis:</span>
                    <strong class="m-v text-success">{{ p.disponiveis }}</strong>
                  </div>
                </div>

                <!-- CONTROLES DE ADIÇÃO À MESA -->
                <div class="prize-card-action">
                  <div v-if="getDisponivelRestante(p) > 0" class="mesa-add-action-group">
                    <div class="qtd-stepper">
                      <button
                        type="button"
                        class="btn-step"
                        :disabled="getQtdSelecionada(p.id, getDisponivelRestante(p)) <= 1"
                        @click="setQtdSelecionada(p.id, getQtdSelecionada(p.id, getDisponivelRestante(p)) - 1, getDisponivelRestante(p))"
                      >
                        -
                      </button>
                      <input
                        type="number"
                        class="input-step"
                        min="1"
                        :max="getDisponivelRestante(p)"
                        :value="getQtdSelecionada(p.id, getDisponivelRestante(p))"
                        @input="setQtdSelecionada(p.id, $event.target.value, getDisponivelRestante(p))"
                      />
                      <button
                        type="button"
                        class="btn-step"
                        :disabled="getQtdSelecionada(p.id, getDisponivelRestante(p)) >= getDisponivelRestante(p)"
                        @click="setQtdSelecionada(p.id, getQtdSelecionada(p.id, getDisponivelRestante(p)) + 1, getDisponivelRestante(p))"
                      >
                        +
                      </button>
                    </div>

                    <button
                      type="button"
                      class="btn-add-mesa font-outfit"
                      :disabled="isDisparandoMesa || mesaStatus === 'sorteando'"
                      @click="handleAdicionarARodada(p)"
                    >
                      <i class="bi bi-plus-circle me-1"></i> Adicionar
                      <span v-if="getQtdNaMesa(p.id) > 0" class="badge-na-mesa-mini">({{ getQtdNaMesa(p.id) }} na mesa)</span>
                    </button>
                  </div>

                  <div v-else-if="getQtdNaMesa(p.id) > 0" class="btn-mesa-full font-outfit">
                    <i class="bi bi-check2-all me-1"></i> Tudo na Mesa ({{ getQtdNaMesa(p.id) }}/{{ p.disponiveis }})
                  </div>

                  <div v-else class="btn-completed font-outfit">
                    <i class="bi bi-check-all me-1"></i> 100% Sorteado
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="premios.length === 0" class="empty-box">
            <i class="bi bi-gift text-muted fs-1 mb-2"></i>
            <p class="text-muted">Nenhum prêmio cadastrado. Vá até a aba <strong>Gestão de Prêmios</strong>.</p>
          </div>
        </div>

      </div>

      <!-- ABA 2: CRUD PRÊMIOS -->
      <div v-if="activeTab === 'premios'" class="tab-pane">
        <div class="tab-actions-header">
          <h3 class="font-outfit text-white fw-bold mb-0">Lista de Prêmios Cadastrados</h3>
          <button type="button" class="btn-primary font-outfit" @click="abrirNovoPremio">
            <i class="bi bi-plus-circle-fill me-1"></i> Cadastrar Novo Prêmio
          </button>
        </div>

        <div class="vip-glass-card table-card">
          <div class="table-responsive">
            <table class="custom-table">
              <thead>
                <tr>
                  <th>Foto</th>
                  <th>Prêmio</th>
                  <th>Categoria</th>
                  <th>Eixo Vinculado</th>
                  <th>Cotas</th>
                  <th class="text-end">Ações</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="premios.length === 0">
                  <td colspan="6" class="text-center py-4 text-muted">Nenhum prêmio cadastrado.</td>
                </tr>
                <tr v-for="p in premios" :key="p.id">
                  <td style="width: 60px;">
                    <div class="table-thumb">
                      <img v-if="p.foto_url" :src="p.foto_url" alt="Foto" class="thumb-img" />
                      <div v-else class="thumb-empty"><i class="bi bi-gift"></i></div>
                    </div>
                  </td>
                  <td>
                    <strong class="text-white">{{ p.nome }}</strong>
                    <span v-if="p.descricao" class="d-block small text-subtle">{{ p.descricao }}</span>
                  </td>
                  <td>
                    <span :class="['cat-badge font-outfit', p.categoria === 'categoria_1' ? 'cat-1' : 'cat-2']">
                      {{ p.categoria_label }}
                    </span>
                  </td>
                  <td>
                    <span v-if="p.eixo_nome" class="sec-tag">{{ p.eixo_nome }}</span>
                    <span v-else class="text-subtle">Geral (Todos)</span>
                  </td>
                  <td>
                    <strong class="text-white">{{ p.quantidade_sorteada }} / {{ p.quantidade }}</strong>
                  </td>
                  <td class="text-end">
                    <button type="button" class="btn-action-icon" title="Editar Prêmio" @click="abrirEditarPremio(p)">
                      <i class="bi bi-pencil-fill text-info"></i>
                    </button>
                    <button
                      type="button"
                      class="btn-action-icon"
                      title="Excluir Prêmio"
                      :disabled="p.quantidade_sorteada > 0"
                      @click="handleExcluirPremio(p.id)"
                    >
                      <i class="bi bi-trash-fill text-danger"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ABA 3: CRUD EIXOS -->
      <div v-if="activeTab === 'eixos'" class="tab-pane">
        <div class="tab-actions-header">
          <div>
            <h3 class="font-outfit text-white fw-bold mb-1">Eixos Temáticos de Secretarias</h3>
            <p class="text-muted small mb-0">Agrupe secretarias para os sorteios exclusivos da Categoria 2.</p>
          </div>
          <button type="button" class="btn-primary font-outfit" @click="abrirNovoEixo">
            <i class="bi bi-diagram-3 me-1"></i> Criar Novo Eixo
          </button>
        </div>

        <div class="eixos-grid">
          <div v-for="e in eixos" :key="e.id" class="vip-glass-card eixo-card">
            <div class="eixo-header">
              <div>
                <h4 class="eixo-title font-outfit">{{ e.nome }}</h4>
                <p v-if="e.descricao" class="eixo-desc">{{ e.descricao }}</p>
              </div>
              <div class="eixo-actions">
                <button type="button" class="btn-action-icon" title="Editar Eixo" @click="abrirEditarEixo(e)">
                  <i class="bi bi-pencil-fill text-info"></i>
                </button>
                <button type="button" class="btn-action-icon" title="Excluir Eixo" @click="handleExcluirEixo(e.id)">
                  <i class="bi bi-trash-fill text-danger"></i>
                </button>
              </div>
            </div>

            <div class="eixo-secretarias-list">
              <span class="sec-label font-outfit">Secretarias Associadas ({{ e.secretarias_count }}):</span>
              <div class="sec-chips-box">
                <span v-for="s in e.secretarias" :key="s.id" class="sec-chip">
                  <i class="bi bi-building me-1"></i> {{ s.nome }}
                </span>
                <span v-if="e.secretarias.length === 0" class="text-subtle small">
                  Nenhuma secretaria vinculada. Clique em editar para vincular.
                </span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="eixos.length === 0" class="empty-box">
          <i class="bi bi-diagram-3 text-muted fs-1 mb-2"></i>
          <p class="text-muted">Nenhum eixo cadastrado. Clique em <strong>Criar Novo Eixo</strong>.</p>
        </div>
      </div>

      <!-- ABA 4: HISTÓRICO -->
      <div v-if="activeTab === 'historico'" class="tab-pane">
        <div class="tab-actions-header">
          <h3 class="font-outfit text-white fw-bold mb-0">Histórico de Ganhadores</h3>
          <button type="button" class="btn-secondary btn-sm" @click="carregarDados">
            <i class="bi bi-arrow-repeat me-1"></i> Atualizar
          </button>
        </div>

        <div class="vip-glass-card table-card">
          <div class="table-responsive">
            <table class="custom-table">
              <thead>
                <tr>
                  <th>Servidor</th>
                  <th>Secretaria</th>
                  <th>Prêmio Conquistado</th>
                  <th>Categoria</th>
                  <th>Data/Hora</th>
                  <th class="text-end">Ação</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="historicoGanhadores.length === 0">
                  <td colspan="6" class="text-center py-4 text-muted">Nenhum sorteio registrado ainda.</td>
                </tr>
                <tr v-for="g in historicoGanhadores" :key="g.id">
                  <td>
                    <strong class="text-white">{{ g.servidor_nome }}</strong>
                    <span class="d-block small text-subtle font-monospace">{{ g.servidor_cpf }}</span>
                  </td>
                  <td><span class="sec-tag">{{ g.secretaria_nome }}</span></td>
                  <td><strong class="text-warning">{{ g.premio_nome }}</strong></td>
                  <td><span class="cat-badge cat-1">{{ g.categoria }}</span></td>
                  <td><span class="small text-light">{{ g.data_sorteio }}</span></td>
                  <td class="text-end">
                    <button
                      type="button"
                      class="btn-danger-sm"
                      title="Anular Sorteio (Servidor Ausente)"
                      @click="abrirAnulacao(g)"
                    >
                      <i class="bi bi-x-circle me-1"></i> Anular
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

    </div>

    <!-- MODAL PRÊMIO -->
    <Modal
      :show="showModalNovoPremio || showModalEditarPremio"
      :title="showModalEditarPremio ? 'Editar Prêmio' : 'Cadastrar Novo Prêmio'"
      icon="bi-gift-fill"
      @close="showModalNovoPremio = false; showModalEditarPremio = false;"
    >
      <form @submit.prevent="handleSalvarPremio(showModalEditarPremio)">
        <div class="form-group">
          <label class="form-label">Nome do Prêmio *</label>
          <input v-model="premioForm.nome" type="text" class="form-control" placeholder="Ex: Smart TV 55 4K" required />
        </div>

        <div class="form-group">
          <label class="form-label">Descrição</label>
          <input v-model="premioForm.descricao" type="text" class="form-control" placeholder="Ex: Modelo 2026 com Bluetooth" />
        </div>

        <div class="form-grid-2">
          <div class="form-group">
            <label class="form-label">Categoria *</label>
            <select v-model="premioForm.categoria" class="form-select" required>
              <option value="categoria_1">Categoria 1 (Geral)</option>
              <option value="categoria_2">Categoria 2 (Eixo Setorial)</option>
            </select>
          </div>

          <div class="form-group" v-if="premioForm.categoria === 'categoria_2'">
            <label class="form-label">Eixo Vinculado *</label>
            <select v-model="premioForm.eixo_id" class="form-select" required>
              <option value="0" disabled>Selecione o Eixo</option>
              <option v-for="e in eixos" :key="e.id" :value="String(e.id)">
                {{ e.nome }}
              </option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Quantidade *</label>
            <input v-model="premioForm.quantidade" type="number" min="1" class="form-control" required />
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Foto do Prêmio</label>
          <input type="file" accept="image/*" class="form-control" @change="onFotoPremioChange" />
          <div v-if="premioForm.foto_preview" class="photo-preview-box mt-2">
            <img :src="premioForm.foto_preview" alt="Preview" class="preview-img" />
          </div>
        </div>

        <div class="modal-footer-box">
          <button type="button" class="btn-secondary" @click="showModalNovoPremio = false; showModalEditarPremio = false;">Cancelar</button>
          <button type="submit" class="btn-primary">Salvar Prêmio</button>
        </div>
      </form>
    </Modal>

    <!-- MODAL EIXO -->
    <Modal
      :show="showModalEixo"
      :title="eixoForm.id ? 'Editar Eixo Temático' : 'Criar Novo Eixo'"
      icon="bi-diagram-3-fill"
      @close="showModalEixo = false"
    >
      <form @submit.prevent="handleSalvarEixo">
        <div class="form-group">
          <label class="form-label">Nome do Eixo *</label>
          <input v-model="eixoForm.nome" type="text" class="form-control" placeholder="Ex: Eixo Saúde e Bem-Estar" required />
        </div>

        <div class="form-group">
          <label class="form-label">Descrição</label>
          <input v-model="eixoForm.descricao" type="text" class="form-control" placeholder="Ex: Secretarias do setor da saúde" />
        </div>

        <div class="form-group">
          <label class="form-label">Secretarias que pertencem a este Eixo:</label>
          <div class="secretarias-checkbox-grid">
            <div
              v-for="s in todasSecretarias"
              :key="s.id"
              :class="['sec-check-item', { selected: eixoForm.secretarias_selecionadas.includes(s.id) }]"
              @click="toggleSecretariaNoEixo(s.id)"
            >
              <i :class="['bi', eixoForm.secretarias_selecionadas.includes(s.id) ? 'bi-check-square-fill text-primary' : 'bi-square']"></i>
              <span>{{ s.nome }}</span>
            </div>
          </div>
        </div>

        <div class="modal-footer-box">
          <button type="button" class="btn-secondary" @click="showModalEixo = false">Cancelar</button>
          <button type="submit" class="btn-primary">Salvar Eixo</button>
        </div>
      </form>
    </Modal>

    <!-- MODAL ANULAR -->
    <Modal
      :show="showModalAnular"
      title="Anular Sorteio"
      icon="bi-exclamation-triangle-fill"
      icon-color="text-danger"
      @close="showModalAnular = false"
    >
      <div v-if="ganhadorAnulando">
        <p class="text-light">
          Deseja anular o sorteio de <strong>{{ ganhadorAnulando.servidor_nome }}</strong> para o prêmio <strong>{{ ganhadorAnulando.premio_nome }}</strong>?
        </p>
        <div class="form-group">
          <label class="form-label">Motivo da Anulação</label>
          <input v-model="motivoAnulacao" type="text" class="form-control" required />
        </div>
      </div>
      <template #footer>
        <button type="button" class="btn-secondary" @click="showModalAnular = false">Cancelar</button>
        <button type="button" class="btn-danger" @click="confirmarAnulacao">Confirmar Anulação</button>
      </template>
    </Modal>

    <!-- MODAL SUCESSO -->
    <Modal
      :show="showModalSucessoSorteio"
      title="Sorteio Realizado com Sucesso!"
      icon="bi-trophy-fill"
      icon-color="text-warning"
      @close="showModalSucessoSorteio = false"
    >
      <div v-if="sorteioResultado" class="text-center py-3">
        <i class="bi bi-stars text-warning display-4 mb-2"></i>
        <h3 class="font-outfit text-white fw-bold mb-1">{{ sorteioResultado.servidor_nome }}</h3>
        <p class="text-warning fs-5 fw-bold mb-2">{{ sorteioResultado.premio_nome }}</p>
        <p class="text-muted small">O telão foi sincronizado e está exibindo a comemoração oficial.</p>
      </div>
      <template #footer>
        <button type="button" class="btn-primary w-100 font-outfit" @click="showModalSucessoSorteio = false">
          Continuar
        </button>
      </template>
    </Modal>

    <!-- MODAL DE CONFIRMAÇÃO DO INÍCIO DO SORTEIO (IN-APP) -->
    <Modal
      :show="showModalConfirmarInicio"
      title="Iniciar Sorteio no Telão"
      icon="bi-stars"
      iconColor="text-warning"
      @close="showModalConfirmarInicio = false"
    >
      <div class="confirm-modal-body">
        <p class="text-white mb-2 font-outfit">
          Você está prestes a dar o aval de início para sortear <strong>{{ premiosRodada.length }} prêmio(s)</strong> no Telão.
        </p>

        <div class="confirm-prizes-list">
          <div v-for="(item, idx) in premiosRodada" :key="item.item_id" class="confirm-prize-row">
            <span class="badge-num font-outfit">#{{ idx + 1 }}</span>
            <div class="confirm-prize-info">
              <strong class="confirm-prize-name font-outfit">{{ item.premio_nome }}</strong>
              <span class="confirm-prize-cat font-outfit">{{ item.categoria === 'categoria_1' ? 'Geral' : (item.eixo_nome || 'Eixo') }}</span>
            </div>
          </div>
        </div>

        <div class="alert-info-box font-outfit mt-3">
          <i class="bi bi-info-circle-fill me-2 text-info"></i>
          Ao confirmar, a animação de roleta de 10 segundos começará imediatamente no Telão do evento.
        </div>
      </div>

      <template #footer>
        <button type="button" class="btn-secondary font-outfit" @click="showModalConfirmarInicio = false">
          Cancelar
        </button>
        <button type="button" class="btn-primary font-outfit btn-confirm-start" @click="confirmarEIniciarSorteio">
          <i class="bi bi-stars me-1"></i> Sim, Iniciar no Telão (10s)
        </button>
      </template>
    </Modal>

    <!-- SISTEMA DE TOAST NOTIFICATIONS (NÃO-BLOQUEANTE) -->
    <Teleport to="body">
      <Transition name="toast-slide">
        <div v-if="toast" class="custom-toast" :class="'toast-' + toast.type">
          <div class="toast-icon">
            <i v-if="toast.type === 'error'" class="bi bi-exclamation-octagon-fill text-danger"></i>
            <i v-else-if="toast.type === 'warning'" class="bi bi-exclamation-triangle-fill text-warning"></i>
            <i v-else-if="toast.type === 'success'" class="bi bi-check-circle-fill text-success"></i>
            <i v-else class="bi bi-info-circle-fill text-info"></i>
          </div>
          <div class="toast-body">
            <span class="toast-text font-outfit">{{ toast.message }}</span>
          </div>
          <button type="button" class="toast-close" @click="toast = null">
            <i class="bi bi-x"></i>
          </button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.admin-sorteios-page {
  padding: 24px 0 60px;
}

.page-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}

.page-title {
  font-size: clamp(1.6rem, 4vw, 2.1rem);
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.page-subtitle {
  color: var(--text-muted);
  font-size: 0.88rem;
}

.btn-telao-pop {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  border: 1px solid rgba(245, 158, 11, 0.6);
  color: #000000 !important;
  font-weight: 800;
  font-size: 0.95rem;
  padding: 10px 20px;
  border-radius: 12px;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(245, 158, 11, 0.4);
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.btn-telao-pop:hover {
  transform: translateY(-2px);
  filter: brightness(1.1);
  box-shadow: 0 6px 25px rgba(245, 158, 11, 0.6);
}

/* ABAS / TABS */
.tabs-nav-bar {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 28px;
  overflow-x: auto;
  padding-bottom: 6px;
}

.tab-btn {
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-muted);
  font-weight: 700;
  font-size: 0.92rem;
  padding: 10px 18px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.tab-btn:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.05);
}

.tab-btn.active {
  color: #ffffff;
  background: var(--serv-gradient);
  border-color: rgba(255, 255, 255, 0.2);
  box-shadow: 0 4px 15px rgba(217, 70, 239, 0.35);
}

.deck-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

.badge-presentes {
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.35);
  color: #34d399;
  padding: 8px 16px;
  border-radius: 999px;
  font-size: 0.9rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
}

/* CARDS DE PRÊMIOS */
.prizes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.prize-card-live {
  background: var(--bg-card);
  border: 1px solid var(--border-glass);
  border-radius: 20px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: all 0.25s ease;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}

.prize-card-live:hover {
  border-color: rgba(6, 182, 212, 0.4);
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5);
  transform: translateY(-2px);
}

.prize-card-live.prize-completed {
  opacity: 0.7;
}

.prize-card-photo-box {
  position: relative;
  width: 100%;
  height: 180px;
  background: #050811;
  display: flex;
  align-items: center;
  justify-content: center;
}

.prize-card-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.prize-placeholder {
  font-size: 3.5rem;
  color: #475569;
}

.cat-badge {
  font-size: 0.74rem;
  font-weight: 800;
  padding: 4px 10px;
  border-radius: 999px;
  letter-spacing: 0.5px;
  display: inline-flex;
  align-items: center;
}

.cat-1 {
  background: rgba(6, 182, 212, 0.2);
  color: #22d3ee;
  border: 1px solid rgba(6, 182, 212, 0.4);
}

.cat-2 {
  background: rgba(245, 158, 11, 0.2);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.4);
}

.prize-card-content {
  padding: 20px;
  display: flex;
  flex-direction: column;
  flex: 1;
}

.prize-card-title {
  font-size: 1.2rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.prize-card-desc {
  font-size: 0.82rem;
  color: var(--text-muted);
  margin-bottom: 14px;
}

.prize-metrics-row {
  display: flex;
  gap: 8px;
  margin-bottom: 18px;
}

.metric-pill {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 0.75rem;
  flex: 1;
}

.m-k {
  display: block;
  color: var(--text-subtle);
  font-size: 0.7rem;
  text-transform: uppercase;
  font-weight: 700;
}

.m-v {
  font-size: 1rem;
  font-weight: 800;
  color: #ffffff;
}

.btn-sortear {
  background: var(--serv-gradient);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #ffffff;
  font-weight: 800;
  font-size: 1rem;
  padding: 12px;
  border-radius: 12px;
  width: 100%;
  cursor: pointer;
  box-shadow: 0 4px 15px rgba(217, 70, 239, 0.35);
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.btn-sortear:hover:not(:disabled) {
  background: var(--serv-gradient-hover);
  transform: translateY(-2px);
  box-shadow: 0 6px 22px rgba(245, 158, 11, 0.45);
}

.btn-sortear:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-completed {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text-muted);
  font-weight: 700;
  padding: 12px;
  border-radius: 12px;
  text-align: center;
}

.tab-actions-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

/* EIXOS */
.eixos-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 20px;
}

.eixo-card {
  padding: 24px;
}

.eixo-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.eixo-title {
  font-size: 1.3rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.eixo-desc {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-bottom: 0;
}

.eixo-actions {
  display: flex;
  gap: 6px;
}

.sec-label {
  display: block;
  font-size: 0.76rem;
  text-transform: uppercase;
  color: var(--text-subtle);
  font-weight: 700;
  margin-bottom: 8px;
}

.sec-chips-box {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sec-chip {
  background: rgba(6, 182, 212, 0.12);
  border: 1px solid rgba(6, 182, 212, 0.3);
  color: #67e8f9;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.sec-tag {
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.3);
  color: #fde047;
  font-size: 0.78rem;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
}

.secretarias-checkbox-grid {
  max-height: 220px;
  overflow-y: auto;
  display: grid;
  grid-template-columns: 1fr;
  gap: 6px;
  padding-right: 6px;
}

.sec-check-item {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: all 0.15s ease;
}

.sec-check-item:hover, .sec-check-item.selected {
  background: rgba(6, 182, 212, 0.15);
  border-color: rgba(6, 182, 212, 0.35);
  color: #ffffff;
}

.table-thumb {
  width: 46px;
  height: 46px;
  border-radius: 10px;
  overflow: hidden;
  background: #000;
  border: 1px solid rgba(255, 255, 255, 0.15);
}

.thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumb-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  font-size: 1.2rem;
}

.photo-preview-box {
  width: 100px;
  height: 100px;
  border-radius: 12px;
  overflow: hidden;
  border: 2px solid var(--primary-accent);
}

.preview-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.empty-box {
  text-align: center;
  padding: 60px 20px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px dashed rgba(255, 255, 255, 0.1);
  border-radius: 20px;
}

.text-end { text-align: right; }
.w-100 { width: 100%; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.mb-0 { margin-bottom: 0; }
.mb-1 { margin-bottom: 4px; }
.mb-2 { margin-bottom: 8px; }
.mt-2 { margin-top: 8px; }
.text-danger { color: #ef4444; }
.text-warning { color: #f59e0b; }
.text-success { color: #10b981; }
.text-info { color: #38bdf8; }
.text-white { color: #ffffff; }
.text-subtle { color: var(--text-subtle); }

/* ========================================================================== */
/* ESTILOS DA MESA DE RODADA DO TELÃO                                         */
/* ========================================================================== */
.mesa-stage-control-panel {
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(20px);
  border: 2px solid rgba(56, 189, 248, 0.3);
  border-radius: 20px;
  padding: 24px;
  box-shadow: 0 15px 40px rgba(0, 0, 0, 0.5), 0 0 25px rgba(56, 189, 248, 0.1);
}

.mesa-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  flex-wrap: wrap;
}

.mesa-badge-tag {
  font-size: 0.75rem;
  font-weight: 800;
  color: #38bdf8;
  letter-spacing: 1px;
}

.mesa-panel-title {
  font-size: 1.6rem;
  font-weight: 900;
  color: #ffffff;
  margin: 4px 0;
}

.mesa-panel-subtitle {
  font-size: 0.88rem;
  color: #94a3b8;
  margin: 0;
  max-width: 600px;
}

.mesa-header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.btn-telao-view {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #ffffff;
  padding: 10px 18px;
  border-radius: 12px;
  font-weight: 700;
  font-size: 0.88rem;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-telao-view:hover {
  background: rgba(255, 255, 255, 0.16);
  border-color: #38bdf8;
}

.btn-danger-soft {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #fca5a5;
  padding: 10px 18px;
  border-radius: 12px;
  font-weight: 700;
  font-size: 0.88rem;
  cursor: pointer;
}
.btn-danger-soft:hover {
  background: rgba(239, 68, 68, 0.3);
  color: #ffffff;
}

.btn-iniciar-mesa {
  background: linear-gradient(135deg, #059669 0%, #10b981 100%);
  border: 1px solid #34d399;
  color: #ffffff;
  padding: 12px 24px;
  border-radius: 12px;
  font-weight: 800;
  font-size: 0.95rem;
  cursor: pointer;
  box-shadow: 0 0 25px rgba(16, 185, 129, 0.4);
  transition: all 0.2s ease;
}
.btn-iniciar-mesa:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 0 35px rgba(16, 185, 129, 0.7);
}
.btn-iniciar-mesa:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.mesa-status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 18px 0 14px 0;
  padding: 10px 16px;
  background: rgba(11, 15, 25, 0.8);
  border-radius: 12px;
  font-size: 0.84rem;
  font-weight: 700;
}

.chip-sorteando {
  color: #fca5a5;
  display: flex;
  align-items: center;
  gap: 8px;
}
.chip-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ef4444;
  animation: pulseDot 0.8s infinite alternate;
}
.chip-finalizado {
  color: #fde68a;
}
.chip-preparando {
  color: #38bdf8;
}
.chip-idle {
  color: #94a3b8;
}
.badge-presentes-chip {
  color: #e2e8f0;
}

.mesa-items-deck {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  margin-top: 14px;
}

.mesa-item-card {
  position: relative;
  background: rgba(11, 15, 25, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 14px;
  padding: 14px;
  display: flex;
  gap: 14px;
  align-items: center;
  transition: all 0.2s ease;
}
.mesa-item-card.item-sorteado {
  border-color: #fbbf24;
  box-shadow: 0 0 18px rgba(251, 191, 36, 0.2);
}
.mesa-item-card.item-anulado {
  opacity: 0.6;
  border-color: #ef4444;
}

.mesa-item-photo {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  overflow: hidden;
  background: #0f172a;
  border: 2px solid rgba(255, 255, 255, 0.1);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.item-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.item-placeholder {
  color: #64748b;
  font-size: 1.5rem;
}

.mesa-item-info {
  flex: 1;
  min-width: 0;
}
.mesa-item-cat {
  font-size: 0.68rem;
  font-weight: 800;
  color: #38bdf8;
  letter-spacing: 0.5px;
}
.mesa-item-nome {
  font-size: 0.95rem;
  font-weight: 800;
  color: #ffffff;
  margin: 2px 0 6px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mesa-item-pending {
  font-size: 0.78rem;
  color: #94a3b8;
}

.mesa-item-winner {
  background: rgba(251, 191, 36, 0.1);
  border: 1px solid rgba(251, 191, 36, 0.25);
  border-radius: 8px;
  padding: 6px 8px;
  font-size: 0.78rem;
}
.winner-label {
  font-size: 0.68rem;
  font-weight: 800;
  color: #fbbf24;
}
.winner-name {
  color: #ffffff;
  display: block;
}
.winner-details {
  color: #cbd5e1;
  font-size: 0.72rem;
  display: block;
}
.btn-anular-mesa-link {
  background: none;
  border: none;
  color: #f87171;
  font-size: 0.74rem;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
  margin-top: 4px;
}
.btn-anular-mesa-link:hover {
  text-decoration: underline;
}

.btn-remover-mesa {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  border: none;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.btn-remover-mesa:hover {
  background: rgba(239, 68, 68, 0.3);
  color: #ffffff;
}

.mesa-deck-empty {
  text-align: center;
  padding: 35px 20px;
  border: 1px dashed rgba(255, 255, 255, 0.1);
  border-radius: 14px;
  margin-top: 14px;
}

.mesa-add-action-group {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
}

.qtd-stepper {
  display: flex;
  align-items: center;
  background: rgba(11, 15, 25, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  overflow: hidden;
}
.btn-step {
  background: none;
  border: none;
  color: #ffffff;
  font-weight: 800;
  width: 28px;
  height: 34px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.btn-step:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
}
.btn-step:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.input-step {
  width: 38px;
  height: 34px;
  background: none;
  border: none;
  color: #38bdf8;
  font-weight: 800;
  text-align: center;
  font-size: 0.9rem;
  outline: none;
  -moz-appearance: textfield;
}
.input-step::-webkit-outer-spin-button,
.input-step::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.btn-add-mesa {
  flex: 1;
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.4);
  color: #38bdf8;
  padding: 8px 12px;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.82rem;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}
.btn-add-mesa:hover:not(:disabled) {
  background: #38bdf8;
  color: #0b1220;
}
.btn-add-mesa:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}


/* ========================================================================== */
/* TOAST NOTIFICATION MODERNO & IN-APP MODAL                                  */
/* ========================================================================== */
.custom-toast {
  position: fixed;
  bottom: 28px;
  right: 28px;
  background: rgba(15, 23, 42, 0.95);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 16px;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.6), 0 0 20px rgba(0, 0, 0, 0.4);
  z-index: 99999;
  max-width: 440px;
}

.toast-error {
  border-color: #ef4444;
  box-shadow: 0 10px 30px rgba(239, 68, 68, 0.25);
}
.toast-warning {
  border-color: #f59e0b;
  box-shadow: 0 10px 30px rgba(245, 158, 11, 0.25);
}
.toast-success {
  border-color: #10b981;
  box-shadow: 0 10px 30px rgba(16, 185, 129, 0.25);
}

.toast-icon {
  font-size: 1.4rem;
  display: flex;
  align-items: center;
}

.toast-text {
  font-size: 0.92rem;
  color: #ffffff;
  font-weight: 600;
  line-height: 1.35;
}

.toast-close {
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0 0 0 6px;
  display: flex;
  align-items: center;
}
.toast-close:hover {
  color: #ffffff;
}

.toast-slide-enter-active,
.toast-slide-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.toast-slide-enter-from {
  opacity: 0;
  transform: translateY(20px) scale(0.95);
}
.toast-slide-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(0.95);
}

.btn-mesa-full {
  background: rgba(6, 182, 212, 0.15);
  border: 1px solid rgba(6, 182, 212, 0.4);
  color: #67e8f9;
  padding: 8px 14px;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.82rem;
  text-align: center;
  width: 100%;
}

.badge-na-mesa-mini {
  font-size: 0.72rem;
  opacity: 0.8;
  margin-left: 4px;
}

.confirm-modal-body {
  padding: 4px 0;
}

.confirm-prizes-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 220px;
  overflow-y: auto;
  margin: 12px 0;
}

.confirm-prize-row {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 8px 12px;
}

.badge-num {
  background: rgba(56, 189, 248, 0.2);
  color: #38bdf8;
  font-weight: 800;
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 6px;
}

.confirm-prize-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex: 1;
}

.confirm-prize-name {
  color: #ffffff;
  font-size: 0.88rem;
}

.confirm-prize-cat {
  color: #fbbf24;
  font-size: 0.75rem;
  font-weight: 700;
}

.alert-info-box {
  background: rgba(6, 182, 212, 0.1);
  border: 1px solid rgba(6, 182, 212, 0.25);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 0.82rem;
  color: #cbd5e1;
}

.btn-confirm-start {
  background: linear-gradient(135deg, #059669 0%, #10b981 100%) !important;
  border-color: #34d399 !important;
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.4) !important;
}

</style>