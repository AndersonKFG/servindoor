<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import Modal from '../components/Modal.vue'

const { toast } = useToast()
const { confirmModal } = useConfirm()

const router = useRouter()
const activeTab = ref('mesa')

const loading = ref(true)
const premios = ref([])
const totalPresentes = ref(0)
const eixos = ref([])
const todasSecretarias = ref([])
const secretariasList = ref([])
const buscaSecretaria = ref('')
const filtroEixoSec = ref('')
const showModalSecretaria = ref(false)
const salvandoSec = ref(false)
const secretariaForm = ref({ id: null, nome: '', sigla: '', eixo_id: '' })

const secretariasFiltradas = computed(() => {
  return secretariasList.value.filter(s => {
    if (filtroEixoSec.value && String(s.eixo_id) !== String(filtroEixoSec.value)) {
      return false
    }
    if (buscaSecretaria.value.trim()) {
      const q = buscaSecretaria.value.toLowerCase().trim()
      const matchNome = (s.nome || '').toLowerCase().includes(q)
      const matchSigla = (s.sigla || '').toLowerCase().includes(q)
      const matchEixo = (s.eixo_nome || '').toLowerCase().includes(q)
      if (!matchNome && !matchSigla && !matchEixo) return false
    }
    return true
  })
})

function abrirNovaSecretaria() {
  secretariaForm.value = { id: null, nome: '', sigla: '', eixo_id: '' }
  showModalSecretaria.value = true
}

function abrirEditarSecretaria(sec) {
  secretariaForm.value = {
    id: sec.id,
    nome: sec.nome,
    sigla: sec.sigla || '',
    eixo_id: sec.eixo_id || ''
  }
  showModalSecretaria.value = true
}

async function handleSalvarSecretaria() {
  if (!secretariaForm.value.nome.trim()) {
    showToast('O nome da secretaria é obrigatório.', 'error')
    return
  }
  salvandoSec.value = true
  try {
    const formData = new FormData()
    formData.append('nome', secretariaForm.value.nome.trim())
    if (secretariaForm.value.sigla) {
      formData.append('sigla', secretariaForm.value.sigla.trim())
    }
    if (secretariaForm.value.eixo_id) {
      formData.append('eixo_id', secretariaForm.value.eixo_id)
    }
    if (secretariaForm.value.id) {
      formData.append('secretaria_id', secretariaForm.value.id)
    }

    const res = await fetch('/api/sorteios/secretarias', { method: 'POST', body: formData })
    if (res.ok) {
      showModalSecretaria.value = false
      showToast('Secretaria salva com sucesso!', 'success')
      await carregarDados()
    } else {
      const d = await res.json()
      showToast(d.detail || 'Erro ao salvar secretaria.', 'error')
    }
  } catch (e) {
    toast.error('Erro ao salvar secretaria.')
    showToast('Erro de comunicação ao salvar secretaria.', 'error')
  } finally {
    salvandoSec.value = false
  }
}

async function handleExcluirSecretaria(secId) {
  const confSec = await confirmModal({
    title: 'Excluir Secretaria',
    message: 'Deseja realmente excluir esta secretaria? Servidores associados ficarão sem vínculo.',
    confirmText: 'Excluir',
    variant: 'danger'
  })
  if (!confSec) return
  try {
    const res = await fetch('/api/sorteios/secretarias/' + secId, { method: 'DELETE' })
    if (res.ok) {
      showToast('Secretaria excluída com sucesso.', 'success')
      await carregarDados()
    } else {
      const d = await res.json()
      showToast(d.detail || 'Erro ao excluir secretaria.', 'error')
    }
  } catch (e) {
    toast.error('Erro ao excluir secretaria.')
  }
}
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

function showToast(message, type = 'error') {
  if (type === 'success') toast.success(message)
  else if (type === 'warning') toast.warning(message)
  else toast.error(message)
}

const sorteioResultado = ref(null)
const sorteandoId = ref(null)
const ganhadorAnulando = ref(null)
const motivoAnulacao = ref('Servidor ausente no momento do sorteio')
const fotoPremioInput = ref(null)

const premioForm = ref({
  id: null,
  nome: '',
  descricao: '',
  categoria: 'categoria_1',
  eixo_id: '0',
  quantidade: 1,
  foto_base64: '',
  foto_preview: '',
  foto_nome: ''
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

    const resSec = await fetch('/api/sorteios/secretarias')
    if (resSec.ok) {
      const dataSec = await resSec.json()
      secretariasList.value = dataSec.secretarias || []
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
    if (!silent) toast.error('Erro ao carregar dados dos sorteios.')
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

  const contagem = {}
  premiosRodada.value.forEach(item => {
    contagem[item.premio_id] = (contagem[item.premio_id] || 0) + 1
  })
  contagem[p.id] = (contagem[p.id] || 0) + qtd

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
    toast.error('Erro ao remover item da mesa.')
  }
}

function handleIniciarSorteioMesa() {
  if (premiosRodada.value.length === 0) {
    showToast('Adicione pelo menos um prêmio à mesa antes de iniciar o sorteio.', 'warning')
    return
  }
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
    toast.error('Erro ao limpar mesa do telão.')
  }
}

function abrirTelao() {
  window.open('/telao', '_blank')
}

async function handleSortear(p) {
  if (p.disponiveis <= 0) return
  const confSorteio = await confirmModal({
    title: 'Iniciar Sorteio',
    message: 'Deseja realizar o sorteio de "' + p.nome + '" agora? O telão será sincronizado instantaneamente!',
    confirmText: 'Iniciar Agora',
    variant: 'primary'
  })
  if (!confSorteio) return

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
    toast.error('Erro ao realizar sorteio.')
  } finally {
    sorteandoId.value = null
  }
}

function abrirAnulacao(g) {
  const targetId = g.ganhador_id || (g.ganhador ? g.ganhador.ganhador_id : g.id)
  const servidorNome = g.servidor_nome || g.nome || (g.ganhador ? g.ganhador.nome : 'Servidor')
  const premioNome = g.premio_nome || g.premio || (g.ganhador ? g.ganhador.premio_nome : 'Prêmio')

  ganhadorAnulando.value = {
    ...g,
    id: targetId,
    ganhador_id: targetId,
    servidor_nome: servidorNome,
    premio_nome: premioNome
  }
  motivoAnulacao.value = 'Servidor ausente no momento do sorteio'
  showModalAnular.value = true
}

async function confirmarAnulacao() {
  if (!ganhadorAnulando.value) return
  const idToAnular = ganhadorAnulando.value.ganhador_id || ganhadorAnulando.value.id
  if (!idToAnular || idToAnular === 'undefined') {
    showToast('Identificador do ganhador inválido para anulação.', 'error')
    return
  }
  try {
    const formData = new FormData()
    formData.append('motivo', motivoAnulacao.value)

    const res = await fetch('/api/sorteios/anular/' + idToAnular, {
      method: 'POST',
      body: formData
    })

    if (res.ok) {
      showModalAnular.value = false
      showToast('Sorteio anulado com sucesso e prêmio reaberto.', 'success')
      await carregarDados()
    } else {
      const d = await res.json()
      showToast(d.detail || 'Erro ao anular sorteio.', 'error')
    }
  } catch (e) {
    toast.error('Erro ao anular sorteio.')
    showToast('Falha na comunicação com o servidor.', 'error')
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
    foto_preview: '',
    foto_nome: ''
  }
  if (fotoPremioInput.value) {
    fotoPremioInput.value.value = ''
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
    foto_preview: p.foto_url || '',
    foto_nome: p.foto_url ? 'Foto Atual' : ''
  }
  showModalEditarPremio.value = true
}

function onFotoPremioChange(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    toast.warning('Por favor, selecione um arquivo de imagem válido (PNG, JPG, WEBP).')
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    toast.warning('A imagem deve ter no máximo 10MB.')
    return
  }
  premioForm.value.foto_nome = file.name
  const reader = new FileReader()
  reader.onload = () => {
    premioForm.value.foto_base64 = reader.result
    premioForm.value.foto_preview = reader.result
  }
  reader.readAsDataURL(file)
}

function removerFotoPremio() {
  premioForm.value.foto_base64 = ''
  premioForm.value.foto_preview = ''
  premioForm.value.foto_nome = ''
  if (fotoPremioInput.value) {
    fotoPremioInput.value.value = ''
  }
}

async function handleSalvarPremio(isEdit = false) {
  try {
    const formData = new FormData()
    formData.append('nome', (premioForm.value.nome || '').trim())
    formData.append('descricao', (premioForm.value.descricao || '').trim())
    formData.append('categoria', premioForm.value.categoria)
    formData.append('eixo_id', premioForm.value.eixo_id || '0')
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
      toast.success(isEdit ? 'Prêmio atualizado com sucesso!' : 'Prêmio cadastrado com sucesso!')
    } else {
      let msg = 'Erro ao salvar prêmio.'
      try {
        const d = await res.json()
        msg = d.detail || d.message || msg
      } catch (err) {}
      showToast(msg, 'error')
    }
  } catch (e) {
    toast.error('Erro de conexão ao salvar prêmio.')
  }
}

async function handleExcluirPremio(pId) {
  const confPremio = await confirmModal({
    title: 'Excluir Prêmio',
    message: 'Deseja realmente excluir este prêmio?',
    confirmText: 'Excluir',
    variant: 'danger'
  })
  if (!confPremio) return
  try {
    const res = await fetch('/api/sorteios/premios/' + pId, { method: 'DELETE' })
    if (res.ok) {
      await carregarDados()
    } else {
      const d = await res.json()
      showToast(d.detail || 'Não foi possível excluir.', 'error')
    }
  } catch (e) {
    toast.error('Erro ao excluir prêmio.')
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
    toast.error('Erro ao salvar eixo.')
  }
}

async function handleExcluirEixo(eixoId) {
  const confEixo = await confirmModal({
    title: 'Excluir Eixo',
    message: 'Deseja realmente excluir este eixo?',
    confirmText: 'Excluir',
    variant: 'danger'
  })
  if (!confEixo) return
  try {
    const res = await fetch('/api/sorteios/eixos/' + eixoId, { method: 'DELETE' })
    if (res.ok) {
      await carregarDados()
    } else {
      const d = await res.json()
      showToast(d.detail || 'Erro ao excluir eixo.', 'error')
    }
  } catch (e) {
    toast.error('Erro ao excluir eixo.')
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
  <div class="admin-page">
    <div class="app-container">
    
    <!-- CABEÇALHO DA PÁGINA -->
    <div class="admin-header-row mb-4">
      <div>
        <span class="admin-eyebrow">
          <i class="bi bi-trophy-fill me-1 text-cyan"></i> CENTRAL DE SORTEIOS
        </span>
        <h1 class="page-title font-quattrocento">Gestão e Mesa de Sorteios</h1>
        <p class="page-subtitle">Controle de prêmios, eixos temáticos e execução em tempo real.</p>
      </div>

      <div class="admin-header-actions d-flex flex-wrap gap-2">
        <button type="button" class="btn-primary" @click="abrirTelaoEmNovaJanela">
          <i class="bi bi-display-fill me-1"></i> Abrir Telão de Projeção
        </button>
        <button type="button" class="btn-secondary" :disabled="loading" @click="carregarDados()">
          <i class="bi bi-arrow-clockwise me-1" :class="{ 'spin-anim': loading }"></i> Atualizar
        </button>
      </div>
    </div>

    <!-- ABAS PRINCIPAIS -->
    <div class="status-tabs mb-4">
      <button
        type="button"
        :class="['tab-btn', { 'is-active': activeTab === 'mesa' }]"
        @click="activeTab = 'mesa'"
      >
        <i class="bi bi-dice-5-fill me-1"></i> Mesa de Sorteio ao Vivo
      </button>

      <button
        type="button"
        :class="['tab-btn', { 'is-active': activeTab === 'premios' }]"
        @click="activeTab = 'premios'"
      >
        <i class="bi bi-gift-fill me-1"></i> Gestão de Prêmios ({{ premios.length }})
      </button>

      <button
        type="button"
        :class="['tab-btn', { 'is-active': activeTab === 'eixos' }]"
        @click="activeTab = 'eixos'"
      >
        <i class="bi bi-diagram-3-fill me-1"></i> Eixos Temáticos ({{ eixos.length }})
      </button>

      <button
        type="button"
        :class="['tab-btn', { 'is-active': activeTab === 'secretarias' }]"
        @click="activeTab = 'secretarias'"
      >
        <i class="bi bi-building-fill me-1"></i> Secretarias Municipais ({{ secretariasList.length }})
      </button>

      <button
        type="button"
        :class="['tab-btn', { 'is-active': activeTab === 'historico' }]"
        @click="activeTab = 'historico'"
      >
        <i class="bi bi-clock-history me-1"></i> Histórico de Ganhadores
      </button>
    </div>

    <!-- ABA 1: MESA DE SORTEIO (PREPARAÇÃO DE RODADA E CONTROLE DO TELÃO) -->
    <div v-if="activeTab === 'mesa'">
      
      <!-- PAINEL 1: CONTROLE DA RODADA AO VIVO NO TELÃO -->
      <div class="mesa-stage-control-panel mb-4">
        
        <div class="mesa-panel-header">
          <div>
            <span class="mesa-badge-tag d-inline-flex align-items-center">
              <i class="bi bi-broadcast me-1"></i> SINCRONIZAÇÃO EM TEMPO REAL
            </span>
            <h2 class="mesa-panel-title font-quattrocento">
              Mesa de Rodada do Telão
            </h2>
            <p class="mesa-panel-subtitle">
              Selecione os prêmios abaixo para exibi-los no Telão. Quando estiver pronto, clique em <strong>Iniciar Sorteio</strong> para rodar a animação de 10s.
            </p>
          </div>

          <div class="mesa-header-actions">
            <button
              type="button"
              class="btn-secondary"
              @click="abrirTelao"
              title="Abrir a tela de projeção em tela cheia"
            >
              <i class="bi bi-display me-1"></i> Abrir Telão (/telao)
            </button>

            <button
              v-if="premiosRodada.length > 0 && mesaStatus !== 'sorteando'"
              type="button"
              class="btn-danger"
              @click="handleLimparMesa"
            >
              <i class="bi bi-trash3 me-1"></i> Limpar Mesa
            </button>

            <button
              type="button"
              class="btn-primary"
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
        <div class="mesa-status-bar">
          <span v-if="mesaStatus === 'sorteando'" class="chip-sorteando">
            <span class="chip-pulse"></span> Animação em andamento no Telão (10 segundos)
          </span>
          <span v-else-if="mesaStatus === 'finalizado'" class="chip-finalizado">
            <i class="bi bi-check-circle-fill me-1"></i> Rodada finalizada! Ganhadores revelados no Telão
          </span>
          <span v-else-if="premiosRodada.length > 0" class="chip-preparando">
            <i class="bi bi-layers-fill me-1"></i> {{ premiosRodada.length }} prêmio(s) preparado(s) no Telão • Aguardando início
          </span>
          <span v-else class="chip-idle">
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
              <span class="mesa-item-cat">
                {{ item.categoria === 'categoria_1' ? 'CATEGORIA GERAL' : 'EIXO: ' + (item.eixo_nome || 'Setorial') }}
              </span>
              <h4 class="mesa-item-nome">{{ item.premio_nome }}</h4>

              <div v-if="item.ganhador" class="mesa-item-winner">
                <div class="winner-label">
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
                  class="btn-anular-mesa-link"
                  @click="abrirAnulacao({ ...item.ganhador, premio_nome: item.premio_nome })"
                >
                  <i class="bi bi-x-circle me-1"></i> Anular (Ausente)
                </button>
              </div>
              <div v-else class="mesa-item-pending">
                <i class="bi bi-hourglass-split me-1"></i> Aguardando sorteio
              </div>
            </div>

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
          <p class="text-muted mb-0">
            A mesa de sorteio está vazia. Escolha os prêmios no catálogo abaixo e clique em <strong>"+ Adicionar à Rodada"</strong>.
          </p>
        </div>

      </div>

      <!-- PAINEL 2: CATÁLOGO DE PRÊMIOS DISPONÍVEIS PARA ADICIONAR À MESA -->
      <div class="catalogo-section mt-4">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h3 class="text-white fw-bold mb-0 font-quattrocento">
            <i class="bi bi-gift-fill me-2 text-cyan"></i> Catálogo de Prêmios Disponíveis
          </h3>
          <span class="text-muted small">
            Defina a quantidade de cada item e adicione à rodada do telão
          </span>
        </div>

        <!-- Barra de Filtros: Categorias e Disponibilidade -->
        <div class="filter-card mb-3 p-2">
          <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <div class="d-flex align-items-center gap-1 flex-wrap">
              <span class="text-muted small fw-bold me-1">Categoria:</span>
              <button
                type="button"
                class="btn btn-sm"
                :class="filtroCategoria === 'todas' ? 'btn-primary' : 'btn-secondary'"
                @click="filtroCategoria = 'todas'"
              >
                Todas
              </button>
              <button
                type="button"
                class="btn btn-sm"
                :class="filtroCategoria === 'categoria_1' ? 'btn-primary' : 'btn-secondary'"
                @click="filtroCategoria = 'categoria_1'"
              >
                Cat 1 (Geral)
              </button>
              <button
                type="button"
                class="btn btn-sm"
                :class="filtroCategoria === 'categoria_2' ? 'btn-primary' : 'btn-secondary'"
                @click="filtroCategoria = 'categoria_2'"
              >
                Cat 2 (Eixos)
              </button>
            </div>

            <div class="d-flex align-items-center gap-1 flex-wrap">
              <span class="text-muted small fw-bold me-1">Disponibilidade:</span>
              <button
                type="button"
                class="btn btn-sm"
                :class="filtroDisponibilidade === 'todos' ? 'btn-primary' : 'btn-secondary'"
                @click="filtroDisponibilidade = 'todos'"
              >
                Todos ({{ premios.length }})
              </button>
              <button
                type="button"
                class="btn btn-sm"
                :class="filtroDisponibilidade === 'disponiveis' ? 'btn-primary' : 'btn-secondary'"
                @click="filtroDisponibilidade = 'disponiveis'"
              >
                Apenas Disponíveis
              </button>
              <button
                type="button"
                class="btn btn-sm"
                :class="filtroDisponibilidade === 'esgotados' ? 'btn-primary' : 'btn-secondary'"
                @click="filtroDisponibilidade = 'esgotados'"
              >
                Sorteados
              </button>
            </div>
          </div>
        </div>

        <div class="prizes-grid">
          <div
            v-for="p in premiosFiltrados" 
            :key="p.id"
            class="prize-card-live"
            :class="{ 'prize-completed': p.disponiveis === 0 }"
          >
            <div class="prize-card-photo-box">
              <img v-if="p.foto_url && !imgErrors[p.id]" :src="p.foto_url" alt="Prêmio" class="prize-card-img" @error="imgErrors[p.id] = true" />
              <div v-else class="prize-placeholder"><i class="bi bi-gift-fill"></i></div>
              
              <span :class="['cat-badge', p.categoria === 'categoria_1' ? 'cat-1' : 'cat-2']">
                {{ p.categoria === 'categoria_1' ? 'Cat 1 (Geral)' : 'Cat 2 (' + (p.eixo_nome || 'Eixo') + ')' }}
              </span>
            </div>

            <div class="prize-card-content">
              <h3 class="prize-card-title">{{ p.nome }}</h3>
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
                    class="btn-add-mesa"
                    :disabled="isDisparandoMesa || mesaStatus === 'sorteando'"
                    @click="handleAdicionarARodada(p)"
                  >
                    <i class="bi bi-plus-circle me-1"></i> Adicionar
                    <span v-if="getQtdNaMesa(p.id) > 0" class="badge-na-mesa-mini">({{ getQtdNaMesa(p.id) }} na mesa)</span>
                  </button>
                </div>

                <div v-else-if="getQtdNaMesa(p.id) > 0" class="btn-mesa-full">
                  <i class="bi bi-check2-all me-1"></i> Tudo na Mesa ({{ getQtdNaMesa(p.id) }}/{{ p.disponiveis }})
                </div>

                <div v-else class="btn-completed">
                  <i class="bi bi-check-all me-1"></i> 100% Sorteado
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="premios.length === 0" class="mesa-deck-empty mt-3">
          <i class="bi bi-gift text-muted fs-1 mb-2"></i>
          <p class="text-muted">Nenhum prêmio cadastrado. Vá até a aba <strong>Gestão de Prêmios</strong>.</p>
        </div>
      </div>

    </div>

    <!-- ABA 2: CRUD PRÊMIOS -->
    <div v-if="activeTab === 'premios'">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h3 class="text-white fw-bold mb-0 font-quattrocento">Lista de Prêmios Cadastrados</h3>
        <button type="button" class="btn-primary" @click="abrirNovoPremio">
          <i class="bi bi-plus-circle-fill me-1"></i> Cadastrar Novo Prêmio
        </button>
      </div>

      <div class="table-card">
        <div class="table-responsive">
          <table class="custom-table">
            <thead>
              <tr>
                <th style="width: 50px;">Foto</th>
                <th>Nome do Prêmio</th>
                <th>Categoria</th>
                <th>Eixo Temático</th>
                <th>Qtd (Sorteada / Total)</th>
                <th class="text-end">Ações</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in premios" :key="p.id">
                <td>
                  <div class="table-avatar">
                    <img v-if="p.foto_url" :src="p.foto_url" alt="Foto Prêmio" />
                    <div v-else class="table-avatar--fallback"><i class="bi bi-gift-fill"></i></div>
                  </div>
                </td>
                <td>
                  <strong class="table-user-name text-white">{{ p.nome }}</strong>
                  <small v-if="p.descricao" class="text-muted d-block mt-1">{{ p.descricao }}</small>
                </td>
                <td>
                  <span :class="['table-tag', p.categoria === 'categoria_1' ? 'table-tag--cyan' : 'table-tag--amber']">
                    {{ p.categoria_label }}
                  </span>
                </td>
                <td>
                  <span v-if="p.eixo_nome" class="table-tag table-tag--cyan">{{ p.eixo_nome }}</span>
                  <span v-else class="text-muted small">Geral (Todos)</span>
                </td>
                <td>
                  <strong class="text-white">{{ p.quantidade_sorteada }} / {{ p.quantidade }}</strong>
                </td>
                <td class="text-end">
                  <div class="d-flex align-items-center justify-content-end gap-1">
                    <button type="button" class="btn-action-icon btn-action-icon--cyan" title="Editar Prêmio" @click="abrirEditarPremio(p)">
                      <i class="bi bi-pencil-fill"></i>
                    </button>
                    <button
                      type="button"
                      class="btn-action-icon btn-action-icon--danger"
                      title="Excluir Prêmio"
                      :disabled="p.quantidade_sorteada > 0"
                      @click="handleExcluirPremio(p.id)"
                    >
                      <i class="bi bi-trash-fill"></i>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ABA 3: CRUD EIXOS -->
    <div v-if="activeTab === 'eixos'">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <div>
          <h3 class="text-white fw-bold mb-1 font-quattrocento">Eixos Temáticos de Secretarias</h3>
          <p class="text-muted small mb-0">Agrupe secretarias para os sorteios exclusivos da Categoria 2.</p>
        </div>
        <button type="button" class="btn-primary" @click="abrirNovoEixo">
          <i class="bi bi-diagram-3 me-1"></i> Criar Novo Eixo
        </button>
      </div>

      <div class="eixos-grid">
        <div v-for="e in eixos" :key="e.id" class="eixo-card">
          <div class="eixo-header">
            <div>
              <h4 class="eixo-title font-quattrocento">{{ e.nome }}</h4>
              <p v-if="e.descricao" class="eixo-desc">{{ e.descricao }}</p>
            </div>
            <div class="eixo-actions">
              <button type="button" class="btn-action-icon btn-action-icon--cyan" title="Editar Eixo" @click="abrirEditarEixo(e)">
                <i class="bi bi-pencil-fill"></i>
              </button>
              <button type="button" class="btn-action-icon btn-action-icon--danger" title="Excluir Eixo" @click="handleExcluirEixo(e.id)">
                <i class="bi bi-trash-fill"></i>
              </button>
            </div>
          </div>

          <div class="eixo-secretarias-list">
            <span class="sec-label">Secretarias Associadas ({{ e.secretarias_count }}):</span>
            <div class="sec-chips-box">
              <span v-for="s in e.secretarias" :key="s.id" class="sec-chip">
                <i class="bi bi-building me-1"></i> {{ s.nome }}
              </span>
              <span v-if="e.secretarias.length === 0" class="text-muted small">
                Nenhuma secretaria vinculada. Clique em editar para vincular.
              </span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="eixos.length === 0" class="mesa-deck-empty mt-3">
        <i class="bi bi-diagram-3 text-muted fs-1 mb-2"></i>
        <p class="text-muted">Nenhum eixo cadastrado. Clique em <strong>Criar Novo Eixo</strong>.</p>
      </div>
    </div>

    <!-- ABA 4: CRUD SECRETARIAS -->
    <div v-if="activeTab === 'secretarias'">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <div>
          <h3 class="text-white fw-bold mb-1 font-quattrocento">Gestão de Secretarias & Órgãos</h3>
          <p class="text-muted small mb-0">Cadastre, edite siglas e vincule as secretarias municipais aos Eixos Temáticos.</p>
        </div>
        <button type="button" class="btn-primary" @click="abrirNovaSecretaria">
          <i class="bi bi-plus-circle me-1"></i> Nova Secretaria
        </button>
      </div>

      <!-- FILTRO DE BUSCA -->
      <div class="filter-card mb-4">
        <div class="filter-grid filter-grid--search-two">
          <div class="search-box">
            <i class="bi bi-search search-icon"></i>
            <input
              v-model="buscaSecretaria"
              type="text"
              class="form-control"
              placeholder="Buscar por nome, sigla ou eixo..."
            />
          </div>
          <div>
            <select v-model="filtroEixoSec" class="form-select">
              <option value="">Todos os Eixos Temáticos</option>
              <option v-for="e in eixos" :key="e.id" :value="e.id">{{ e.nome }}</option>
            </select>
          </div>
        </div>
      </div>

      <!-- TABELA DE SECRETARIAS -->
      <div class="table-card">
        <div class="table-responsive">
          <table class="custom-table">
            <thead>
              <tr>
                <th>Órgão / Secretaria Oficial</th>
                <th>Sigla</th>
                <th>Eixo Temático Vinculado</th>
                <th>Servidores</th>
                <th class="text-end">Ações</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in secretariasFiltradas" :key="s.id">
                <td>
                  <div class="d-flex align-items-center gap-2">
                    <i class="bi bi-building text-cyan fs-5"></i>
                    <strong class="text-white">{{ s.nome }}</strong>
                  </div>
                </td>
                <td>
                  <span v-if="s.sigla" class="table-code-pill">{{ s.sigla }}</span>
                  <span v-else class="text-muted small">-</span>
                </td>
                <td>
                  <span v-if="s.eixo_nome" class="table-tag table-tag--cyan">
                    <i class="bi bi-diagram-3-fill me-1"></i> {{ s.eixo_nome }}
                  </span>
                  <span v-else class="text-muted small">Sem Eixo Vinculado</span>
                </td>
                <td>
                  <span class="text-muted small">{{ s.total_servidores === 1 ? '1 servidor' : (s.total_servidores || 0) + ' servidores' }}</span>
                </td>
                <td class="text-end">
                  <div class="d-flex align-items-center justify-content-end gap-1">
                    <button type="button" class="btn-action-icon btn-action-icon--cyan" title="Editar Secretaria" @click="abrirEditarSecretaria(s)">
                      <i class="bi bi-pencil-fill"></i>
                    </button>
                    <button type="button" class="btn-action-icon btn-action-icon--danger" title="Excluir Secretaria" @click="handleExcluirSecretaria(s.id)">
                      <i class="bi bi-trash-fill"></i>
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="secretariasFiltradas.length === 0">
                <td colspan="5" class="text-center py-4 text-muted">
                  Nenhuma secretaria encontrada.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ABA 5: HISTÓRICO -->
    <div v-if="activeTab === 'historico'">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h3 class="text-white fw-bold mb-0 font-quattrocento">Histórico de Ganhadores</h3>
        <button type="button" class="btn-secondary" @click="carregarDados">
          <i class="bi bi-arrow-clockwise me-1" :class="{ 'spin-anim': loading }"></i> Atualizar
        </button>
      </div>

      <div class="table-card">
        <div class="table-responsive">
          <table class="custom-table">
            <thead>
              <tr>
                <th style="width: 50px;">Foto</th>
                <th>Servidor Contemplado</th>
                <th>Secretaria / Órgão</th>
                <th>Prêmio Oficial</th>
                <th>Categoria</th>
                <th>Data / Hora</th>
                <th class="text-end" style="width: 140px;">Ação</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="historicoGanhadores.length === 0">
                <td colspan="7" class="text-center py-5 text-muted">
                  <i class="bi bi-trophy text-muted fs-2 d-block mb-2"></i>
                  Nenhum sorteio registrado no sistema até o momento.
                </td>
              </tr>
              <tr v-for="g in historicoGanhadores" :key="g.ganhador_id || g.id">
                <td>
                  <div class="table-avatar">
                    <img v-if="g.servidor_foto" :src="g.servidor_foto" alt="Foto" />
                    <div v-else class="table-avatar--fallback"><i class="bi bi-person-fill"></i></div>
                  </div>
                </td>
                <td>
                  <strong class="table-user-name text-white">{{ g.servidor_nome }}</strong>
                  <span class="small text-muted font-monospace d-block mt-1">{{ g.servidor_cpf }}</span>
                </td>
                <td>
                  <span class="table-tag table-tag--cyan">{{ g.secretaria_nome }}</span>
                </td>
                <td>
                  <div class="d-flex align-items-center gap-2">
                    <strong class="text-warning">{{ g.premio_nome }}</strong>
                  </div>
                </td>
                <td>
                  <span :class="['table-tag', g.categoria === 'categoria_1' ? 'table-tag--cyan' : 'table-tag--amber']">
                    {{ g.categoria === 'categoria_1' ? 'Geral' : 'Eixo' }}
                  </span>
                </td>
                <td>
                  <span class="text-muted small">{{ g.data_sorteio }}</span>
                </td>
                <td class="text-end">
                  <div class="d-flex align-items-center justify-content-end gap-1">
                    <span v-if="g.anulado" class="badge badge-danger">Anulado</span>
                    <button
                      v-else
                      type="button"
                      class="btn-danger btn-sm"
                      @click="abrirAnulacao(g)"
                    >
                      <i class="bi bi-x-circle me-1"></i> Anular
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- MODAL PRÊMIO -->
    <Modal
      :show="showModalNovoPremio || showModalEditarPremio"
      :title="premioForm.id ? 'Editar Prêmio' : 'Cadastrar Novo Prêmio'"
      icon="bi-gift-fill"
      :max-width="'600px'"
      @close="showModalNovoPremio = false; showModalEditarPremio = false;"
    >
      <form @submit.prevent="handleSalvarPremio(!!premioForm.id)">
        <div class="form-group mb-3">
          <label class="form-label">Nome do Prêmio *</label>
          <input v-model="premioForm.nome" type="text" class="form-control" placeholder="Ex: Smart TV 55 polegadas 4K" required />
        </div>

        <div class="form-group mb-3">
          <label class="form-label">Descrição (opcional)</label>
          <input v-model="premioForm.descricao" type="text" class="form-control" placeholder="Ex: Modelo UHD com Wi-Fi integrado" />
        </div>

        <div class="row g-3 mb-3">
          <div class="col-md-6 form-group">
            <label class="form-label">Categoria de Sorteio *</label>
            <select v-model="premioForm.categoria" class="form-select">
              <option value="categoria_1">Categoria 1 - Geral (Todos os servidores)</option>
              <option value="categoria_2">Categoria 2 - Eixo Temático Específico</option>
            </select>
          </div>

          <div class="col-md-6 form-group">
            <label class="form-label">Quantidade de Unidades *</label>
            <input v-model.number="premioForm.quantidade" type="number" min="1" max="100" class="form-control" required />
          </div>
        </div>

        <div v-if="premioForm.categoria === 'categoria_2'" class="form-group mb-3">
          <label class="form-label">Eixo Temático Exclusivo *</label>
          <select v-model="premioForm.eixo_id" class="form-select" required>
            <option v-for="e in eixos" :key="e.id" :value="String(e.id)">{{ e.nome }}</option>
          </select>
        </div>

        <div class="form-group mb-4">
          <label class="form-label">Foto Oficial do Prêmio</label>
          <div v-if="!premioForm.foto_preview" class="upload-dropzone">
            <input
              ref="fotoPremioInput"
              type="file"
              accept="image/*"
              class="d-none"
              id="inputFotoPremio"
              @change="onFotoPremioChange"
            />
            <label for="inputFotoPremio" class="upload-dropzone-label">
              <i class="bi bi-cloud-arrow-up-fill upload-icon"></i>
              <span class="upload-title">Clique para selecionar imagem</span>
              <span class="upload-subtitle">Formatos PNG, JPG ou WEBP (máx. 10MB)</span>
            </label>
          </div>

          <div v-else class="upload-preview-container">
            <img :src="premioForm.foto_preview" alt="Prévia do Prêmio" class="upload-preview-thumb" />
            <div class="upload-preview-info">
              <span class="upload-preview-filename">{{ premioForm.foto_nome || 'Imagem Selecionada' }}</span>
              <span class="upload-preview-tag">
                <i class="bi bi-check-circle-fill"></i> Foto pronta para envio
              </span>
            </div>
            <button type="button" class="btn-remove-upload" @click="removerFotoPremio">
              <i class="bi bi-trash3-fill"></i>
              <span>Remover</span>
            </button>
          </div>
        </div>

        <div class="d-flex align-items-center justify-content-end gap-2">
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
      :max-width="'560px'"
      @close="showModalEixo = false"
    >
      <form @submit.prevent="handleSalvarEixo">
        <div class="form-group mb-3">
          <label class="form-label">Nome do Eixo *</label>
          <input v-model="eixoForm.nome" type="text" class="form-control" placeholder="Ex: Eixo Saúde e Bem-Estar" required />
        </div>

        <div class="form-group mb-3">
          <label class="form-label">Descrição</label>
          <input v-model="eixoForm.descricao" type="text" class="form-control" placeholder="Ex: Secretarias do setor da saúde" />
        </div>

        <div class="form-group mb-4">
          <label class="form-label">Secretarias que pertencem a este Eixo:</label>
          <div class="secretarias-checkbox-grid">
            <div
              v-for="s in todasSecretarias"
              :key="s.id"
              :class="['sec-check-item', { selected: eixoForm.secretarias_selecionadas.includes(s.id) }]"
              @click="toggleSecretariaNoEixo(s.id)"
            >
              <i :class="['bi', eixoForm.secretarias_selecionadas.includes(s.id) ? 'bi-check-square-fill text-cyan' : 'bi-square']"></i>
              <span>{{ s.nome }}</span>
            </div>
          </div>
        </div>

        <div class="d-flex align-items-center justify-content-end gap-2">
          <button type="button" class="btn-secondary" @click="showModalEixo = false">Cancelar</button>
          <button type="submit" class="btn-primary">Salvar Eixo</button>
        </div>
      </form>
    </Modal>

    <!-- MODAL SECRETARIA -->
    <Modal
      :show="showModalSecretaria"
      :title="secretariaForm.id ? 'Editar Secretaria / Órgão' : 'Nova Secretaria / Órgão'"
      icon="bi-building-fill"
      :max-width="'560px'"
      @close="showModalSecretaria = false"
    >
      <form @submit.prevent="handleSalvarSecretaria">
        <div class="form-group mb-3">
          <label class="form-label">Nome Oficial da Secretaria *</label>
          <input v-model="secretariaForm.nome" type="text" class="form-control" placeholder="Ex: Secretaria Municipal de Educação" required />
        </div>

        <div class="form-group mb-3">
          <label class="form-label">Sigla Oficial (opcional)</label>
          <input v-model="secretariaForm.sigla" type="text" class="form-control" placeholder="Ex: SME, SMS, SEMOB..." />
        </div>

        <div class="form-group mb-4">
          <label class="form-label">Eixo Temático Associado</label>
          <select v-model="secretariaForm.eixo_id" class="form-select">
            <option value="">Nenhum (Sem eixo)</option>
            <option v-for="e in eixos" :key="e.id" :value="e.id">{{ e.nome }}</option>
          </select>
          <small class="text-muted d-block mt-1">Vincula servidores desta secretaria aos sorteios da Categoria 2 do eixo escolhido.</small>
        </div>

        <div class="d-flex align-items-center justify-content-end gap-2">
          <button type="button" class="btn-secondary" @click="showModalSecretaria = false">Cancelar</button>
          <button type="submit" class="btn-primary" :disabled="salvandoSec">
            {{ salvandoSec ? 'Salvando...' : 'Salvar Secretaria' }}
          </button>
        </div>
      </form>
    </Modal>

    <!-- MODAL ANULAR -->
    <Modal
      :show="showModalAnular"
      title="Anular Sorteio"
      icon="bi-exclamation-triangle-fill"
      icon-color="text-danger"
      :max-width="'500px'"
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
        <div class="d-flex align-items-center justify-content-end gap-2 w-100">
          <button type="button" class="btn-secondary" @click="showModalAnular = false">Cancelar</button>
          <button type="button" class="btn-danger" @click="confirmarAnulacao">Confirmar Anulação</button>
        </div>
      </template>
    </Modal>

    <!-- MODAL SUCESSO -->
    <Modal
      :show="showModalSucessoSorteio"
      title="Sorteio Realizado com Sucesso!"
      icon="bi-trophy-fill"
      icon-color="text-warning"
      :max-width="'480px'"
      @close="showModalSucessoSorteio = false"
    >
      <div v-if="sorteioResultado" class="text-center py-3">
        <i class="bi bi-stars text-warning display-4 mb-2"></i>
        <h3 class="text-white fw-bold mb-1 font-quattrocento">{{ sorteioResultado.servidor_nome }}</h3>
        <p class="text-warning fs-5 fw-bold mb-2">{{ sorteioResultado.premio_nome }}</p>
        <p class="text-muted small">O telão foi sincronizado e está exibindo a comemoração oficial.</p>
      </div>
      <template #footer>
        <button type="button" class="btn-primary w-100" @click="showModalSucessoSorteio = false">
          Continuar
        </button>
      </template>
    </Modal>

    <!-- MODAL DE CONFIRMAÇÃO DO INÍCIO DO SORTEIO (IN-APP) -->
    <Modal
      :show="showModalConfirmarInicio"
      title="Iniciar Sorteio no Telão"
      icon="bi-stars"
      icon-color="text-warning"
      :max-width="'520px'"
      @close="showModalConfirmarInicio = false"
    >
      <div class="confirm-modal-body">
        <p class="text-white mb-2">
          Você está prestes a dar o aval de início para sortear <strong>{{ premiosRodada.length }} prêmio(s)</strong> no Telão.
        </p>

        <div class="confirm-prizes-list">
          <div v-for="(item, idx) in premiosRodada" :key="item.item_id" class="confirm-prize-row">
            <span class="badge-num font-monospace">#{{ idx + 1 }}</span>
            <div class="confirm-prize-info">
              <strong class="confirm-prize-name text-white">{{ item.premio_nome }}</strong>
              <span class="confirm-prize-cat text-cyan small">{{ item.categoria === 'categoria_1' ? 'Geral' : (item.eixo_nome || 'Eixo') }}</span>
            </div>
          </div>
        </div>

        <div class="modal-alert-card modal-alert-card--warning mt-3">
          <div class="d-flex align-items-center gap-2">
            <i class="bi bi-info-circle-fill text-warning fs-5"></i>
            <span class="small">Ao confirmar, a animação de roleta de 10 segundos começará imediatamente no Telão do evento.</span>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="d-flex align-items-center justify-content-end gap-2 w-100">
          <button type="button" class="btn-secondary" @click="showModalConfirmarInicio = false">
            Cancelar
          </button>
          <button type="button" class="btn-primary" @click="confirmarEIniciarSorteio">
            <i class="bi bi-stars me-1"></i> Sim, Iniciar no Telão (10s)
          </button>
        </div>
      </template>
    </Modal>

    </div>
  </div>
</template>

<style scoped>
/* ==========================================================================
   ESTILOS ESCOPADOS ESTRITAMENTE ESPECÍFICOS DA MESA DE SORTEIO
   Tabelas, botões, modais, cabeçalhos e formulários vêm do Design System global
   ========================================================================== */
.spin-anim {
  animation: spin 1s infinite linear;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
