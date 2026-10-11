<script setup>
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import Modal from '../components/Modal.vue'
import KpiCard from '../components/KpiCard.vue'
import DropdownSelect from '../components/DropdownSelect.vue'

const { toast } = useToast()
const { confirmModal } = useConfirm()

const router = useRouter()
const { currentUser, isAdminGeral } = useAuth()

const loading = ref(true)
const usuarios = ref([])
const kpis = ref({
  admin_geral_total: 0,
  admin_geral_logados: 0,
  admin_total: 0,
  admin_logados: 0,
  validador_total: 0,
  validador_logados: 0,
  portaria_total: 0,
  portaria_logados: 0,
  entregadores_total: 0,
  entregadores_logados: 0
})
const secretariasDisponiveis = ref([])

const optionsRoles = [
  { value: '', label: 'Todas as Funções' },
  { value: 'admin_geral', label: 'Administrador Geral' },
  { value: 'admin', label: 'Administrador' },
  { value: 'validador', label: 'Validador de Servidores' },
  { value: 'portaria', label: 'Portaria / Scanner' },
  { value: 'entregador', label: 'Entregador de Prêmios' }
]

const optionsStatus = [
  { value: 'todos', label: 'Status: Todos' },
  { value: 'logado', label: '🟢 Apenas Logados / Ativos' },
  { value: 'offline', label: '⚪ Apenas Offline' }
]

// Filtros
const busca = ref('')
const filtroRole = ref('')
const filtroStatus = ref('todos')

// Modal Criar
const showModalCriar = ref(false)
const salvandoCriar = ref(false)
const formCriar = ref({
  nome: '',
  cpf: '',
  email: '',
  telefone: '',
  roles: ['portaria'],
  secretarias_validador: []
})

// Modal Editar
const showModalEditar = ref(false)
const salvandoEditar = ref(false)
const formEditar = ref({
  id: null,
  nome: '',
  email: '',
  telefone: '',
  roles: [],
  secretarias_validador: []
})

// Modal Excluir
const showModalExcluir = ref(false)
const usuarioExcluir = ref(null)
const excluindo = ref(false)

function formatCPF(val) {
  const digits = (val || '').replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 3) return digits
  if (digits.length <= 6) return `${digits.slice(0, 3)}.${digits.slice(3)}`
  if (digits.length <= 9) return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6)}`
  return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`
}

function onCpfInput(e) {
  formCriar.value.cpf = formatCPF(e.target.value)
}

function formatTelefone(val) {
  const digits = (val || '').replace(/\D/g, '').slice(0, 11)
  if (digits.length === 0) return ''
  if (digits.length <= 2) return `(${digits}`
  if (digits.length <= 6) return `(${digits.slice(0, 2)}) ${digits.slice(2)}`
  if (digits.length <= 10) return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`
  return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`
}

function onTelefoneInputCriar(e) {
  formCriar.value.telefone = formatTelefone(e.target.value)
}

function onTelefoneInputEditar(e) {
  formEditar.value.telefone = formatTelefone(e.target.value)
}

function obterIniciais(nome) {
  if (!nome) return '?'
  const partes = nome.trim().split(/\s+/).filter(Boolean)
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase()
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase()
}

let pollInterval = null

async function carregarEquipe(silent = false) {
  try {
    if (!silent) loading.value = true
    const res = await fetch('/api/admin/usuarios-equipe')
    if (res.status === 401 || res.status === 403) {
      router.push('/login')
      return
    }
    const data = await res.json()
    usuarios.value = data.usuarios || []
    if (data.secretarias && Array.isArray(data.secretarias)) {
      secretariasDisponiveis.value = data.secretarias
    } else {
      try {
        const secRes = await fetch('/api/secretarias')
        if (secRes.ok) secretariasDisponiveis.value = await secRes.json()
      } catch (e) {
        console.warn('Erro ao carregar secretarias:', e)
      }
    }
    kpis.value = data.kpis || {
      admin_geral_total: 0, admin_geral_logados: 0,
      admin_total: 0, admin_logados: 0,
      portaria_total: 0, portaria_logados: 0,
      entregadores_total: 0, entregadores_logados: 0
    }
  } catch (e) {
    if (!silent) toast.error('Erro ao carregar equipe.')
  } finally {
    if (!silent) loading.value = false
  }
}

const usuariosFiltrados = computed(() => {
  return usuarios.value.filter(u => {
    if (busca.value.trim()) {
      const q = busca.value.toLowerCase().trim()
      const matchNome = (u.nome || '').toLowerCase().includes(q)
      const matchCpf = (u.cpf || '').includes(q)
      const matchTel = (u.telefone || '').includes(q)
      if (!matchNome && !matchCpf && !matchTel) {
        return false
      }
    }

    if (filtroRole.value) {
      if (!u.roles || !u.roles.includes(filtroRole.value)) return false
    }

    if (filtroStatus.value === 'logado' && !u.is_logado) return false
    if (filtroStatus.value === 'offline' && u.is_logado) return false

    return true
  })
})

function toggleRole(arrayRef, role) {
  const index = arrayRef.indexOf(role)
  if (index > -1) {
    arrayRef.splice(index, 1)
  } else {
    arrayRef.push(role)
  }
}

function toggleSecId(arrayRef, id) {
  const numId = Number(id)
  const index = arrayRef.indexOf(numId)
  if (index > -1) {
    arrayRef.splice(index, 1)
  } else {
    arrayRef.push(numId)
  }
}

function abrirModalCriar() {
  formCriar.value = {
    nome: '',
    cpf: '',
    email: '',
    telefone: '',
    roles: ['portaria'],
    secretarias_validador: []
  }
  showModalCriar.value = true
}

async function salvarCriarUsuario() {
  if (!formCriar.value.nome.trim() || !formCriar.value.cpf.trim() || !formCriar.value.email.trim()) {
    toast.warning('Nome, CPF e E-mail são obrigatórios.')
    return
  }
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!emailRegex.test(formCriar.value.email.trim())) {
    toast.warning('Informe um endereço de e-mail válido.')
    return
  }
  if (!formCriar.value.roles.length) {
    toast.warning('Selecione pelo menos uma função para o usuário.')
    return
  }

  try {
    salvandoCriar.value = true
    const res = await fetch('/api/admin/usuarios', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formCriar.value)
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      showModalCriar.value = false
      toast.success(data.mensagem || 'Membro cadastrado com sucesso! Uma senha provisória foi enviada por e-mail.')
      await carregarEquipe()
    } else {
      toast.error(data.detail || 'Erro ao cadastrar membro da equipe.')
    }
  } catch {
    toast.error('Erro de conexão ao cadastrar usuário.')
  } finally {
    salvandoCriar.value = false
  }
}

function abrirModalEditar(u) {
  const secVal = u.secretarias_validador
    ? u.secretarias_validador.split(',').map(s => Number(s.trim())).filter(Boolean)
    : []
  formEditar.value = {
    id: u.id,
    nome: u.nome,
    email: u.email || '',
    telefone: formatTelefone(u.telefone || ''),
    roles: [...(u.roles || [u.role])],
    secretarias_validador: secVal
  }
  showModalEditar.value = true
}

async function salvarEditarUsuario() {
  if (!formEditar.value.nome.trim()) {
    toast.warning('O nome do usuário é obrigatório.')
    return
  }
  if (formEditar.value.email.trim()) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!emailRegex.test(formEditar.value.email.trim())) {
      toast.warning('Informe um endereço de e-mail válido.')
      return
    }
  }
  if (!formEditar.value.roles.length) {
    toast.warning('Selecione pelo menos uma função para o usuário.')
    return
  }
  if (!formEditar.value.roles.includes('validador')) {
    formEditar.value.secretarias_validador = []
  }
  try {
    salvandoEditar.value = true
    const res = await fetch(`/api/admin/usuarios/${formEditar.value.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formEditar.value)
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      showModalEditar.value = false
      toast.success('Usuário atualizado com sucesso!')
      await carregarEquipe()
    } else {
      toast.error(data.detail || 'Erro ao atualizar usuário.')
    }
  } catch (err) {
    toast.error('Erro de conexão ao atualizar.')
  } finally {
    salvandoEditar.value = false
  }
}

function confirmarExcluir(u) {
  usuarioExcluir.value = u
  showModalExcluir.value = true
}

async function confirmarRedefinirSenhaEmail(u) {
  if (!u.email) {
    toast.error('Este usuário não possui e-mail cadastrado. Edite o usuário e adicione um e-mail válido antes de resetar a senha.')
    return
  }

  const confirmed = await confirmModal({
    title: 'Resetar Senha de Acesso',
    message: `Deseja gerar uma nova senha provisória para "${u.nome}" e enviá-la para o e-mail (${u.email})?\n\nQualquer sessão ativa será desconectada e o usuário será obrigado a cadastrar uma nova senha pessoal definitiva no próximo login.`,
    confirmText: 'Resetar e Enviar E-mail',
    variant: 'warning'
  })
  if (!confirmed) return

  try {
    const res = await fetch(`/api/admin/usuarios/${u.id}/redefinir-senha-email`, {
      method: 'POST'
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      toast.success(data.mensagem || 'Nova senha enviada com sucesso!')
      await carregarEquipe(true)
    } else {
      toast.error(data.detail || 'Erro ao redefinir senha.')
    }
  } catch {
    toast.error('Erro de conexão ao redefinir senha.')
  }
}

async function executarExcluir() {
  if (!usuarioExcluir.value) return
  try {
    excluindo.value = true
    const res = await fetch(`/api/admin/usuarios/${usuarioExcluir.value.id}`, {
      method: 'DELETE'
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      showModalExcluir.value = false
      toast.success('Usuário excluído com sucesso!')
      await carregarEquipe()
    } else {
      toast.error(data.detail || 'Erro ao excluir usuário.')
    }
  } catch (err) {
    toast.error('Erro de conexão ao excluir.')
  } finally {
    excluindo.value = false
  }
}

function podeGerenciarUsuario(u) {
  if (isAdminGeral.value) return true
  const targetRoles = u.roles || [u.role]
  return !targetRoles.includes('admin_geral') && !targetRoles.includes('admin')
}

onMounted(async () => {
  await carregarEquipe(false)
  pollInterval = setInterval(() => {
    if (!document.hidden && !showModalCriar.value && !showModalEditar.value && !showModalExcluir.value) {
      carregarEquipe(true)
    }
  }, 3000)
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

    <!-- CABEÇALHO DA PÁGINA -->
    <div class="admin-header-row mb-4">
      <div>
        <span class="badge-cyber mb-2 d-inline-flex align-items-center">
          <i class="bi bi-shield-lock-fill me-1 text-cyan"></i> PAINEL ADMINISTRATIVO
        </span>
        <h1 class="page-title font-quattrocento">Gestão da Equipe & Permissões</h1>
        <p class="page-subtitle">Controle de acessos de Administradores Gerais, Administradores, Portaria e Entregadores.</p>
      </div>

      <div class="admin-header-actions d-flex flex-wrap gap-2">
        <button type="button" class="btn-primary" @click="abrirModalCriar">
          <i class="bi bi-person-plus-fill me-1"></i> Novo Membro da Equipe
        </button>
        <button type="button" class="btn-secondary" :disabled="loading" @click="carregarEquipe()">
          <i class="bi bi-arrow-clockwise me-1" :class="{ 'spin-anim': loading }"></i> Atualizar
        </button>
      </div>
    </div>

    <!-- CARDS DE KPI CANÔNICOS DA EQUIPE -->
    <div class="kpi-grid mb-4">
      <KpiCard
        title="Administradores Gerais"
        :value="kpis.admin_geral_total"
        subtitle="Acesso total e gestão irrestrita"
        icon="bi bi-shield-fill-check"
        variant="danger"
        :badge-text="kpis.admin_geral_logados + ' logado(s)'"
        :badge-pulse="kpis.admin_geral_logados > 0"
      />

      <KpiCard
        title="Administradores"
        :value="kpis.admin_total"
        subtitle="Sorteios, visualização e operação"
        icon="bi bi-shield-shaded"
        variant="warning"
        :badge-text="kpis.admin_logados + ' logado(s)'"
        :badge-pulse="kpis.admin_logados > 0"
      />

      <KpiCard
        title="Equipe de Portaria"
        :value="kpis.portaria_total"
        subtitle="Validação de entrada e saída"
        icon="bi bi-qr-code-scan"
        variant="cyan"
        :badge-text="kpis.portaria_logados + ' logado(s)'"
        :badge-pulse="kpis.portaria_logados > 0"
      />

      <KpiCard
        title="Entregadores de Prêmios"
        :value="kpis.entregadores_total"
        subtitle="Registro e foto de entregas"
        icon="bi bi-gift-fill"
        variant="emerald"
        :badge-text="kpis.entregadores_logados + ' logado(s)'"
        :badge-pulse="kpis.entregadores_logados > 0"
      />
    </div>

    <!-- BARRA DE FERRAMENTAS E FILTROS -->
    <div class="filter-card mb-4">
      <div class="filter-grid" style="grid-template-columns: 2fr 1fr 1fr;">
        <div class="search-box">
          <i class="bi bi-search search-icon"></i>
          <input
            v-model="busca"
            type="text"
            class="form-control"
            placeholder="Buscar por Nome, CPF, Telefone..."
          />
          <button v-if="busca" type="button" class="btn-clear-search" @click="busca = ''">
            <i class="bi bi-x"></i>
          </button>
        </div>

        <div>
          <DropdownSelect
            v-model="filtroRole"
            :options="optionsRoles"
            placeholder="Todas as Funções"
            icon="bi bi-person-badge"
          />
        </div>

        <div>
          <DropdownSelect
            v-model="filtroStatus"
            :options="optionsStatus"
            placeholder="Status: Todos"
            icon="bi bi-circle-fill"
          />
        </div>
      </div>
    </div>

    <!-- TABELA DA EQUIPE -->
    <div class="table-card">
      <div class="table-header-box">
        <h2 class="table-title font-quattrocento">
          <i class="bi bi-person-gear text-cyan me-2"></i>
          Membros da Equipe Cadastrados
          <span class="table-badge-count">{{ usuariosFiltrados.length }}</span>
        </h2>
      </div>

      <div v-if="loading && !usuarios.length" class="table-loading-state">
        <div class="spinner-border text-cyan mb-2"></div>
        <p>Carregando equipe...</p>
      </div>

      <div v-else-if="!usuariosFiltrados.length" class="table-empty-state">
        <i class="bi bi-inbox fs-1 mb-2 d-block opacity-50"></i>
        <p>Nenhum membro da equipe encontrado.</p>
      </div>

            <!-- GRID DE CARDS CANÔNICO DE USUÁRIOS E EQUIPE -->
      <div v-else class="entity-cards-grid">
        <div
          v-for="u in usuariosFiltrados"
          :key="u.id"
          :class="['entity-card', u.is_logado ? 'entity-card--presente' : 'entity-card--neutral']"
        >
          <!-- 1. Topo: CPF à esquerda, Status de Sessão à direita -->
          <div class="entity-card-top-bar">
            <span class="table-code-pill font-monospace">{{ u.cpf_formatado }}</span>

            <!-- Status de Sessão Ativa -->
            <span v-if="u.is_logado" class="status-pill status-pill--presente">
              <i class="bi bi-circle-fill dot-active"></i> Online
            </span>
            <span v-else class="status-pill status-pill--neutral" :title="'Último acesso: ' + (u.ultimo_acesso || 'Nunca')">
              <i class="bi bi-clock-history"></i> Offline
            </span>
          </div>

          <!-- 2. Identidade: Avatar com Iniciais + Nome e Contato em Largura Total -->
          <div class="entity-card-identity">
            <div class="entity-card-avatar" :title="u.nome">
              <div class="entity-card-avatar-fallback">
                <span>{{ obterIniciais(u.nome) }}</span>
              </div>
            </div>

            <div class="entity-card-info">
              <h3 class="entity-card-title">{{ u.nome }}</h3>
              <div class="entity-card-sub">
                <small v-if="u.telefone" class="text-muted d-inline-flex align-items-center">
                  <i class="bi bi-telephone-fill me-1 text-cyan"></i>{{ u.telefone }}
                </small>
                <small v-else class="text-muted opacity-50">
                  <i class="bi bi-telephone me-1"></i>Sem telefone
                </small>
              </div>
              <div v-if="u.email" class="text-muted small mt-1 text-truncate" :title="u.email">
                <i class="bi bi-envelope me-1"></i>{{ u.email }}
              </div>
            </div>
          </div>

          <!-- 3. Metadados: Funções e Situação da Conta -->
          <div class="entity-meta-grid">
            <!-- Funções / Permissões Atribuídas -->
            <div class="entity-meta-item full-width">
              <span class="meta-label">Funções Atribuídas</span>
              <div class="d-flex flex-wrap gap-1 mt-1">
                <span
                  v-for="r in (u.roles || [u.role])"
                  :key="r"
                  class="role-badge"
                  :class="'role-' + r"
                >
                  <i v-if="r === 'admin_geral'" class="bi bi-shield-fill-check me-1"></i>
                  <i v-else-if="r === 'admin'" class="bi bi-shield-shaded me-1"></i>
                  <i v-else-if="r === 'validador'" class="bi bi-person-check-fill me-1"></i>
                  <i v-else-if="r === 'portaria'" class="bi bi-qr-code-scan me-1"></i>
                  <i v-else-if="r === 'entregador'" class="bi bi-gift-fill me-1"></i>
                  {{ r === 'admin_geral' ? 'Admin Geral' : r === 'admin' ? 'Administrador' : r === 'validador' ? 'Validador' : r === 'portaria' ? 'Portaria' : r === 'entregador' ? 'Entregador' : r }}
                </span>
              </div>
            </div>

            <!-- Status de Ativação / Senha -->
            <div class="entity-meta-item full-width">
              <span class="meta-label">Situação da Conta</span>
              <div class="mt-1">
                <span v-if="u.deve_trocar_senha" class="badge-pass bg-pending-pass" title="Usuário cadastrado com senha provisória, aguardando primeiro acesso para ativação">
                  <i class="bi bi-hourglass-split me-1"></i> Aguardando Ativação
                </span>
                <span v-else-if="u.has_senha" class="badge-pass bg-has-pass" title="Conta ativa com senha pessoal definitiva cadastrada">
                  <i class="bi bi-shield-check me-1"></i> Conta Ativada
                </span>
                <span v-else class="badge-pass bg-no-pass" title="Usuário sem credencial de acesso">
                  <i class="bi bi-unlock me-1"></i> Sem Senha
                </span>
              </div>
            </div>
          </div>

          <!-- 4. Rodapé: Ações de Gestão do Membro -->
          <div class="entity-card-footer justify-end">
            <div class="d-flex align-items-center gap-1">
              <button
                type="button"
                class="btn-action-icon btn-action-icon--cyan"
                :title="podeGerenciarUsuario(u) ? 'Editar Usuário' : 'Apenas Administrador Geral pode editar este usuário'"
                :disabled="!podeGerenciarUsuario(u)"
                @click="abrirModalEditar(u)"
              >
                <i class="bi bi-pencil-fill"></i>
              </button>

              <button
                type="button"
                class="btn-action-icon btn-action-icon--amber"
                :title="podeGerenciarUsuario(u) ? 'Resetar Senha (Enviar provisória por e-mail)' : 'Apenas Administrador Geral pode alterar a senha deste usuário'"
                :disabled="!podeGerenciarUsuario(u)"
                @click="confirmarRedefinirSenhaEmail(u)"
              >
                <i class="bi bi-arrow-clockwise"></i>
              </button>

              <button
                type="button"
                class="btn-action-icon btn-action-icon--danger"
                :title="podeGerenciarUsuario(u) ? 'Excluir Usuário' : 'Apenas Administrador Geral pode excluir este usuário'"
                :disabled="!podeGerenciarUsuario(u)"
                @click="confirmarExcluir(u)"
              >
                <i class="bi bi-trash-fill"></i>
              </button>
            </div>
          </div>

        </div>
      </div>
    </div>
    </div>

    <!-- MODAL CRIAR USUÁRIO -->
    <Modal
      :show="showModalCriar"
      title="Cadastrar Novo Membro da Equipe"
      icon="bi-person-plus-fill"
      :max-width="'640px'"
      @close="showModalCriar = false"
    >
      <form @submit.prevent="salvarCriarUsuario">
        <div class="form-group mb-3">
          <label class="form-label">Nome Completo: *</label>
          <input v-model="formCriar.nome" type="text" class="form-control" placeholder="Ex: Carlos Andrade" required />
        </div>

        <div class="row g-3 mb-3">
          <div class="col-md-6 form-group">
            <label class="form-label">CPF (11 dígitos): *</label>
            <input
              v-model="formCriar.cpf"
              type="tel"
              inputmode="numeric"
              maxlength="14"
              class="form-control font-monospace"
              placeholder="000.000.000-00"
              required
              @input="onCpfInput"
            />
          </div>

          <div class="col-md-6 form-group">
            <label class="form-label">E-mail: *</label>
            <input
              v-model="formCriar.email"
              type="email"
              class="form-control"
              placeholder="exemplo@caruaru.pe.gov.br"
              required
            />
          </div>
        </div>

        <div class="form-group mb-3">
          <label class="form-label">Telefone / WhatsApp (11 dígitos):</label>
          <input
            v-model="formCriar.telefone"
            type="tel"
            inputmode="numeric"
            maxlength="15"
            class="form-control"
            placeholder="(81) 90000-0000"
            @input="onTelefoneInputCriar"
          />
        </div>

        <div class="modal-alert-card mb-3" style="border-left: 4px solid var(--primary-accent);">
          <div class="d-flex align-items-start gap-2">
            <i class="bi bi-envelope-check-fill text-cyan fs-5"></i>
            <div>
              <strong class="text-cyan d-block">Envio Automático de Senha Provisória</strong>
              <p class="mb-0 small text-light">
                Uma mensagem de apresentação com senha temporária será enviada automaticamente para o e-mail cadastrado.
              </p>
            </div>
          </div>
        </div>

        <div class="form-group mb-4">
          <label class="form-label">Funções / Permissões de Acesso: *</label>
          <div class="roles-selection-box">
            
            <label v-if="isAdminGeral" class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formCriar.roles.includes('admin_geral')"
                @change="toggleRole(formCriar.roles, 'admin_geral')"
              />
              <div class="role-desc-wrap">
                <strong class="text-danger"><i class="bi bi-shield-fill-check me-1"></i> Administrador Geral</strong>
                <p>Acesso total: CRUD de Lotes, cancelar participantes e gerenciar administradores.</p>
              </div>
            </label>

            <label v-if="isAdminGeral" class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formCriar.roles.includes('admin')"
                @change="toggleRole(formCriar.roles, 'admin')"
              />
              <div class="role-desc-wrap">
                <strong class="text-warning"><i class="bi bi-shield-shaded me-1"></i> Administrador</strong>
                <p>Mesa de Sorteios, visualização de participantes e gestão de portaria/entregadores.</p>
              </div>
            </label>

            <label class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formCriar.roles.includes('validador')"
                @change="toggleRole(formCriar.roles, 'validador')"
              />
              <div class="role-desc-wrap">
                <strong class="text-emerald"><i class="bi bi-person-check-fill me-1"></i> Validador de Servidores</strong>
                <p>Homologação manual de servidores pendentes e controle de lotes.</p>
              </div>
            </label>

            <div v-if="formCriar.roles.includes('validador')" class="sec-assignment-box">
              <label class="sec-assign-label">Secretarias sob responsabilidade (Sem seleção = Nenhuma secretaria atribuída):</label>
              <div class="sec-checks-grid">
                <label v-for="sec in secretariasDisponiveis" :key="sec.id" class="sec-check-item">
                  <input
                    type="checkbox"
                    :checked="formCriar.secretarias_validador.includes(sec.id)"
                    @change="toggleSecId(formCriar.secretarias_validador, sec.id)"
                  />
                  <span>{{ sec.nome }}</span>
                </label>
              </div>
            </div>

            <label class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formCriar.roles.includes('portaria')"
                @change="toggleRole(formCriar.roles, 'portaria')"
              />
              <div class="role-desc-wrap">
                <strong class="text-cyan"><i class="bi bi-qr-code-scan me-1"></i> Portaria / Scanner</strong>
                <p>Acesso exclusivo ao scanner e controle de entrada/saída de participantes.</p>
              </div>
            </label>

            <label class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formCriar.roles.includes('entregador')"
                @change="toggleRole(formCriar.roles, 'entregador')"
              />
              <div class="role-desc-wrap">
                <strong class="text-info"><i class="bi bi-gift-fill me-1"></i> Entregador de Prêmios</strong>
                <p>Acesso exclusivo ao registro fotográfico e confirmação de entrega de prêmios.</p>
              </div>
            </label>

          </div>
        </div>

        <div class="d-flex align-items-center justify-content-end gap-2">
          <button type="button" class="btn-secondary" @click="showModalCriar = false">Cancelar</button>
          <button type="submit" class="btn-primary" :disabled="salvandoCriar">
            <span v-if="!salvandoCriar">Cadastrar Usuário</span>
            <span v-else>Salvando...</span>
          </button>
        </div>
      </form>
    </Modal>

    <!-- MODAL EDITAR USUÁRIO -->
    <Modal
      :show="showModalEditar"
      title="Editar Membro da Equipe"
      icon="bi-pencil-square"
      :max-width="'640px'"
      @close="showModalEditar = false"
    >
      <form @submit.prevent="salvarEditarUsuario">
        <div class="form-group mb-3">
          <label class="form-label">Nome Completo: *</label>
          <input v-model="formEditar.nome" type="text" class="form-control" required />
        </div>

        <div class="row g-3 mb-3">
          <div class="col-md-6 form-group">
            <label class="form-label">E-mail: *</label>
            <input v-model="formEditar.email" type="email" class="form-control" placeholder="exemplo@caruaru.pe.gov.br" required />
          </div>

          <div class="col-md-6 form-group">
            <label class="form-label">Telefone / WhatsApp (11 dígitos):</label>
            <input
              v-model="formEditar.telefone"
              type="tel"
              inputmode="numeric"
              maxlength="15"
              class="form-control"
              placeholder="(81) 90000-0000"
              @input="onTelefoneInputEditar"
            />
          </div>
        </div>

        <div class="form-group mb-4">
          <label class="form-label">Funções / Permissões Atribuídas: *</label>
          <div class="roles-selection-box">
            
            <label v-if="isAdminGeral" class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formEditar.roles.includes('admin_geral')"
                @change="toggleRole(formEditar.roles, 'admin_geral')"
              />
              <div class="role-desc-wrap">
                <strong class="text-danger"><i class="bi bi-shield-fill-check me-1"></i> Administrador Geral</strong>
                <p>Acesso total: CRUD de Lotes, cancelar participantes e gerenciar administradores.</p>
              </div>
            </label>

            <label v-if="isAdminGeral" class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formEditar.roles.includes('admin')"
                @change="toggleRole(formEditar.roles, 'admin')"
              />
              <div class="role-desc-wrap">
                <strong class="text-warning"><i class="bi bi-shield-shaded me-1"></i> Administrador</strong>
                <p>Mesa de Sorteios, visualização de participantes e gestão de portaria/entregadores.</p>
              </div>
            </label>

            <label class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formEditar.roles.includes('validador')"
                @change="toggleRole(formEditar.roles, 'validador')"
              />
              <div class="role-desc-wrap">
                <strong class="text-emerald"><i class="bi bi-person-check-fill me-1"></i> Validador de Servidores</strong>
                <p>Homologação manual de servidores pendentes e controle de lotes.</p>
              </div>
            </label>

            <div v-if="formEditar.roles.includes('validador')" class="sec-assignment-box">
              <label class="sec-assign-label">Secretarias sob responsabilidade (Sem seleção = Nenhuma secretaria atribuída):</label>
              <div class="sec-checks-grid">
                <label v-for="sec in secretariasDisponiveis" :key="sec.id" class="sec-check-item">
                  <input
                    type="checkbox"
                    :checked="formEditar.secretarias_validador.includes(sec.id)"
                    @change="toggleSecId(formEditar.secretarias_validador, sec.id)"
                  />
                  <span>{{ sec.nome }}</span>
                </label>
              </div>
            </div>

            <label class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formEditar.roles.includes('portaria')"
                @change="toggleRole(formEditar.roles, 'portaria')"
              />
              <div class="role-desc-wrap">
                <strong class="text-cyan"><i class="bi bi-qr-code-scan me-1"></i> Portaria / Scanner</strong>
                <p>Acesso exclusivo ao scanner e controle de entrada/saída de participantes.</p>
              </div>
            </label>

            <label class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formEditar.roles.includes('entregador')"
                @change="toggleRole(formEditar.roles, 'entregador')"
              />
              <div class="role-desc-wrap">
                <strong class="text-info"><i class="bi bi-gift-fill me-1"></i> Entregador de Prêmios</strong>
                <p>Acesso exclusivo ao registro fotográfico e confirmação de entrega de prêmios.</p>
              </div>
            </label>

          </div>
        </div>

        <div class="d-flex align-items-center justify-content-end gap-2">
          <button type="button" class="btn-secondary" @click="showModalEditar = false">Cancelar</button>
          <button type="submit" class="btn-primary" :disabled="salvandoEditar">
            <span v-if="!salvandoEditar">Salvar Alterações</span>
            <span v-else>Salvando...</span>
          </button>
        </div>
      </form>
    </Modal>

    <!-- MODAL EXCLUIR USUÁRIO -->
    <Modal
      :show="showModalExcluir"
      title="Excluir Usuário da Equipe?"
      icon="bi-exclamation-triangle-fill"
      icon-color="text-danger"
      :max-width="'480px'"
      @close="showModalExcluir = false"
    >
      <p class="text-white">
        Deseja remover <strong>{{ usuarioExcluir?.nome }}</strong> da equipe?
      </p>
      <p class="text-danger small mb-0">
        Esta ação revogará o acesso deste usuário a todos os painéis e ferramentas operacionais.
      </p>

      <template #footer>
        <div class="d-flex align-items-center justify-content-end gap-2 w-100">
          <button type="button" class="btn-secondary" @click="showModalExcluir = false">Cancelar</button>
          <button type="button" class="btn-danger" :disabled="excluindo" @click="executarExcluir">
            <span v-if="!excluindo">Sim, Excluir Usuário</span>
            <span v-else>Excluindo...</span>
          </button>
        </div>
      </template>
    </Modal>

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
