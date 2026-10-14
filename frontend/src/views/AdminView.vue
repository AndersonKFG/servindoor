<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import Modal from '../components/Modal.vue'
import KpiCard from '../components/KpiCard.vue'
import { useAuth } from '../composables/useAuth'
import { formatarDataHoraSp, paraDatetimeLocalSp } from '../utils/formatters'

const { toast } = useToast()

const router = useRouter()
const { isAdmin, isAdminGeral, checkAuth } = useAuth()
const loading = ref(true)
let adminEventSource = null
let adminRefreshTimer = null
const metricas = ref({
  total_vagas: 0,
  total_resgatados: 0,
  total_em_resgate: 0,
  total_checkins: 0,
  lotes_abertos: 0,
  taxa_ocupacao: 0
})
const lotes = ref([])
const secretarias = ref([])

// Modais Lote
const showModalNovo = ref(false)
const showModalEditar = ref(false)
const loteEditando = ref(null)

const novoLote = ref({
  nome: '',
  quantidade_total: 100,
  data_abertura: '',
  data_fechamento: '',
  secretaria_id: '0',
  ativo: true
})

// ==========================================
// ESTADO DO FLUXO DE EXCLUSÃO CRÍTICA DE LOTE
// ==========================================
const showModalExcluirLote = ref(false)
const loteParaExcluir = ref(null)
const verificandoExclusao = ref(false)
const processandoExclusao = ref(false)
const erroExclusao = ref('')

const excluirConfirmacaoTexto = ref('')
const excluirSenha = ref('')
const mostrarExcluirSenha = ref(false)

const excluirTokenCodigo = ref('')
const excluirCodigoEmail = ref('')
const enviandoCodigoEmail = ref(false)
const codigoEmailEnviado = ref(false)
const emailEnvioMsg = ref('')

const FRASE_CONFIRMACAO_OBRIGATORIA = 'Sim, eu realmente desejo excluir esse lote'

const textoFraseValida = computed(() => {
  return excluirConfirmacaoTexto.value.trim() === FRASE_CONFIRMACAO_OBRIGATORIA
})

const podeConfirmarExclusao = computed(() => {
  if (!loteParaExcluir.value) return false
  const senhaValida = excluirSenha.value.trim().length > 0

  if (!loteParaExcluir.value.tem_participantes) {
    // Caso NÃO tenha participantes: apenas confirmação de senha
    return senhaValida
  }

  // Caso TENHA participantes: Texto + Senha + Código do E-mail
  const codigoValido = codigoEmailEnviado.value && excluirCodigoEmail.value.trim().length === 6
  return textoFraseValida.value && senhaValida && codigoValido
})

// ==========================================
// ESTADO DO SISTEMA DE BACKUPS (RETENÇÃO 3 DIAS)
// ==========================================
const backups = ref([])
const carregandoBackups = ref(false)

// Modal Restaurar Backup
const showModalRestaurarBackup = ref(false)
const backupParaRestaurar = ref(null)
const senhaRestaurar = ref('')
const mostrarSenhaRestaurar = ref(false)
const processandoRestauracao = ref(false)
const erroRestaurar = ref('')

// Modal Importar Backup JSON
const showModalImportarBackup = ref(false)
const arquivoBackupSelecionado = ref(null)
const dadosBackupJson = ref(null)
const previewBackup = ref(null)
const senhaImportar = ref('')
const mostrarSenhaImportar = ref(false)
const processandoImportacao = ref(false)
const erroImportar = ref('')

// Modal Aviso Retenção Inviolável
const showModalRegraRetencao = ref(false)

// ==========================================
// CARREGAMENTO DE DADOS
// ==========================================
async function carregarDadosAdmin(silent = false) {
  try {
    if (!silent) loading.value = true
    await checkAuth()
    if (!isAdmin.value) {
      router.push('/admin/participantes')
      return
    }
    const res = await fetch('/admin', {
      headers: { 'Accept': 'application/json, text/html' }
    })

    if (res.status === 401 || res.status === 403 || res.redirected) {
      router.push('/login')
      return
    }

    try {
      const lotesRes = await fetch('/api/lotes-admin')
      if (lotesRes.ok) {
        const data = await lotesRes.json()
        metricas.value = data.metricas
        lotes.value = data.lotes
        secretarias.value = Array.isArray(data.secretarias) ? data.secretarias : []
      }
    } catch {
      // Falha temporária de rede
    }
    if (!silent) loading.value = false
  } catch (err) {
    if (!silent) toast.error('Erro ao carregar dados do painel.')
    if (!silent) loading.value = false
  }
}

async function carregarBackups() {
  carregandoBackups.value = true
  try {
    const res = await fetch('/api/admin/lotes/backups')
    if (res.ok) {
      const data = await res.json()
      backups.value = data.backups || []
    }
  } catch (e) {
    // Falha ao carregar backups
  } finally {
    carregandoBackups.value = false
  }
}

// ==========================================
// AÇÕES DE LOTES
// ==========================================
async function handleCriarLote() {
  if (!isAdminGeral.value) return
  try {
    const formData = new FormData()
    formData.append('nome', novoLote.value.nome)
    formData.append('quantidade_total', novoLote.value.quantidade_total)
    formData.append('data_abertura', novoLote.value.data_abertura)
    if (novoLote.value.data_fechamento) {
      formData.append('data_fechamento', novoLote.value.data_fechamento)
    }
    formData.append('secretaria_id', novoLote.value.secretaria_id || '0')
    if (novoLote.value.ativo) {
      formData.append('ativo', 'on')
    }

    await fetch('/admin/lote', {
      method: 'POST',
      body: formData
    })

    showModalNovo.value = false
    novoLote.value = {
      nome: '',
      quantidade_total: 100,
      data_abertura: '',
      data_fechamento: '',
      secretaria_id: '0',
      ativo: true
    }
    await carregarDadosAdmin()
  } catch (e) {
    toast.error('Erro ao criar lote.')
  }
}

function abrirEditarLote(l) {
  if (!isAdminGeral.value) return
  loteEditando.value = {
    id: l.model.id,
    nome: l.model.nome,
    quantidade_total: l.model.quantidade_total,
    data_abertura: l.model.data_abertura_input ?? paraDatetimeLocalSp(l.model.data_abertura),
    data_fechamento: l.model.data_fechamento_input ?? paraDatetimeLocalSp(l.model.data_fechamento),
    secretaria_id: l.model.secretaria_id ? String(l.model.secretaria_id) : '0',
    ativo: l.model.ativo
  }
  showModalEditar.value = true
}

async function handleSalvarEdicao() {
  if (!isAdminGeral.value) return
  if (!loteEditando.value) return
  try {
    const formData = new FormData()
    formData.append('nome', loteEditando.value.nome)
    formData.append('quantidade_total', loteEditando.value.quantidade_total)
    formData.append('data_abertura', loteEditando.value.data_abertura)
    if (loteEditando.value.data_fechamento) {
      formData.append('data_fechamento', loteEditando.value.data_fechamento)
    }
    formData.append('secretaria_id', loteEditando.value.secretaria_id || '0')
    if (loteEditando.value.ativo) {
      formData.append('ativo', 'on')
    }

    const response = await fetch(`/admin/lote/${loteEditando.value.id}/editar`, {
      method: 'POST',
      body: formData
    })
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      throw new Error(errorData.detail || 'Não foi possível salvar as alterações do lote.')
    }

    showModalEditar.value = false
    await carregarDadosAdmin()
  } catch (e) {
    toast.error(e.message || 'Erro ao salvar edição do lote.')
  }
}

async function handleToggleLote(loteId) {
  if (!isAdminGeral.value) return
  try {
    const response = await fetch(`/admin/lote/${loteId}/toggle`, { method: 'POST' })
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      throw new Error(errorData.detail || 'Não foi possível alterar o status do lote.')
    }
    await carregarDadosAdmin()
  } catch (e) {
    toast.error(e.message || 'Erro ao alternar status do lote.')
  }
}

// ==========================================
// FLUXO DE EXCLUSÃO CRÍTICA E DIFICULTOSA
// ==========================================
async function iniciarExclusaoLote(loteItem) {
  if (!isAdminGeral.value) return
  erroExclusao.value = ''
  excluirConfirmacaoTexto.value = ''
  excluirSenha.value = ''
  excluirTokenCodigo.value = ''
  excluirCodigoEmail.value = ''
  codigoEmailEnviado.value = false
  emailEnvioMsg.value = ''
  verificandoExclusao.value = true

  try {
    const res = await fetch(`/api/admin/lote/${loteItem.model.id}/verificar-exclusao`)
    const data = await res.json()
    if (!res.ok) {
      toast.error(data.detail || 'Erro ao verificar condições do lote.')
      return
    }

    loteParaExcluir.value = {
      id: data.lote.id,
      nome: data.lote.nome,
      tem_participantes: data.tem_participantes,
      total_participantes: data.total_participantes,
      admin_email: data.admin_email,
      admin_email_mascarado: data.admin_email_mascarado
    }
    showModalExcluirLote.value = true
  } catch (e) {
    toast.error('Erro de conexão ao verificar o lote.')
  } finally {
    verificandoExclusao.value = false
  }
}

async function handleSolicitarCodigoExclusao() {
  if (!isAdminGeral.value) return
  if (!loteParaExcluir.value) return
  enviandoCodigoEmail.value = true
  erroExclusao.value = ''

  try {
    const res = await fetch(`/api/admin/lote/${loteParaExcluir.value.id}/solicitar-codigo-exclusao`, {
      method: 'POST'
    })
    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || 'Não foi possível enviar o código de segurança.')
    }
    excluirTokenCodigo.value = data.token
    codigoEmailEnviado.value = true
    emailEnvioMsg.value = data.mensagem || 'Código de 6 dígitos enviado para seu e-mail!'
  } catch (e) {
    erroExclusao.value = e.message || 'Erro ao solicitar código.'
  } finally {
    enviandoCodigoEmail.value = false
  }
}

async function handleConfirmarExclusao() {
  if (!isAdminGeral.value) return
  if (!loteParaExcluir.value || !podeConfirmarExclusao.value) return
  processandoExclusao.value = true
  erroExclusao.value = ''

  try {
    const payload = {
      senha: excluirSenha.value,
      confirmacao_texto: excluirConfirmacaoTexto.value,
      token_codigo: excluirTokenCodigo.value,
      codigo_email: excluirCodigoEmail.value
    }

    const res = await fetch(`/api/admin/lote/${loteParaExcluir.value.id}/confirmar-exclusao`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify(payload)
    })

    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || 'Falha ao excluir o lote.')
    }

    showModalExcluirLote.value = false
    toast.success(data.mensagem || 'Lote excluído com sucesso! O backup protegido de 3 dias já está disponível na lixeira.')
    await carregarDadosAdmin()
    await carregarBackups()
  } catch (e) {
    erroExclusao.value = e.message || 'Erro inesperado na exclusão.'
  } finally {
    processandoExclusao.value = false
  }
}

// ==========================================
// AÇÕES DE BACKUPS (RESTAURAR, EXPORTAR, IMPORTAR)
// ==========================================
function abrirModalRestaurar(b) {
  if (!isAdminGeral.value) return
  backupParaRestaurar.value = b
  senhaRestaurar.value = ''
  erroRestaurar.value = ''
  showModalRestaurarBackup.value = true
}

async function handleConfirmarRestauracao() {
  if (!isAdminGeral.value) return
  if (!backupParaRestaurar.value || !senhaRestaurar.value.trim()) return
  processandoRestauracao.value = true
  erroRestaurar.value = ''

  try {
    const res = await fetch(`/api/admin/lotes/backups/${backupParaRestaurar.value.id}/restaurar`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({ senha: senhaRestaurar.value })
    })

    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || 'Não foi possível restaurar o backup.')
    }

    showModalRestaurarBackup.value = false
    toast.success(data.mensagem || 'Lote e ingressos restaurados com sucesso!')
    await carregarDadosAdmin()
    await carregarBackups()
  } catch (e) {
    erroRestaurar.value = e.message || 'Erro na restauração.'
  } finally {
    processandoRestauracao.value = false
  }
}

function handleExportarBackup(b) {
  if (!isAdminGeral.value) return
  window.open(`/api/admin/lotes/backups/${b.id}/exportar`, '_blank')
}

function abrirModalImportar() {
  if (!isAdminGeral.value) return
  arquivoBackupSelecionado.value = null
  dadosBackupJson.value = null
  previewBackup.value = null
  senhaImportar.value = ''
  erroImportar.value = ''
  showModalImportarBackup.value = true
}

function onArquivoSelecionado(e) {
  erroImportar.value = ''
  const file = e.target.files?.[0]
  if (!file) return

  if (!file.name.endsWith('.json')) {
    erroImportar.value = 'Por favor, selecione um arquivo válido no formato .json'
    return
  }

  arquivoBackupSelecionado.value = file
  const reader = new FileReader()
  reader.onload = (event) => {
    try {
      const parsed = JSON.parse(event.target.result)
      if (!parsed.lote || !parsed.lote.nome) {
        throw new Error('Estrutura de arquivo incompatível com backups do Serv indoor.')
      }
      dadosBackupJson.value = parsed
      previewBackup.value = {
        nome: parsed.lote.nome,
        total_ingressos: parsed.total_ingressos || (parsed.ingressos ? parsed.ingressos.length : 0),
        criado_em: parsed.criado_em ? formatarDataHoraSp(parsed.criado_em) : 'Desconhecido',
        excluido_por: parsed.excluido_por?.nome || 'Administrador'
      }
    } catch (err) {
      erroImportar.value = 'Erro ao ler arquivo JSON: ' + (err.message || 'Arquivo corrompido ou inválido.')
      dadosBackupJson.value = null
      previewBackup.value = null
    }
  }
  reader.readAsText(file)
}

async function handleConfirmarImportacao() {
  if (!isAdminGeral.value) return
  if (!dadosBackupJson.value || !senhaImportar.value.trim()) return
  processandoImportacao.value = true
  erroImportar.value = ''

  try {
    const res = await fetch('/api/admin/lotes/importar-backup', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({
        senha: senhaImportar.value,
        backup_json: dadosBackupJson.value
      })
    })

    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || 'Falha ao importar backup.')
    }

    showModalImportarBackup.value = false
    toast.success(data.mensagem || 'Backup importado com sucesso!')
    await carregarDadosAdmin()
    await carregarBackups()
  } catch (e) {
    erroImportar.value = e.message || 'Erro ao importar backup.'
  } finally {
    processandoImportacao.value = false
  }
}

function copiarFrase() {
  navigator.clipboard.writeText(FRASE_CONFIRMACAO_OBRIGATORIA)
  excluirConfirmacaoTexto.value = FRASE_CONFIRMACAO_OBRIGATORIA
}

function conectarAtualizacoesLote() {
  if (adminEventSource) return

  adminEventSource = new EventSource('/api/lote/stream')
  const atualizarPainel = () => {
    // Eventos contínuos de reservas não podem adiar a atualização indefinidamente.
    if (adminRefreshTimer) return
    adminRefreshTimer = setTimeout(() => {
      adminRefreshTimer = null
      carregarDadosAdmin(true)
    }, 1000)
  }

  adminEventSource.addEventListener('ESTADO_CONSOLIDADO', atualizarPainel)
  adminEventSource.addEventListener('LOTE_ATUALIZADO', atualizarPainel)
  adminEventSource.addEventListener('RESERVA_ATUALIZADA', atualizarPainel)
}

onMounted(() => {
  carregarDadosAdmin().then(() => {
    if (isAdmin.value) conectarAtualizacoesLote()
  })
  carregarBackups()
})

onUnmounted(() => {
  if (adminRefreshTimer) clearTimeout(adminRefreshTimer)
  adminEventSource?.close()
  adminEventSource = null
})
</script>


<template>
  <div class="admin-page">
    <div class="app-container">
      
      <!-- Cabeçalho do Painel -->
      <div class="admin-header-row">
        <div>
          <span class="admin-eyebrow"><i class="bi bi-shield-lock-fill"></i> PAINEL ADMINISTRATIVO</span>
          <h1 class="page-title font-quattrocento">Painel de Gestão VIP</h1>
          <p class="admin-subtitle">Monitoramento de resgates, liberação de lotes e controle de participantes.</p>
        </div>
        <div v-if="isAdminGeral" class="header-actions">
          <button type="button" class="btn-primary font-outfit" @click="showModalNovo = true">
            <i class="bi bi-plus-circle-fill me-1"></i> Criar Novo Lote
          </button>
        </div>
      </div>

      <!-- Cards de M?tricas Gerais -->
      <div class="kpi-grid">
        <KpiCard
          title="Vagas Totais"
          :value="metricas.total_vagas"
          icon="bi bi-ticket-detailed-fill"
          variant="cyan"
        />

        <KpiCard
          title="Ingressos Resgatados"
          :value="metricas.total_resgatados"
          icon="bi bi-people-fill"
          variant="emerald"
        />

        <KpiCard
          title="Em Resgate"
          :value="metricas.total_em_resgate ?? 0"
          subtitle="Reservas ativas dentro do prazo"
          icon="bi bi-hourglass-split"
          variant="blue"
        />

        <KpiCard
          title="Check-ins na Portaria"
          :value="metricas.total_checkins"
          icon="bi bi-qr-code-scan"
          variant="purple"
        />

        <KpiCard
          title="Taxa de Ocupação"
          :value="metricas.taxa_ocupacao + '%'"
          icon="bi bi-percent"
          variant="warning"
        />
      </div>

      <!-- TABELA: Lotes Cadastrados -->
      <div class="table-card lotes-table-card">
        <div class="table-header-box">
          <div class="table-title font-outfit">
            <i class="bi bi-layers-fill me-2 text-primary"></i> Lotes Cadastrados
          </div>
          <span class="badge-count">{{ lotes.length }} lotes no total</span>
        </div>

        <div class="table-responsive">
          <table class="custom-table">
            <thead>
              <tr>
                <th>Lote</th>
                <th>Secretaria</th>
                <th>Abertura / Fechamento</th>
                <th>Status</th>
                <th>Ocupação</th>
                <th v-if="isAdminGeral" class="text-end">Ações</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="lotes.length === 0">
                <td :colspan="isAdminGeral ? 6 : 5" class="text-center py-4 text-subtle">
                  Nenhum lote cadastrado no momento.<template v-if="isAdminGeral"> Clique em <strong>Criar Novo Lote</strong>.</template>
                </td>
              </tr>
              <tr v-for="item in lotes" :key="item.model.id">
                <td>
                  <strong class="text-white">{{ item.model.nome }}</strong>
                  <span class="d-block small text-subtle">#{{ item.model.id }}</span>
                </td>
                <td>
                  <span v-if="item.model.secretaria" class="sec-tag">{{ item.model.secretaria.nome }}</span>
                  <span v-else class="sec-tag-global">Geral / Todos</span>
                </td>
                <td>
                  <div class="date-info">
                    <span><i class="bi bi-calendar-event me-1"></i> {{ item.model.data_abertura ? formatarDataHoraSp(item.model.data_abertura) : 'Imediato' }}</span>
                    <span v-if="item.model.data_fechamento" class="text-subtle"><i class="bi bi-clock-history me-1"></i> {{ formatarDataHoraSp(item.model.data_fechamento) }}</span>
                  </div>
                </td>
                <td>
                  <span :class="['status-badge', item.status.badge_class]">
                    <i :class="['bi', item.status.icon, 'me-1']"></i> {{ item.status.label }}
                  </span>
                </td>
                <td style="min-width: 140px;">
                  <div class="progress-info">
                    <div class="progress-bar-bg">
                      <div class="progress-bar-fill" :class="['progress-bar-fill', item.pct >= 100 ? 'fill-danger' : item.pct >= 80 ? 'fill-warning' : 'fill-success']" :style="{ width: item.pct + '%' }"></div>
                    </div>
                    <span class="progress-text">{{ item.model.quantidade_resgatada }} / {{ item.model.quantidade_total }} ({{ item.pct }}%)</span>
                  </div>
                </td>
                <td v-if="isAdminGeral" class="text-end">
                  <div class="action-buttons-group">
                    <router-link :to="'/admin/lote/' + item.model.id + '/ingressos'" class="btn-action-icon btn-action-icon--blue" title="Ver Ingressos Resgatados">
                      <i class="bi bi-people-fill"></i>
                    </router-link>

                    <button
                      v-if="item.status.pode_toggle"
                      type="button"
                      class="btn-action-icon"
                      :title="item.status.key === 'pausado' ? 'Despausar Lote' : 'Pausar Lote'"
                      @click="handleToggleLote(item.model.id)"
                    >
                      <i :class="['bi', item.status.key === 'pausado' ? 'bi-play-circle-fill text-success' : 'bi-pause-circle-fill text-warning']"></i>
                    </button>

                    <button type="button" class="btn-action-icon btn-action-icon--cyan" title="Editar Lote" @click="abrirEditarLote(item)">
                      <i class="bi bi-pencil-fill text-info"></i>
                    </button>

                    <button
                      type="button"
                      class="btn-action-icon btn-action-icon--danger"
                      title="Excluir Lote (Protocolo Blindado)"
                      :disabled="verificandoExclusao"
                      @click="iniciarExclusaoLote(item)"
                    >
                      <i class="bi bi-trash-fill text-danger"></i>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- SEÇÃO: Lixeira & Backups Blindados (Retenção 3 Dias) -->
      <div class="table-card lotes-table-card mt-5">
        <div class="table-header-box backup-header-box">
          <div>
            <div class="table-title font-outfit text-warning">
              <i class="bi bi-shield-lock-fill me-2 text-warning"></i> Backups e Recuperação de Lotes
            </div>
            <p class="backup-header-desc">
              Lotes excluídos ficam salvos por <strong>3 dias com retenção blindada</strong>. O backup não pode ser excluído manualmente.
            </p>
          </div>
          <div v-if="isAdminGeral" class="backup-header-actions">
            <button type="button" class="btn-secondary-sm me-2" @click="carregarBackups" :disabled="carregandoBackups" title="Atualizar Backups">
              <i :class="['bi bi-arrow-clockwise', { 'spin-icon': carregandoBackups }]"></i> Atualizar
            </button>
            <button type="button" class="btn-primary-sm font-outfit" @click="abrirModalImportar">
              <i class="bi bi-file-earmark-arrow-up-fill me-1"></i> Importar Backup (.json)
            </button>
          </div>
        </div>

        <!-- Alerta de Retenção Obrigatória -->
        <div class="backup-policy-alert">
          <i class="bi bi-info-circle-fill text-warning me-2 fs-5"></i>
          <span>
            <strong>Diretriz de Segurança Inviolável:</strong> Todos os lotes excluídos geram um snapshot criptografado completo que permanece preservado por no mínimo 72 horas (3 dias). Exclusão manual de backups é estritamente bloqueada pelo servidor.
          </span>
        </div>

        <div class="table-responsive">
          <table class="custom-table">
            <thead>
              <tr>
                <th>Lote Excluído</th>
                <th>Ingressos Preservados</th>
                <th>Data da Exclusão</th>
                <th>Excluído Por</th>
                <th>Retenção Obrigatória</th>
                <th>Estado</th>
                <th v-if="isAdminGeral" class="text-end">Ações Protegidas</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="backups.length === 0">
                <td :colspan="isAdminGeral ? 7 : 6" class="text-center py-4 text-subtle">
                  <i class="bi bi-shield-check text-success me-2"></i> Nenhum lote na lixeira de proteção. O histórico de backups está vazio.
                </td>
              </tr>
              <tr v-for="b in backups" :key="b.id">
                <td>
                  <strong class="text-white">{{ b.lote_nome }}</strong>
                  <span class="d-block small text-subtle">ID Original #{{ b.lote_id }}</span>
                </td>
                <td>
                  <span class="badge-tickets">
                    <i class="bi bi-ticket-perforated-fill me-1"></i> {{ b.total_ingressos }} ingressos
                  </span>
                </td>
                <td>
                  <span class="small text-white"><i class="bi bi-calendar-x me-1"></i> {{ b.excluido_em }}</span>
                </td>
                <td>
                  <span class="small text-subtle">{{ b.excluido_por_nome }}</span>
                </td>
                <td>
                  <span class="retention-pill" :title="'Expira em ' + b.expira_em">
                    <i class="bi bi-hourglass-split me-1 text-warning"></i>
                    {{ b.horas_restantes > 0 ? b.horas_restantes + 'h restantes' : 'Protegido (3 dias)' }}
                  </span>
                </td>
                <td>
                  <span v-if="b.restaurado" class="status-badge bg-info-subtle text-info">
                    <i class="bi bi-arrow-counterclockwise me-1"></i> Restaurado
                  </span>
                  <span v-else class="status-badge bg-warning-subtle text-warning">
                    <i class="bi bi-archive-fill me-1"></i> Ativo no Backup
                  </span>
                </td>
                <td v-if="isAdminGeral" class="text-end">
                  <div class="action-buttons-group">
                    <!-- Restaurar Lote -->
                    <button
                      v-if="!b.restaurado"
                      type="button"
                      class="btn-action-icon text-success"
                      title="Restaurar Lote e Ingressos"
                      @click="abrirModalRestaurar(b)"
                    >
                      <i class="bi bi-arrow-counterclockwise"></i>
                    </button>

                    <!-- Exportar Arquivo JSON -->
                    <button
                      type="button"
                      class="btn-action-icon text-info"
                      title="Salvar Backup em Arquivo (.json)"
                      @click="handleExportarBackup(b)"
                    >
                      <i class="bi bi-download"></i>
                    </button>

                    <!-- Excluir Backup (BLOQUEADO INVIOLAVELMENTE) -->
                    <button
                      type="button"
                      class="btn-action-icon btn-action-locked"
                      title="Exclusão Proibida: Retenção obrigatória de 3 dias"
                      @click="showModalRegraRetencao = true"
                    >
                      <i class="bi bi-lock-fill text-muted"></i>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

    </div>

    <!-- MODAL: Criar Novo Lote -->
    <Modal
      v-if="isAdminGeral"
      :show="showModalNovo"
      title="Criar Novo Lote"
      icon="bi-plus-circle-fill"
      @close="showModalNovo = false"
    >
      <form @submit.prevent="handleCriarLote">
        <div class="form-group">
          <label class="form-label" for="novo-nome">Nome do Lote</label>
          <input id="novo-nome" v-model="novoLote.nome" type="text" class="form-control" placeholder="Ex: Lote 01 - Geral" required />
        </div>

        <div class="form-group">
          <label class="form-label" for="novo-qtd">Quantidade Total de Vagas</label>
          <input id="novo-qtd" v-model="novoLote.quantidade_total" type="number" min="1" class="form-control" required />
        </div>

        <div class="form-group">
          <label class="form-label" for="novo-abertura">Data e Horário de Abertura</label>
          <input id="novo-abertura" v-model="novoLote.data_abertura" type="datetime-local" class="form-control" required />
        </div>

        <div class="form-group">
          <label class="form-label" for="novo-fechamento">Data e Horário de Fechamento (Opcional)</label>
          <input id="novo-fechamento" v-model="novoLote.data_fechamento" type="datetime-local" class="form-control" />
        </div>

        <div class="form-group">
          <label class="form-label" for="novo-secretaria">Secretaria Exclusiva (Opcional)</label>
          <select id="novo-secretaria" v-model="novoLote.secretaria_id" class="form-select">
            <option value="0">Geral (Todas as Secretarias)</option>
            <option v-for="sec in secretarias" :key="sec.id" :value="String(sec.id)">
              {{ sec.nome }}
            </option>
          </select>
        </div>

        <div class="modal-footer-box">
          <button type="button" class="btn-secondary" @click="showModalNovo = false">Cancelar</button>
          <button type="submit" class="btn-primary">Criar Lote</button>
        </div>
      </form>
    </Modal>

    <!-- MODAL: Editar Lote -->
    <Modal
      v-if="isAdminGeral"
      :show="showModalEditar"
      title="Editar Lote"
      icon="bi-pencil-square"
      @close="showModalEditar = false"
    >
      <form v-if="loteEditando" @submit.prevent="handleSalvarEdicao">
        <div class="form-group">
          <label class="form-label" for="edit-nome">Nome do Lote</label>
          <input id="edit-nome" v-model="loteEditando.nome" type="text" class="form-control" required />
        </div>

        <div class="form-group">
          <label class="form-label" for="edit-qtd">Quantidade Total de Vagas</label>
          <input id="edit-qtd" v-model="loteEditando.quantidade_total" type="number" min="1" class="form-control" required />
        </div>

        <div class="form-group">
          <label class="form-label" for="edit-abertura">Data e Horário de Abertura</label>
          <input id="edit-abertura" v-model="loteEditando.data_abertura" type="datetime-local" class="form-control" required />
        </div>

        <div class="form-group">
          <label class="form-label" for="edit-fechamento">Data e Horário de Fechamento</label>
          <input id="edit-fechamento" v-model="loteEditando.data_fechamento" type="datetime-local" class="form-control" />
        </div>

        <div class="form-group">
          <label class="form-label" for="edit-secretaria">Secretaria Exclusiva</label>
          <select id="edit-secretaria" v-model="loteEditando.secretaria_id" class="form-select">
            <option value="0">Geral (Todas as Secretarias)</option>
            <option v-for="sec in secretarias" :key="sec.id" :value="String(sec.id)">
              {{ sec.nome }}
            </option>
          </select>
        </div>

        <div class="modal-footer-box">
          <button type="button" class="btn-secondary" @click="showModalEditar = false">Cancelar</button>
          <button type="submit" class="btn-primary">Salvar Alterações</button>
        </div>
      </form>
    </Modal>

    <!-- MODAL: EXCLUSÃO DIFICULTOSA E SEGURA DE LOTE -->
    <Modal
      v-if="isAdminGeral"
      :show="showModalExcluirLote"
      :title="loteParaExcluir?.tem_participantes ? 'Exclusão Crítica: Lote com Ingressos' : 'Confirmação de Exclusão de Lote'"
      :icon="loteParaExcluir?.tem_participantes ? 'bi-exclamation-triangle-fill' : 'bi-trash-fill'"
      :icon-color="loteParaExcluir?.tem_participantes ? 'text-danger' : 'text-warning'"
      max-width="620px"
      @close="!processandoExclusao ? showModalExcluirLote = false : null"
    >
      <div v-if="loteParaExcluir" class="exclusao-modal-body">
        
        <!-- Alerta quando TEM participantes -->
        <div v-if="loteParaExcluir.tem_participantes" class="alert-danger-custom">
          <div class="alert-icon-col">
            <i class="bi bi-shield-fill-exclamation text-danger fs-3"></i>
          </div>
          <div>
            <h4 class="alert-danger-title">ATENÇÃO EXTREMA: LOTE EMITIDO!</h4>
            <p class="alert-danger-text">
              O lote <strong>"{{ loteParaExcluir.nome }}"</strong> possui <strong>{{ loteParaExcluir.total_participantes }} participante(s)</strong> com ingressos emitidos e resgatados.
            </p>
            <p class="alert-danger-sub">
              Para impossibilitar exclusões acidentais ou não autorizadas, a eliminação deste lote exige o cumprimento obrigatório de <strong>todas as 3 etapas de segurança</strong> abaixo.
            </p>
          </div>
        </div>

        <!-- Alerta quando NÃO tem participantes -->
        <div v-else class="alert-warning-custom">
          <i class="bi bi-info-circle-fill text-warning fs-4 me-3"></i>
          <div>
            <h4 class="alert-warning-title">Exclusão de Lote Sem Ingressos</h4>
            <p class="alert-warning-text">
              O lote <strong>"{{ loteParaExcluir.nome }}"</strong> não possui participantes nem ingressos resgatados. Para prosseguir, confirme a senha da sua conta de administrador.
            </p>
          </div>
        </div>

        <form @submit.prevent="handleConfirmarExclusao" class="form-exclusao">

          <!-- ETAPA 1: Confirmação Textual Obrigatória (apenas se tiver participantes) -->
          <div v-if="loteParaExcluir.tem_participantes" class="step-card" :class="{ 'step-valid': textoFraseValida }">
            <div class="step-header">
              <span class="step-badge">Etapa 1 de 3</span>
              <span class="step-title">Confirmação Textual Obrigatória</span>
              <i v-if="textoFraseValida" class="bi bi-check-circle-fill text-success ms-auto fs-5"></i>
            </div>
            <p class="step-desc">
              Digite exatamente a frase entre aspas abaixo para confirmar que está ciente:
            </p>
            <div class="phrase-box">
              <code>"Sim, eu realmente desejo excluir esse lote"</code>
              <button type="button" class="btn-copy-phrase" title="Copiar e preencher" @click="copiarFrase">
                <i class="bi bi-clipboard-check"></i>
              </button>
            </div>
            <input
              v-model="excluirConfirmacaoTexto"
              type="text"
              class="form-control mt-2"
              placeholder="Digite a frase exatamente como exibida acima"
              :class="{ 'is-valid': textoFraseValida, 'is-invalid': excluirConfirmacaoTexto && !textoFraseValida }"
              required
            />
          </div>

          <!-- ETAPA 2: Senha da Conta (Obrigatório em ambos os casos) -->
          <div class="step-card" :class="{ 'step-valid': excluirSenha.trim().length > 0 }">
            <div class="step-header">
              <span v-if="loteParaExcluir.tem_participantes" class="step-badge">Etapa 2 de 3</span>
              <span v-else class="step-badge">Confirmação de Identidade</span>
              <span class="step-title">Senha da sua Conta de Administrador</span>
              <i v-if="excluirSenha.trim().length > 0" class="bi bi-check-circle-fill text-success ms-auto fs-5"></i>
            </div>
            <p class="step-desc">
              Informe a sua senha atual de acesso para autenticar a solicitação:
            </p>
            <div class="password-input-wrapper">
              <input
                v-model="excluirSenha"
                :type="mostrarExcluirSenha ? 'text' : 'password'"
                class="form-control"
                placeholder="Sua senha de administrador"
                required
              />
              <button
                type="button"
                class="btn-toggle-eye"
                @click="mostrarExcluirSenha = !mostrarExcluirSenha"
              >
                <i :class="['bi', mostrarExcluirSenha ? 'bi-eye-slash-fill' : 'bi-eye-fill']"></i>
              </button>
            </div>
          </div>

          <!-- ETAPA 3: Código de Confirmação 2FA via E-mail (Apenas se tiver participantes) -->
          <div v-if="loteParaExcluir.tem_participantes" class="step-card" :class="{ 'step-valid': codigoEmailEnviado && excluirCodigoEmail.trim().length === 6 }">
            <div class="step-header">
              <span class="step-badge">Etapa 3 de 3</span>
              <span class="step-title">Código 2FA Enviado ao seu E-mail</span>
              <i v-if="codigoEmailEnviado && excluirCodigoEmail.trim().length === 6" class="bi bi-check-circle-fill text-success ms-auto fs-5"></i>
            </div>
            <p class="step-desc">
              Um código numérico de 6 dígitos será enviado ao seu endereço:
              <strong class="text-white">{{ loteParaExcluir.admin_email_mascarado }}</strong>
            </p>

            <div class="email-code-action-row">
              <button
                type="button"
                class="btn-request-code"
                :disabled="enviandoCodigoEmail"
                @click="handleSolicitarCodigoExclusao"
              >
                <i v-if="enviandoCodigoEmail" class="bi bi-arrow-repeat spin-icon me-1"></i>
                <i v-else class="bi bi-envelope-arrow-up-fill me-1"></i>
                {{ codigoEmailEnviado ? 'Reenviar Código' : 'Enviar Código ao Meu E-mail' }}
              </button>

              <div v-if="codigoEmailEnviado" class="code-input-box">
                <input
                  v-model="excluirCodigoEmail"
                  type="text"
                  maxlength="6"
                  class="form-control text-center code-input"
                  placeholder="000000"
                  required
                />
              </div>
            </div>

            <div v-if="emailEnvioMsg" class="email-success-note">
              <i class="bi bi-check2-circle text-success me-1"></i> {{ emailEnvioMsg }}
            </div>
          </div>

          <!-- Mensagem de Erro Geral -->
          <div v-if="erroExclusao" class="error-banner">
            <i class="bi bi-x-circle-fill me-2"></i> {{ erroExclusao }}
          </div>

          <!-- Nota de Retenção e Backup Seguro -->
          <div class="backup-guarantee-box">
            <i class="bi bi-shield-check text-info fs-5 me-2"></i>
            <span class="small text-subtle">
              <strong>Garantia de Recuperação:</strong> Ao confirmar, um backup blindado com todos os dados e participantes será arquivado por <strong>3 dias</strong> e poderá ser restaurado a qualquer momento.
            </span>
          </div>

          <!-- Botões do Rodapé -->
          <div class="modal-footer-box mt-4">
            <button
              type="button"
              class="btn-secondary"
              :disabled="processandoExclusao"
              @click="showModalExcluirLote = false"
            >
              Cancelar e Manter Lote
            </button>
            <button
              type="submit"
              class="btn-danger-critical"
              :disabled="!podeConfirmarExclusao || processandoExclusao"
            >
              <i v-if="processandoExclusao" class="bi bi-arrow-repeat spin-icon me-1"></i>
              <i v-else class="bi bi-trash3-fill me-1"></i>
              {{ loteParaExcluir.tem_participantes ? 'Excluir Definitivamente o Lote' : 'Confirmar Exclusão' }}
            </button>
          </div>

        </form>
      </div>
    </Modal>

    <!-- MODAL: Restaurar Backup -->
    <Modal
      v-if="isAdminGeral"
      :show="showModalRestaurarBackup"
      title="Restaurar Lote e Ingressos"
      icon="bi-arrow-counterclockwise"
      icon-color="text-success"
      max-width="500px"
      @close="!processandoRestauracao ? showModalRestaurarBackup = false : null"
    >
      <div v-if="backupParaRestaurar" class="p-2">
        <p class="text-white mb-2">
          Você está prestes a restaurar o lote <strong>"{{ backupParaRestaurar.lote_nome }}"</strong> com todos os seus <strong>{{ backupParaRestaurar.total_ingressos }} ingressos resgatados</strong>.
        </p>
        <p class="small text-subtle mb-4">
          O lote voltará a ficar ativo no sistema exatamente com os mesmos dados e QR Codes originais.
        </p>

        <form @submit.prevent="handleConfirmarRestauracao">
          <div class="form-group">
            <label class="form-label" for="senha-restaurar">Digite sua Senha de Administrador para Confirmar</label>
            <div class="password-input-wrapper">
              <input
                id="senha-restaurar"
                v-model="senhaRestaurar"
                :type="mostrarSenhaRestaurar ? 'text' : 'password'"
                class="form-control"
                placeholder="Sua senha"
                required
              />
              <button
                type="button"
                class="btn-toggle-eye"
                @click="mostrarSenhaRestaurar = !mostrarSenhaRestaurar"
              >
                <i :class="['bi', mostrarSenhaRestaurar ? 'bi-eye-slash-fill' : 'bi-eye-fill']"></i>
              </button>
            </div>
          </div>

          <div v-if="erroRestaurar" class="error-banner mb-3">
            <i class="bi bi-x-circle-fill me-2"></i> {{ erroRestaurar }}
          </div>

          <div class="modal-footer-box">
            <button type="button" class="btn-secondary" @click="showModalRestaurarBackup = false">Cancelar</button>
            <button type="submit" class="btn-success-custom" :disabled="!senhaRestaurar.trim() || processandoRestauracao">
              <i v-if="processandoRestauracao" class="bi bi-arrow-repeat spin-icon me-1"></i>
              <i v-else class="bi bi-check-circle-fill me-1"></i>
              Confirmar Restauração
            </button>
          </div>
        </form>
      </div>
    </Modal>

    <!-- MODAL: Importar Backup (.json) -->
    <Modal
      v-if="isAdminGeral"
      :show="showModalImportarBackup"
      title="Importar Backup em Arquivo (.json)"
      icon="bi-file-earmark-arrow-up-fill"
      icon-color="text-info"
      max-width="560px"
      @close="!processandoImportacao ? showModalImportarBackup = false : null"
    >
      <div class="p-2">
        <p class="small text-subtle mb-3">
          Selecione o arquivo <code>.json</code> exportado anteriormente pelo sistema para recuperar o lote e seus ingressos.
        </p>

        <div class="file-upload-box mb-3">
          <input
            type="file"
            id="file-backup-json"
            accept=".json,application/json"
            class="d-none"
            @change="onArquivoSelecionado"
          />
          <label for="file-backup-json" class="file-upload-label">
            <i class="bi bi-cloud-arrow-up-fill fs-2 text-primary mb-1"></i>
            <span v-if="arquivoBackupSelecionado" class="text-white font-weight-bold">
              {{ arquivoBackupSelecionado.name }}
            </span>
            <span v-else class="text-subtle">
              Clique para selecionar o arquivo <strong>.json</strong>
            </span>
          </label>
        </div>

        <!-- Preview do Arquivo Selecionado -->
        <div v-if="previewBackup" class="preview-backup-card mb-3">
          <div class="d-flex justify-content-between align-items-center mb-1">
            <strong class="text-white font-outfit">{{ previewBackup.nome }}</strong>
            <span class="badge-tickets">{{ previewBackup.total_ingressos }} ingressos</span>
          </div>
          <div class="small text-subtle">
            Criado em: {{ previewBackup.criado_em }} • Backup por: {{ previewBackup.excluido_por }}
          </div>
        </div>

        <form @submit.prevent="handleConfirmarImportacao">
          <div class="form-group">
            <label class="form-label" for="senha-importar">Confirme sua Senha de Administrador</label>
            <div class="password-input-wrapper">
              <input
                id="senha-importar"
                v-model="senhaImportar"
                :type="mostrarSenhaImportar ? 'text' : 'password'"
                class="form-control"
                placeholder="Sua senha"
                required
              />
              <button
                type="button"
                class="btn-toggle-eye"
                @click="mostrarSenhaImportar = !mostrarSenhaImportar"
              >
                <i :class="['bi', mostrarSenhaImportar ? 'bi-eye-slash-fill' : 'bi-eye-fill']"></i>
              </button>
            </div>
          </div>

          <div v-if="erroImportar" class="error-banner mb-3">
            <i class="bi bi-x-circle-fill me-2"></i> {{ erroImportar }}
          </div>

          <div class="modal-footer-box">
            <button type="button" class="btn-secondary" @click="showModalImportarBackup = false">Cancelar</button>
            <button
              type="submit"
              class="btn-primary"
              :disabled="!dadosBackupJson || !senhaImportar.trim() || processandoImportacao"
            >
              <i v-if="processandoImportacao" class="bi bi-arrow-repeat spin-icon me-1"></i>
              <i v-else class="bi bi-cloud-check-fill me-1"></i>
              Importar e Restaurar
            </button>
          </div>
        </form>
      </div>
    </Modal>

    <!-- MODAL: Regra de Ouro (Retenção Inviolável de 3 Dias) -->
    <Modal
      v-if="isAdminGeral"
      :show="showModalRegraRetencao"
      title="Ação Estritamente Proibida"
      icon="bi-shield-slash-fill"
      icon-color="text-danger"
      max-width="480px"
      @close="showModalRegraRetencao = false"
    >
      <div class="p-3 text-center">
        <div class="shield-lock-icon mb-3">
          <i class="bi bi-lock-fill text-warning fs-1"></i>
        </div>
        <h4 class="text-white font-outfit mb-2">Backups Blindados por 3 Dias</h4>
        <p class="text-subtle small mb-3">
          Conforme as regras de integridade do sistema, <strong>nenhum administrador possui permissão para deletar backups</strong> antes do prazo de retenção de 72 horas.
        </p>
        <p class="text-subtle small mb-4">
          Essa medida garante que qualquer exclusão de lote, mesmo que feita por administradores gerais, possua uma janela segura e auditável para recuperação integral.
        </p>
        <button type="button" class="btn-secondary w-100" @click="showModalRegraRetencao = false">
          Entendido
        </button>
      </div>
    </Modal>

  </div>
</template>

