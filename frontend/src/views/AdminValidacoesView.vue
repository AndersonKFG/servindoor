<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import Modal from '../components/Modal.vue'
import KpiCard from '../components/KpiCard.vue'
import DropdownSelect from '../components/DropdownSelect.vue'
import { formatarDataNascimento, formatarData } from '../utils/formatters'
import { useAuth } from '../composables/useAuth'

const { toast } = useToast()
const { confirmModal } = useConfirm()

function obterIniciais(nome) {
  if (!nome) return '?'
  const partes = nome.trim().split(/\s+/).filter(Boolean)
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase()
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase()
}

const router = useRouter()
const { isValidador, isAdmin, isAdminGeral } = useAuth()

const loading = ref(true)
const solicitacoes = ref([])
const kpis = ref({
  total_pendentes: 0,
  total_aprovados: 0,
  total_rejeitados: 0,
  total_geral: 0,
  total_confirmados_api: 0,
  total_comunicacao_pendente: 0
})

// Filtros
const busca = ref('')
const filtroStatus = ref('pendente_analise')
const filtroSecretaria = ref('')
const secretariasDisponiveis = ref([])

const itensPorPagina = ref(25)
const paginaAtual = ref(1)
const totalPaginasServer = ref(1)
const totalRegistrosServer = ref(0)

const optionsStatus = [
  { value: 'todos', label: 'Status: Todos', icon: 'bi bi-list-check' },
  { value: 'confirmados_api', label: 'Confirmados pela API (Aprovação Rápida)', icon: 'bi bi-stars' },
  { value: 'pendente_analise', label: 'Pendentes de Análise', icon: 'bi bi-hourglass-split' },
  { value: 'aprovado', label: 'Aprovados', icon: 'bi bi-check-circle-fill' },
  { value: 'rejeitado', label: 'Rejeitados', icon: 'bi bi-x-circle-fill' }
]

const optionsSecretarias = computed(() => [
  { value: '', label: 'Todas as Secretarias' },
  ...secretariasDisponiveis.value.map(sec => ({ value: sec.id, label: sec.nome }))
])

// Modais
const showModalAnalise = ref(false)
const solicitacaoSelecionada = ref(null)
const processandoAprovacao = ref(false)
const processandoRejeicao = ref(false)

const showModalRejeitar = ref(false)
const motivoRejeicao = ref('Vínculo funcional não localizado nos registros da Secretaria.')
const outroMotivoTexto = ref('')

const showModalZoom = ref(false)
const zoomImgUrl = ref('')
const zoomImgTitulo = ref('')

const enviandoComunicacaoId = ref(null)
const processandoComunicacaoLote = ref(false)
const comunicacoesEnfileiradas = ref(0)
const showModalListaCpfs = ref(false)
const listaCpfsTexto = ref('')
const listaCpfsConferida = ref('')
const conferenciaCpfs = ref(null)
const resultadoListaCpfs = ref(null)
const processandoListaCpfs = ref(false)
const erroListaCpfs = ref('')
const buscaConferenciaCpfs = ref('')
const paginaConferenciaCpfs = ref(1)
const servidoresConferenciaCpfs = computed(() => {
  const termo = buscaConferenciaCpfs.value.trim().toLocaleLowerCase('pt-BR')
  const digitos = termo.replace(/\D/g, '')
  return (conferenciaCpfs.value?.servidores_a_homologar || []).filter(servidor =>
    !termo || servidor.nome.toLocaleLowerCase('pt-BR').includes(termo) ||
    (digitos && servidor.cpf.includes(digitos))
  )
})
const paginasConferenciaCpfs = computed(() => Math.max(1, Math.ceil(servidoresConferenciaCpfs.value.length / 25)))
const servidoresConferenciaPagina = computed(() =>
  servidoresConferenciaCpfs.value.slice((paginaConferenciaCpfs.value - 1) * 25, paginaConferenciaCpfs.value * 25)
)
watch(buscaConferenciaCpfs, () => { paginaConferenciaCpfs.value = 1 })
watch(conferenciaCpfs, () => {
  buscaConferenciaCpfs.value = ''
  paginaConferenciaCpfs.value = 1
})

watch(listaCpfsTexto, () => {
  conferenciaCpfs.value = null
  resultadoListaCpfs.value = null
  listaCpfsConferida.value = ''
  erroListaCpfs.value = ''
})

function abrirModalListaCpfs() {
  if (!isAdminGeral.value || processandoListaCpfs.value) return
  listaCpfsTexto.value = ''
  conferenciaCpfs.value = null
  resultadoListaCpfs.value = null
  listaCpfsConferida.value = ''
  erroListaCpfs.value = ''
  showModalListaCpfs.value = true
}

async function processarListaCpfs(confirmar = false) {
  if (!isAdminGeral.value || processandoListaCpfs.value) return
  const texto = listaCpfsTexto.value.trim()
  if (!texto) {
    erroListaCpfs.value = 'Informe a lista de CPFs para conferir.'
    return
  }
  if (confirmar && (!conferenciaCpfs.value || listaCpfsConferida.value !== texto || resultadoListaCpfs.value)) return
  if (confirmar && conferenciaCpfs.value.pendentes_encontrados === 0) return
  erroListaCpfs.value = ''
  processandoListaCpfs.value = true
  try {
    const res = await fetch('/api/admin/validacoes/homologar-por-cpfs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lista_cpfs: texto, confirmar })
    })
    const data = await res.json()
    if (!res.ok || !data.sucesso) {
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Não foi possível processar a lista de CPFs.')
    }
    if (confirmar) {
      resultadoListaCpfs.value = data
      conferenciaCpfs.value = null
      toast.success(data.mensagem)
      await carregarValidacoes()
    } else if (listaCpfsTexto.value.trim() === texto) {
      conferenciaCpfs.value = data
      listaCpfsConferida.value = texto
    }
  } catch (err) {
    erroListaCpfs.value = confirmar
      ? `${err.message} Confira as solicitações atualizadas antes de tentar novamente.`
      : err.message || 'Erro de conexão ao conferir a lista.'
    conferenciaCpfs.value = null
    if (confirmar) await carregarValidacoes()
  } finally {
    processandoListaCpfs.value = false
  }
}

async function dispararComunicacaoIndividual(solic) {
  if (!solic || !solic.id || enviandoComunicacaoId.value || processandoComunicacaoLote.value) return
  const isAprov = solic.status === 'aprovado'
  const acaoTexto = isAprov ? 'o ingresso oficial com QR Code' : 'a notificação de indeferimento'
  const servidorNome = solic.usuario?.nome || 'Servidor'
  const servidorEmail = solic.usuario?.email || 'e-mail cadastrado'

  const confirmado = await confirmModal({
    title: 'Disparar Comunicação',
    message: `Deseja realmente enviar ${acaoTexto} para o e-mail de ${servidorNome} (${servidorEmail})?`,
    confirmText: 'Enviar Agora',
    variant: 'primary'
  })
  if (!confirmado) return

  enviandoComunicacaoId.value = solic.id
  try {
    const res = await fetch(`/api/admin/validacoes/${solic.id}/comunicar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      toast.success(data.mensagem || 'Comunicação registrada na fila de e-mails!')
      solic.comunicado = true
      solic.comunicado_em = data.comunicado_em || 'Agora'
      await carregarValidacoes()
    } else {
      toast.error(data.detail || 'Erro ao disparar comunicação.')
    }
  } catch (err) {
    toast.error('Erro de conexão com o servidor.')
  } finally {
    enviandoComunicacaoId.value = null
  }
}

async function dispararComunicacoesLote() {
  if (processandoComunicacaoLote.value || enviandoComunicacaoId.value) return
  const total = kpis.value.total_comunicacao_pendente || 0
  if (total === 0) {
    toast.info('Não há comunicações pendentes de envio no momento.')
    return
  }

  const confirmado = await confirmModal({
    title: 'Disparo em Lote de Comunicações',
    message: `Deseja liberar e disparar o envio por e-mail para todos os ${total} servidores homologados pendentes?

- Os servidores APROVADOS receberão seus ingressos com QR Code.
- Os servidores REJEITADOS receberão a justificativa do indeferimento.`,
    confirmText: 'Disparar Todas',
    variant: 'primary'
  })
  if (!confirmado) return

  processandoComunicacaoLote.value = true
  comunicacoesEnfileiradas.value = 0
  let afterId = 0
  let falhas = 0
  const motivos = { sem_email: 0, sem_ingresso: 0, fila: 0 }
  try {
    while (!unmounted) {
      const params = new URLSearchParams({ tipo_filtro: 'todos', limit: '25', after_id: String(afterId) })
      const res = await fetch(`/api/admin/validacoes/comunicar-em-lote?${params.toString()}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })
      const data = await res.json()
      if (!res.ok || !data.sucesso) {
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Erro ao processar envio em lote.')
      }
      comunicacoesEnfileiradas.value += data.total_enfileirados || 0
      falhas += data.falhas || 0
      for (const motivo of Object.keys(motivos)) motivos[motivo] += data.falhas_por_motivo?.[motivo] || 0
      if (!data.tem_mais) break
      if (!Number.isInteger(data.proximo_id) || data.proximo_id <= afterId) {
        throw new Error('Não foi possível continuar o processamento do lote.')
      }
      afterId = data.proximo_id
    }
    if (unmounted) return
    const resumo = `${comunicacoesEnfileiradas.value} comunicação(ões) registrada(s) na fila de e-mails.`
    if (falhas > 0) {
      const detalhes = [
        motivos.sem_email && `${motivos.sem_email} sem e-mail cadastrado`,
        motivos.sem_ingresso && `${motivos.sem_ingresso} sem ingresso ativo correspondente`,
        motivos.fila && `${motivos.fila} com falha ao preparar ou enfileirar o e-mail`
      ].filter(Boolean).join('; ')
      toast.warning(`${resumo} ${falhas} pendência(s): ${detalhes || 'falha no processamento'}.`)
    } else {
      toast.success(resumo)
    }
  } catch (err) {
    if (!unmounted) {
      toast.error(`${err.message || 'Erro de conexão com o servidor.'} O processamento foi interrompido; confira as pendências atualizadas. Os lotes já confirmados foram preservados.`)
    }
  } finally {
    if (!unmounted) await carregarValidacoes()
    processandoComunicacaoLote.value = false
  }
}

let pollTimer = null
let debounceTimer = null
let requestController = null
let requestVersion = 0
let unmounted = false

async function carregarValidacoes(silent = false) {
  if (unmounted || (silent && requestController)) return
  requestController?.abort()
  const controller = new AbortController()
  requestController = controller
  const version = ++requestVersion
  try {
    if (!silent) loading.value = true
    const params = new URLSearchParams({
      page: String(paginaAtual.value),
      limit: String(Math.min(Number(itensPorPagina.value), 50)),
      status_filtro: filtroStatus.value || 'todos'
    })
    if (filtroSecretaria.value) params.set('secretaria_id', String(filtroSecretaria.value))
    if (busca.value.trim()) params.set('busca', busca.value.trim())
    const res = await fetch(`/api/admin/validacoes?${params.toString()}`, { signal: controller.signal })
    if (version !== requestVersion || unmounted) return
    if (res.status === 401 || res.status === 403) {
      router.push('/login')
      return
    }
    const data = await res.json()
    if (version !== requestVersion || unmounted) return
    if (res.ok && data.sucesso) {
      solicitacoes.value = data.solicitacoes || []
      kpis.value = data.kpis || {
        total_pendentes: 0,
        total_aprovados: 0,
        total_rejeitados: 0,
        total_geral: 0,
        total_confirmados_api: 0,
        total_comunicacao_pendente: 0
      }

      paginaAtual.value = data.pagination.page
      totalPaginasServer.value = data.pagination.total_pages
      totalRegistrosServer.value = data.pagination.total
      secretariasDisponiveis.value = data.secretarias_disponiveis || []
    } else if (!silent) {
      toast.error(typeof data.detail === 'string' ? data.detail : 'Erro ao carregar validações.')
    }
  } catch (err) {
    if (!silent && err.name !== 'AbortError' && version === requestVersion && !unmounted) {
      toast.error('Erro ao carregar validações.')
    }
  } finally {
    if (version === requestVersion) {
      requestController = null
      loading.value = false
    }
  }
}

onMounted(async () => {
  await carregarValidacoes()
  if (unmounted) return
  pollTimer = setInterval(() => {
    carregarValidacoes(true)
  }, 10000)
})

onUnmounted(() => {
  unmounted = true
  requestVersion++
  requestController?.abort()
  clearTimeout(debounceTimer)
  if (pollTimer) clearInterval(pollTimer)
})

// A API aplica os filtros antes da paginação; os cards representam a página atual.
const solicitacoesFiltradas = computed(() => solicitacoes.value)

const totalPaginas = computed(() => totalPaginasServer.value)
const infoPaginacao = computed(() => {
  const total = totalRegistrosServer.value
  if (total === 0) return '0 de 0'
  const inicio = (paginaAtual.value - 1) * Number(itensPorPagina.value) + 1
  const fim = Math.min(paginaAtual.value * Number(itensPorPagina.value), total)
  return `${inicio} - ${fim} de ${total}`
})

const paginasVisiveis = computed(() => {
  const total = totalPaginas.value
  const atual = paginaAtual.value
  const delta = 2
  const range = []
  for (let i = Math.max(2, atual - delta); i <= Math.min(total - 1, atual + delta); i++) range.push(i)
  if (atual - delta > 2) range.unshift('...')
  if (atual + delta < total - 1) range.push('...')
  range.unshift(1)
  if (total > 1) range.push(total)
  return range
})

function irParaPagina(p) {
  if (loading.value || p === '...' || p < 1 || p > totalPaginasServer.value || p === paginaAtual.value) return
  paginaAtual.value = p
  return carregarValidacoes()
}

watch(busca, () => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    paginaAtual.value = 1
    carregarValidacoes()
  }, 350)
})

watch([filtroStatus, filtroSecretaria, itensPorPagina], () => {
  clearTimeout(debounceTimer)
  paginaAtual.value = 1
  carregarValidacoes()
})

function abrirModalAnalise(solic) {
  solicitacaoSelecionada.value = solic
  showModalAnalise.value = true
}

function abrirZoom(url, titulo) {
  if (!url) return
  zoomImgUrl.value = url
  zoomImgTitulo.value = titulo || 'Foto de Identificação'
  showModalZoom.value = true
}

const processandoLote = ref(false)

async function aprovarTodosVerificados() {
  const total = kpis.value.total_confirmados_api || 0
  if (total === 0) {
    toast.info('Nenhuma solicitação confirmada pela API pendente no momento.')
    return
  }
  const confirmado = await confirmModal({
    title: 'Aprovação em Lote',
    message: `Deseja realmente APROVAR em lote todos os ${total} servidores confirmados pela API oficial?\n\nOs ingressos oficiais serão emitidos no sistema e o envio por e-mail ficará sob controle do Administrador Geral.`,
    confirmText: 'Aprovar Todos',
    variant: 'primary'
  })
  if (!confirmado) return
  processandoLote.value = true
  try {
    const res = await fetch('/api/admin/validacoes/aprovar-verificados', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      toast.success(data.mensagem || 'Servidores aprovados com sucesso!')
      await carregarValidacoes()
    } else {
      toast.error(data.detail || 'Erro ao processar aprovações em lote.')
    }
  } catch (err) {
    toast.error('Erro de conexão ao processar aprovações.')
  } finally {
    processandoLote.value = false
  }
}

async function aprovarSolicitacao() {
  if (!solicitacaoSelecionada.value) return
  const id = solicitacaoSelecionada.value.id
  const confirmado = await confirmModal({
    title: 'Aprovar Servidor',
    message: `Deseja realmente APROVAR a solicitação do servidor ${solicitacaoSelecionada.value.usuario?.nome}?\n\nO ingresso oficial será gerado imediatamente. No entanto, não será enviado e ficará aguardando o envio em massa pelo Administrador Geral do sistema.`,
    confirmText: 'Aprovar e Emitir',
    variant: 'primary'
  })
  if (!confirmado) return

  processandoAprovacao.value = true
  try {
    const res = await fetch(`/api/admin/validacoes/${id}/aprovar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      toast.success(data.mensagem || 'Solicitação aprovada e ingresso emitido!')
      showModalAnalise.value = false
      await carregarValidacoes()
    } else {
      toast.error(data.detail || 'Erro ao aprovar solicitação.')
    }
  } catch (err) {
    toast.error('Erro de conexão com o servidor.')
  } finally {
    processandoAprovacao.value = false
  }
}

function abrirModalRejeitar() {
  motivoRejeicao.value = 'Vínculo funcional não localizado nos registros da Secretaria.'
  outroMotivoTexto.value = ''
  showModalRejeitar.value = true
}

async function confirmarRejeicao() {
  if (!solicitacaoSelecionada.value) return
  const id = solicitacaoSelecionada.value.id
  let motivoFinal = motivoRejeicao.value
  if (motivoFinal === 'outro') {
    motivoFinal = outroMotivoTexto.value.trim()
    if (!motivoFinal) {
      toast.warning('Por favor, informe a justificativa da rejeição.')
      return
    }
  }

  processandoRejeicao.value = true
  try {
    const res = await fetch(`/api/admin/validacoes/${id}/rejeitar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ motivo: motivoFinal })
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      toast.success('Solicitação rejeitada com sucesso!')
      showModalRejeitar.value = false
      showModalAnalise.value = false
      await carregarValidacoes()
    } else {
      toast.error(data.detail || 'Erro ao rejeitar solicitação.')
    }
  } catch (err) {
    toast.error('Erro de comunicação ao rejeitar solicitação.')
  } finally {
    processandoRejeicao.value = false
  }
}
</script>

<template>
  <div class="admin-page">
    <div class="app-container">

    <!-- CABEÇALHO -->
    <div class="admin-header-row mb-4">
      <div>
        <span class="admin-eyebrow">
          <i class="bi bi-shield-lock-fill me-1 text-cyan"></i> PAINEL ADMINISTRATIVO
        </span>
        <h1 class="page-title font-quattrocento">Validações de Servidores</h1>
        <p class="page-subtitle">
          Homologação de vínculos funcionais pendentes para liberação de ingressos e controle de lotes
        </p>
      </div>

      <div class="admin-header-actions d-flex flex-wrap gap-2">
        <button
          v-if="isAdminGeral"
          type="button"
          class="btn-secondary"
          :disabled="loading || processandoListaCpfs || processandoLote || processandoComunicacaoLote"
          @click="abrirModalListaCpfs"
        >
          <i class="bi bi-person-check-fill me-1"></i>
          <span>Homologar por CPFs</span>
        </button>

        <button
          v-if="kpis.total_confirmados_api > 0"
          type="button"
          class="btn-primary"
          :disabled="processandoLote || loading"
          @click="aprovarTodosVerificados()"
        >
          <i class="bi bi-check2-all me-1"></i>
          <span>Aprovar da API ({{ kpis.total_confirmados_api }})</span>
        </button>

        <button
          v-if="isAdminGeral && (kpis.total_comunicacao_pendente > 0)"
          type="button"
          class="btn-secondary"
          :disabled="processandoComunicacaoLote || enviandoComunicacaoId !== null || loading"
          @click="dispararComunicacoesLote()"
        >
          <i class="bi bi-send-check-fill me-1" :class="{ 'spin-anim': processandoComunicacaoLote }"></i>
          <span>{{ processandoComunicacaoLote ? `Registrando e-mails (${comunicacoesEnfileiradas})...` : `Disparar E-mails (${kpis.total_comunicacao_pendente})` }}</span>
        </button>

        <button type="button" class="btn-secondary" :disabled="loading" @click="carregarValidacoes()">
          <i class="bi bi-arrow-clockwise" :class="{ 'spin-anim': loading }"></i>
          <span>Atualizar</span>
        </button>
      </div>
    </div>

    <!-- CARDS DE METRICAS KPI CANÔNICOS -->
    <div class="kpi-grid mb-4">
      <KpiCard
        title="Pendentes de Homologação"
        :value="kpis.total_pendentes"
        subtitle="Vagas retidas aguardando análise"
        icon="bi bi-hourglass-split"
        variant="warning"
        :badge-text="kpis.total_pendentes > 0 ? 'Ação Requerida' : ''"
        :badge-pulse="kpis.total_pendentes > 0"
      />

      <KpiCard
        title="Aprovados / Ingressos Emitidos"
        :value="kpis.total_aprovados"
        subtitle="Confirmados com QR Code"
        icon="bi bi-check-circle-fill"
        variant="emerald"
      />

      <KpiCard
        title="Rejeitados / Ocupação Mantida"
        :value="kpis.total_rejeitados"
        subtitle="Resgates rejeitados continuam ocupando o lote"
        icon="bi bi-x-circle-fill"
        variant="danger"
      />

      <KpiCard
        title="Total de Solicitações"
        :value="kpis.total_geral"
        subtitle="Histórico completo de validações"
        icon="bi bi-folder2-open"
        variant="cyan"
      />
    </div>

    <!-- BARRA DE FILTROS -->
    <div class="filter-card mb-4">
      <div
        class="filter-grid"
        :class="secretariasDisponiveis.length > 1 ? 'filter-grid--validation-many' : 'filter-grid--validation-one'"
      >
        <div class="search-box">
          <i class="bi bi-search search-icon"></i>
          <input
            v-model="busca"
            type="text"
            class="form-control"
            maxlength="200"
            placeholder="Buscar por Nome, CPF, Protocolo, Secretaria..."
          />
          <button v-if="busca" type="button" class="btn-clear-search" @click="busca = ''">
            <i class="bi bi-x"></i>
          </button>
        </div>

        <div>
          <DropdownSelect
            v-model="filtroStatus"
            :options="optionsStatus"
            placeholder="Status: Todos"
            icon="bi bi-funnel"
          />
        </div>

        <div v-if="secretariasDisponiveis.length > 1">
          <DropdownSelect
            v-model="filtroSecretaria"
            :options="optionsSecretarias"
            placeholder="Todas as Secretarias"
            icon="bi bi-building"
          />
        </div>
      </div>
    </div>

    <!-- TABELA DE SOLICITAÇÕES -->
    <div class="table-card">
      <div class="table-header-box">
        <h2 class="table-title font-quattrocento">
          <i class="bi bi-list-check text-cyan me-2"></i>
          Solicitações de Validação
          <span class="table-badge-count">{{ totalRegistrosServer }}</span>
        </h2>
        <div class="table-header-controls">
          <label for="validacoes-page-size" class="text-muted small me-2">Exibir:</label>
          <select id="validacoes-page-size" v-model="itensPorPagina" class="form-select form-select-sm select-page-size" :disabled="loading">
            <option :value="10">10</option>
            <option :value="25">25</option>
            <option :value="50">50</option>
          </select>
        </div>
      </div>

      <div v-if="loading" class="table-loading-state">
        <div class="spinner-border text-cyan mb-3"></div>
        <p>Carregando solicitações de validação...</p>
      </div>

      <div v-else-if="!solicitacoesFiltradas.length" class="table-empty-state">
        <i class="bi bi-inbox fs-1 mb-2 d-block opacity-50"></i>
        <p>Nenhuma solicitação encontrada para os filtros aplicados.</p>
      </div>

            <!-- GRID DE CARDS CANÔNICO DE VALIDAÇÃO -->
      <div v-else class="entity-cards-grid">
        <div
          v-for="s in solicitacoesFiltradas"
          :key="s.id"
          :class="[
            'entity-card',
            s.status === 'pendente_analise' ? 'entity-card--em_validacao' : (s.status === 'aprovado' ? 'entity-card--presente' : 'entity-card--cancelado')
          ]"
        >
          <!-- Topo do Card: Protocolo, Data e Status de Validação -->
          <div class="entity-card-top-bar">
            <div>
              <strong class="table-code-pill font-monospace d-block">VAL-{{ String(s.id).padStart(6, '0') }}</strong>
              <span class="text-muted d-block mt-1" style="font-size: 0.78rem;">
                <i class="bi bi-calendar3 me-1"></i>{{ s.criado_em }}
              </span>
            </div>

            <div class="d-flex flex-column align-items-end gap-1">
              <span v-if="s.status === 'pendente_analise'" class="status-pill status-pill--em_validacao">
                <i class="bi bi-hourglass-split"></i> Pendente
              </span>
              <span v-else-if="s.status === 'aprovado'" class="status-pill status-pill--presente">
                <i class="bi bi-check-circle-fill"></i> Aprovado
              </span>
              <span v-else-if="s.status === 'rejeitado'" class="status-pill status-pill--cancelado">
                <i class="bi bi-x-circle-fill"></i> Rejeitado
              </span>

              <!-- Status de Comunicação por E-mail -->
              <template v-if="s.status !== 'pendente_analise'">
                <span v-if="s.comunicado" class="badge badge-secondary" :title="'Registrado na fila em ' + (s.comunicado_em || '')">
                  <i class="bi bi-check-all me-1 text-emerald"></i> Liberado para envio
                </span>
                <span v-else class="badge badge-secondary" title="Comunicação por e-mail aguardando liberação do Administrador Geral">
                  <i class="bi bi-clock-history me-1 text-warning"></i> Envio Pendente
                </span>
              </template>
            </div>
          </div>

          <!-- Identidade do Servidor: Foto/Rosto, Nome, CPF e Contato -->
          <div class="entity-card-identity">
            <div
              class="entity-card-avatar entity-card-avatar--lg"
              :title="s.usuario?.foto_rosto_url ? 'Clique para ampliar foto facial' : 'Foto não cadastrada'"
              @click="s.usuario?.foto_rosto_url && abrirZoom(s.usuario.foto_rosto_url, s.usuario.nome)"
            >
              <img
                v-if="s.usuario?.foto_rosto_url"
                :src="s.usuario.foto_rosto_url"
                alt="Foto do Rosto"
                class="entity-card-avatar-img"
                @error="(e) => { e.target.style.display = 'none'; if (e.target.nextElementSibling) e.target.nextElementSibling.style.display = 'flex'; }"
              />
              <div
                class="entity-card-avatar-fallback"
                :style="{ display: s.usuario?.foto_rosto_url ? 'none' : 'flex' }"
              >
                <span>{{ obterIniciais(s.usuario?.nome) }}</span>
              </div>
            </div>

            <div class="entity-card-info">
              <h3 class="entity-card-title">{{ s.usuario?.nome || 'Desconhecido' }}</h3>
              <div class="entity-card-sub">
                <span class="table-code-pill font-monospace">{{ s.usuario?.cpf_formatado || s.usuario?.cpf }}</span>
                <span v-if="s.identificado_api" class="badge badge-cyan" title="Vínculo confirmado via API da Escola de Governo">
                  <i class="bi bi-patch-check-fill me-1 text-cyan"></i> Servidor (API)
                </span>
                <span v-else-if="['queued', 'processing'].includes(s.validacao_externa_status)" class="badge badge-amber">
                  <i class="bi bi-hourglass-split me-1"></i> Consulta em andamento
                </span>
                <span v-else-if="s.validacao_externa_status === 'failed'" class="badge badge-amber">
                  <i class="bi bi-exclamation-circle me-1"></i> Consulta indisponível — análise manual
                </span>
              </div>
              <div v-if="s.usuario?.email" class="text-muted small mt-1 text-truncate" :title="s.usuario.email">
                <i class="bi bi-envelope me-1"></i>{{ s.usuario.email }}
              </div>
            </div>
          </div>

          <!-- Metadados em Grade: Secretaria, Vínculo, Lote e Análise -->
          <div class="entity-meta-grid">
            <div class="entity-meta-item">
              <span class="meta-label">Secretaria / Setor</span>
              <span class="meta-value" :title="s.secretaria_nome">{{ s.secretaria_nome }}</span>
              <span v-if="s.usuario?.setor" class="meta-sub" :title="s.usuario.setor">
                <i class="bi bi-geo-alt me-1"></i>{{ s.usuario.setor }}
              </span>
            </div>

            <div class="entity-meta-item">
              <span class="meta-label">Lote / Vaga</span>
              <span class="meta-value text-amber" :title="s.lote_nome">{{ s.lote_nome }}</span>
              <span class="meta-sub text-warning" v-if="s.status === 'pendente_analise'">
                <i class="bi bi-lock-fill me-1"></i>Vaga Retida
              </span>
              <span class="meta-sub text-emerald" v-else-if="s.status === 'aprovado'">
                <i class="bi bi-check2 me-1"></i>Confirmada
              </span>
              <span class="meta-sub text-danger" v-else>
                <i class="bi bi-lock-fill me-1"></i>Retida no Lote
              </span>
            </div>

            <div v-if="s.analisado_em" class="entity-meta-item full-width">
              <span class="meta-label">Análise Realizada</span>
              <div class="small">
                <div><span class="text-muted">Por:</span> <strong class="text-white ms-1">{{ s.analisado_por_nome || 'Validador' }}</strong></div>
                <div class="mt-1"><span class="text-muted">Em:</span> <span class="text-white ms-1">{{ formatarData(s.analisado_em) }}</span></div>
              </div>
              <div v-if="s.motivo_rejeicao" class="text-danger small mt-1 allow-wrap" :title="s.motivo_rejeicao">
                <i class="bi bi-chat-left-quote me-1"></i>{{ s.motivo_rejeicao }}
              </div>
            </div>
          </div>

          <!-- Rodapé do Card: Ações Operacionais -->
          <div class="entity-card-footer">
            <div class="actions-left">
              <button
                v-if="s.status === 'pendente_analise'"
                :disabled="s.pode_gerenciar === false"
                type="button"
                class="btn-card-primary font-outfit"
                @click="abrirModalAnalise(s)"
              >
                <i class="bi bi-shield-check"></i> Homologar
              </button>
              <button
                v-else
                type="button"
                class="btn-card-secondary font-outfit"
                @click="abrirModalAnalise(s)"
              >
                <i class="bi bi-eye"></i> Ver Análise
              </button>
            </div>

            <div class="actions-right">
              <button
                v-if="isAdminGeral && s.status !== 'pendente_analise' && !s.comunicado"
                type="button"
                class="btn-action-icon btn-action-icon--blue"
                :disabled="enviandoComunicacaoId !== null || processandoComunicacaoLote"
                title="Disparar e-mail ao servidor agora"
                @click="dispararComunicacaoIndividual(s)"
              >
                <i class="bi bi-send-fill" :class="{ 'spin-anim': enviandoComunicacaoId === s.id }"></i>
              </button>
            </div>
          </div>

        </div>
      </div>
      <div v-if="totalRegistrosServer > 0" class="pagination-footer">
        <div class="pagination-info">
          Mostrando <strong>{{ infoPaginacao }}</strong>
        </div>
        <div class="pagination-buttons">
          <button type="button" class="btn-page-nav" :disabled="loading || paginaAtual === 1"
            title="Primeira Página" aria-label="Primeira página" @click="irParaPagina(1)">
            <i class="bi bi-chevron-double-left"></i>
          </button>
          <button type="button" class="btn-page-nav" :disabled="loading || paginaAtual === 1"
            title="Página Anterior" aria-label="Página anterior" @click="irParaPagina(paginaAtual - 1)">
            <i class="bi bi-chevron-left"></i>
          </button>
          <button v-for="(p, idx) in paginasVisiveis" :key="idx" type="button" class="btn-page-number"
            :class="{ 'is-active': p === paginaAtual, 'is-dots': p === '...' }"
            :disabled="loading || p === '...'" :aria-current="p === paginaAtual ? 'page' : undefined"
            :aria-label="p === '...' ? 'Mais páginas' : `Página ${p}`" @click="irParaPagina(p)">
            {{ p }}
          </button>
          <button type="button" class="btn-page-nav" :disabled="loading || paginaAtual === totalPaginas"
            title="Próxima Página" aria-label="Próxima página" @click="irParaPagina(paginaAtual + 1)">
            <i class="bi bi-chevron-right"></i>
          </button>
          <button type="button" class="btn-page-nav" :disabled="loading || paginaAtual === totalPaginas"
            title="Última Página" aria-label="Última página" @click="irParaPagina(totalPaginas)">
            <i class="bi bi-chevron-double-right"></i>
          </button>
        </div>
      </div>
    </div>

    <!-- MODAL DE HOMOLOGAÇÃO / ANÁLISE DETALHADA -->
    <Modal
      :show="showModalAnalise"
      :title="solicitacaoSelecionada?.status === 'pendente_analise' ? 'Homologação de Servidor' : 'Detalhes da Solicitação'"
      icon="bi-shield-check"
      :max-width="'760px'"
      @close="showModalAnalise = false"
    >
      <div v-if="solicitacaoSelecionada">
        
        <div class="modal-hero-card mb-4">
          <div
            v-if="solicitacaoSelecionada.usuario?.foto_rosto_url"
            class="modal-hero-avatar"
            title="Clique para ampliar"
            @click="abrirZoom(solicitacaoSelecionada.usuario.foto_rosto_url, solicitacaoSelecionada.usuario.nome)"
          >
            <img :src="solicitacaoSelecionada.usuario.foto_rosto_url" alt="Foto Rosto" />
          </div>
          <div v-else class="modal-hero-avatar">
            <div class="modal-hero-avatar-fallback">
              <i class="bi bi-person-fill"></i>
            </div>
          </div>

          <div class="modal-hero-info">
            <h3 class="modal-hero-name font-quattrocento">{{ solicitacaoSelecionada.usuario?.nome }}</h3>
            <span class="table-code-pill font-monospace">{{ solicitacaoSelecionada.usuario?.cpf_formatado }}</span>
            <div class="d-flex flex-wrap gap-2 mt-2">
              <span class="table-tag table-tag--cyan">{{ solicitacaoSelecionada.secretaria_nome }}</span>
              <span class="table-tag table-tag--amber">{{ solicitacaoSelecionada.lote_nome }}</span>
            </div>
          </div>
        </div>

        <div class="modal-section mb-4">
          <h4 class="modal-section-heading">
            <i class="bi bi-person-vcard text-cyan me-2"></i>
            Informações Cadastrais
          </h4>

          <div class="modal-info-grid">
            <div class="modal-field-card">
              <span class="modal-field-label">Protocolo</span>
              <span class="modal-field-value font-monospace text-cyan">VAL-{{ String(solicitacaoSelecionada.id).padStart(6, '0') }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">Data de Nascimento</span>
              <span class="modal-field-value">{{ formatarDataNascimento(solicitacaoSelecionada.usuario?.data_nascimento) }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">Vínculo Declarado</span>
              <span class="modal-field-value">{{ solicitacaoSelecionada.usuario?.vinculo || 'Servidor Público' }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">Setor / Lotação</span>
              <span class="modal-field-value">{{ solicitacaoSelecionada.usuario?.setor || 'Não informado' }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">E-mail</span>
              <span class="modal-field-value">{{ solicitacaoSelecionada.usuario?.email || 'Não informado' }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">Telefone / WhatsApp</span>
              <span class="modal-field-value">{{ solicitacaoSelecionada.usuario?.telefone || 'Não informado' }}</span>
            </div>
          </div>
        </div>

        <div v-if="solicitacaoSelecionada.identificado_api" class="modal-alert-card mb-3" style="border-left: 4px solid var(--primary-accent);">
          <div class="d-flex align-items-start gap-2">
            <i class="bi bi-patch-check-fill text-cyan fs-5"></i>
            <div>
              <strong class="text-cyan d-block">Identificado como Servidor via API Oficial</strong>
              <p class="mb-0 small text-light">Este CPF foi confirmado junto à Escola de Governo. O servidor é elegível.</p>
            </div>
          </div>
        </div>

        <div v-if="['queued', 'processing'].includes(solicitacaoSelecionada.validacao_externa_status)" class="modal-alert-card modal-alert-card--warning mb-3">
          <strong class="d-block">Consulta à Escola de Governo em andamento</strong>
          <p class="mb-0 small">O cadastro está salvo. O resultado da consulta aparecerá assim que estiver disponível; a equipe também pode realizar a análise manual.</p>
        </div>

        <div v-if="solicitacaoSelecionada.status === 'pendente_analise'" class="modal-alert-card modal-alert-card--warning mb-3">
          <div class="d-flex align-items-start gap-2">
            <i class="bi bi-info-circle-fill fs-5"></i>
            <div>
              <strong class="d-block">A vaga já está retida neste lote</strong>
              <p class="mb-0 small">A vaga permanece ocupada neste lote mesmo se a homologação for rejeitada.</p>
            </div>
          </div>
        </div>

        <div v-if="solicitacaoSelecionada.status !== 'pendente_analise'" class="mb-3">
          <div v-if="solicitacaoSelecionada.comunicado" class="modal-alert-card modal-alert-card--success">
            <div class="d-flex align-items-start gap-2">
              <i class="bi bi-check-all fs-5 text-emerald"></i>
              <div>
                <strong class="text-emerald d-block">Comunicação Liberada para Envio</strong>
                <p class="mb-0 small text-muted">A notificação oficial foi registrada na fila de e-mails em {{ solicitacaoSelecionada.comunicado_em }}. A entrega depende do processamento da fila.</p>
              </div>
            </div>
          </div>
          <div v-else class="modal-alert-card modal-alert-card--warning">
            <div class="d-flex align-items-start gap-2">
              <i class="bi bi-clock-history fs-5 text-warning"></i>
              <div>
                <strong class="text-warning d-block">Comunicação Pendente de Liberação</strong>
                <p class="mb-0 small text-muted">A homologação foi registrada, mas o e-mail oficial ainda não foi disparado ao participante.</p>
              </div>
            </div>
          </div>
        </div>

        <div v-if="solicitacaoSelecionada.status === 'rejeitado'" class="modal-alert-card modal-alert-card--danger mb-3">
          <div class="d-flex align-items-start gap-2">
            <i class="bi bi-x-octagon-fill fs-5"></i>
            <div>
              <strong class="d-block">Solicitação Indeferida</strong>
              <p class="mb-0 small"><strong>Recusado por:</strong> {{ solicitacaoSelecionada.analisado_por_nome || 'Responsável não informado' }}</p>
              <p class="mb-0 small"><strong>Motivo:</strong> {{ solicitacaoSelecionada.motivo_rejeicao }}</p>
            </div>
          </div>
        </div>

      </div>

      <template #footer>
        <div class="d-flex align-items-center justify-content-end gap-2 w-100">
          <button type="button" class="btn-secondary" @click="showModalAnalise = false">Fechar</button>

          <template v-if="solicitacaoSelecionada?.status === 'pendente_analise' && solicitacaoSelecionada?.pode_gerenciar !== false">
            <button
              type="button"
              class="btn-danger"
              :disabled="processandoRejeicao || processandoAprovacao"
              @click="abrirModalRejeitar"
            >
              <i class="bi bi-x-lg me-1"></i>
              <span>Rejeitar</span>
            </button>

            <button
              type="button"
              class="btn-primary"
              :disabled="processandoAprovacao || processandoRejeicao"
              @click="aprovarSolicitacao"
            >
              <span v-if="!processandoAprovacao"><i class="bi bi-check2-circle me-1"></i> Aprovar Ingresso</span>
              <span v-else>Aprovando...</span>
            </button>
          </template>

          <template v-else-if="isAdminGeral && !solicitacaoSelecionada?.comunicado">
            <button
              type="button"
              class="btn-primary"
              :disabled="enviandoComunicacaoId !== null || processandoComunicacaoLote"
              @click="dispararComunicacaoIndividual(solicitacaoSelecionada)"
            >
              <i class="bi bi-send-fill me-1" :class="{ 'spin-anim': enviandoComunicacaoId === solicitacaoSelecionada.id }"></i>
              <span>Disparar Comunicação por E-mail</span>
            </button>
          </template>
        </div>
      </template>
    </Modal>

    <!-- MODAL MOTIVO DE REJEIÇÃO -->
    <Modal
      :show="showModalRejeitar"
      title="Justificativa da Rejeição"
      icon="bi-exclamation-octagon-fill"
      icon-color="text-danger"
      :max-width="'520px'"
      @close="showModalRejeitar = false"
    >
      <div>
        <p class="text-white mb-3" style="font-size: 0.88rem;">
          Selecione o motivo da rejeição da solicitação de <strong>{{ solicitacaoSelecionada?.usuario?.nome }}</strong>:
        </p>

        <div class="form-group mb-3">
          <div class="radio-options">
            <label class="radio-label">
              <input type="radio" v-model="motivoRejeicao" value="Vínculo funcional não localizado nos registros da Secretaria." />
              <span>Vínculo funcional não localizado nos registros da Secretaria.</span>
            </label>
            <label class="radio-label">
              <input type="radio" v-model="motivoRejeicao" value="CPF ou dados cadastrais divergentes dos arquivos municipais." />
              <span>CPF ou dados cadastrais divergentes dos arquivos municipais.</span>
            </label>
            <label class="radio-label">
              <input type="radio" v-model="motivoRejeicao" value="Servidor com status inativo ou desligado do quadro." />
              <span>Servidor com status inativo ou desligado do quadro.</span>
            </label>
            <label class="radio-label">
              <input type="radio" v-model="motivoRejeicao" value="outro" />
              <span>Outro motivo (especificar)</span>
            </label>
          </div>

          <div v-if="motivoRejeicao === 'outro'" class="mt-3">
            <textarea
              v-model="outroMotivoTexto"
              class="form-control"
              rows="3"
              placeholder="Digite a justificativa detalhada para o e-mail do participante..."
            ></textarea>
          </div>
        </div>

        <p class="text-warning small mb-0">
          <i class="bi bi-exclamation-triangle me-1"></i>
          Esta ação manterá a ocupação do lote. O e-mail formal ao solicitante ficará aguardando liberação do Administrador Geral.
        </p>
      </div>

      <template #footer>
        <div class="d-flex align-items-center justify-content-end gap-2 w-100">
          <button type="button" class="btn-secondary" @click="showModalRejeitar = false">Cancelar</button>
          <button
            type="button"
            class="btn-danger"
            :disabled="processandoRejeicao"
            @click="confirmarRejeicao"
          >
            <span v-if="!processandoRejeicao">Confirmar Rejeição</span>
            <span v-else>Processando...</span>
          </button>
        </div>
      </template>
    </Modal>

    <Modal
      v-if="isAdminGeral"
      :show="showModalListaCpfs"
      title="Homologar servidores por lista de CPFs"
      icon="bi-person-check-fill"
      max-width="680px"
      :dismissible="!processandoListaCpfs"
      @close="!processandoListaCpfs && (showModalListaCpfs = false)"
    >
      <div class="modal-hero-card">
        <div class="modal-hero-info">
          <strong>Confirmação pelo Administrador Geral</strong>
          <p class="mb-0 small text-muted">A lista será comparada com todas as solicitações pendentes de usuários ativos, em todas as páginas, lotes e secretarias, independentemente dos filtros da tela.</p>
        </div>
      </div>
      <div class="modal-section">
        <label for="lista-cpfs-validacao" class="form-label">Lista de CPFs</label>
        <textarea
          id="lista-cpfs-validacao"
          v-model="listaCpfsTexto"
          class="form-control font-monospace"
          rows="8"
          maxlength="200000"
          :disabled="processandoListaCpfs"
          placeholder="Cole os CPFs aqui, um por linha"
          aria-describedby="lista-cpfs-ajuda"
        ></textarea>
        <p id="lista-cpfs-ajuda" class="small text-muted mt-2 mb-0">Até 10.000 CPFs por vez, com 11 dígitos ou no formato 000.000.000-00. Separe por linhas, espaços, vírgulas ou ponto e vírgula. CPFs repetidos serão considerados uma única vez.</p>
      </div>
      <div v-if="erroListaCpfs" class="modal-alert-card modal-alert-card--danger" role="alert">{{ erroListaCpfs }}</div>
      <div v-if="conferenciaCpfs" class="modal-section" aria-live="polite">
        <h3 class="modal-section-title">Conferência da lista</h3>
        <div class="modal-info-grid">
          <div class="modal-field-card">
            <span class="modal-field-label">CPFs válidos e únicos</span>
            <strong>{{ conferenciaCpfs.cpfs_validos }}</strong>
          </div>
          <div class="modal-field-card">
            <span class="modal-field-label">Solicitações a homologar</span>
            <strong>{{ conferenciaCpfs.pendentes_encontrados }}</strong>
          </div>
          <div class="modal-field-card">
            <span class="modal-field-label">CPFs sem pendência elegível</span>
            <strong>{{ conferenciaCpfs.cpfs_sem_pendencia }}</strong>
          </div>
          <div class="modal-field-card">
            <span class="modal-field-label">Inválidos / Repetidos</span>
            <strong>{{ conferenciaCpfs.cpfs_invalidos }} / {{ conferenciaCpfs.cpfs_duplicados }}</strong>
          </div>
        </div>
        <div v-if="conferenciaCpfs.servidores_a_homologar?.length" class="table-card mt-3">
          <div class="table-header-box">
            <h4 class="table-title">CPFs que serão homologados <span class="table-badge-count">{{ conferenciaCpfs.cpfs_com_pendencia }}</span></h4>
            <div class="search-box">
              <i class="bi bi-search" aria-hidden="true"></i>
              <input v-model="buscaConferenciaCpfs" type="search" class="form-control" placeholder="Buscar nome ou CPF" aria-label="Buscar nos CPFs que serão homologados" />
            </div>
          </div>
          <div class="table-responsive">
            <table class="custom-table">
              <caption class="visually-hidden">Servidores com pendência elegível na lista informada</caption>
              <thead><tr><th scope="col">CPF</th><th scope="col">Servidor</th></tr></thead>
              <tbody>
                <tr v-for="servidor in servidoresConferenciaPagina" :key="servidor.usuario_id">
                  <td><span class="table-code-pill font-monospace">{{ servidor.cpf_formatado }}</span></td>
                  <td><div class="table-user-cell"><span class="table-user-name">{{ servidor.nome }}</span></div></td>
                </tr>
                <tr v-if="!servidoresConferenciaCpfs.length"><td colspan="2">Nenhum servidor corresponde à busca.</td></tr>
              </tbody>
            </table>
          </div>
          <div class="pagination-footer">
            <span class="pagination-info">{{ servidoresConferenciaCpfs.length }} servidor(es) · Página {{ paginaConferenciaCpfs }} de {{ paginasConferenciaCpfs }}</span>
            <div>
              <button type="button" class="btn-page-nav" :disabled="paginaConferenciaCpfs <= 1" @click="paginaConferenciaCpfs--" aria-label="Página anterior dos CPFs">Anterior</button>
              <button type="button" class="btn-page-nav" :disabled="paginaConferenciaCpfs >= paginasConferenciaCpfs" @click="paginaConferenciaCpfs++" aria-label="Próxima página dos CPFs">Próxima</button>
            </div>
          </div>
          <p class="small text-muted p-3 mb-0">A busca apenas facilita a conferência. Todos os CPFs desta relação serão homologados, inclusive os das outras páginas. As pendências serão verificadas novamente ao confirmar.</p>
        </div>
        <p v-if="conferenciaCpfs.cpfs_invalidos > 0" class="small text-warning mt-2">Os CPFs inválidos serão ignorados. Você pode corrigir a lista e conferir novamente.</p>
        <p v-if="conferenciaCpfs.pendentes_encontrados === 0" class="small text-muted mt-2">Nenhuma solicitação pendente foi encontrada para os CPFs válidos desta lista.</p>
      </div>
      <div v-if="resultadoListaCpfs" class="modal-alert-card modal-alert-card--success" role="status">
        {{ resultadoListaCpfs.mensagem }}
      </div>
      <div class="modal-alert-card modal-alert-card--warning">
        Serão homologadas apenas as solicitações ainda pendentes que correspondam à lista. Os ingressos serão emitidos sem duplicar ingressos ativos. O envio por e-mail continuará aguardando o botão “Disparar E-mails” do Administrador Geral.
      </div>
      <template #footer>
        <div class="modal-footer-grid">
          <button type="button" class="btn-secondary" :disabled="processandoListaCpfs" @click="showModalListaCpfs = false">Fechar</button>
          <button type="button" class="btn-secondary" :disabled="processandoListaCpfs || !listaCpfsTexto.trim()" @click="processarListaCpfs(false)">
            {{ processandoListaCpfs ? 'Processando...' : 'Conferir Lista' }}
          </button>
          <button
            type="button"
            class="btn-primary"
            :disabled="processandoListaCpfs || !conferenciaCpfs || conferenciaCpfs.pendentes_encontrados === 0 || listaCpfsConferida !== listaCpfsTexto.trim()"
            @click="processarListaCpfs(true)"
          >Homologar Correspondentes</button>
        </div>
      </template>
    </Modal>

    <!-- MODAL DE ZOOM DE FOTO -->
    <Modal
      :show="showModalZoom"
      :title="zoomImgTitulo"
      icon="bi-image"
      :max-width="'640px'"
      @close="showModalZoom = false"
    >
      <div class="text-center py-2">
        <img :src="zoomImgUrl" :alt="zoomImgTitulo" class="modal-photo-zoom" />
      </div>
      <template #footer>
        <button type="button" class="btn-secondary w-100" @click="showModalZoom = false">Fechar</button>
      </template>
    </Modal>

    </div>
  </div>
</template>

<style scoped>
/* ==========================================================================
   ESTILOS ESCOPADOS ESTRITAMENTE ESPECÍFICOS DESTA TELA
   Todo o restante (tabela, botões, modais, cabeçalhos, paginação) é 100% global
   ========================================================================== */
.spin-anim {
  animation: spin 1s infinite linear;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
