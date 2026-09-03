<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import Modal from '../components/Modal.vue'

const router = useRouter()
const { currentUser, isAdminGeral } = useAuth()

const loading = ref(true)
const usuarios = ref([])
const kpis = ref({
  admin_geral_total: 0,
  admin_geral_logados: 0,
  admin_total: 0,
  admin_logados: 0,
  portaria_total: 0,
  portaria_logados: 0,
  entregadores_total: 0,
  entregadores_logados: 0
})

// Filtros
const busca = ref('')
const filtroRole = ref('')
const filtroStatus = ref('todos') // 'todos', 'logado', 'offline'

// Modal Criar
const showModalCriar = ref(false)
const salvandoCriar = ref(false)
const formCriar = ref({
  nome: '',
  cpf: '',
  telefone: '',
  roles: ['portaria'],
  senha: ''
})

// Modal Editar
const showModalEditar = ref(false)
const salvandoEditar = ref(false)
const formEditar = ref({
  id: null,
  nome: '',
  telefone: '',
  roles: []
})

// Modal Senha
const showModalSenha = ref(false)
const salvandoSenha = ref(false)
const formSenha = ref({
  id: null,
  nome: '',
  nova_senha: ''
})

// Modal Excluir
const showModalExcluir = ref(false)
const usuarioExcluir = ref(null)
const excluindo = ref(false)

// MÁSCARAS E LIMITADORES DE 11 DÍGITOS
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
    kpis.value = data.kpis || {
      admin_geral_total: 0, admin_geral_logados: 0,
      admin_total: 0, admin_logados: 0,
      portaria_total: 0, portaria_logados: 0,
      entregadores_total: 0, entregadores_logados: 0
    }
  } catch (e) {
    if (!silent) console.error('Erro ao carregar equipe:', e)
  } finally {
    if (!silent) loading.value = false
  }
}

// Filtragem
const usuariosFiltrados = computed(() => {
  return usuarios.value.filter(u => {
    // Busca
    if (busca.value.trim()) {
      const q = busca.value.toLowerCase().trim()
      const matchNome = (u.nome || '').toLowerCase().includes(q)
      const matchCpf = (u.cpf || '').includes(q)
      const matchTel = (u.telefone || '').includes(q)
      if (!matchNome && !matchCpf && !matchTel) {
        return false
      }
    }

    // Filtro de Role
    if (filtroRole.value) {
      if (!u.roles || !u.roles.includes(filtroRole.value)) return false
    }

    // Filtro de Sessão
    if (filtroStatus.value === 'logado' && !u.is_logado) return false
    if (filtroStatus.value === 'offline' && u.is_logado) return false

    return true
  })
})

function toggleRole(arrayRef, role) {
  const index = arrayRef.indexOf(role)
  if (index > -1) {
    if (arrayRef.length > 1) {
      arrayRef.splice(index, 1)
    }
  } else {
    arrayRef.push(role)
  }
}

function abrirModalCriar() {
  formCriar.value = {
    nome: '',
    cpf: '',
    telefone: '',
    roles: ['portaria'],
    senha: ''
  }
  showModalCriar.value = true
}

async function salvarCriarUsuario() {
  if (!formCriar.value.nome.trim() || !formCriar.value.cpf.trim()) {
    alert('Nome e CPF são obrigatórios.')
    return
  }
  if (!formCriar.value.roles.length) {
    alert('Selecione pelo menos uma função para o usuário.')
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
      await carregarEquipe()
    } else {
      alert(data.detail || 'Erro ao criar usuário.')
    }
  } catch (err) {
    alert('Erro de conexão ao criar usuário.')
  } finally {
    salvandoCriar.value = false
  }
}

function abrirModalEditar(u) {
  formEditar.value = {
    id: u.id,
    nome: u.nome,
    telefone: formatTelefone(u.telefone || ''),
    roles: [...(u.roles || [u.role])]
  }
  showModalEditar.value = true
}

async function salvarEditarUsuario() {
  if (!formEditar.value.roles.length) {
    alert('Selecione pelo menos uma função para o usuário.')
    return
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
      await carregarEquipe()
    } else {
      alert(data.detail || 'Erro ao atualizar usuário.')
    }
  } catch (err) {
    alert('Erro de conexão ao atualizar.')
  } finally {
    salvandoEditar.value = false
  }
}

function abrirModalSenha(u) {
  formSenha.value = {
    id: u.id,
    nome: u.nome,
    nova_senha: ''
  }
  showModalSenha.value = true
}

async function salvarNovaSenha() {
  if (!formSenha.value.nova_senha.trim()) {
    alert('Digite a nova senha.')
    return
  }
  try {
    salvandoSenha.value = true
    const res = await fetch(`/api/admin/usuarios/${formSenha.value.id}/senha`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nova_senha: formSenha.value.nova_senha.trim() })
    })
    const data = await res.json()
    if (res.ok && data.sucesso) {
      showModalSenha.value = false
      await carregarEquipe()
    } else {
      alert(data.detail || 'Erro ao alterar senha.')
    }
  } catch (err) {
    alert('Erro de conexão ao redefinir senha.')
  } finally {
    salvandoSenha.value = false
  }
}

function confirmarExcluir(u) {
  usuarioExcluir.value = u
  showModalExcluir.value = true
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
      await carregarEquipe()
    } else {
      alert(data.detail || 'Erro ao excluir usuário.')
    }
  } catch (err) {
    alert('Erro de conexão ao excluir.')
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
    // Não atualiza durante digitação em modais para não interferir
    if (!document.hidden && !showModalCriar.value && !showModalEditar.value && !showModalSenha.value && !showModalExcluir.value) {
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
      <div class="admin-header-row">
        <div>
          <span class="vip-badge bg-primary mb-2">
            <i class="bi bi-shield-lock-fill me-1"></i> PAINEL ADMINISTRATIVO
          </span>
          <h1 class="admin-title font-outfit">Gestão da Equipe & Permissões</h1>
          <p class="admin-subtitle">Controle de acessos de Administradores Gerais, Administradores, Portaria e Entregadores.</p>
        </div>

        <div class="header-actions">
          <button type="button" class="btn-primary" @click="abrirModalCriar">
            <i class="bi bi-person-plus-fill me-1"></i> Novo Membro da Equipe
          </button>
          <button type="button" class="btn-secondary" @click="carregarEquipe">
            <i class="bi bi-arrow-clockwise me-1"></i> Atualizar
          </button>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- CARDS DE KPI ESPECÍFICOS DA EQUIPE             -->
      <!-- ============================================== -->
      <div class="metrics-grid">
        
        <!-- 1. Administradores Gerais -->
        <div class="metric-card">
          <div class="metric-icon-box bg-red">
            <i class="bi bi-shield-fill-check"></i>
          </div>
          <div class="metric-info">
            <span class="metric-label">Administradores Gerais</span>
            <div class="metric-value font-outfit">
              {{ kpis.admin_geral_total }}
              <span class="metric-status-tag" :class="kpis.admin_geral_logados > 0 ? 'tag-online' : 'tag-offline'">
                {{ kpis.admin_geral_logados }} logado(s)
              </span>
            </div>
            <span class="metric-sublabel text-muted">Acesso total e gestão irrestrita</span>
          </div>
        </div>

        <!-- 2. Administradores -->
        <div class="metric-card">
          <div class="metric-icon-box bg-purple">
            <i class="bi bi-shield-shaded"></i>
          </div>
          <div class="metric-info">
            <span class="metric-label">Administradores</span>
            <div class="metric-value font-outfit">
              {{ kpis.admin_total }}
              <span class="metric-status-tag" :class="kpis.admin_logados > 0 ? 'tag-online' : 'tag-offline'">
                {{ kpis.admin_logados }} logado(s)
              </span>
            </div>
            <span class="metric-sublabel text-muted">Sorteios, visualização e operação</span>
          </div>
        </div>

        <!-- 3. Portaria -->
        <div class="metric-card">
          <div class="metric-icon-box bg-blue">
            <i class="bi bi-qr-code-scan"></i>
          </div>
          <div class="metric-info">
            <span class="metric-label">Equipe de Portaria</span>
            <div class="metric-value font-outfit">
              {{ kpis.portaria_total }}
              <span class="metric-status-tag" :class="kpis.portaria_logados > 0 ? 'tag-online' : 'tag-offline'">
                {{ kpis.portaria_logados }} logado(s)
              </span>
            </div>
            <span class="metric-sublabel text-muted">Validação de entrada e saída</span>
          </div>
        </div>

        <!-- 4. Entregadores -->
        <div class="metric-card">
          <div class="metric-icon-box bg-cyan">
            <i class="bi bi-gift-fill"></i>
          </div>
          <div class="metric-info">
            <span class="metric-label">Entregadores de Prêmios</span>
            <div class="metric-value font-outfit">
              {{ kpis.entregadores_total }}
              <span class="metric-status-tag" :class="kpis.entregadores_logados > 0 ? 'tag-online' : 'tag-offline'">
                {{ kpis.entregadores_logados }} logado(s)
              </span>
            </div>
            <span class="metric-sublabel text-muted">Registro e foto de entregas</span>
          </div>
        </div>

      </div>

      <!-- ============================================== -->
      <!-- BARRA DE FERRAMENTAS E FILTROS                 -->
      <!-- ============================================== -->
      <div class="vip-glass-card filter-card mb-4">
        <div class="filter-grid">
          
          <div class="search-box">
            <i class="bi bi-search search-icon"></i>
            <input
              v-model="busca"
              type="text"
              class="form-control filter-input"
              placeholder="Buscar por Nome, CPF, Telefone..."
            />
          </div>

          <div class="select-box">
            <select v-model="filtroRole" class="form-select filter-select">
              <option value="">Todas as Funções</option>
              <option value="admin_geral">Administrador Geral</option>
              <option value="admin">Administrador</option>
              <option value="portaria">Portaria / Scanner</option>
              <option value="entregador">Entregador de Prêmios</option>
            </select>
          </div>

          <div class="select-box">
            <select v-model="filtroStatus" class="form-select filter-select">
              <option value="todos">Status: Todos</option>
              <option value="logado">🟢 Apenas Logados / Ativos</option>
              <option value="offline">⚪ Apenas Offline</option>
            </select>
          </div>

        </div>
      </div>

      <!-- ============================================== -->
      <!-- TABELA DA EQUIPE                               -->
      <!-- ============================================== -->
      <div class="vip-glass-card table-card">
        
        <div class="table-header-box">
          <div class="table-title font-outfit">
            <i class="bi bi-person-gear text-primary me-2"></i>
            <span>Membros da Equipe Cadastrados</span>
            <span class="badge-count ms-2">{{ usuariosFiltrados.length }}</span>
          </div>
        </div>

        <div v-if="loading" class="text-center py-5 text-muted">
          <div class="spinner-border text-primary mb-2"></div>
          <p>Carregando equipe...</p>
        </div>

        <div v-else-if="!usuariosFiltrados.length" class="text-center py-5 text-muted">
          <i class="bi bi-inbox fs-1 mb-2 d-block"></i>
          <p>Nenhum membro da equipe encontrado.</p>
        </div>

        <div v-else class="table-responsive">
          <table class="custom-table">
            <thead>
              <tr>
                <th>Membro / Telefone</th>
                <th>CPF</th>
                <th>Funções / Permissões Atribuídas</th>
                <th>Status de Acesso</th>
                <th>Senha</th>
                <th class="text-end">Ações</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in usuariosFiltrados" :key="u.id">
                
                <!-- Membro / Telefone -->
                <td>
                  <strong class="text-white d-block">{{ u.nome }}</strong>
                  <small v-if="u.telefone" class="text-muted">
                    <i class="bi bi-telephone-fill me-1 text-primary"></i>{{ u.telefone }}
                  </small>
                  <small v-else class="text-muted opacity-50">
                    <i class="bi bi-telephone me-1"></i>Sem telefone
                  </small>
                </td>

                <!-- CPF -->
                <td>
                  <span class="font-monospace text-primary fw-bold">{{ u.cpf_formatado }}</span>
                </td>

                <!-- Múltiplas Funções Atribuídas -->
                <td>
                  <div class="roles-chips-wrapper">
                    <span
                      v-for="r in (u.roles || [u.role])"
                      :key="r"
                      class="role-badge"
                      :class="'role-' + r"
                    >
                      <i v-if="r === 'admin_geral'" class="bi bi-shield-fill-check me-1"></i>
                      <i v-else-if="r === 'admin'" class="bi bi-shield-shaded me-1"></i>
                      <i v-else-if="r === 'portaria'" class="bi bi-qr-code-scan me-1"></i>
                      <i v-else-if="r === 'entregador'" class="bi bi-gift-fill me-1"></i>
                      {{ r === 'admin_geral' ? 'Admin Geral' : r === 'admin' ? 'Administrador' : r === 'portaria' ? 'Portaria' : r === 'entregador' ? 'Entregador' : r }}
                    </span>
                  </div>
                </td>

                <!-- Status de Acesso -->
                <td>
                  <span v-if="u.is_logado" class="session-badge session-online">
                    <i class="bi bi-circle-fill me-1 dot-active"></i> Logado / Ativo
                  </span>
                  <span v-else class="session-badge session-offline">
                    <i class="bi bi-clock-history me-1"></i> {{ u.ultimo_acesso }}
                  </span>
                </td>

                <!-- Senha -->
                <td>
                  <span v-if="u.has_senha" class="badge-pass bg-has-pass">
                    <i class="bi bi-lock-fill me-1"></i> Configurada
                  </span>
                  <span v-else class="badge-pass bg-no-pass">
                    <i class="bi bi-unlock me-1"></i> Sem Senha
                  </span>
                </td>

                <!-- Ações -->
                <td class="text-end">
                  <div class="action-buttons-group">
                    <button
                      type="button"
                      class="btn-action-icon text-info"
                      :title="podeGerenciarUsuario(u) ? 'Editar Usuário' : 'Apenas Administrador Geral pode editar este usuário'"
                      :disabled="!podeGerenciarUsuario(u)"
                      @click="abrirModalEditar(u)"
                    >
                      <i class="bi bi-pencil-fill"></i>
                    </button>

                    <button
                      type="button"
                      class="btn-action-icon text-warning"
                      :title="podeGerenciarUsuario(u) ? 'Redefinir Senha' : 'Apenas Administrador Geral pode alterar a senha deste usuário'"
                      :disabled="!podeGerenciarUsuario(u)"
                      @click="abrirModalSenha(u)"
                    >
                      <i class="bi bi-key-fill"></i>
                    </button>

                    <button
                      type="button"
                      class="btn-action-icon text-danger"
                      :title="podeGerenciarUsuario(u) ? 'Excluir Usuário' : 'Apenas Administrador Geral pode excluir este usuário'"
                      :disabled="!podeGerenciarUsuario(u)"
                      @click="confirmarExcluir(u)"
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

    <!-- MODAL CRIAR USUÁRIO -->
    <Modal
      :show="showModalCriar"
      title="Cadastrar Novo Membro da Equipe"
      icon="bi-person-plus-fill"
      @close="showModalCriar = false"
    >
      <form @submit.prevent="salvarCriarUsuario">
        <div class="form-group">
          <label class="form-label">Nome Completo: *</label>
          <input v-model="formCriar.nome" type="text" class="form-control" placeholder="Ex: Carlos Andrade" required />
        </div>

        <div class="form-grid-modal">
          <!-- CPF com Formatação Automática e Limitação de 11 Dígitos -->
          <div class="form-group">
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

          <!-- Telefone com Formatação Automática e Limitação de 11 Dígitos -->
          <div class="form-group">
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
        </div>

        <!-- MÚLTIPLAS ROLES / CHECKBOXES -->
        <div class="form-group">
          <label class="form-label">Funções / Permissões de Acesso (Selecione 1 ou mais): *</label>
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
                <strong class="text-purple"><i class="bi bi-shield-shaded me-1"></i> Administrador</strong>
                <p>Mesa de Sorteios, visualização de participantes e gestão de portaria/entregadores.</p>
              </div>
            </label>

            <label class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formCriar.roles.includes('portaria')"
                @change="toggleRole(formCriar.roles, 'portaria')"
              />
              <div class="role-desc-wrap">
                <strong class="text-primary"><i class="bi bi-qr-code-scan me-1"></i> Portaria / Scanner</strong>
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

        <div class="form-group">
          <label class="form-label">Senha de Acesso ao Painel: *</label>
          <input v-model="formCriar.senha" type="password" class="form-control" placeholder="Digite uma senha forte" required />
        </div>

        <div class="modal-footer-box">
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
      @close="showModalEditar = false"
    >
      <form @submit.prevent="salvarEditarUsuario">
        <div class="form-group">
          <label class="form-label">Nome Completo:</label>
          <input v-model="formEditar.nome" type="text" class="form-control" required />
        </div>

        <!-- Telefone com Formatação Automática e Limitação de 11 Dígitos -->
        <div class="form-group">
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

        <!-- MÚLTIPLAS ROLES / CHECKBOXES -->
        <div class="form-group">
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
                <strong class="text-purple"><i class="bi bi-shield-shaded me-1"></i> Administrador</strong>
                <p>Mesa de Sorteios, visualização de participantes e gestão de portaria/entregadores.</p>
              </div>
            </label>

            <label class="role-checkbox-item">
              <input
                type="checkbox"
                :checked="formEditar.roles.includes('portaria')"
                @change="toggleRole(formEditar.roles, 'portaria')"
              />
              <div class="role-desc-wrap">
                <strong class="text-primary"><i class="bi bi-qr-code-scan me-1"></i> Portaria / Scanner</strong>
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

        <div class="modal-footer-box">
          <button type="button" class="btn-secondary" @click="showModalEditar = false">Cancelar</button>
          <button type="submit" class="btn-primary" :disabled="salvandoEditar">
            <span v-if="!salvandoEditar">Salvar Alterações</span>
            <span v-else>Salvando...</span>
          </button>
        </div>
      </form>
    </Modal>

    <!-- MODAL REDEFINIR SENHA -->
    <Modal
      :show="showModalSenha"
      :title="'Redefinir Senha de ' + formSenha.nome"
      icon="bi-key-fill"
      @close="showModalSenha = false"
    >
      <form @submit.prevent="salvarNovaSenha">
        <div class="form-group">
          <label class="form-label">Nova Senha de Acesso:</label>
          <input v-model="formSenha.nova_senha" type="password" class="form-control" placeholder="Digite a nova senha..." required />
        </div>

        <div class="modal-footer-box">
          <button type="button" class="btn-secondary" @click="showModalSenha = false">Cancelar</button>
          <button type="submit" class="btn-primary" :disabled="salvandoSenha">
            <span v-if="!salvandoSenha">Atualizar Senha</span>
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
      @close="showModalExcluir = false"
    >
      <p class="text-white">
        Deseja remover <strong>{{ usuarioExcluir?.nome }}</strong> da equipe?
      </p>
      <p class="text-danger small">
        Esta ação revogará o acesso deste usuário a todos os painéis e ferramentas operacionais.
      </p>

      <template #footer>
        <button type="button" class="btn-secondary" @click="showModalExcluir = false">Cancelar</button>
        <button type="button" class="btn-danger" :disabled="excluindo" @click="executarExcluir">
          <span v-if="!excluindo">Sim, Excluir Usuário</span>
          <span v-else>Excluindo...</span>
        </button>
      </template>
    </Modal>

  </div>
</template>

<style scoped>
.admin-page {
  padding: 24px 0 60px;
}

.admin-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 16px;
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.admin-title {
  font-size: clamp(1.6rem, 4vw, 2.1rem);
  font-weight: 800;
  color: #ffffff;
  margin: 0;
}

.admin-subtitle {
  color: var(--text-muted);
  font-size: 0.88rem;
  margin-top: 4px;
}

/* CARDS DE KPI */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.metric-card {
  background: var(--bg-card);
  border: 1px solid var(--border-glass);
  border-radius: 18px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.metric-icon-box {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.6rem;
  flex-shrink: 0;
}

.bg-red { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.bg-purple { background: rgba(168, 85, 247, 0.15); color: #c084fc; }
.bg-blue { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
.bg-cyan { background: rgba(6, 182, 212, 0.15); color: #22d3ee; }

.metric-label {
  display: block;
  font-size: 0.74rem;
  text-transform: uppercase;
  color: var(--text-subtle);
  font-weight: 700;
  letter-spacing: 0.5px;
}

.metric-value {
  font-size: 1.8rem;
  font-weight: 900;
  color: #ffffff;
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.1;
  margin: 4px 0 2px;
}

.metric-status-tag {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 6px;
}

.tag-online {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.35);
}

.tag-offline {
  background: rgba(100, 116, 139, 0.2);
  color: #94a3b8;
  border: 1px solid rgba(100, 116, 139, 0.3);
}

.metric-sublabel {
  font-size: 0.72rem;
  display: block;
}

/* FILTROS */
.filter-card {
  padding: 18px;
  border-radius: 16px;
  margin-bottom: 28px;
}

.filter-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 12px;
}

@media (max-width: 768px) {
  .filter-grid {
    grid-template-columns: 1fr;
  }
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 12px;
  color: #64748b;
}

.filter-input {
  padding-left: 38px;
}

/* TABELA */
.table-card {
  border-radius: 20px;
  overflow: hidden;
}

.table-header-box {
  padding: 18px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.table-title {
  font-size: 1.15rem;
  font-weight: 800;
  color: #ffffff;
  display: flex;
  align-items: center;
}

.badge-count {
  font-size: 0.8rem;
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  padding: 3px 10px;
  border-radius: 999px;
  font-weight: 700;
}

.custom-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.custom-table th {
  padding: 14px 16px;
  font-size: 0.76rem;
  text-transform: uppercase;
  color: var(--text-subtle);
  font-weight: 700;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.custom-table td {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 0.88rem;
  vertical-align: middle;
}

.custom-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.02);
}

/* BADGES DE ROLES */
.roles-chips-wrapper {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.role-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 9px;
  border-radius: 6px;
  font-size: 0.74rem;
  font-weight: 800;
}

.role-admin_geral {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.35);
}

.role-admin {
  background: rgba(168, 85, 247, 0.15);
  color: #c084fc;
  border: 1px solid rgba(168, 85, 247, 0.35);
}

.role-portaria {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.35);
}

.role-entregador {
  background: rgba(6, 182, 212, 0.15);
  color: #22d3ee;
  border: 1px solid rgba(6, 182, 212, 0.35);
}

/* CHECKBOXES DE FUNÇÕES */
.roles-selection-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #090d16;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 12px;
}

.role-checkbox-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.role-checkbox-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.role-checkbox-item input[type="checkbox"] {
  width: 18px;
  height: 18px;
  margin-top: 3px;
  cursor: pointer;
}

.role-desc-wrap strong {
  display: block;
  font-size: 0.88rem;
  margin-bottom: 2px;
}

.role-desc-wrap p {
  margin: 0;
  font-size: 0.76rem;
  color: var(--text-muted);
}

/* SESSÃO BADGE */
.session-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 700;
}

.session-online {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.35);
}

.session-offline {
  background: rgba(100, 116, 139, 0.15);
  color: #94a3b8;
  border: 1px solid rgba(100, 116, 139, 0.25);
}

.dot-active {
  font-size: 0.55rem;
  animation: dotPulse 1.2s infinite;
}

@keyframes dotPulse {
  0% { opacity: 0.4; }
  50% { opacity: 1; }
  100% { opacity: 0.4; }
}

.badge-pass {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 0.74rem;
  font-weight: 600;
}

.bg-has-pass {
  background: rgba(16, 185, 129, 0.12);
  color: #34d399;
}

.bg-no-pass {
  background: rgba(239, 68, 68, 0.12);
  color: #f87171;
}

.action-buttons-group {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.btn-action-icon {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 0.95rem;
}

.btn-action-icon:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.15);
  transform: translateY(-2px);
}

.btn-action-icon:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.form-grid-modal {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

@media (max-width: 576px) {
  .form-grid-modal {
    grid-template-columns: 1fr;
  }
}

.modal-footer-box {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.text-end { text-align: right; }
.text-center { text-align: center; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.ms-2 { margin-left: 8px; }
.d-block { display: block; }
.text-white { color: #ffffff; }
.text-muted { color: #94a3b8; }
.text-primary { color: #38bdf8; }
.text-purple { color: #c084fc; }
.text-info { color: #38bdf8; }
.text-warning { color: #f59e0b; }
.text-danger { color: #ef4444; }
.opacity-50 { opacity: 0.5; }
.font-monospace { font-family: monospace; }
</style>
