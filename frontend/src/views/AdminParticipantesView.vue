<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import Modal from '../components/Modal.vue'
import PhotoCorrectionRequestModal from '../components/PhotoCorrectionRequestModal.vue'
import KpiCard from '../components/KpiCard.vue'
import DropdownSelect from '../components/DropdownSelect.vue'
import QRCode from 'qrcode'
import { useAuth } from '../composables/useAuth'
import { useToast } from '../composables/useToast'
import { formatarCpf, formatarTelefone, formatarData, formatarDataNascimento } from '../utils/formatters'

const router = useRouter()
const { isAdminGeral } = useAuth()
const { toast } = useToast()

const loading = ref(true)
const participantes = ref([])
const kpisGerais = ref({
  total_ingressos_resgatados: 0,
  total_presentes: 0,
  total_fora: 0
})

// Filtros
const busca = ref('')
const filtroLote = ref('')
const filtroPresenca = ref(['presente', 'fora']) // Status selecionados no filtro múltiplo
const secretariasSelecionadas = ref([]) // IDs das secretarias selecionadas (Array para multi-select)

// Paginação no Servidor (Rule 6 - Strict max 50)
const itensPorPagina = ref(25)
const paginaAtual = ref(1)
const totalPaginasServer = ref(1)
const totalRegistrosServer = ref(0)
const lotesServer = ref([])
const secretariasServer = ref([])
const showModalExportacao = ref(false)
const modoExportacao = ref('unico')
const agrupamentoExportacao = ref('secretaria')
const exportandoPlanilha = ref(false)
const erroExportacao = ref('')

function abrirExportacaoPlanilha() {
  if (exportandoPlanilha.value) return
  erroExportacao.value = ''
  showModalExportacao.value = true
}

async function exportarPlanilhaParticipantes() {
  if (exportandoPlanilha.value) return
  exportandoPlanilha.value = true
  erroExportacao.value = ''
  const modo = modoExportacao.value
  const agrupamento = agrupamentoExportacao.value
  try {
    const params = new URLSearchParams({ modo, agrupar: agrupamento })
    const response = await fetch(`/api/admin/participantes/exportar-planilha?${params}`)
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Não foi possível exportar os participantes.')
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = modo === 'unico' ? 'participantes.xlsx' : `participantes_por_${agrupamento}.${modo === 'arquivos' ? 'zip' : 'xlsx'}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    showModalExportacao.value = false
    toast.success('Exportação gerada. Download iniciado.')
  } catch (err) {
    erroExportacao.value = err.message || 'Erro de conexão ao exportar os participantes.'
  } finally {
    exportandoPlanilha.value = false
  }
}

// Modais
const showModalFoto = ref(false)
const showModalCorrecaoFoto = ref(false)
const participanteCorrecaoFoto = ref(null)

function abrirModalCorrecaoFoto(p) {
  participanteCorrecaoFoto.value = p
  showModalCorrecaoFoto.value = true
}
const fotoZoomUrl = ref('')
const fotoZoomNome = ref('')

const showModalIngresso = ref(false)
const participanteIngresso = ref(null)
const qrDataUrl = ref('')

const showModalEmail = ref(false)
const participanteEmail = ref(null)
const emailAssunto = ref('')
const emailMensagem = ref('')
const enviandoEmail = ref(false)
const emailResultado = ref(null)

const showModalCancelar = ref(false)
const participanteCancelar = ref(null)
const cancelando = ref(false)
const motivoCancelamento = ref('')
const senhaAdminCancelamento = ref('')

const showModalExplicacaoStatus = ref(false)
const showModalDetalhesStatus = ref(false)
const participanteStatusDetalhes = ref(null)

function abrirModalExplicacaoStatus() {
  showModalExplicacaoStatus.value = true
}

function abrirModalDetalhesStatus(p) {
  participanteStatusDetalhes.value = p
  showModalDetalhesStatus.value = true
}

const showModalInfo = ref(false)
const participanteInfo = ref(null)

// Modal Editar Participante (Admin e Admin Geral)
const showModalEditar = ref(false)
const participanteEditar = ref(null)
const salvandoEditar = ref(false)
const vinculosDisponiveis = [
  'Efetivo', 'Comissionado', 'Contrato Temporário', 'Estagiário',
  'Terceirizado', 'Prestador de Serviço', 'Aposentado'
]
const formEditar = ref({
  nome: '',
  vinculo: '',
  secretaria_id: null,
  setor: '',
  telefone: '',
  data_nascimento: '',
  email: ''
})

const maxDataNascimento = computed(() => {
  const d = new Date()
  return d.toISOString().split('T')[0]
})

function formatarDataParaInput(dataStr) {
  if (!dataStr) return ''
  const trimmed = String(dataStr).trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed
  const match = trimmed.match(/^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$/)
  if (match) {
    const [, dia, mes, ano] = match
    return `${ano}-${mes.padStart(2, '0')}-${dia.padStart(2, '0')}`
  }
  return ''
}

function onTelefoneInput(event) {
  const val = event.target.value
  const digits = String(val).replace(/\D/g, '').slice(0, 11)
  if (!digits) {
    formEditar.value.telefone = ''
    return
  }
  if (digits.length <= 2) {
    formEditar.value.telefone = `(${digits}`
  } else if (digits.length <= 6) {
    formEditar.value.telefone = `(${digits.slice(0, 2)}) ${digits.slice(2)}`
  } else if (digits.length <= 10) {
    formEditar.value.telefone = `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`
  } else {
    formEditar.value.telefone = `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`
  }
}

function abrirModalEditar(p) {
  participanteEditar.value = p
  formEditar.value = {
    nome: p.nome || '',
    vinculo: p.vinculo || '',
    secretaria_id: p.secretaria ? p.secretaria.id : null,
    setor: p.setor || '',
    telefone: p.telefone || '',
    data_nascimento: formatarDataParaInput(p.data_nascimento),
    email: p.email || ''
  }
  showModalEditar.value = true
}

function fecharModalEditar() {
  if (salvandoEditar.value) return
  showModalEditar.value = false
  participanteEditar.value = null
}

async function salvarEdicaoParticipante() {
  if (!participanteEditar.value || salvandoEditar.value) return

  if (!formEditar.value.nome.trim()) {
    toast.warning('Por favor, informe o nome completo do participante.')
    return
  }

  if (formEditar.value.email && formEditar.value.email.trim()) {
    const em = formEditar.value.email.trim()
    if (!em.includes('@') || !em.includes('.')) {
      toast.warning('Por favor, informe um endereço de e-mail válido.')
      return
    }
  }

  if (formEditar.value.telefone && formEditar.value.telefone.trim()) {
    const digitos = formEditar.value.telefone.replace(/\D/g, '')
    if (digitos.length !== 10 && digitos.length !== 11) {
      toast.warning('O telefone deve conter DDD e 8 ou 9 dígitos.')
      return
    }
  }

  try {
    salvandoEditar.value = true
    const payload = {
      nome: formEditar.value.nome.trim(),
      vinculo: formEditar.value.vinculo.trim() || null,
      secretaria_id: formEditar.value.secretaria_id,
      setor: formEditar.value.setor ? formEditar.value.setor.trim() : null,
      telefone: formEditar.value.telefone ? formEditar.value.telefone.trim() : null,
      data_nascimento: formEditar.value.data_nascimento || null,
      email: formEditar.value.email ? formEditar.value.email.trim() : null
    }

    const res = await fetch(`/api/admin/participantes/${participanteEditar.value.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    const data = await res.json()

    if (!res.ok) {
      toast.error(data.detail || 'Erro ao atualizar dados do participante.')
      return
    }

    toast.success(data.mensagem || 'Dados do participante atualizados com sucesso!')

    const idx = participantes.value.findIndex(p => p.id === participanteEditar.value.id)
    if (idx !== -1) {
      const secAtualizada = secretariasServer.value.find(s => s.id === formEditar.value.secretaria_id)
      participantes.value[idx] = {
        ...participantes.value[idx],
        nome: data.participante?.nome ?? payload.nome,
        vinculo: data.participante?.vinculo ?? payload.vinculo,
        secretaria: secAtualizada ? { id: secAtualizada.id, nome: secAtualizada.nome } : null,
        setor: payload.setor,
        telefone: data.participante?.telefone || payload.telefone,
        data_nascimento: data.participante?.data_nascimento || payload.data_nascimento,
        email: payload.email
      }
    }

    if (participanteInfo.value && participanteInfo.value.id === participanteEditar.value.id) {
      const secAtualizada = secretariasServer.value.find(s => s.id === formEditar.value.secretaria_id)
      participanteInfo.value = {
        ...participanteInfo.value,
        nome: data.participante?.nome ?? payload.nome,
        vinculo: data.participante?.vinculo ?? payload.vinculo,
        secretaria: secAtualizada ? { id: secAtualizada.id, nome: secAtualizada.nome } : null,
        setor: payload.setor,
        telefone: data.participante?.telefone || payload.telefone,
        data_nascimento: data.participante?.data_nascimento || payload.data_nascimento,
        email: payload.email
      }
    }

    salvandoEditar.value = false
    fecharModalEditar()
  } catch (err) {
    toast.error('Erro de conexão ao atualizar dados do participante.')
  } finally {
    salvandoEditar.value = false
  }
}

const reenviandoEmailIngresso = ref(false)
const reenviarEmailSucesso = ref(null)

let pollInterval = null

function isIngressoInvalido(participante) {
  const status = participante?.situacao_evento?.status_slug
  return Boolean(
    participante?.ingresso?.cancelado ||
    status === 'cancelado' ||
    status === 'extraviado'
  )
}

async function carregarParticipantes(silent = false) {
  try {
    if (!silent) loading.value = true
    const params = new URLSearchParams()
    params.append('page', String(paginaAtual.value))
    params.append('limit', String(Math.min(itensPorPagina.value, 50)))
    if (busca.value.trim()) params.append('busca', busca.value.trim())
    if (filtroLote.value) params.append('lote_id', String(filtroLote.value))
    if (filtroPresenca.value.length > 0) params.append('status_presenca', filtroPresenca.value.join(','))
    if (secretariasSelecionadas.value.length > 0) params.append('secretarias', secretariasSelecionadas.value.join(','))

    const res = await fetch(`/api/admin/participantes?${params.toString()}`)
    if (res.status === 401 || res.status === 403) {
      router.push('/login')
      return
    }
    const data = await res.json()
    participantes.value = data.participantes || []
    kpisGerais.value = data.kpis || {
      total_ingressos_resgatados: 0,
      total_presentes: 0,
      total_fora: 0
    }
    if (data.pagination) {
      totalPaginasServer.value = data.pagination.total_pages || 1
      totalRegistrosServer.value = data.pagination.total || 0
    }
    if (data.lotes_disponiveis) lotesServer.value = data.lotes_disponiveis
    if (data.secretarias_disponiveis) secretariasServer.value = data.secretarias_disponiveis
  } catch (e) {
    if (!silent) toast.error('Erro de conexão ao carregar participantes.')
  } finally {
    if (!silent) loading.value = false
  }
}

// Lista única de lotes fornecida pelo servidor
const lotesDisponiveis = computed(() => {
  return lotesServer.value || []
})

// Lista única de secretarias fornecida pelo servidor
const secretariasDisponiveis = computed(() => {
  return (secretariasServer.value || []).map(s => ({
    id: s.id,
    nome: s.nome,
    count: ''
  }))
})

const optionsLotes = computed(() => [
  { value: '', label: 'Todos os Lotes' },
  ...lotesDisponiveis.value.map(l => ({ value: l.id, label: l.nome }))
])

const optionsPresenca = [
  { value: 'em_validacao', label: 'Em validação', icon: 'bi bi-hourglass-split' },
  { value: 'validacao_recusada', label: 'Validação Recusada', icon: 'bi bi-slash-circle' },
  { value: 'presente', label: 'Presente no Evento', icon: 'bi bi-ticket-perforated-fill' },
  { value: 'fora', label: 'Fora do Evento', icon: 'bi bi-door-open' },
  { value: 'cancelado', label: 'Ingresso Cancelado', icon: 'bi bi-x-circle' },
  { value: 'extraviado', label: 'Ingresso Extraviado', icon: 'bi bi-exclamation-octagon-fill' }
]

const optionsSecretarias = computed(() =>
  secretariasDisponiveis.value.map(s => ({
    value: s.id,
    label: s.nome
  }))
)

function toggleSecretaria(id) {
  const index = secretariasSelecionadas.value.indexOf(id)
  if (index > -1) {
    secretariasSelecionadas.value.splice(index, 1)
  } else {
    secretariasSelecionadas.value.push(id)
  }
}

function limparSecretarias() {
  secretariasSelecionadas.value = []
}

// KPIs Reativos sincronizados com o servidor
const kpis = computed(() => {
  return kpisGerais.value
})

const participantesFiltrados = computed(() => {
  return participantes.value
})

const participantesPaginados = computed(() => {
  return participantes.value
})

// Debounce para busca textual
let debounceTimer = null
watch(busca, () => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    paginaAtual.value = 1
    carregarParticipantes()
  }, 350)
})

// Watchers de filtros que recarregam a página via servidor
watch([filtroLote, filtroPresenca, secretariasSelecionadas, itensPorPagina], () => {
  paginaAtual.value = 1
  carregarParticipantes()
}, { deep: true })

// Paginação Servidor
const totalPaginas = computed(() => {
  return totalPaginasServer.value
})

const infoPaginacao = computed(() => {
  const total = totalRegistrosServer.value
  if (total === 0) return '0 de 0'
  const inicio = (paginaAtual.value - 1) * itensPorPagina.value + 1
  const fim = Math.min(paginaAtual.value * itensPorPagina.value, total)
  return `${inicio} - ${fim} de ${total}`
})

const paginasVisiveis = computed(() => {
  const total = totalPaginas.value
  const atual = paginaAtual.value
  const delta = 2
  const range = []
  for (let i = Math.max(2, atual - delta); i <= Math.min(total - 1, atual + delta); i++) {
    range.push(i)
  }

  if (atual - delta > 2) range.unshift('...')
  if (atual + delta < total - 1) range.push('...')

  range.unshift(1)
  if (total > 1 && !range.includes(total)) range.push(total)
  return range
})

function irParaPagina(p) {
  if (p === '...' || p < 1 || p > totalPaginasServer.value) return
  paginaAtual.value = p
  carregarParticipantes()
}

// Atalhos rápidos ao clicar nos cards de KPI
function toggleFiltroPresenca(tipo) {
  if (filtroPresenca.value.includes(tipo)) {
    filtroPresenca.value = filtroPresenca.value.filter(status => status !== tipo)
  } else {
    filtroPresenca.value = [...filtroPresenca.value, tipo]
  }
}

function limparFiltroPresenca() {
  filtroPresenca.value = []
}

function obterIniciais(nome) {
  if (!nome) return '?'
  const partes = nome.trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '?'
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase()
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase()
}

function abrirFotoZoom(p) {
  fotoZoomUrl.value = p.foto_url
  fotoZoomNome.value = p.nome
  showModalFoto.value = true
}

function abrirModalInfo(p) {
  participanteInfo.value = p
  showModalInfo.value = true
}

async function reenviarIngressoEmail() {
  if (!participanteIngresso.value) return
  try {
    reenviandoEmailIngresso.value = true
    reenviarEmailSucesso.value = null
    const res = await fetch(`/api/admin/usuarios/${participanteIngresso.value.id}/email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tipo: 'ingresso' })
    })
    const data = await res.json()
    if (res.ok) {
      reenviarEmailSucesso.value = { tipo: 'sucesso', msg: data.mensagem || 'Ingresso reenviado com sucesso para o e-mail!' }
    } else {
      reenviarEmailSucesso.value = { tipo: 'erro', msg: data.detail || 'Erro ao reenviar ingresso.' }
    }
  } catch (err) {
    reenviarEmailSucesso.value = { tipo: 'erro', msg: 'Falha de comunicação com o servidor.' }
  } finally {
    reenviandoEmailIngresso.value = false
  }
}

function salvarPDFIngresso(p) {
  if (!p || !p.ingresso) return
  const token = p.ingresso.qr_code_token || ''
  if (!token) return
  window.open(`/api/meu-ingresso/download-pdf/${token}`, '_blank')
}

async function abrirModalIngresso(p) {
  participanteIngresso.value = p
  qrDataUrl.value = ''
  reenviarEmailSucesso.value = null
  showModalIngresso.value = true
  if (p.ingresso?.qr_code_token) {
    try {
      qrDataUrl.value = await QRCode.toDataURL(p.ingresso.qr_code_token, {
        width: 260,
        margin: 2,
        color: {
          dark: '#000000',
          light: '#ffffff'
        }
      })
    } catch (e) {
      // Falha ao gerar preview QR code
    }
  }
}

function abrirModalEmail(p) {
  participanteEmail.value = p
  emailAssunto.value = 'Informações Importantes - Serv indoor 2026'
  emailMensagem.value = `Olá ${p.nome},\n\nSeu ingresso para o Serv indoor 2026 está confirmado!\n\nLote: ${p.ingresso?.lote_nome || 'Geral'}\nToken: ${p.ingresso?.qr_code_token || 'N/A'}\n\nApresente seu QR Code na portaria do evento.\n\nAtenciosamente,\nOrganização Serv indoor 2026`
  emailResultado.value = null
  showModalEmail.value = true
}

async function enviarEmail() {
  if (!participanteEmail.value) return
  try {
    enviandoEmail.value = true
    emailResultado.value = null
    const res = await fetch(`/api/admin/usuarios/${participanteEmail.value.id}/email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tipo: 'comunicado',
        assunto: emailAssunto.value,
        mensagem: emailMensagem.value
      })
    })
    const data = await res.json()
    if (res.ok) {
      emailResultado.value = { tipo: 'sucesso', msg: data.mensagem || data.message || 'E-mail enviado com sucesso!' }
      setTimeout(() => {
        showModalEmail.value = false
      }, 1500)
    } else {
      emailResultado.value = { tipo: 'erro', msg: data.detail || 'Erro ao enviar e-mail.' }
    }
  } catch (err) {
    emailResultado.value = { tipo: 'erro', msg: 'Falha na comunicação com o servidor.' }
  } finally {
    enviandoEmail.value = false
  }
}

function confirmarCancelarIngresso(p) {
  participanteCancelar.value = p
  motivoCancelamento.value = ''
  senhaAdminCancelamento.value = ''
  showModalCancelar.value = true
}

async function executarCancelamento() {
  if (!participanteCancelar.value?.ingresso?.id) return
  if (!motivoCancelamento.value.trim()) {
    toast.error('Informe o motivo do cancelamento.')
    return
  }
  if (!senhaAdminCancelamento.value) {
    toast.error('Informe sua senha de administrador para autorizar.')
    return
  }
  try {
    cancelando.value = true
    const res = await fetch(`/api/admin/ingressos/${participanteCancelar.value.ingresso.id}/cancelar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        motivo: motivoCancelamento.value.trim(),
        senha_admin: senhaAdminCancelamento.value
      })
    })
    if (res.ok) {
      toast.success('Ingresso cancelado e extravio registrado com sucesso!')
      showModalCancelar.value = false
      await carregarParticipantes()
    } else {
      const data = await res.json()
      toast.error(data.detail || 'Erro ao cancelar ingresso.')
    }
  } catch (err) {
    toast.error('Erro de conexão ao cancelar ingresso.')
  } finally {
    cancelando.value = false
  }
}

function exportarCSV() {
  window.open('/api/admin/ingressos/exportar-csv', '_blank')
}

onMounted(() => {
  carregarParticipantes()
  pollInterval = setInterval(() => {
    if (!document.hidden && !showModalIngresso.value && !showModalEmail.value && !showModalCancelar.value && !showModalFoto.value && !showModalExplicacaoStatus.value && !showModalDetalhesStatus.value && !showModalEditar.value && !showModalInfo.value && !showModalExportacao.value) {
      carregarParticipantes(true)
    }
  }, 2500)
})

onUnmounted(() => {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
})
</script>

<template>
  <div class="admin-page">
    <div class="app-container">

      <!-- CABEÇALHO DA PÁGINA COM TIPOGRAFIA QUATTROCENTO CANÔNICA -->
      <div class="admin-header-row">
        <div>
          <span class="admin-eyebrow">
            <i class="bi bi-ticket-perforated-fill me-1"></i> PAINEL ADMINISTRATIVO
          </span>
          <h1 class="page-title font-quattrocento">Gestão de Participantes</h1>
          <p class="page-subtitle">Servidores com ingressos resgatados e controle de fluxo em tempo real.</p>
        </div>

        <div class="admin-header-actions">
          <button type="button" class="btn btn-secondary" :disabled="exportandoPlanilha" @click="abrirExportacaoPlanilha">
            <i class="bi bi-file-earmark-excel text-success me-2"></i>
            <span>Exportar Planilha</span>
          </button>
          <button type="button" class="btn btn-secondary" @click="exportarCSV">
            <i class="bi bi-file-earmark-spreadsheet-fill text-success me-2"></i>
            <span>Exportar CSV</span>
          </button>
          <button type="button" class="btn btn-primary" @click="carregarParticipantes(false)">
            <i class="bi bi-arrow-clockwise me-2" :class="{ 'spin-icon': loading }"></i>
            <span>Atualizar</span>
          </button>
        </div>
      </div>

      <!-- CARDS DE KPI (REATIVOS AOS FILTROS) -->
      <div class="kpi-grid">
        <KpiCard
          title="Ingressos Filtrados"
          :value="kpis.total_ingressos_resgatados"
          subtitle="Total no recorte atual"
          icon="bi bi-ticket-perforated-fill"
          variant="cyan"
          :clickable="true"
          :active="filtroPresenca.length === 0 || filtroPresenca.length === optionsPresenca.length"
          @click="limparFiltroPresenca"
        />

        <KpiCard
          title="Presentes no Evento"
          :value="kpis.total_presentes"
          subtitle="Na área do evento"
          icon="bi bi-check-circle-fill"
          variant="emerald"
          :clickable="true"
          :active="filtroPresenca.includes('presente')"
          @click="toggleFiltroPresenca('presente')"
        />

        <KpiCard
          title="Fora do Evento"
          :value="kpis.total_fora"
          subtitle="Ainda não entraram ou saíram"
          icon="bi bi-geo-alt-fill"
          variant="warning"
          :clickable="true"
          :active="filtroPresenca.includes('fora')"
          @click="toggleFiltroPresenca('fora')"
        />
      </div>

      <!-- BARRA DE FILTROS CANÔNICA -->
      <div class="filter-card">
        <div class="filter-grid">
          <!-- 1. Campo de Busca Geral -->
          <div class="search-box">
            <i class="bi bi-search search-icon"></i>
            <input
              v-model="busca"
              type="text"
              class="form-control"
              placeholder="Buscar por Nome, CPF, Setor ou Token..."
            />
            <button v-if="busca" type="button" class="btn-clear-search" title="Limpar busca" @click="busca = ''">
              <i class="bi bi-x-circle-fill"></i>
            </button>
          </div>

          <!-- 2. Multi-Select de Secretarias -->
          <div class="select-box">
            <DropdownSelect
              v-model="secretariasSelecionadas"
              :options="optionsSecretarias"
              placeholder="Secretarias: Todas"
              :multiple="true"
              :searchable="true"
              searchPlaceholder="Filtrar secretarias..."
              icon="bi bi-building"
            />
          </div>

          <!-- 3. Filtro de Lote -->
          <div class="select-box">
            <DropdownSelect
              v-model="filtroLote"
              :options="optionsLotes"
              placeholder="Todos os Lotes"
              icon="bi bi-layers"
            />
          </div>

          <!-- 4. Filtro de Status no Evento -->
          <div class="select-box">
            <DropdownSelect
              v-model="filtroPresenca"
              :options="optionsPresenca"
              placeholder="Status: Todos"
              :multiple="true"
              icon="bi bi-funnel"
            />
          </div>
        </div>

        <!-- Tags ativas de secretarias selecionadas -->
        <div v-if="secretariasSelecionadas.length > 0" class="active-tags-row">
          <span class="text-muted small me-2">Filtrando por:</span>
          <span
            v-for="secId in secretariasSelecionadas"
            :key="secId"
            class="active-sec-pill"
          >
            <span>{{ secretariasDisponiveis.find(s => s.id === secId)?.nome || secId }}</span>
            <button type="button" class="btn-remove-tag" title="Remover filtro" @click="toggleSecretaria(secId)">
              <i class="bi bi-x"></i>
            </button>
          </span>
          <button type="button" class="btn-clear-all-tags" @click="limparSecretarias">
            Limpar Filtro de Secretarias
          </button>
        </div>
      </div>

      <!-- TABELA DE PARTICIPANTES CANÔNICA -->
      <div class="table-card">
        <div class="table-header-box">
          <h2 class="table-title">
            <i class="bi bi-people-fill text-cyan me-2"></i>
            <span>Participantes Cadastrados</span>
            <span class="table-badge-count">{{ participantesFiltrados.length }}</span>
          </h2>

          <div class="table-header-controls">
            <span class="text-muted small me-2">Exibir:</span>
            <select v-model="itensPorPagina" class="form-select form-select-sm select-page-size">
              <option :value="10">10</option>
              <option :value="25">25</option>
              <option :value="50">50</option>
            </select>
          </div>
        </div>

        <div v-if="loading" class="table-loading-state">
          <div class="spinner-border text-primary mb-3"></div>
          <p class="font-outfit text-muted">Sincronizando participantes...</p>
        </div>

        <div v-else-if="!participantes.length" class="table-empty-state">
          <i class="bi bi-inbox"></i>
          <p>Nenhum participante encontrado com os filtros aplicados.</p>
        </div>

                <!-- GRID DE CARDS CANÔNICO DE PARTICIPANTES V2 -->
        <div v-else class="entity-cards-grid">
          <div
            v-for="p in participantesPaginados"
            :key="p.id"
            :class="['entity-card', 'entity-card--' + (p.situacao_evento?.status_slug || 'neutral')]"
          >
            <!-- 1. Topo: Lote / Ingresso à esquerda, Status no Evento à direita -->
            <div class="entity-card-top-bar">
              <div>
                <span v-if="p.ingresso" class="badge-subtle-warning">
                  <i class="bi bi-ticket-perforated me-1"></i>{{ p.ingresso.lote_nome }}
                </span>
                <span v-else class="status-pill status-pill--neutral">
                  <i class="bi bi-ticket me-1"></i>Sem Ingresso
                </span>
              </div>

              <div class="d-flex align-items-center gap-1">
                <span
                  class="status-pill"
                  :class="'status-pill--' + (p.situacao_evento?.status_slug || 'neutral')"
                >
                  <i :class="(p.situacao_evento?.icon_class || 'bi bi-circle')"></i>
                  <span>{{ p.situacao_evento?.label }}</span>
                </span>
                <button
                  v-if="p.situacao_evento?.detalhes"
                  type="button"
                  class="btn-inline-info-square"
                  :title="'Ver detalhes: ' + p.situacao_evento?.label"
                  @click="abrirModalDetalhesStatus(p)"
                >
                  <i class="bi bi-info-circle-fill"></i>
                </button>
              </div>
            </div>

            <!-- 2. Identidade: Avatar (ou Iniciais) + Nome Completo e CPF em Largura Total -->
            <div class="entity-card-identity">
              <div
                class="entity-card-avatar"
                :title="p.foto_url ? 'Clique para ampliar foto' : 'Foto não cadastrada'"
                @click="p.foto_url && abrirFotoZoom(p)"
              >
                <img
                  v-if="p.foto_url"
                  :src="p.foto_url"
                  alt="Foto do participante"
                  class="entity-card-avatar-img"
                  @error="(e) => { e.target.style.display = 'none'; if (e.target.nextElementSibling) e.target.nextElementSibling.style.display = 'flex'; }"
                />
                <div
                  class="entity-card-avatar-fallback"
                  :style="{ display: p.foto_url ? 'none' : 'flex' }"
                >
                  <span>{{ obterIniciais(p.nome) }}</span>
                </div>
              </div>

              <div class="entity-card-info">
                <h3 class="entity-card-title">{{ p.nome }}</h3>
                <div class="entity-card-sub">
                  <span class="table-code-pill font-monospace">{{ p.cpf_formatado }}</span>
                  <span class="table-tag">{{ p.vinculo || 'Servidor' }}</span>
                </div>
              </div>
            </div>

            <!-- 3. Metadados: Hierarquia Visual Limpa (Secretaria/Setor & Lote/Horário) -->
            <div class="entity-meta-grid">
              <div class="entity-meta-item">
                <span class="meta-label">Secretaria / Setor</span>
                <span class="meta-value" :title="p.secretaria?.nome || 'Geral'">
                  {{ p.secretaria?.nome || 'Geral' }}
                </span>
                <span v-if="p.setor" class="meta-sub" :title="p.setor">
                  {{ p.setor }}
                </span>
              </div>

              <div class="entity-meta-item">
                <span class="meta-label">Situação do Ingresso</span>
                <template v-if="p.ingresso">
                  <span v-if="isIngressoInvalido(p)" class="status-badge bg-danger">
                    <i class="bi bi-x-circle-fill me-1"></i> Cancelado
                  </span>
                  <span v-else class="status-badge bg-success">
                    <i class="bi bi-check-circle-fill me-1"></i> Emitido
                  </span>
                  <span v-if="p.situacao_evento?.dentro" class="meta-sub text-success mt-1">
                    <i class="bi bi-check-circle-fill me-1"></i>Check-in Confirmado
                  </span>
                  <span v-else-if="!isIngressoInvalido(p)" class="meta-sub mt-1">
                    Aguardando entrada
                  </span>
                </template>
                <template v-else>
                  <span class="status-badge bg-warning">
                    <i class="bi bi-hourglass-split me-1"></i> Pendente
                  </span>
                  <span class="meta-sub mt-1">Resgate não realizado</span>
                </template>
              </div>
            </div>

            <!-- 4. Rodapé: Ação Principal à Esquerda, Secundárias e Destrutiva Isolada -->
            <div class="entity-card-footer">
              <div class="actions-left">
                <button
                  v-if="p.ingresso && !isIngressoInvalido(p)"
                  type="button"
                  class="btn-card-primary"
                  title="Visualizar Ingresso Oficial com QR Code"
                  @click="abrirModalIngresso(p)"
                >
                  <i class="bi bi-qr-code"></i>
                  <span>Ingresso</span>
                </button>
                <button
                  v-else
                  type="button"
                  class="btn-card-secondary"
                  title="Ver ficha cadastral completa"
                  @click="abrirModalInfo(p)"
                >
                  <i class="bi bi-person-vcard"></i>
                  <span>Ficha</span>
                </button>
              </div>

              <div class="actions-right">
                <!-- Ver Ficha: em Verde (--emerald) -->
                <button
                  v-if="p.ingresso && !isIngressoInvalido(p)"
                  type="button"
                  class="btn-action-icon btn-action-icon--emerald action-expandable action-expandable--details"
                  title="Ficha Completa do Participante"
                  aria-label="Ver ficha"
                  @click="abrirModalInfo(p)"
                >
                  <i class="bi bi-person-vcard"></i>
                  <span class="action-label">Ver ficha</span>
                </button>

                <!-- Editar: em Amarelo (--amber), desabilitado se extraviado -->
                <button
                  type="button"
                  class="btn-action-icon btn-action-icon--amber action-expandable action-expandable--edit"
                  :disabled="isIngressoInvalido(p)"
                  :title="isIngressoInvalido(p) ? 'Ingresso extraviado/cancelado não permite edição de dados' : 'Editar Dados do Participante'"
                  aria-label="Editar participante"
                  @click="!isIngressoInvalido(p) && abrirModalEditar(p)"
                >
                  <i class="bi bi-pencil-square"></i>
                  <span class="action-label">Editar</span>
                </button>

                <!-- Email: em Amarelo (--amber), desabilitado se extraviado -->
                <button
                  type="button"
                  class="btn-action-icon btn-action-icon--amber action-expandable action-expandable--email"
                  :disabled="isIngressoInvalido(p)"
                  :title="isIngressoInvalido(p) ? 'Ingresso extraviado/cancelado' : 'Enviar E-mail com Ingresso'"
                  aria-label="Enviar e-mail com ingresso"
                  @click="!isIngressoInvalido(p) && abrirModalEmail(p)"
                >
                  <i class="bi bi-envelope-fill"></i>
                  <span class="action-label">Enviar e-mail</span>
                </button>

                <button
                  type="button"
                  class="btn-action-icon btn-action-icon--cyan action-expandable action-expandable--wide"
                  :disabled="isIngressoInvalido(p) || !p.email"
                  :title="!p.email ? 'Cadastre um e-mail para solicitar a correção' : (isIngressoInvalido(p) ? 'Ingresso extraviado/cancelado' : 'Solicitar correção de foto por e-mail')"
                  aria-label="Solicitar correção de foto"
                  @click="abrirModalCorrecaoFoto(p)"
                >
                  <i class="bi bi-camera"></i>
                  <span class="action-label">Corrigir foto</span>
                </button>

                <span v-if="p.ingresso && !p.ingresso.cancelado" class="action-divider"></span>

                <!-- Lixeira: em Vermelho (--danger) -->
                <button
                  v-if="p.ingresso && !p.ingresso.cancelado"
                  type="button"
                  class="btn-action-icon btn-action-icon--danger action-expandable action-expandable--cancel"
                  title="Cancelar Ingresso (Extravio Administrativo)"
                  aria-label="Cancelar ingresso"
                  @click="confirmarCancelarIngresso(p)"
                >
                  <i class="bi bi-trash3-fill"></i>
                  <span class="action-label">Cancelar</span>
                </button>
              </div>
            </div>

          </div>
        </div>

        <!-- RODAPÉ DE PAGINAÇÃO CANÔNICO -->
        <div v-if="participantesFiltrados.length > 0" class="pagination-footer">
          <div class="pagination-info">
            Mostrando <strong>{{ infoPaginacao }}</strong>
          </div>

          <div class="pagination-buttons">
            <button
              type="button"
              class="btn-page-nav"
              :disabled="paginaAtual === 1"
              title="Primeira Página"
              @click="irParaPagina(1)"
            >
              <i class="bi bi-chevron-double-left"></i>
            </button>

            <button
              type="button"
              class="btn-page-nav"
              :disabled="paginaAtual === 1"
              title="Página Anterior"
              @click="irParaPagina(paginaAtual - 1)"
            >
              <i class="bi bi-chevron-left"></i>
            </button>

            <button
              v-for="(p, idx) in paginasVisiveis"
              :key="idx"
              type="button"
              class="btn-page-number"
              :class="{ 'is-active': p === paginaAtual, 'is-dots': p === '...' }"
              :disabled="p === '...'"
              @click="irParaPagina(p)"
            >
              {{ p }}
            </button>

            <button
              type="button"
              class="btn-page-nav"
              :disabled="paginaAtual === totalPaginas"
              title="Próxima Página"
              @click="irParaPagina(paginaAtual + 1)"
            >
              <i class="bi bi-chevron-right"></i>
            </button>

            <button
              type="button"
              class="btn-page-nav"
              :disabled="paginaAtual === totalPaginas"
              title="Última Página"
              @click="irParaPagina(totalPaginas)"
            >
              <i class="bi bi-chevron-double-right"></i>
            </button>
          </div>
        </div>
      </div>

    </div>

    <!-- MODAL 1: VER INGRESSO / QR CODE -->
    <Modal
      :show="showModalIngresso"
      title="Ingresso do Participante"
      icon="bi-qr-code"
      @close="showModalIngresso = false"
    >
      <div v-if="participanteIngresso" class="text-center p-3">
        <h4 class="font-outfit text-white mb-2">{{ participanteIngresso.nome }}</h4>
        <p class="text-muted small mb-4">CPF: {{ participanteIngresso.cpf_formatado }}</p>

        <div class="modal-qr-preview">
          <img v-if="qrDataUrl" :src="qrDataUrl" alt="QR Code Oficial" class="modal-qr-img" />
          <div v-else class="spinner-border text-primary my-4"></div>
        </div>

        <div class="mt-4">
          <span class="badge-subtle-warning mb-2">{{ participanteIngresso.ingresso?.lote_nome }}</span>
          <div class="ticket-token-display mt-3">
            <span class="token-title">Token Oficial:</span>
            <span class="token-value font-monospace">{{ participanteIngresso.ingresso?.qr_code_token }}</span>
          </div>
        </div>

        <div v-if="reenviarEmailSucesso" class="modal-alert-card mt-3" :class="reenviarEmailSucesso.tipo === 'sucesso' ? 'modal-alert-card--success' : 'modal-alert-card--danger'">
          <i :class="reenviarEmailSucesso.tipo === 'sucesso' ? 'bi bi-check-circle-fill me-2' : 'bi bi-exclamation-triangle-fill me-2'"></i>
          {{ reenviarEmailSucesso.msg }}
        </div>
      </div>

      <template #footer>
        <div class="modal-footer-grid">
          <button
            type="button"
            class="btn btn-secondary"
            :disabled="reenviandoEmailIngresso"
            title="Enviar novamente o ingresso para o e-mail cadastrado"
            @click="reenviarIngressoEmail"
          >
            <i class="bi bi-envelope-arrow-up me-1" :class="{ 'spin-icon': reenviandoEmailIngresso }"></i>
            <span>{{ reenviandoEmailIngresso ? 'Enviando...' : 'Reenviar E-mail' }}</span>
          </button>

          <button
            type="button"
            class="btn btn-primary"
            title="Baixar como PDF no formato oficial do ingresso"
            @click="salvarPDFIngresso(participanteIngresso)"
          >
            <i class="bi bi-file-earmark-pdf-fill me-1"></i>
            <span>Baixar como PDF</span>
          </button>

          <a
            v-if="participanteIngresso?.ingresso?.qr_code_token"
            :href="'/api/meu-ingresso/download-imagem/' + participanteIngresso.ingresso.qr_code_token"
            target="_blank"
            download
            class="btn btn-secondary text-decoration-none"
            title="Baixar imagem PNG do ingresso"
          >
            <i class="bi bi-download me-1"></i>
            <span>Baixar PNG</span>
          </a>

          <button type="button" class="btn btn-secondary" @click="showModalIngresso = false">
            Fechar
          </button>
        </div>
      </template>
    </Modal>

    <PhotoCorrectionRequestModal
      :show="showModalCorrecaoFoto"
      :participante="participanteCorrecaoFoto"
      @close="showModalCorrecaoFoto = false"
    />

    <!-- MODAL 2: ENVIAR E-MAIL -->
    <Modal
      :show="showModalEmail"
      title="Enviar E-mail ao Participante"
      icon="bi-envelope-at-fill"
      maxWidth="620px"
      @close="showModalEmail = false"
    >
      <div v-if="participanteEmail" class="p-2">
        <div class="form-group mb-3">
          <label class="form-label text-muted small">Destinatário:</label>
          <div class="recipient-badge">
            <i class="bi bi-person-fill text-cyan me-2"></i>
            <strong class="text-white">{{ participanteEmail.nome }}</strong>
            <span class="text-muted ms-2">&lt;{{ participanteEmail.email }}&gt;</span>
          </div>
        </div>

        <div class="form-group mb-3">
          <label class="form-label text-muted small">Assunto:</label>
          <input v-model="emailAssunto" type="text" class="form-control" />
        </div>

        <div class="form-group mb-3">
          <label class="form-label text-muted small">Mensagem:</label>
          <textarea v-model="emailMensagem" rows="8" class="form-control email-textarea" placeholder="Escreva a mensagem aqui..."></textarea>
        </div>

        <div v-if="emailResultado" class="modal-alert-card mt-3" :class="emailResultado.tipo === 'sucesso' ? 'modal-alert-card--success' : 'modal-alert-card--danger'">
          <i :class="emailResultado.tipo === 'sucesso' ? 'bi bi-check-circle-fill me-2' : 'bi bi-exclamation-triangle-fill me-2'"></i>
          {{ emailResultado.msg }}
        </div>
      </div>

      <template #footer>
        <div class="d-flex gap-3 w-100">
          <button type="button" class="btn btn-secondary flex-1" @click="showModalEmail = false">
            Cancelar
          </button>
          <button type="button" class="btn btn-primary flex-1" :disabled="enviandoEmail" @click="enviarEmail">
            <span v-if="enviandoEmail" class="spinner-border spinner-border-sm me-2"></span>
            <span>{{ enviandoEmail ? 'Enviando...' : 'Enviar E-mail' }}</span>
          </button>
        </div>
      </template>
    </Modal>

    <!-- MODAL 3: CANCELAR INGRESSO -->
    <Modal
      :show="showModalCancelar"
      title="Cancelar Ingresso (Extravio Administrativo)"
      icon="bi-exclamation-triangle"
      maxWidth="560px"
      @close="showModalCancelar = false"
    >
      <div v-if="participanteCancelar" class="p-3 text-start">
        <div class="text-center mb-3">
          <i class="bi bi-slash-circle-fill text-danger fs-1 mb-2 d-block"></i>
          <h4 class="font-outfit text-white mb-1">Confirmar Cancelamento</h4>
          <p class="text-muted small">
            Participante: <strong class="text-white">{{ participanteCancelar.nome }}</strong> (CPF: {{ participanteCancelar.cpf_formatado }})
          </p>
        </div>

        <div class="modal-alert-card modal-alert-card--danger mb-3">
          <i class="bi bi-shield-lock-fill text-danger fs-4 flex-shrink-0"></i>
          <div class="small">
            <strong class="text-danger d-block">Ação Irreversível com Bloqueio de CPF</strong>
            O ingresso será cancelado administrativamente como <strong>Ingresso Extraviado</strong>, a vaga será devolvida ao lote e o CPF será <strong>permanentemente bloqueado</strong> para resgate em outros lotes.
          </div>
        </div>

        <div class="mb-3">
          <label class="form-label text-white small fw-bold mb-1">
            <i class="bi bi-chat-left-text text-danger me-1"></i> Motivo do Cancelamento <span class="text-danger">*</span>
          </label>
          <textarea
            v-model="motivoCancelamento"
            class="form-control"
            rows="3"
            placeholder="Informe detalhadamente a justificativa para o cancelamento deste ingresso..."
            required
          ></textarea>
        </div>

        <div class="mb-2">
          <label class="form-label text-white small fw-bold mb-1">
            <i class="bi bi-key-fill text-warning me-1"></i> Sua Senha de Administrador <span class="text-danger">*</span>
          </label>
          <input
            v-model="senhaAdminCancelamento"
            type="password"
            class="form-control"
            placeholder="Digite sua senha de login para confirmar"
            required
            autocomplete="current-password"
            @keyup.enter="executarCancelamento"
          />
        </div>
      </div>

      <template #footer>
        <div class="d-flex gap-2 w-100">
          <button type="button" class="btn btn-secondary flex-1" :disabled="cancelando" @click="showModalCancelar = false">
            Voltar / Cancelar
          </button>
          <button type="button" class="btn btn-danger flex-1" :disabled="cancelando" @click="executarCancelamento">
            <span v-if="cancelando" class="spinner-border spinner-border-sm me-2"></span>
            <i v-else class="bi bi-shield-x me-1"></i>
            <span>{{ cancelando ? 'Processando...' : 'Confirmar Cancelamento' }}</span>
          </button>
        </div>
      </template>
    </Modal>

    <!-- MODAL 4: GUIA DE STATUS DO EVENTO -->
    <Modal
      :show="showModalExplicacaoStatus"
      title="Guia de Status do Evento"
      icon="bi-info-circle"
      maxWidth="620px"
      @close="showModalExplicacaoStatus = false"
    >
      <div class="p-1">
        <p class="text-muted small mb-3">
          Compreenda o significado de cada status exibido na tabela de participantes e o ciclo de vida do participante no evento:
        </p>

        <div class="d-flex flex-column gap-3">
          <div class="status-guide-card">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="badge-status-compact bg-info">
                <i class="bi bi-hourglass-split me-1"></i> Em Validação
              </span>
              <span class="badge-subtle-primary small">Servidor em Análise</span>
            </div>
            <p class="status-guide-text mb-0">
              O participante realizou o cadastro de validação de servidor público, mas seus documentos ainda estão sob análise. Ele <strong>não possui QR Code ativo</strong> até a validação ser aprovada.
            </p>
          </div>

          <div class="status-guide-card">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="badge-status-compact bg-danger">
                <i class="bi bi-x-octagon-fill me-1"></i> Validação Recusada
              </span>
              <span class="badge-subtle-danger small">Identificado como Não-Servidor</span>
            </div>
            <p class="status-guide-text mb-0">
              A equipe de validação analisou os comprovantes e <strong>recusou a solicitação</strong> por inconsistência ou por não comprovação de vínculo público. O CPF foi bloqueado para novos resgates.
            </p>
          </div>

          <div class="status-guide-card">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="badge-status-compact bg-success">
                <i class="bi bi-check-circle-fill me-1"></i> Presente no Evento
              </span>
              <span class="badge-subtle-success small">Dentro do Espaço</span>
            </div>
            <p class="status-guide-text mb-0">
              O participante compareceu à portaria, teve seu QR Code lido e validado com sucesso e <strong>encontra-se atualmente dentro do evento</strong>.
            </p>
          </div>

          <div class="status-guide-card">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="badge-status-compact bg-warning">
                <i class="bi bi-geo-alt-fill me-1"></i> Fora do Evento
              </span>
              <span class="badge-subtle-warning small">Não Ingressou ou Saiu</span>
            </div>
            <p class="status-guide-text mb-0">
              O participante possui ingresso ativo e emitido, mas ainda não deu entrada na portaria, ou registrou saída temporária/definitiva do espaço.
            </p>
          </div>

          <div class="status-guide-card">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="badge-status-compact bg-secondary">
                <i class="bi bi-slash-circle me-1"></i> Ingresso Cancelado
              </span>
              <span class="badge-subtle-secondary small">Desistência Voluntária</span>
            </div>
            <p class="status-guide-text mb-0">
              O participante solicitou o cancelamento voluntário do seu ingresso por meio do autoatendimento. A vaga foi liberada e o QR Code invalidado.
            </p>
          </div>

          <div class="status-guide-card">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="badge-status-compact bg-danger">
                <i class="bi bi-slash-circle-fill me-1"></i> Ingresso Extraviado
              </span>
              <span class="badge-subtle-danger small">Cancelamento Administrativo</span>
            </div>
            <p class="status-guide-text mb-0">
              O ingresso foi cancelado diretamente por um administrador por motivo de extravio ou irregularidade. O CPF foi permanentemente bloqueado.
            </p>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="d-flex justify-content-end w-100">
          <button type="button" class="btn btn-primary px-4" @click="showModalExplicacaoStatus = false">
            <i class="bi bi-check2 me-1"></i> Entendido
          </button>
        </div>
      </template>
    </Modal>

    <!-- MODAL 5: DETALHES DE OCORRÊNCIA -->
    <Modal
      :show="showModalDetalhesStatus"
      :title="participanteStatusDetalhes?.situacao_evento?.label || 'Detalhes da Ocorrência'"
      icon="bi-shield-exclamation"
      maxWidth="580px"
      @close="showModalDetalhesStatus = false"
    >
      <div v-if="participanteStatusDetalhes" class="p-1">
        <div class="modal-hero-card mb-3">
          <div class="modal-hero-info">
            <div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
              <h3 class="modal-hero-name font-outfit">{{ participanteStatusDetalhes.nome }}</h3>
              <span class="badge-status-compact" :class="participanteStatusDetalhes.situacao_evento?.badge_class">
                <i :class="(participanteStatusDetalhes.situacao_evento?.icon_class || 'bi bi-circle') + ' me-1'"></i>
                {{ participanteStatusDetalhes.situacao_evento?.label }}
              </span>
            </div>
            <div class="d-flex align-items-center gap-3 flex-wrap small">
              <div>
                <span class="text-muted fw-bold me-1">CPF:</span>
                <span class="font-monospace text-light">{{ participanteStatusDetalhes.cpf_formatado }}</span>
              </div>
              <div v-if="participanteStatusDetalhes.secretaria?.nome">
                <span class="text-muted fw-bold me-1">Secretaria:</span>
                <span class="text-light">{{ participanteStatusDetalhes.secretaria.nome }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Ocorrência 2: Recusada -->
        <div v-if="participanteStatusDetalhes.situacao_evento?.detalhes?.tipo === 'validacao_recusada'">
          <div class="modal-info-grid mb-3">
            <div class="modal-field-card">
              <span class="modal-field-label text-danger">Data e Hora da Recusa</span>
              <strong class="modal-field-value font-monospace">{{ participanteStatusDetalhes.situacao_evento.detalhes.quando }}</strong>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label text-cyan">Validador Responsável</span>
              <strong class="modal-field-value">{{ participanteStatusDetalhes.situacao_evento.detalhes.por_quem }}</strong>
            </div>
          </div>
          <div class="modal-alert-card modal-alert-card--danger mb-3">
            <div>
              <strong class="d-block mb-1">Motivo Apontado:</strong>
              {{ participanteStatusDetalhes.situacao_evento.detalhes.motivo }}
            </div>
          </div>
        </div>

        <!-- Ocorrência 5: Cancelado Voluntário -->
        <div v-else-if="participanteStatusDetalhes.situacao_evento?.detalhes?.tipo === 'cancelado'">
          <div class="modal-info-grid mb-3">
            <div class="modal-field-card">
              <span class="modal-field-label text-warning">Data do Cancelamento</span>
              <strong class="modal-field-value font-monospace">{{ participanteStatusDetalhes.situacao_evento.detalhes.quando }}</strong>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label text-muted">Cancelado Por</span>
              <strong class="modal-field-value">{{ participanteStatusDetalhes.situacao_evento.detalhes.por_quem }}</strong>
            </div>
          </div>
          <div class="modal-alert-card modal-alert-card--warning mb-3">
            <div>
              <strong class="d-block mb-1">Motivo Declarado:</strong>
              {{ participanteStatusDetalhes.situacao_evento.detalhes.motivo }}
            </div>
          </div>
        </div>

        <!-- Ocorrência 6: Extraviado Administrativo -->
        <div v-else-if="participanteStatusDetalhes.situacao_evento?.detalhes?.tipo === 'extraviado'">
          <div class="modal-info-grid mb-3">
            <div class="modal-field-card">
              <span class="modal-field-label text-danger">Data do Extravio</span>
              <strong class="modal-field-value font-monospace">{{ participanteStatusDetalhes.situacao_evento.detalhes.quando }}</strong>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label text-danger">Administrador Responsável</span>
              <strong class="modal-field-value">{{ participanteStatusDetalhes.situacao_evento.detalhes.por_quem }}</strong>
            </div>
          </div>
          <div class="modal-alert-card modal-alert-card--danger mb-3">
            <div>
              <strong class="d-block mb-1">Justificativa Administrativa:</strong>
              {{ participanteStatusDetalhes.situacao_evento.detalhes.motivo }}
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="d-flex justify-content-end w-100">
          <button type="button" class="btn btn-secondary px-4" @click="showModalDetalhesStatus = false">
            <i class="bi bi-x-lg me-1"></i> Fechar
          </button>
        </div>
      </template>
    </Modal>

    <!-- MODAL 6: INFORMAÇÕES COMPLETAS DO PARTICIPANTE -->
    <Modal
      :show="showModalInfo"
      title="Informações do Participante"
      icon="bi-person-vcard"
      maxWidth="650px"
      @close="showModalInfo = false"
    >
      <div v-if="participanteInfo">
        <!-- Hero Card com Avatar Canônico -->
        <div class="modal-hero-card">
          <div
            class="modal-hero-avatar"
            :title="participanteInfo.foto_url ? 'Clique para ampliar foto' : 'Sem foto'"
            @click="participanteInfo.foto_url && abrirFotoZoom(participanteInfo)"
          >
            <img
              v-if="participanteInfo.foto_url"
              :src="participanteInfo.foto_url"
              alt="Foto do Participante"
            />
            <div v-else class="modal-hero-avatar-fallback">
              <i class="bi bi-person-fill"></i>
            </div>
          </div>

          <div class="modal-hero-info">
            <h3 class="modal-hero-name font-outfit">{{ participanteInfo.nome }}</h3>
            <div class="d-flex align-items-center flex-wrap gap-2">
              <span class="badge-subtle-primary">
                <i class="bi bi-briefcase-fill me-1"></i> {{ participanteInfo.vinculo || 'Servidor' }}
              </span>
              <span v-if="participanteInfo.role && participanteInfo.role !== 'participante'" class="badge-subtle-magenta">
                <i class="bi bi-shield-check me-1"></i> {{ participanteInfo.role }}
              </span>
              <span v-if="participanteInfo.liberado" class="badge-subtle-success">
                <i class="bi bi-check-circle-fill me-1"></i> Liberado
              </span>
              <span v-if="participanteInfo.bloqueado" class="badge-subtle-danger">
                <i class="bi bi-slash-circle-fill me-1"></i> Bloqueado
              </span>
            </div>
          </div>
        </div>

        <!-- Dados Cadastrais -->
        <div class="modal-section">
          <h4 class="modal-section-heading font-outfit">
            <i class="bi bi-person-lines-fill text-cyan me-2"></i> Dados Cadastrais
          </h4>
          <div class="modal-info-grid">
            <div class="modal-field-card">
              <span class="modal-field-label">CPF</span>
              <span class="modal-field-value font-monospace">{{ participanteInfo.cpf_formatado || participanteInfo.cpf }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">Data de Nascimento</span>
              <span class="modal-field-value">{{ formatarDataNascimento(participanteInfo.data_nascimento) || 'Não informada' }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">Telefone / WhatsApp</span>
              <span class="modal-field-value font-monospace">{{ formatarTelefone(participanteInfo.telefone) || 'Não informado' }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">E-mail</span>
              <span class="modal-field-value">{{ participanteInfo.email || 'Não informado' }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">Secretaria / Órgão</span>
              <span class="modal-field-value">{{ participanteInfo.secretaria?.nome || 'Geral' }}</span>
            </div>
            <div class="modal-field-card">
              <span class="modal-field-label">Setor / Lotação</span>
              <span class="modal-field-value">{{ participanteInfo.setor || 'Não informado' }}</span>
            </div>
          </div>
        </div>

        <!-- Ingresso e Lote -->
        <div class="modal-section">
          <h4 class="modal-section-heading font-outfit">
            <i class="bi bi-ticket-detailed-fill text-warning me-2"></i> Ingresso do Evento
          </h4>

          <div v-if="participanteInfo.ingresso">
            <div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
              <span class="badge-subtle-warning">{{ participanteInfo.ingresso.lote_nome }}</span>
              <span class="text-muted small">
                Resgatado em: {{ formatarData(participanteInfo.ingresso.data_resgate) }}
              </span>
            </div>
            <div class="ticket-token-display">
              <span class="token-title">Token Oficial:</span>
              <span class="token-value font-monospace">{{ participanteInfo.ingresso.qr_code_token }}</span>
            </div>
          </div>
          <div v-else class="text-muted small py-2">
            <i class="bi bi-exclamation-circle me-1"></i> Este participante ainda não possui um ingresso ativo vinculado.
          </div>
        </div>

        <!-- Presença no Evento e Portaria -->
        <div class="modal-section mb-0">
          <h4 class="modal-section-heading font-outfit">
            <i class="bi bi-shield-check text-success me-2"></i> Presença no Evento
          </h4>
          <div class="mb-3">
            <span class="status-badge" :class="participanteInfo.situacao_evento?.dentro ? 'bg-success' : 'bg-warning'">
              <i :class="participanteInfo.situacao_evento?.dentro ? 'bi bi-check-circle-fill me-1 text-success' : 'bi bi-geo-alt me-1 text-warning'"></i>
              <span>{{ participanteInfo.situacao_evento?.label }}</span>
            </span>
          </div>

          <div v-if="participanteInfo.logs_acesso && participanteInfo.logs_acesso.length > 0">
            <span class="text-muted small fw-bold d-block mb-2">Histórico de Portaria:</span>
            <div class="modal-timeline">
              <div
                v-for="log in participanteInfo.logs_acesso"
                :key="log.id"
                class="modal-timeline-item"
              >
                <span class="modal-timeline-badge" :class="log.tipo === 'entrada' ? 'modal-timeline-badge--in' : 'modal-timeline-badge--out'">
                  <i :class="log.tipo === 'entrada' ? 'bi bi-box-arrow-in-right me-1' : 'bi bi-box-arrow-right me-1'"></i>
                  {{ log.tipo.toUpperCase() }}
                </span>
                <span class="modal-timeline-badge modal-timeline-badge--operator ms-2" title="Operador responsável pelo registro">
                  <i class="bi bi-person-fill me-1"></i>
                  {{ log.operador_nome || 'Operador' }}
                </span>
                <span class="modal-timeline-time ms-auto">{{ log.data_hora }}</span>
              </div>
            </div>
          </div>
          <div v-else class="text-muted small py-1">
            <i class="bi bi-info-circle me-1"></i> Nenhuma movimentação de portaria registrada.
          </div>
        </div>
      </div>

      <template #footer>
        <div class="d-flex justify-content-between align-items-center w-100 gap-2">
          <button
            v-if="participanteInfo?.ingresso"
            type="button"
            class="btn btn-secondary flex-1"
            @click="abrirModalIngresso(participanteInfo); showModalInfo = false"
          >
            <i class="bi bi-qr-code me-1"></i> Ver Ingresso
          </button>
          <button
            type="button"
            class="btn btn-primary flex-1"
            @click="abrirModalEditar(participanteInfo); showModalInfo = false"
          >
            <i class="bi bi-pencil-square me-1"></i> Editar Dados
          </button>
          <button type="button" class="btn btn-secondary flex-1" @click="showModalInfo = false">
            Fechar
          </button>
        </div>
      </template>
    </Modal>

    <!-- MODAL 7: EDITAR PARTICIPANTE -->
    <Modal
      :show="showModalEditar"
      title="Editar Dados do Participante"
      icon="bi-pencil-square"
      maxWidth="620px"
      @close="fecharModalEditar"
    >
      <div v-if="participanteEditar">
        <div class="modal-hero-card mb-3">
          <div class="modal-hero-avatar" style="width: 52px; height: 52px; border-radius: 10px;">
            <img v-if="participanteEditar.foto_url" :src="participanteEditar.foto_url" alt="Foto do participante" />
            <div v-else class="modal-hero-avatar-fallback" style="font-size: 1.5rem;">
              <i class="bi bi-person-fill"></i>
            </div>
          </div>
          <div class="modal-hero-info">
            <h4 class="modal-hero-name font-outfit" style="font-size: 1.05rem;">{{ participanteEditar.nome }}</h4>
            <div class="d-flex align-items-center gap-2 flex-wrap">
              <span class="table-code-pill">{{ participanteEditar.cpf_formatado || participanteEditar.cpf }}</span>
              <span class="badge-subtle-primary">
                <i class="bi bi-briefcase-fill me-1"></i> {{ participanteEditar.vinculo || 'Servidor' }}
              </span>
            </div>
          </div>
        </div>

        <form @submit.prevent="salvarEdicaoParticipante">
          <div class="form-group mb-3">
            <label for="editar-participante-nome" class="form-label text-muted small mb-1">
              <i class="bi bi-person-fill me-1 text-cyan"></i> Nome Completo
            </label>
            <input
              id="editar-participante-nome"
              v-model="formEditar.nome"
              type="text"
              class="form-control"
              autocomplete="name"
              placeholder="Digite o nome completo do participante"
              required
            />
          </div>

          <div class="form-group mb-3">
            <label for="editar-participante-vinculo" class="form-label text-muted small mb-1">
              <i class="bi bi-briefcase-fill me-1 text-cyan"></i> Vínculo
            </label>
            <select id="editar-participante-vinculo" v-model="formEditar.vinculo" class="form-select">
              <option value="">-- Não informado --</option>
              <option
                v-if="formEditar.vinculo && !vinculosDisponiveis.includes(formEditar.vinculo)"
                :value="formEditar.vinculo"
              >{{ formEditar.vinculo }}</option>
              <option v-for="vinculo in vinculosDisponiveis" :key="vinculo" :value="vinculo">
                {{ vinculo }}
              </option>
            </select>
          </div>

          <div class="form-group mb-3">
            <label class="form-label text-muted small mb-1">
              <i class="bi bi-building me-1 text-warning"></i> Secretaria / Órgão
            </label>
            <select v-model="formEditar.secretaria_id" class="form-select">
              <option :value="null">-- Sem Secretaria Vinculada / Geral --</option>
              <option v-for="sec in secretariasServer" :key="sec.id" :value="sec.id">
                {{ sec.nome }}
              </option>
            </select>
          </div>

          <div class="form-group mb-3">
            <label class="form-label text-muted small mb-1">
              <i class="bi bi-geo-alt me-1 text-danger"></i> Setor / Lotação
            </label>
            <input
              v-model="formEditar.setor"
              type="text"
              class="form-control"
              placeholder="Ex: Recursos Humanos, Almoxarifado, Escola Municipal..."
              maxlength="150"
            />
          </div>

          <div class="row g-3 mb-3">
            <div class="col-12 col-md-6">
              <div class="form-group">
                <label class="form-label text-muted small mb-1">
                  <i class="bi bi-telephone me-1 text-success"></i> Telefone / Celular
                </label>
                <input
                  v-model="formEditar.telefone"
                  type="tel"
                  class="form-control font-monospace"
                  placeholder="(00) 00000-0000"
                  maxlength="15"
                  @input="onTelefoneInput"
                />
              </div>
            </div>

            <div class="col-12 col-md-6">
              <div class="form-group">
                <label class="form-label text-muted small mb-1">
                  <i class="bi bi-calendar-event me-1 text-warning"></i> Data de Nascimento
                </label>
                <input
                  v-model="formEditar.data_nascimento"
                  type="date"
                  class="form-control"
                  min="1900-01-01"
                  :max="maxDataNascimento"
                />
              </div>
            </div>
          </div>

          <div class="form-group mb-3">
            <label class="form-label text-muted small mb-1">
              <i class="bi bi-envelope-at me-1 text-cyan"></i> Endereço de E-mail
            </label>
            <input
              v-model="formEditar.email"
              type="email"
              class="form-control"
              placeholder="servidor@exemplo.com"
              maxlength="120"
            />
          </div>
        </form>
      </div>

      <template #footer>
        <div class="d-flex justify-content-end align-items-center w-100 gap-2">
          <button
            type="button"
            class="btn btn-secondary"
            :disabled="salvandoEditar"
            @click="fecharModalEditar"
          >
            Cancelar
          </button>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="salvandoEditar"
            @click="salvarEdicaoParticipante"
          >
            <span v-if="salvandoEditar" class="spinner-border spinner-border-sm me-2" role="status"></span>
            <i v-else class="bi bi-check-circle-fill me-2"></i>
            {{ salvandoEditar ? 'Salvando...' : 'Salvar Alterações' }}
          </button>
        </div>
      </template>
    </Modal>

    <!-- MODAL 8: FOTO ZOOM -->
    <Modal :show="showModalExportacao" title="Exportar participantes" icon="bi-file-earmark-excel" max-width="680px" :dismissible="!exportandoPlanilha" @close="!exportandoPlanilha && (showModalExportacao = false)">
      <div class="modal-hero-card">
        <div class="modal-hero-info">
          <strong>Cadastro completo e situação no evento</strong>
          <p class="mb-0 small text-muted">Todos os participantes não excluídos, inclusive inativos, com uma linha por pessoa. Usuários da equipe ficam de fora. Os filtros e a paginação da tela não limitam a exportação.</p>
        </div>
      </div>
      <div class="modal-section">
        <div class="modal-info-grid modal-info-grid--single">
          <div class="modal-field-card">
            <label for="exportacao-modo" class="form-label">Organização dos arquivos</label>
            <select id="exportacao-modo" v-model="modoExportacao" class="form-select" :disabled="exportandoPlanilha">
              <option value="unico">1 arquivo Excel, 1 aba com todos</option>
              <option value="abas">1 arquivo Excel, 1 aba por grupo</option>
              <option value="arquivos">Vários arquivos Excel, 1 aba cada (ZIP)</option>
            </select>
          </div>
          <div v-if="modoExportacao !== 'unico'" class="modal-field-card">
            <label for="exportacao-agrupamento" class="form-label">Separar por</label>
            <select id="exportacao-agrupamento" v-model="agrupamentoExportacao" class="form-select" :disabled="exportandoPlanilha">
              <option value="secretaria">Secretaria</option>
              <option value="lote">Lote</option>
            </select>
          </div>
        </div>
        <p class="small text-muted mt-3 mb-0">Inclui CPF, contato, vínculo, secretaria, homologação, comunicação registrada, ingresso, cancelamento e presença. Datas e horários no fuso de São Paulo.</p>
        <p v-if="modoExportacao !== 'unico' && agrupamentoExportacao === 'lote'" class="small text-muted mt-2 mb-0">O lote vem do ingresso ativo ou, sem ele, da última solicitação de validação ou do histórico do ingresso. Participantes sem vínculo com um lote ficam em “Sem lote”.</p>
        <p v-if="modoExportacao !== 'unico' && agrupamentoExportacao === 'secretaria'" class="small text-muted mt-2 mb-0">Cada participante fica na secretaria do seu cadastro. Cadastros sem secretaria ficam em “Sem secretaria”.</p>
      </div>
      <div v-if="erroExportacao" class="modal-alert-card modal-alert-card--danger" role="alert">{{ erroExportacao }}</div>
      <template #footer>
        <div class="modal-footer-grid">
          <button type="button" class="btn-secondary" :disabled="exportandoPlanilha" @click="showModalExportacao = false">Fechar</button>
          <button type="button" class="btn-primary" :disabled="exportandoPlanilha" @click="exportarPlanilhaParticipantes">{{ exportandoPlanilha ? 'Gerando exportação...' : 'Baixar exportação' }}</button>
        </div>
      </template>
    </Modal>

    <Modal :show="showModalFoto" :title="fotoZoomNome" icon="bi-image" @close="showModalFoto = false">
      <div class="text-center p-3">
        <img :src="fotoZoomUrl" alt="Foto do Participante" class="modal-photo-zoom" />
      </div>
      <template #footer>
        <button type="button" class="btn btn-secondary w-100" @click="showModalFoto = false">
          Fechar
        </button>
      </template>
    </Modal>

  </div>
</template>

<style scoped>
/* ==========================================================================
   ESTILOS ESCOPADOS ESTRITAMENTE ESPECÍFICOS DESTA TELA
   Todo o restante (tabela, botões, modais, cabeçalhos, paginação) é 100% global
   ========================================================================== */
.spin-icon {
  animation: spin 1s infinite linear;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.status-guide-card {
  padding: 14px 16px;
  border-radius: var(--radius-md, 12px);
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid var(--border-glass);
}

.status-guide-text {
  font-size: 0.84rem;
  color: var(--text-secondary);
  line-height: 1.55;
  margin-top: 6px;
}

.ticket-token-display {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-surface-elevated, rgba(6, 9, 19, 0.9));
  border: 1px dashed rgba(6, 182, 212, 0.4);
  border-radius: var(--radius-sm, 6px);
  padding: 10px 14px;
}

.token-title {
  font-size: 0.75rem;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--text-muted);
}

.token-value {
  font-size: 1.05rem;
  font-weight: 800;
  color: var(--primary-accent);
}
</style>
