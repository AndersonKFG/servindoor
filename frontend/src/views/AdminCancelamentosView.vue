<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import Modal from '../components/Modal.vue'
import KpiCard from '../components/KpiCard.vue'
import { useAuth } from '../composables/useAuth'

const { toast } = useToast()
const { confirmModal } = useConfirm()

const router = useRouter()
const { isAdmin } = useAuth()

const loading = ref(true)
const solicitacoes = ref([])
const kpis = ref({
  total_pendentes: 0,
  total_aprovados: 0,
  total_rejeitados: 0,
  total_geral: 0
})

// Filtros
const busca = ref('')
const filtroStatus = ref('pendente_analise') // 'pendente_analise', 'aprovado', 'rejeitado', 'todos'

// Modal de Comparação Facial
const showModalComparacao = ref(false)
const solicitacaoSelecionada = ref(null)
const processandoAprovacao = ref(false)
const processandoRejeicao = ref(false)

// Modal de Rejeição (Justificativa)
const showModalRejeitar = ref(false)
const motivoRejeicao = ref('A foto ao vivo enviada não conferiu com a foto de identificação cadastrada.')
const outroMotivoTexto = ref('')

// Modal de Zoom de Foto
const showModalZoom = ref(false)
const zoomImgUrl = ref('')
const zoomImgTitulo = ref('')

let pollTimer = null

async function carregarCancelamentos(silent = false) {
  try {
    if (!silent) loading.value = true
    const res = await fetch('/api/admin/cancelamentos')
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
        total_geral: 0
      }
    }
  } catch (err) {
    if (!silent) toast.error('Erro ao carregar solicitações de cancelamento.')
  } finally {
    if (!silent) loading.value = false
  }
}

onMounted(async () => {
  await carregarCancelamentos()
  pollTimer = setInterval(() => {
    carregarCancelamentos(true)
  }, 10000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

// Lista filtrada
const solicitacoesFiltradas = computed(() => {
  return solicitacoes.value.filter(s => {
    // Filtro por status
    if (filtroStatus.value !== 'todos') {
      if (s.status !== filtroStatus.value) return false
    }

    // Filtro por texto de busca
    if (busca.value.trim()) {
      const b = busca.value.trim().toLowerCase()
      const nomeMatch = s.usuario?.nome?.toLowerCase().includes(b)
      const cpfMatch = s.usuario?.cpf?.includes(b) || s.usuario?.cpf_formatado?.includes(b)
      const protMatch = s.protocolo?.toLowerCase().includes(b)
      const secMatch = s.usuario?.secretaria_nome?.toLowerCase().includes(b)
      if (!nomeMatch && !cpfMatch && !protMatch && !secMatch) return false
    }

    return true
  })
})

function abrirComparacao(item) {
  solicitacaoSelecionada.value = item
  showModalComparacao.value = true
}

function abrirZoom(url, titulo) {
  zoomImgUrl.value = url
  zoomImgTitulo.value = titulo
  showModalZoom.value = true
}

// APROVAR CANCELAMENTO
async function handleAprovarCancelamento() {
  if (!solicitacaoSelecionada.value) return
  const id = solicitacaoSelecionada.value.id

  const confirmado = await confirmModal({
    title: 'Aprovar Cancelamento',
    message: 'Deseja realmente APROVAR o cancelamento deste ingresso?\n\nO ingresso será anulado automaticamente, continuará contabilizado na ocupação do lote e o servidor receberá um e-mail de confirmação.',
    confirmText: 'Aprovar Cancelamento',
    variant: 'danger'
  })
  if (!confirmado) return

  processandoAprovacao.value = true
  try {
    const res = await fetch(`/api/admin/cancelamentos/${id}/aprovar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    const data = await res.json()
    if (!res.ok) {
      toast.error(data.detail || 'Erro ao aprovar cancelamento.')
      return
    }

    toast.success('Cancelamento aprovado com sucesso!')
    showModalComparacao.value = false
    solicitacaoSelecionada.value = null
    await carregarCancelamentos(true)
  } catch (err) {
    toast.error('Erro de conexão ao aprovar cancelamento.')
  } finally {
    processandoAprovacao.value = false
  }
}

// REJEITAR CANCELAMENTO
function iniciarRejeicao() {
  outroMotivoTexto.value = ''
  motivoRejeicao.value = 'A foto ao vivo enviada não conferiu com a foto de identificação cadastrada.'
  showModalRejeitar.value = true
}

async function handleConfirmarRejeicao() {
  if (!solicitacaoSelecionada.value) return
  const id = solicitacaoSelecionada.value.id

  let motivoFinal = motivoRejeicao.value
  if (motivoFinal === 'outro') {
    motivoFinal = outroMotivoTexto.value.trim()
    if (!motivoFinal) {
      toast.warning('Por favor, descreva o motivo da rejeição.')
      return
    }
  }

  processandoRejeicao.value = true
  try {
    const res = await fetch(`/api/admin/cancelamentos/${id}/rejeitar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ motivo: motivoFinal })
    })
    const data = await res.json()
    if (!res.ok) {
      toast.error(data.detail || 'Erro ao rejeitar cancelamento.')
      return
    }

    showModalRejeitar.value = false
    toast.success('Solicitação rejeitada com sucesso.')
    showModalComparacao.value = false
    solicitacaoSelecionada.value = null
    await carregarCancelamentos(true)
  } catch (err) {
    toast.error('Erro de conexão ao rejeitar cancelamento.')
  } finally {
    processandoRejeicao.value = false
  }
}

function obterIniciais(nome) {
  if (!nome) return '?'
  const partes = nome.trim().split(/\s+/).filter(Boolean)
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase()
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase()
}

function getStatusBadge(status) {
  switch (status) {
    case 'pendente_analise':
      return {
        label: 'Pendente de Análise',
        class: 'badge-warning',
        pillClass: 'status-pill status-pill--em_validacao',
        slug: 'em_validacao',
        icon: 'bi-hourglass-split'
      }
    case 'aprovado':
      return {
        label: 'Cancelamento Aprovado',
        class: 'badge-emerald',
        pillClass: 'status-pill status-pill--cancelado',
        slug: 'cancelado',
        icon: 'bi-check-circle-fill'
      }
    case 'rejeitado':
      return {
        label: 'Solicitação Rejeitada',
        class: 'badge-danger',
        pillClass: 'status-pill status-pill--neutral',
        slug: 'neutral',
        icon: 'bi-x-circle-fill'
      }
    default:
      return {
        label: status,
        class: 'badge-secondary',
        pillClass: 'status-pill status-pill--neutral',
        slug: 'neutral',
        icon: 'bi-info-circle'
      }
  }
}
</script>

<template>
  <div class="admin-page">
    <div class="app-container">

    <!-- Topo: Título e Ação de Atualizar -->
    <div class="admin-header-row mb-4">
      <div>
        <span class="admin-eyebrow">
          <i class="bi bi-shield-lock-fill me-1 text-cyan"></i> PAINEL ADMINISTRATIVO
        </span>
        <h1 class="page-title font-quattrocento">Central de Cancelamentos</h1>
        <p class="page-subtitle">
          Conferência facial ao vivo de solicitações de cancelamento de ingressos
        </p>
      </div>

      <div class="admin-header-actions">
        <button
          type="button"
          class="btn-primary"
          :disabled="loading"
          @click="carregarCancelamentos"
        >
          <i class="bi bi-arrow-clockwise" :class="{ 'spin-icon': loading }"></i>
          <span>Atualizar</span>
        </button>
      </div>
    </div>

    <!-- KPI CARDS CANÔNICOS -->
    <div class="kpi-grid mb-4">
      <KpiCard
        title="Pendentes de Análise"
        :value="kpis.total_pendentes"
        icon="bi bi-person-bounding-box"
        variant="warning"
        :badge-pulse="kpis.total_pendentes > 0"
        :clickable="true"
        :active="filtroStatus === 'pendente_analise'"
        @click="filtroStatus = 'pendente_analise'"
      />

      <KpiCard
        title="Cancelados (Aprovados)"
        :value="kpis.total_aprovados"
        icon="bi bi-check-circle-fill"
        variant="emerald"
        :clickable="true"
        :active="filtroStatus === 'aprovado'"
        @click="filtroStatus = 'aprovado'"
      />

      <KpiCard
        title="Rejeitados"
        :value="kpis.total_rejeitados"
        icon="bi bi-x-circle-fill"
        variant="danger"
        :clickable="true"
        :active="filtroStatus === 'rejeitado'"
        @click="filtroStatus = 'rejeitado'"
      />

      <KpiCard
        title="Total de Solicitações"
        :value="kpis.total_geral"
        icon="bi bi-ticket-perforated"
        variant="cyan"
        :clickable="true"
        :active="filtroStatus === 'todos'"
        @click="filtroStatus = 'todos'"
      />
    </div>

    <!-- Barra de Filtros e Busca -->
    <div class="filter-card mb-4">
      <div class="d-flex flex-wrap align-items-center justify-content-between gap-3">
        <div class="search-box" style="max-width: 420px; flex: 1;">
          <i class="bi bi-search search-icon"></i>
          <input
            type="text"
            class="form-control"
            placeholder="Buscar por nome, CPF ou protocolo..."
            v-model="busca"
          />
          <button v-if="busca" type="button" class="btn-clear-search" @click="busca = ''">
            <i class="bi bi-x"></i>
          </button>
        </div>

        <!-- Abas de Status -->
        <div class="status-tabs">
          <button
            type="button"
            class="tab-btn"
            :class="{ 'is-active': filtroStatus === 'pendente_analise' }"
            @click="filtroStatus = 'pendente_analise'"
          >
            Pendentes ({{ kpis.total_pendentes }})
          </button>
          <button
            type="button"
            class="tab-btn"
            :class="{ 'is-active': filtroStatus === 'aprovado' }"
            @click="filtroStatus = 'aprovado'"
          >
            Aprovados ({{ kpis.total_aprovados }})
          </button>
          <button
            type="button"
            class="tab-btn"
            :class="{ 'is-active': filtroStatus === 'rejeitado' }"
            @click="filtroStatus = 'rejeitado'"
          >
            Rejeitados ({{ kpis.total_rejeitados }})
          </button>
          <button
            type="button"
            class="tab-btn"
            :class="{ 'is-active': filtroStatus === 'todos' }"
            @click="filtroStatus = 'todos'"
          >
            Todos ({{ kpis.total_geral }})
          </button>
        </div>
      </div>
    </div>

    <!-- Tabela / Lista de Solicitações -->
    <div class="table-card">
      
      <div v-if="loading && solicitacoes.length === 0" class="table-loading-state">
        <span class="spinner-border text-cyan"></span>
        <p class="mt-2">Carregando solicitações...</p>
      </div>

      <div v-else-if="solicitacoesFiltradas.length === 0" class="table-empty-state">
        <i class="bi bi-inbox fs-1 text-muted"></i>
        <h3 class="mt-2 text-white">Nenhuma solicitação encontrada</h3>
        <p class="text-muted">
          {{ filtroStatus === 'pendente_analise' ? 'Não há solicitações pendentes de análise no momento.' : 'Nenhum registro corresponde aos filtros selecionados.' }}
        </p>
      </div>

            <!-- GRID DE CARDS CANÔNICO DE CANCELAMENTOS -->
      <div v-else class="entity-cards-grid">
        <div
          v-for="item in solicitacoesFiltradas"
          :key="item.id"
          :class="['entity-card', 'entity-card--' + getStatusBadge(item.status).slug]"
        >
          <!-- Topo do Card: Protocolo, Data e Status da Solicitação -->
          <div class="entity-card-top-bar">
            <div>
              <strong class="table-code-pill font-monospace d-block">{{ item.protocolo }}</strong>
              <span class="text-muted d-block mt-1" style="font-size: 0.78rem;">
                <i class="bi bi-calendar3 me-1"></i>{{ item.criado_em }}
              </span>
            </div>

            <span :class="getStatusBadge(item.status).pillClass">
              <i :class="'bi ' + getStatusBadge(item.status).icon"></i>
              <span>{{ getStatusBadge(item.status).label }}</span>
            </span>
          </div>

          <!-- Identidade do Servidor: Foto Original/Iniciais, Nome, CPF e Secretaria -->
          <div class="entity-card-identity">
            <div
              class="entity-card-avatar"
              :title="item.usuario?.foto_original_url ? 'Clique para ver detalhes e fotos' : (item.usuario?.nome || 'Servidor')"
              @click="abrirComparacao(item)"
            >
              <img
                v-if="item.usuario?.foto_original_url"
                :src="item.usuario.foto_original_url"
                alt="Foto do Cadastro"
                class="entity-card-avatar-img"
                @error="(e) => { e.target.style.display = 'none'; if (e.target.nextElementSibling) e.target.nextElementSibling.style.display = 'flex'; }"
              />
              <div
                class="entity-card-avatar-fallback"
                :style="{ display: item.usuario?.foto_original_url ? 'none' : 'flex' }"
              >
                <span>{{ obterIniciais(item.usuario?.nome) }}</span>
              </div>
            </div>

            <div class="entity-card-info">
              <h3 class="entity-card-title">{{ item.usuario?.nome }}</h3>
              <div class="entity-card-sub">
                <span class="table-code-pill font-monospace">{{ item.usuario?.cpf_formatado }}</span>
                <span class="table-tag" :title="item.usuario?.secretaria_nome">{{ item.usuario?.secretaria_nome }}</span>
              </div>
              <div v-if="item.usuario?.setor" class="meta-sub" :title="item.usuario?.setor">
                <i class="bi bi-geo-alt me-1"></i>{{ item.usuario?.setor }}
              </div>
            </div>
          </div>

          <!-- Metadados do Ingresso e Comparativo Facial -->
          <div class="entity-meta-grid">
            <div class="entity-meta-item">
              <span class="meta-label">Lote Vinculado</span>
              <span class="meta-value text-amber">{{ item.ingresso?.lote_nome }}</span>
              <span class="meta-sub">
                <i class="bi bi-ticket-perforated me-1"></i>Ingresso Vinculado
              </span>
            </div>

            <div class="entity-meta-item">
              <span class="meta-label">Situação do Chamado</span>
              <span class="meta-value" :class="item.status === 'pendente_analise' ? 'text-warning' : 'text-muted'">
                {{ item.status === 'pendente_analise' ? 'Aguardando Homologação' : 'Finalizado' }}
              </span>
              <span class="meta-sub" v-if="item.status === 'pendente_analise'">
                Ação do Administrador
              </span>
              <span class="meta-sub" v-else>
                Encerrado
              </span>
            </div>

            <!-- Miniatura das Fotos Lado a Lado (Full Width) -->
            <div class="entity-meta-item full-width">
              <span class="meta-label mb-1">Fotos Comparativas (Clique para ampliar)</span>
              <div class="thumb-compare-row" @click="abrirComparacao(item)" title="Clique para comparar em tamanho ampliado">
                <!-- Foto Original -->
                <div class="thumb-box" title="Foto do Cadastro">
                  <img
                    v-if="item.usuario?.foto_original_url"
                    :src="item.usuario.foto_original_url"
                    alt="Original"
                    class="thumb-img"
                  />
                  <div v-else class="thumb-placeholder">
                    <i class="bi bi-person-fill"></i>
                  </div>
                  <span class="thumb-label">Original</span>
                </div>

                <i class="bi bi-arrow-left-right text-muted" style="font-size: 0.8rem;"></i>

                <!-- Foto ao Vivo -->
                <div class="thumb-box thumb-box-live" title="Foto ao Vivo">
                  <img
                    v-if="item.foto_ao_vivo_url"
                    :src="item.foto_ao_vivo_url"
                    alt="Ao Vivo"
                    class="thumb-img"
                  />
                  <div v-else class="thumb-placeholder">
                    <i class="bi bi-camera-fill"></i>
                  </div>
                  <span class="thumb-label label-live">Ao Vivo</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Rodapé do Card: Ação Operacional -->
          <div class="entity-card-footer justify-end">
            <button
              v-if="item.status === 'pendente_analise'"
              type="button"
              class="btn-card-primary font-outfit"
              @click="abrirComparacao(item)"
            >
              <i class="bi bi-person-bounding-box"></i> Analisar & Homologar
            </button>
            <button
              v-else
              type="button"
              class="btn-card-secondary font-outfit"
              @click="abrirComparacao(item)"
            >
              <i class="bi bi-eye"></i> Ver Detalhes
            </button>
          </div>

        </div>
      </div>

    </div>

    <!-- ==================================================================== -->
    <!-- MODAL DE COMPARAÇÃO FACIAL LADO A LADO                               -->
    <!-- ==================================================================== -->
    <Modal
      :show="showModalComparacao"
      :title="'Conferência Facial • ' + (solicitacaoSelecionada?.protocolo || '')"
      icon="bi-person-bounding-box"
      icon-color="text-cyan"
      :max-width="'820px'"
      @close="showModalComparacao = false"
    >
      <div v-if="solicitacaoSelecionada" class="modal-face-body">

        <!-- Banner com Dados do Servidor -->
        <div class="servidor-summary-card">
          <div class="summary-col">
            <span class="summary-label">Servidor</span>
            <strong class="summary-val">{{ solicitacaoSelecionada.usuario?.nome }}</strong>
            <span class="summary-sub">{{ solicitacaoSelecionada.usuario?.cpf_formatado }}</span>
          </div>

          <div class="summary-col">
            <span class="summary-label">Secretaria / Setor</span>
            <strong class="summary-val">{{ solicitacaoSelecionada.usuario?.secretaria_nome }}</strong>
            <span class="summary-sub">{{ solicitacaoSelecionada.usuario?.setor || 'Sem setor informado' }}</span>
          </div>

          <div class="summary-col">
            <span class="summary-label">Ingresso / Lote</span>
            <strong class="summary-val text-cyan">{{ solicitacaoSelecionada.ingresso?.lote_nome }}</strong>
            <span class="summary-sub">Resgatado em {{ solicitacaoSelecionada.ingresso?.data_resgate }}</span>
          </div>

          <div class="summary-col">
            <span class="summary-label">Status Atual</span>
            <span class="badge mt-1" :class="getStatusBadge(solicitacaoSelecionada.status).class">
              {{ getStatusBadge(solicitacaoSelecionada.status).label }}
            </span>
          </div>
        </div>

        <!-- QUADRO COMPARATIVO DE FOTOS LADO A LADO -->
        <div class="side-by-side-grid">
          
          <!-- Lado Esquerdo: Foto de Cadastro Oficial -->
          <div class="face-card-box">
            <div class="face-card-header">
              <span class="face-tag-badge badge-primary">
                <i class="bi bi-person-vcard-fill me-1"></i> FOTO DO CADASTRO (OFICIAL)
              </span>
              <button
                v-if="solicitacaoSelecionada.usuario?.foto_original_url"
                type="button"
                class="btn-zoom-corner"
                title="Ampliar Foto Oficial"
                @click="abrirZoom(solicitacaoSelecionada.usuario.foto_original_url, 'Foto do Cadastro Oficial')"
              >
                <i class="bi bi-arrows-fullscreen"></i>
              </button>
            </div>

            <div class="face-image-viewport">
              <img
                v-if="solicitacaoSelecionada.usuario?.foto_original_url"
                :src="solicitacaoSelecionada.usuario.foto_original_url"
                alt="Foto do Cadastro"
                class="face-img"
              />
              <div v-else class="face-placeholder">
                <i class="bi bi-person-fill"></i>
                <span>Foto de cadastro não disponível</span>
              </div>
            </div>

            <span class="face-footer-desc">
              Utilizada no resgate original do ingresso
            </span>
          </div>

          <!-- Lado Direito: Foto ao Vivo Capturada pela Câmera -->
          <div class="face-card-box face-card-live">
            <div class="face-card-header">
              <span class="face-tag-badge badge-warning">
                <i class="bi bi-camera-fill me-1"></i> FOTO AO VIVO (SOLICITAÇÃO)
              </span>
              <button
                v-if="solicitacaoSelecionada.foto_ao_vivo_url"
                type="button"
                class="btn-zoom-corner"
                title="Ampliar Foto ao Vivo"
                @click="abrirZoom(solicitacaoSelecionada.foto_ao_vivo_url, 'Foto ao Vivo Capturada pela Câmera')"
              >
                <i class="bi bi-arrows-fullscreen"></i>
              </button>
            </div>

            <div class="face-image-viewport">
              <img
                v-if="solicitacaoSelecionada.foto_ao_vivo_url"
                :src="solicitacaoSelecionada.foto_ao_vivo_url"
                alt="Foto ao Vivo"
                class="face-img"
              />
              <div v-else class="face-placeholder">
                <i class="bi bi-camera-video-off"></i>
                <span>Foto ao vivo não encontrada</span>
              </div>
            </div>

            <span class="face-footer-desc">
              Capturada via webcam em {{ solicitacaoSelecionada.criado_em }}
            </span>
          </div>

        </div>

        <!-- Se já tiver sido analisado -->
        <div v-if="solicitacaoSelecionada.status !== 'pendente_analise'" class="analysis-result-box">
          <div class="analysis-info-row">
            <i class="bi bi-info-circle-fill text-cyan me-2"></i>
            <div>
              <strong>Processado por:</strong> {{ solicitacaoSelecionada.analisado_por_nome || 'Administrador' }}
              <span class="text-muted ms-2" style="font-size: 0.78rem;">em {{ solicitacaoSelecionada.analisado_em }}</span>
            </div>
          </div>
          <div v-if="solicitacaoSelecionada.motivo_rejeicao" class="motivo-rejeicao-text">
            <strong>Motivo informado:</strong> {{ solicitacaoSelecionada.motivo_rejeicao }}
          </div>
        </div>

      </div>

      <template #footer>
        <div class="d-flex align-items-center justify-content-end gap-2 w-100">
          
          <button
            type="button"
            class="btn-secondary"
            @click="showModalComparacao = false"
          >
            Fechar
          </button>

          <!-- Se estiver pendente, exibe botões de Decisão -->
          <template v-if="solicitacaoSelecionada?.status === 'pendente_analise'">
            <button
              type="button"
              class="btn-danger"
              :disabled="processandoAprovacao || processandoRejeicao"
              @click="iniciarRejeicao"
            >
              <i class="bi bi-x-circle me-1"></i> Rejeitar
            </button>

            <button
              type="button"
              class="btn-primary"
              :disabled="processandoAprovacao || processandoRejeicao"
              @click="handleAprovarCancelamento"
            >
              <span v-if="processandoAprovacao" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-check2-circle me-1"></i>
              <span>Aprovar & Cancelar Ingresso</span>
            </button>
          </template>

        </div>
      </template>
    </Modal>

    <!-- ==================================================================== -->
    <!-- MODAL DE JUSTIFICATIVA DE REJEIÇÃO                                    -->
    <!-- ==================================================================== -->
    <Modal
      :show="showModalRejeitar"
      title="Rejeitar Solicitação de Cancelamento"
      icon="bi-exclamation-triangle-fill"
      icon-color="text-danger"
      :max-width="'520px'"
      @close="showModalRejeitar = false"
    >
      <div class="modal-rejeitar-body">
        <p class="text-muted mb-3" style="font-size: 0.88rem; line-height: 1.5;">
          Ao rejeitar, <strong>o ingresso do servidor permanecerá ativo</strong> e ele receberá um e-mail com a justificativa selecionada abaixo:
        </p>

        <div class="form-group mb-3">
          <label class="form-label">Selecione o motivo da rejeição:</label>
          <div class="radio-options">
            <label class="radio-label">
              <input type="radio" value="A foto ao vivo enviada não conferiu com a foto de identificação cadastrada." v-model="motivoRejeicao" />
              <span>A foto ao vivo não confere com o titular cadastrado</span>
            </label>
            <label class="radio-label">
              <input type="radio" value="A foto ao vivo está escura, desfocada ou o rosto não pôde ser claramente identificado." v-model="motivoRejeicao" />
              <span>Foto escura, ilegível ou rosto não identificado</span>
            </label>
            <label class="radio-label">
              <input type="radio" value="A foto enviada não se trata de uma captura ao vivo em frente à câmera." v-model="motivoRejeicao" />
              <span>A foto não aparenta ser uma captura ao vivo</span>
            </label>
            <label class="radio-label">
              <input type="radio" value="outro" v-model="motivoRejeicao" />
              <span>Outro motivo (especificar)</span>
            </label>
          </div>
        </div>

        <div v-if="motivoRejeicao === 'outro'" class="form-group">
          <label class="form-label">Descreva o motivo detalhado:</label>
          <textarea
            class="form-control"
            rows="3"
            placeholder="Informe o motivo da não aprovação..."
            v-model="outroMotivoTexto"
          ></textarea>
        </div>
      </div>

      <template #footer>
        <div class="d-flex align-items-center justify-content-end gap-2 w-100">
          <button type="button" class="btn-secondary" @click="showModalRejeitar = false">
            Cancelar
          </button>
          <button
            type="button"
            class="btn-danger"
            :disabled="processandoRejeicao"
            @click="handleConfirmarRejeicao"
          >
            <span v-if="processandoRejeicao" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-x-octagon-fill me-1"></i>
            <span>Confirmar Rejeição</span>
          </button>
        </div>
      </template>
    </Modal>

    <!-- ==================================================================== -->
    <!-- MODAL DE ZOOM DE FOTO                                                -->
    <!-- ==================================================================== -->
    <Modal
      :show="showModalZoom"
      :title="zoomImgTitulo || 'Visualização Ampliada'"
      icon="bi-zoom-in"
      icon-color="text-cyan"
      :max-width="'640px'"
      @close="showModalZoom = false"
    >
      <div class="text-center p-3">
        <img :src="zoomImgUrl" alt="Zoom Foto" class="modal-photo-zoom" />
      </div>
      <template #footer>
        <button type="button" class="btn-secondary w-100" @click="showModalZoom = false">
          Fechar
        </button>
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
.spin-icon {
  animation: spin 1s infinite linear;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
