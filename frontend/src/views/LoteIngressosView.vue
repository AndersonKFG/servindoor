<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const { toast } = useToast()
const { confirmModal } = useConfirm()
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
    toast.error('Erro ao carregar ingressos do lote.')
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
  const confirmado = await confirmModal({
    title: 'Cancelar Ingresso',
    message: 'Deseja realmente cancelar/estornar este ingresso? A vaga será devolvida ao lote.',
    confirmText: 'Sim, Cancelar',
    variant: 'danger'
  })
  if (!confirmado) return
  try {
    const res = await fetch(`/admin/ingresso/${ingressoId}/cancelar`, { method: 'POST' })
    if (res.ok) {
      toast.success('Ingresso cancelado com sucesso.')
      await carregarIngressos()
    } else {
      toast.error('Erro ao cancelar ingresso.')
    }
  } catch (e) {
    toast.error('Erro de conexão ao cancelar ingresso.')
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
            <a :href="'/api/admin/lote/' + loteId + '/exportar-csv'" class="btn-success-export font-outfit">
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
                <th>Status no Lote</th>
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
                  <span v-if="item.status === 'aprovado'" class="badge bg-success">
                    <i class="bi bi-check-circle-fill me-1"></i> Aprovado
                  </span>
                  <span v-else-if="item.status === 'rejeitado'" class="badge bg-danger" :title="item.motivo_rejeicao">
                    <i class="bi bi-x-circle-fill me-1"></i> Recusado
                  </span>
                  <span v-else class="badge bg-warning text-dark">
                    <i class="bi bi-hourglass-split me-1"></i> Em Análise
                  </span>
                  <span v-if="item.motivo_rejeicao" class="d-block small text-danger mt-1">{{ item.motivo_rejeicao }}</span>
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
</style>
