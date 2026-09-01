<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const loteId = route.params.loteId

const loading = ref(true)
const lote = ref(null)
const ingressos = ref([])
const totalIngressos = ref(0)
const searchQuery = ref('')

async function carregarIngressos() {
  try {
    loading.value = true
    const res = await fetch(`/admin/lote/${loteId}/ingressos`, {
      headers: { 'Accept': 'application/json, text/html' }
    })

    if (res.status === 401 || res.status === 403 || res.redirected) {
      router.push('/login')
      return
    }

    try {
      const data = await res.json()
      lote.value = data.lote
      ingressos.value = data.ingressos
      totalIngressos.value = data.total_ingressos
    } catch {
      // Fallback
    }
    loading.value = false
  } catch (err) {
    console.error('Erro carregando ingressos:', err)
    loading.value = false
  }
}

const ingressosFiltrados = computed(() => {
  if (!searchQuery.value) return ingressos.value
  const q = searchQuery.value.toLowerCase()
  return ingressos.value.filter(item => {
    const nome = item.usuario?.nome?.toLowerCase() || ''
    const cpf = item.usuario?.cpf?.toLowerCase() || ''
    const sec = item.secretaria_nome?.toLowerCase() || ''
    return nome.includes(q) || cpf.includes(q) || sec.includes(q)
  })
})

async function handleCancelarIngresso(ingressoId) {
  if (!confirm('Deseja realmente cancelar/estornar este ingresso? A vaga será devolvida ao lote.')) return
  try {
    await fetch(`/admin/ingresso/${ingressoId}/cancelar`, { method: 'POST' })
    await carregarIngressos()
  } catch (e) {
    console.error('Erro ao cancelar:', e)
  }
}

onMounted(() => {
  carregarIngressos()
})
</script>

<template>
  <div class="lote-ingressos-page">
    <div class="app-container">
      
      <!-- Breadcrumb -->
      <div class="breadcrumb-box">
        <router-link to="/admin" class="back-breadcrumb">
          <i class="bi bi-arrow-left me-1"></i> Painel Admin
        </router-link>
        <span class="sep">/</span>
        <span class="current-crumb">{{ lote?.nome || 'Ingressos do Lote' }}</span>
      </div>

      <!-- Cabeçalho do Lote -->
      <div class="vip-glass-card lote-summary-card">
        <div class="summary-header">
          <div>
            <div class="lote-title-row">
              <h2 class="lote-title font-outfit">{{ lote?.nome || 'Lote de Ingressos' }}</h2>
              <span class="lote-id-tag">Lote #{{ loteId }}</span>
            </div>
            <p class="lote-dates">
              <i class="bi bi-calendar-event me-1"></i> Abertura: <strong>{{ lote?.data_abertura ? new Date(lote.data_abertura).toLocaleString('pt-BR') : 'Imediato' }}</strong>
              <span v-if="lote?.data_fechamento"> &bull; Fechamento: <strong>{{ new Date(lote.data_fechamento).toLocaleString('pt-BR') }}</strong></span>
            </p>
          </div>

          <div class="summary-actions">
            <a :href="'/admin/lote/' + loteId + '/exportar-csv'" class="btn-success-export font-outfit">
              <i class="bi bi-file-earmark-spreadsheet-fill me-1"></i> Exportar para Excel / CSV
            </a>
          </div>
        </div>

        <div class="metrics-row">
          <div class="mini-metric">
            <span class="mini-label">Vagas Totais</span>
            <strong class="mini-value">{{ lote?.quantidade_total || 0 }}</strong>
          </div>
          <div class="mini-metric">
            <span class="mini-label">Resgatados</span>
            <strong class="mini-value text-primary">{{ totalIngressos }}</strong>
          </div>
          <div class="mini-metric">
            <span class="mini-label">Vagas Restantes</span>
            <strong class="mini-value text-success">{{ Math.max(0, (lote?.quantidade_total || 0) - totalIngressos) }}</strong>
          </div>
          <div class="mini-metric">
            <span class="mini-label">Ocupação</span>
            <strong class="mini-value text-info">
              {{ (lote?.quantidade_total > 0 ? ((totalIngressos / lote.quantidade_total) * 100).toFixed(1) : 0) }}%
            </strong>
          </div>
        </div>
      </div>

      <!-- Tabela de Participantes -->
      <div class="vip-glass-card table-card">
        <div class="table-top-bar">
          <h3 class="table-title font-outfit">
            <i class="bi bi-people-fill text-primary me-2"></i> Servidores com Ingresso Garantido
          </h3>

          <div class="search-box">
            <i class="bi bi-search search-icon"></i>
            <input
              v-model="searchQuery"
              type="text"
              class="form-control search-input"
              placeholder="Buscar por Nome, CPF ou Secretaria..."
            />
          </div>
        </div>

        <div class="table-responsive">
          <table class="custom-table">
            <thead>
              <tr>
                <th>Servidor / CPF</th>
                <th>Secretaria / Setor</th>
                <th>Vínculo / Contato</th>
                <th>Data do Resgate</th>
                <th>Portaria</th>
                <th class="text-end">Ação</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="ingressosFiltrados.length === 0">
                <td colspan="6" class="text-center py-4 text-muted">
                  Nenhum ingresso encontrado.
                </td>
              </tr>
              <tr v-for="item in ingressosFiltrados" :key="item.model.id">
                <td>
                  <strong class="text-white">{{ item.usuario?.nome }}</strong>
                  <span class="d-block small text-subtle font-monospace">{{ item.usuario?.cpf }}</span>
                </td>
                <td>
                  <span class="sec-tag">{{ item.secretaria_nome }}</span>
                  <span v-if="item.usuario?.setor" class="d-block small text-subtle mt-1">{{ item.usuario.setor }}</span>
                </td>
                <td>
                  <span class="text-light">{{ item.usuario?.vinculo || 'Servidor' }}</span>
                  <span class="d-block small text-subtle">{{ item.usuario?.telefone }}</span>
                </td>
                <td>
                  <span class="small text-light">{{ new Date(item.model.data_resgate).toLocaleString('pt-BR') }}</span>
                </td>
                <td>
                  <span v-if="item.ja_entrou" class="badge-portaria bg-success">
                    <i class="bi bi-check-circle-fill me-1"></i> Já Entrou
                  </span>
                  <span v-else class="badge-portaria bg-secondary">
                    <i class="bi bi-hourglass-split me-1"></i> Aguardando
                  </span>
                </td>
                <td class="text-end">
                  <button
                    type="button"
                    class="btn-danger-sm"
                    title="Cancelar Ingresso e Devolver Vaga"
                    @click="handleCancelarIngresso(item.model.id)"
                  >
                    <i class="bi bi-x-circle me-1"></i> Cancelar
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.lote-ingressos-page {
  padding: 32px 0 60px;
}

.breadcrumb-box {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
  font-size: 0.9rem;
}

.back-breadcrumb {
  color: var(--text-muted);
  text-decoration: none;
  transition: color 0.15s ease;
}

.back-breadcrumb:hover {
  color: #ffffff;
}

.sep {
  color: var(--text-subtle);
}

.current-crumb {
  color: var(--text-main);
  font-weight: 600;
}

.lote-summary-card {
  padding: 28px;
  margin-bottom: 28px;
}

.summary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}

.lote-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.lote-title {
  font-size: 1.75rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 0;
}

.lote-id-tag {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-muted);
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.8rem;
}

.lote-dates {
  color: var(--text-muted);
  font-size: 0.88rem;
  margin-top: 6px;
}

.btn-success-export {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: #ffffff;
  font-weight: 700;
  padding: 10px 20px;
  border-radius: 10px;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
  transition: all 0.2s ease;
}

.btn-success-export:hover {
  filter: brightness(1.1);
  transform: translateY(-2px);
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.mini-metric {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 14px;
  text-align: center;
}

.mini-label {
  display: block;
  font-size: 0.72rem;
  text-transform: uppercase;
  color: var(--text-subtle);
  font-weight: 700;
  letter-spacing: 0.5px;
}

.mini-value {
  font-size: 1.4rem;
  font-weight: 800;
  color: #ffffff;
}

.table-card {
  overflow: hidden;
}

.table-top-bar {
  padding: 20px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}

.table-title {
  font-size: 1.15rem;
  font-weight: 700;
  color: #ffffff;
  display: flex;
  align-items: center;
}

.search-box {
  position: relative;
  width: 100%;
  max-width: 340px;
}

.search-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-subtle);
}

.search-input {
  padding-left: 38px;
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
  padding: 14px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 0.88rem;
  vertical-align: middle;
}

.sec-tag {
  background: rgba(59, 130, 246, 0.1);
  color: #93c5fd;
  border: 1px solid rgba(59, 130, 246, 0.2);
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 0.78rem;
}

.badge-portaria {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 700;
}

.badge-portaria.bg-success {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
}

.badge-portaria.bg-secondary {
  background: rgba(100, 116, 139, 0.15);
  color: #94a3b8;
}

.btn-danger-sm {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #f87171;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-danger-sm:hover {
  background: rgba(239, 68, 68, 0.25);
  color: #ffffff;
}

.text-end { text-align: right; }
.text-center { text-align: center; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.mt-1 { margin-top: 4px; }
.text-white { color: #ffffff; }
.text-subtle { color: var(--text-subtle); }
.text-primary { color: var(--primary-accent); }
.text-success { color: var(--success-color); }
.text-info { color: #38bdf8; }
.font-monospace { font-family: monospace; }
</style>
