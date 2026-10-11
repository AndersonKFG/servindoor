<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
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

async function dispararComunicacaoIndividual(solic) {
  if (!solic || !solic.id) return
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
      toast.success(data.mensagem || 'Comunicação enviada com sucesso!')
      solic.comunicado = true
      solic.comunicado_em = data.comunicado_em || 'Agora'
      if (kpis.value.total_comunicacao_pendente > 0) {
        kpis.value.total_comunicacao_pendente -= 1
      }
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
  try {
    const res = await fetch('/api/admin/validacoes/comunicar-em-lote?tipo_filtro=todos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      toast.success(data.mensagem || 'Comunicações disparadas com sucesso!')
      await carregarValidacoes()
    } else {
      toast.error(data.detail || 'Erro ao processar envio em lote.')
    }
  } catch (err) {
    toast.error('Erro de conexão com o servidor.')
  } finally {
    processandoComunicacaoLote.value = false
  }
}

let pollTimer = null

async function carregarValidacoes(silent = false) {
  try {
    if (!silent) loading.value = true
    const res = await fetch('/api/admin/validacoes?status_filtro=todos')
    if (res.status === 401 || res.status === 403) {
      router.push('/login')
      return
    }
    const data = await res.json()
    if (data.sucesso) {
      solicitacoes.value = data.solicitacoes || []
      kpis.value = data.kpis || {
        total_pendentes: 0,
        total_aprovados: 0,
        total_rejeitados: 0,
        total_geral: 0,
        total_confirmados_api: 0,
        total_comunicacao_pendente: 0
      }

      const secMap = new Map()
      solicitacoes.value.forEach(s => {
        if (s.secretaria_id && s.secretaria_nome) {
          secMap.set(s.secretaria_id, s.secretaria_nome)
        }
      })
      secretariasDisponiveis.value = Array.from(secMap.entries()).map(([id, nome]) => ({ id, nome }))
    }
  } catch (err) {
    if (!silent) toast.error('Erro ao carregar validações.')
  } finally {
    if (!silent) loading.value = false
  }
}

onMounted(async () => {
  await carregarValidacoes()
  pollTimer = setInterval(() => {
    carregarValidacoes(true)
  }, 10000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

const solicitacoesFiltradas = computed(() => {
  return solicitacoes.value.filter(s => {
    if (filtroStatus.value && filtroStatus.value !== 'todos') {
      if (filtroStatus.value === 'confirmados_api') {
        if (!s.identificado_api || s.status !== 'pendente_analise') return false
      } else if (s.status !== filtroStatus.value) {
        return false
      }
    }
    if (filtroSecretaria.value) {
      if (String(s.secretaria_id) !== String(filtroSecretaria.value)) return false
    }
    if (busca.value.trim()) {
      const b = busca.value.trim().toLowerCase()
      const nome = s.usuario?.nome?.toLowerCase() || ''
      const cpf = s.usuario?.cpf || ''
      const prot = `val-${String(s.id).padStart(6, '0')}`.toLowerCase()
      const sec = s.secretaria_nome?.toLowerCase() || ''
      if (!nome.includes(b) && !cpf.includes(b) && !prot.includes(b) && !sec.includes(b)) {
        return false
      }
    }
    return true
  })
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
          :disabled="processandoComunicacaoLote || loading"
          @click="dispararComunicacoesLote()"
        >
          <i class="bi bi-send-check-fill me-1" :class="{ 'spin-anim': processandoComunicacaoLote }"></i>
          <span>Disparar E-mails ({{ kpis.total_comunicacao_pendente }})</span>
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
        title="Rejeitados / Vagas Devolvidas"
        :value="kpis.total_rejeitados"
        subtitle="Vagas liberadas para outros servidores"
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
          <span class="table-badge-count">{{ solicitacoesFiltradas.length }}</span>
        </h2>
      </div>

      <div v-if="loading && !solicitacoes.length" class="table-loading-state">
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
                <span v-if="s.comunicado" class="badge badge-secondary" :title="'Enviado em ' + (s.comunicado_em || '')">
                  <i class="bi bi-check-all me-1 text-emerald"></i> Comunicado
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
                <span v-if="s.identificado_api" class="badge badge-cyan" title="Vínculo confirmado em tempo real via API da Escola de Governo">
                  <i class="bi bi-patch-check-fill me-1 text-cyan"></i> Servidor (API)
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
                :disabled="enviandoComunicacaoId === s.id"
                title="Disparar e-mail ao servidor agora"
                @click="dispararComunicacaoIndividual(s)"
              >
                <i class="bi bi-send-fill" :class="{ 'spin-anim': enviandoComunicacaoId === s.id }"></i>
              </button>
            </div>
          </div>

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
              <p class="mb-0 small text-light">Este CPF foi confirmado em tempo real junto à Escola de Governo. O servidor é elegível.</p>
            </div>
          </div>
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
                <strong class="text-emerald d-block">Comunicação Realizada</strong>
                <p class="mb-0 small text-muted">A notificação oficial foi enviada ao e-mail do servidor em {{ solicitacaoSelecionada.comunicado_em }}.</p>
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

          <template v-if="solicitacaoSelecionada?.status === 'pendente_analise'">
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
              :disabled="enviandoComunicacaoId === solicitacaoSelecionada.id"
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
          Esta ação liberará a vaga para o lote e enviará um e-mail formal ao solicitante.
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
