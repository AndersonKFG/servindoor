<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import Modal from '../components/Modal.vue'
import { useAuth } from '../composables/useAuth'

const router = useRouter()
const { isAdminGeral, checkAuth } = useAuth()
const loading = ref(true)
const metricas = ref({
  total_vagas: 0,
  total_resgatados: 0,
  total_checkins: 0,
  lotes_abertos: 0,
  taxa_ocupacao: 0
})
const lotes = ref([])
const secretarias = ref([])

// Modais
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

let pollInterval = null

async function carregarDadosAdmin(silent = false) {
  try {
    if (!silent) loading.value = true
    await checkAuth()
    if (!isAdminGeral.value) {
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

    // Se o backend retornou HTML tradicional, fazemos o parse das métricas ou usamos endpoints
    // Para garantir máxima sincronização e reatividade, consultamos os lotes
    try {
      const lotesRes = await fetch('/api/lotes-admin')
      if (lotesRes.ok) {
        const data = await lotesRes.json()
        metricas.value = data.metricas
        lotes.value = data.lotes
        secretarias.value = data.secretarias
      }
    } catch {
      // Fallback
    }

    // Carregar secretarias para o select
    if (secretarias.value.length === 0) {
      secretarias.value = [
        { id: 1, nome: 'Secretaria Municipal de Administração' },
        { id: 2, nome: 'Secretaria Municipal de Educação' },
        { id: 3, nome: 'Secretaria Municipal de Saúde' },
        { id: 4, nome: 'Secretaria Municipal de Obras e Serviços Públicos' },
        { id: 5, nome: 'Secretaria Municipal de Finanças e Fazenda' },
        { id: 6, nome: 'Secretaria Municipal de Assistência Social' },
        { id: 7, nome: 'Gabinete do Prefeito' }
      ]
    }
    if (!silent) loading.value = false
  } catch (err) {
    if (!silent) console.error('Erro carregando admin:', err)
    if (!silent) loading.value = false
  }
}

async function handleCriarLote() {
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

    const res = await fetch('/admin/lote', {
      method: 'POST',
      body: formData
    })

    showModalNovo.value = false
    await carregarDadosAdmin()
  } catch (e) {
    console.error('Erro ao criar lote:', e)
  }
}

function abrirEditarLote(l) {
  loteEditando.value = {
    id: l.model.id,
    nome: l.model.nome,
    quantidade_total: l.model.quantidade_total,
    data_abertura: l.model.data_abertura ? l.model.data_abertura.substring(0, 16) : '',
    data_fechamento: l.model.data_fechamento ? l.model.data_fechamento.substring(0, 16) : '',
    secretaria_id: l.model.secretaria_id ? String(l.model.secretaria_id) : '0',
    ativo: l.model.ativo
  }
  showModalEditar.value = true
}

async function handleSalvarEdicao() {
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

    await fetch(`/admin/lote/${loteEditando.value.id}/editar`, {
      method: 'POST',
      body: formData
    })

    showModalEditar.value = false
    await carregarDadosAdmin()
  } catch (e) {
    console.error('Erro ao salvar edição:', e)
  }
}

async function handleToggleLote(loteId) {
  try {
    await fetch(`/admin/lote/${loteId}/toggle`, { method: 'POST' })
    await carregarDadosAdmin()
  } catch (e) {
    console.error('Erro no toggle:', e)
  }
}

async function handleEncerrarLote(loteId) {
  if (!confirm('Deseja realmente encerrar este lote imediatamente?')) return
  try {
    await fetch(`/admin/lote/${loteId}/encerrar`, { method: 'POST' })
    await carregarDadosAdmin()
  } catch (e) {
    console.error('Erro ao encerrar lote:', e)
  }
}

async function handleExcluirLote(loteId) {
  if (!confirm('ATENÇÃO: Deseja realmente excluir este lote e todos os seus ingressos emitidos?')) return
  try {
    await fetch(`/admin/lote/${loteId}/excluir`, { method: 'POST' })
    await carregarDadosAdmin()
  } catch (e) {
    console.error('Erro ao excluir lote:', e)
  }
}

onMounted(() => {
  carregarDadosAdmin()
})
</script>

<template>
  <div class="admin-page">
    <div class="app-container">
      
      <!-- Cabeçalho do Painel -->
      <div class="admin-header-row">
        <div>
          <h1 class="admin-title font-outfit">Painel de Gestão VIP</h1>
          <p class="admin-subtitle">Monitoramento de resgates, liberação de lotes e controle de participantes.</p>
        </div>
        <div class="header-actions">
          <button type="button" class="btn-primary font-outfit" @click="showModalNovo = true">
            <i class="bi bi-plus-circle-fill me-1"></i> Criar Novo Lote
          </button>
        </div>
      </div>

      <!-- Cards de Métricas Gerais -->
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="metric-icon-box bg-blue">
            <i class="bi bi-ticket-detailed-fill"></i>
          </div>
          <div class="metric-body">
            <span class="metric-label">Vagas Totais</span>
            <strong class="metric-value font-outfit">{{ metricas.total_vagas }}</strong>
          </div>
        </div>

        <div class="metric-card">
          <div class="metric-icon-box bg-green">
            <i class="bi bi-people-fill"></i>
          </div>
          <div class="metric-body">
            <span class="metric-label">Ingressos Resgatados</span>
            <strong class="metric-value text-success font-outfit">{{ metricas.total_resgatados }}</strong>
          </div>
        </div>

        <div class="metric-card">
          <div class="metric-icon-box bg-purple">
            <i class="bi bi-qr-code-scan"></i>
          </div>
          <div class="metric-body">
            <span class="metric-label">Check-ins na Portaria</span>
            <strong class="metric-value text-info font-outfit">{{ metricas.total_checkins }}</strong>
          </div>
        </div>

        <div class="metric-card">
          <div class="metric-icon-box bg-orange">
            <i class="bi bi-percent"></i>
          </div>
          <div class="metric-body">
            <span class="metric-label">Taxa de Ocupação</span>
            <strong class="metric-value text-warning font-outfit">{{ metricas.taxa_ocupacao }}%</strong>
          </div>
        </div>
      </div>

      <!-- Tabela de Gestão de Lotes -->
      <div class="vip-glass-card lotes-table-card">
        <div class="table-header-box">
          <h3 class="table-title font-outfit">
            <i class="bi bi-layers-fill text-primary me-2"></i> Lotes Cadastrados
          </h3>
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
                <th class="text-end">Ações</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="lotes.length === 0">
                <td colspan="6" class="text-center py-4 text-muted">
                  Nenhum lote cadastrado no momento. Clique em <strong>Criar Novo Lote</strong>.
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
                    <span><i class="bi bi-calendar-event me-1"></i> {{ item.model.data_abertura ? new Date(item.model.data_abertura).toLocaleString('pt-BR') : 'Imediato' }}</span>
                    <span v-if="item.model.data_fechamento" class="text-subtle"><i class="bi bi-clock-history me-1"></i> {{ new Date(item.model.data_fechamento).toLocaleString('pt-BR') }}</span>
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
                      <div class="progress-bar-fill" :style="{ width: item.pct + '%', backgroundColor: item.pct >= 100 ? '#ef4444' : item.pct >= 80 ? '#f59e0b' : '#10b981' }"></div>
                    </div>
                    <span class="progress-text">{{ item.model.quantidade_resgatada }} / {{ item.model.quantidade_total }} ({{ item.pct }}%)</span>
                  </div>
                </td>
                <td class="text-end">
                  <div class="action-buttons-group">
                    <router-link :to="'/admin/lote/' + item.model.id + '/ingressos'" class="btn-action-icon" title="Ver Ingressos Resgatados">
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

                    <button type="button" class="btn-action-icon" title="Editar Lote" @click="abrirEditarLote(item)">
                      <i class="bi bi-pencil-fill text-info"></i>
                    </button>

                    <button type="button" class="btn-action-icon" title="Excluir Lote" @click="handleExcluirLote(item.model.id)">
                      <i class="bi bi-trash-fill text-danger"></i>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

    </div>

    <!-- Modal: Criar Novo Lote -->
    <Modal
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

    <!-- Modal: Editar Lote -->
    <Modal
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

  </div>
</template>

<style scoped>
.admin-page {
  padding: 32px 0 60px;
}

.admin-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 28px;
  flex-wrap: wrap;
  gap: 16px;
}

.admin-title {
  font-size: 2rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.admin-subtitle {
  color: var(--text-muted);
  font-size: 0.9rem;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 32px;
}

.metric-card {
  background: var(--bg-card);
  border: 1px solid var(--border-glass);
  border-radius: 16px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
}

.metric-icon-box {
  width: 50px;
  height: 50px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
}

.bg-blue { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
.bg-green { background: rgba(16, 185, 129, 0.15); color: #34d399; }
.bg-purple { background: rgba(168, 85, 247, 0.15); color: #c084fc; }
.bg-orange { background: rgba(245, 158, 11, 0.15); color: #fbbf24; }

.metric-label {
  display: block;
  font-size: 0.78rem;
  text-transform: uppercase;
  color: var(--text-subtle);
  font-weight: 700;
  letter-spacing: 0.5px;
}

.metric-value {
  font-size: 1.75rem;
  font-weight: 800;
  color: #ffffff;
}

.lotes-table-card {
  overflow: hidden;
}

.table-header-box {
  padding: 20px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.table-title {
  font-size: 1.2rem;
  font-weight: 700;
  color: #ffffff;
  display: flex;
  align-items: center;
}

.badge-count {
  font-size: 0.8rem;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-muted);
  padding: 4px 10px;
  border-radius: 999px;
}

.table-responsive {
  overflow-x: auto;
}

.custom-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.custom-table th {
  padding: 14px 20px;
  font-size: 0.78rem;
  text-transform: uppercase;
  color: var(--text-subtle);
  font-weight: 700;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.custom-table td {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 0.9rem;
  vertical-align: middle;
}

.custom-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.02);
}

.sec-tag {
  background: rgba(59, 130, 246, 0.1);
  color: #93c5fd;
  border: 1px solid rgba(59, 130, 246, 0.2);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 0.78rem;
}

.sec-tag-global {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-muted);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 0.78rem;
}

.date-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.82rem;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
}

.progress-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.progress-bar-bg {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.action-buttons-group {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.btn-action-icon {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #ffffff;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
  text-decoration: none;
  font-size: 0.95rem;
}

.btn-action-icon:hover {
  background: rgba(255, 255, 255, 0.15);
  transform: translateY(-2px);
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
.text-white { color: #ffffff; }
.text-subtle { color: var(--text-subtle); }
.text-info { color: #38bdf8; }
.text-danger { color: #f87171; }
.text-success { color: var(--success-color); }
.text-warning { color: var(--warning-color); }
</style>
