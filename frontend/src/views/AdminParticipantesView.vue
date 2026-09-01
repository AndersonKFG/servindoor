<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import Modal from '../components/Modal.vue'
import QRCode from 'qrcode'
import { useAuth } from '../composables/useAuth'

const router = useRouter()
const { isAdminGeral } = useAuth()

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
const filtroPresenca = ref('todos') // 'todos', 'presente', 'fora'
const secretariasSelecionadas = ref([]) // IDs das secretarias selecionadas (Array para multi-select)
const showDropdownSec = ref(false)
const buscaSec = ref('')

// Paginação
const itensPorPagina = ref(25)
const paginaAtual = ref(1)

// Modais
const showModalFoto = ref(false)
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

let pollInterval = null

async function carregarParticipantes(silent = false) {
  try {
    if (!silent) loading.value = true
    const res = await fetch('/api/admin/participantes')
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
  } catch (e) {
    if (!silent) console.error('Erro ao carregar participantes:', e)
  } finally {
    if (!silent) loading.value = false
  }
}

// Lista única de lotes para o dropdown de filtro
const lotesDisponiveis = computed(() => {
  const lotesMap = new Map()
  participantes.value.forEach(p => {
    if (p.ingresso?.lote_id) {
      lotesMap.set(p.ingresso.lote_id, p.ingresso.lote_nome)
    }
  })
  return Array.from(lotesMap.entries()).map(([id, nome]) => ({ id, nome }))
})

// Lista única de secretarias com contagem para o multi-select
const secretariasDisponiveis = computed(() => {
  const secMap = new Map()
  participantes.value.forEach(p => {
    const id = p.secretaria?.id || 'sem_secretaria'
    const nome = p.secretaria?.nome || 'Sem Secretaria / Geral'
    if (!secMap.has(id)) {
      secMap.set(id, { id, nome, count: 0 })
    }
    secMap.get(id).count++
  })
  return Array.from(secMap.values()).sort((a, b) => a.nome.localeCompare(b.nome))
})

// Secretarias filtradas pela busca interna do dropdown
const secretariasFiltradas = computed(() => {
  if (!buscaSec.value.trim()) return secretariasDisponiveis.value
  const q = buscaSec.value.toLowerCase().trim()
  return secretariasDisponiveis.value.filter(s => s.nome.toLowerCase().includes(q))
})

// Rótulo do botão do multi-select de secretarias
const labelSecretarias = computed(() => {
  const total = secretariasSelecionadas.value.length
  if (total === 0) return 'Secretarias: Todas'
  if (total === 1) {
    const s = secretariasDisponiveis.value.find(item => item.id === secretariasSelecionadas.value[0])
    return s ? s.nome : '1 Secretaria'
  }
  return `${total} Secretarias selecionadas`
})

function toggleSecretaria(id) {
  const index = secretariasSelecionadas.value.indexOf(id)
  if (index > -1) {
    secretariasSelecionadas.value.splice(index, 1)
  } else {
    secretariasSelecionadas.value.push(id)
  }
}

function selecionarTodasSecretarias() {
  secretariasSelecionadas.value = secretariasDisponiveis.value.map(s => s.id)
}

function limparSecretarias() {
  secretariasSelecionadas.value = []
}

// Fechar dropdown ao clicar fora
function handleClickOutside(e) {
  const dropdown = document.getElementById('sec-multiselect-container')
  if (dropdown && !dropdown.contains(e.target)) {
    showDropdownSec.value = false
  }
}

// Base de participantes filtrados por busca, lote e secretarias selecionadas
const participantesBaseFiltrados = computed(() => {
  return participantes.value.filter(p => {
    // 1. Filtro de busca textual
    if (busca.value.trim()) {
      const q = busca.value.toLowerCase().trim()
      const matchNome = (p.nome || '').toLowerCase().includes(q)
      const matchCpf = (p.cpf || '').includes(q)
      const matchEmail = (p.email || '').toLowerCase().includes(q)
      const matchSetor = (p.setor || '').toLowerCase().includes(q)
      const matchSec = (p.secretaria?.nome || '').toLowerCase().includes(q)
      const matchToken = (p.ingresso?.qr_code_token || '').toLowerCase().includes(q)
      if (!matchNome && !matchCpf && !matchEmail && !matchSetor && !matchSec && !matchToken) {
        return false
      }
    }

    // 2. Filtro de Lote
    if (filtroLote.value) {
      if (String(p.ingresso?.lote_id) !== String(filtroLote.value)) {
        return false
      }
    }

    // 3. Multi-Select de Secretarias
    if (secretariasSelecionadas.value.length > 0) {
      const secId = p.secretaria?.id || 'sem_secretaria'
      if (!secretariasSelecionadas.value.includes(secId)) {
        return false
      }
    }

    return true
  })
})

// KPIs Reativos e Dinâmicos com base nos filtros
const kpis = computed(() => {
  const base = participantesBaseFiltrados.value
  let total_presentes = 0
  let total_fora = 0

  base.forEach(p => {
    if (p.situacao_evento?.dentro || p.situacao_evento?.status_slug === 'presente') {
      total_presentes++
    } else {
      total_fora++
    }
  })

  return {
    total_ingressos_resgatados: base.length,
    total_presentes,
    total_fora
  }
})

// Participantes filtrados finais (incluindo filtro de presença)
const participantesFiltrados = computed(() => {
  return participantesBaseFiltrados.value.filter(p => {
    const estaDentro = p.situacao_evento?.dentro || p.situacao_evento?.status_slug === 'presente'
    if (filtroPresenca.value === 'presente') {
      return estaDentro
    } else if (filtroPresenca.value === 'fora') {
      return !estaDentro
    }
    return true
  })
})

// Reseta para a primeira página quando qualquer filtro ou tamanho de página mudar
watch([busca, filtroLote, filtroPresenca, secretariasSelecionadas, itensPorPagina], () => {
  paginaAtual.value = 1
}, { deep: true })

// Paginação
const totalPaginas = computed(() => {
  return Math.ceil(participantesFiltrados.value.length / itensPorPagina.value) || 1
})

const participantesPaginados = computed(() => {
  const inicio = (paginaAtual.value - 1) * itensPorPagina.value
  const fim = inicio + itensPorPagina.value
  return participantesFiltrados.value.slice(inicio, fim)
})

const infoPaginacao = computed(() => {
  const total = participantesFiltrados.value.length
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
  if (p === '...' || p < 1 || p > totalPaginas.value) return
  paginaAtual.value = p
}

// Atalhos rápidos ao clicar nos cards de KPI
function toggleFiltroPresenca(tipo) {
  if (filtroPresenca.value === tipo) {
    filtroPresenca.value = 'todos'
  } else {
    filtroPresenca.value = tipo
  }
}

function abrirFotoZoom(p) {
  fotoZoomUrl.value = p.foto_url
  fotoZoomNome.value = p.nome
  showModalFoto.value = true
}

async function abrirModalIngresso(p) {
  participanteIngresso.value = p
  qrDataUrl.value = ''
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
      console.error('Erro ao gerar QR code:', e)
    }
  }
}

function abrirModalEmail(p) {
  participanteEmail.value = p
  emailAssunto.value = 'Informações Importantes - Servindoor 2026'
  emailMensagem.value = `Olá ${p.nome},\n\nSeu ingresso para o Servindoor 2026 está confirmado!\n\nLote: ${p.ingresso?.lote_nome || 'Geral'}\nToken: ${p.ingresso?.qr_code_token || 'N/A'}\n\nApresente seu QR Code na portaria do evento.\n\nAtenciosamente,\nOrganização Servindoor 2026`
  emailResultado.value = null
  showModalEmail.value = true
}

async function enviarEmail() {
  if (!participanteEmail.value) return
  try {
    enviandoEmail.value = true
    emailResultado.value = null
    const res = await fetch(`/api/admin/participantes/${participanteEmail.value.id}/enviar-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        assunto: emailAssunto.value,
        mensagem: emailMensagem.value
      })
    })
    const data = await res.json()
    if (res.ok) {
      emailResultado.value = { tipo: 'sucesso', msg: data.message || 'E-mail enviado com sucesso!' }
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
  showModalCancelar.value = true
}

async function executarCancelamento() {
  if (!participanteCancelar.value?.ingresso?.id) return
  try {
    cancelando.value = true
    const res = await fetch(`/api/admin/ingressos/${participanteCancelar.value.ingresso.id}/cancelar`, {
      method: 'POST'
    })
    if (res.ok) {
      showModalCancelar.value = false
      await carregarParticipantes()
    } else {
      const data = await res.json()
      alert(data.detail || 'Erro ao cancelar ingresso.')
    }
  } catch (err) {
    alert('Erro de conexão.')
  } finally {
    cancelando.value = false
  }
}

function exportarCSV() {
  window.open('/api/admin/ingressos/exportar-csv', '_blank')
}

onMounted(() => {
  carregarParticipantes()
  window.addEventListener('click', handleClickOutside)
  pollInterval = setInterval(() => {
    if (!document.hidden && !showModalIngresso.value && !showModalEmail.value && !showModalCancelar.value && !showModalFoto.value && !showDropdownSec.value) {
      carregarParticipantes(true)
    }
  }, 2500)
})

onUnmounted(() => {
  window.removeEventListener('click', handleClickOutside)
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
          <span class="badge-role-tag mb-2">
            <i class="bi bi-ticket-perforated-fill me-1"></i> PAINEL ADMINISTRATIVO
          </span>
          <h1 class="admin-title font-outfit">Gestão de Participantes</h1>
          <p class="admin-subtitle">Servidores com ingressos resgatados e controle de fluxo em tempo real.</p>
        </div>

        <div class="header-actions">
          <button type="button" class="btn-action-outline" @click="exportarCSV">
            <i class="bi bi-file-earmark-spreadsheet-fill text-success me-2"></i>
            <span>Exportar CSV</span>
          </button>
          <button type="button" class="btn-action-glow" @click="carregarParticipantes(false)">
            <i class="bi bi-arrow-clockwise me-2" :class="{ 'spin-icon': loading }"></i>
            <span>Atualizar</span>
          </button>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- CARDS DE KPI (REATIVOS AOS FILTROS)            -->
      <!-- ============================================== -->
      <div class="metrics-grid">
        
        <!-- 1. Total Ingressos Resgatados -->
        <div
          class="kpi-card card-blue"
          :class="{ 'kpi-active': filtroPresenca === 'todos' }"
          title="Clique para ver todos os participantes filtrados"
          @click="filtroPresenca = 'todos'"
        >
          <div class="kpi-icon-box bg-blue">
            <i class="bi bi-ticket-perforated-fill"></i>
          </div>
          <div class="kpi-info">
            <span class="kpi-label">Ingressos Filtrados</span>
            <div class="kpi-value font-outfit">{{ kpis.total_ingressos_resgatados }}</div>
            <span class="kpi-sublabel">Total no recorte atual</span>
          </div>
        </div>

        <!-- 2. Presentes no Evento (DENTRO) -->
        <div
          class="kpi-card card-green"
          :class="{ 'kpi-active': filtroPresenca === 'presente' }"
          title="Clique para filtrar apenas os presentes"
          @click="toggleFiltroPresenca('presente')"
        >
          <div class="kpi-icon-box bg-green">
            <i class="bi bi-check-circle-fill"></i>
          </div>
          <div class="kpi-info">
            <span class="kpi-label">Presentes no Evento</span>
            <div class="kpi-value font-outfit text-success">{{ kpis.total_presentes }}</div>
            <span class="kpi-sublabel text-success">
              <i class="bi bi-circle-fill dot-pulse me-1"></i> Na área do evento
            </span>
          </div>
        </div>

        <!-- 3. Fora do Evento (FORA) -->
        <div
          class="kpi-card card-orange"
          :class="{ 'kpi-active': filtroPresenca === 'fora' }"
          title="Clique para filtrar apenas os fora do evento"
          @click="toggleFiltroPresenca('fora')"
        >
          <div class="kpi-icon-box bg-orange">
            <i class="bi bi-geo-alt-fill"></i>
          </div>
          <div class="kpi-info">
            <span class="kpi-label">Fora do Evento</span>
            <div class="kpi-value font-outfit text-warning">{{ kpis.total_fora }}</div>
            <span class="kpi-sublabel">Ainda não entraram ou saíram</span>
          </div>
        </div>

      </div>

      <!-- ============================================== -->
      <!-- BARRA DE FERRAMENTAS E FILTROS (INCLUINDO SEC) -->
      <!-- ============================================== -->
      <div class="filter-card">
        <div class="filter-grid">
          
          <!-- 1. Campo de Busca Geral -->
          <div class="search-box">
            <i class="bi bi-search search-icon"></i>
            <input
              v-model="busca"
              type="text"
              class="form-control filter-input"
              placeholder="Buscar por Nome, CPF, Setor ou Token..."
            />
            <button v-if="busca" type="button" class="btn-clear-search" @click="busca = ''">
              <i class="bi bi-x-circle-fill"></i>
            </button>
          </div>

          <!-- 2. Multi-Select de Secretarias -->
          <div id="sec-multiselect-container" class="multiselect-box">
            <button
              type="button"
              class="btn-multiselect-toggle"
              :class="{ 'has-selection': secretariasSelecionadas.length > 0 }"
              @click="showDropdownSec = !showDropdownSec"
            >
              <i class="bi bi-building me-2 text-cyan"></i>
              <span class="multiselect-label">{{ labelSecretarias }}</span>
              <span v-if="secretariasSelecionadas.length > 0" class="badge-selection-count">
                {{ secretariasSelecionadas.length }}
              </span>
              <i class="bi bi-chevron-down ms-auto toggle-icon" :class="{ 'rotate': showDropdownSec }"></i>
            </button>

            <!-- Menu Flutuante do Multi-Select -->
            <div v-if="showDropdownSec" class="multiselect-dropdown-menu">
              <!-- Busca de Secretarias -->
              <div class="dropdown-search-wrapper">
                <i class="bi bi-search dropdown-search-icon"></i>
                <input
                  v-model="buscaSec"
                  type="text"
                  class="form-control dropdown-search-input"
                  placeholder="Filtrar secretarias..."
                  @click.stop
                />
              </div>

              <!-- Ações Rápidas -->
              <div class="dropdown-actions-row">
                <button type="button" class="btn-quick-link" @click.stop="selecionarTodasSecretarias">
                  Selecionar Todas
                </button>
                <button
                  v-if="secretariasSelecionadas.length > 0"
                  type="button"
                  class="btn-quick-link text-danger"
                  @click.stop="limparSecretarias"
                >
                  Limpar ({{ secretariasSelecionadas.length }})
                </button>
              </div>

              <!-- Lista de Secretarias com Checkbox -->
              <div class="dropdown-items-list custom-scrollbar">
                <label
                  v-for="s in secretariasFiltradas"
                  :key="s.id"
                  class="dropdown-checkbox-item"
                  @click.stop
                >
                  <input
                    type="checkbox"
                    :checked="secretariasSelecionadas.includes(s.id)"
                    @change="toggleSecretaria(s.id)"
                  />
                  <span class="sec-name">{{ s.nome }}</span>
                  <span class="sec-count">{{ s.count }}</span>
                </label>
                <div v-if="!secretariasFiltradas.length" class="p-3 text-center text-muted small">
                  Nenhuma secretaria encontrada
                </div>
              </div>
            </div>
          </div>

          <!-- 3. Filtro de Lote -->
          <div class="select-box">
            <select v-model="filtroLote" class="form-select filter-select">
              <option value="">Todos os Lotes</option>
              <option v-for="l in lotesDisponiveis" :key="l.id" :value="l.id">
                {{ l.nome }}
              </option>
            </select>
          </div>

          <!-- 4. Filtro de Presença -->
          <div class="select-box">
            <select v-model="filtroPresenca" class="form-select filter-select">
              <option value="todos">Presença: Todos</option>
              <option value="presente">🟢 Apenas Presentes (Dentro)</option>
              <option value="fora">⚪ Apenas Fora do Evento</option>
            </select>
          </div>

        </div>

        <!-- Tags ativas de secretarias selecionadas -->
        <div v-if="secretariasSelecionadas.length > 0" class="active-tags-row mt-3">
          <span class="text-muted small me-2">Filtrando por:</span>
          <span
            v-for="secId in secretariasSelecionadas"
            :key="secId"
            class="active-sec-pill"
          >
            <span>{{ secretariasDisponiveis.find(s => s.id === secId)?.nome || secId }}</span>
            <button type="button" class="btn-remove-tag" @click="toggleSecretaria(secId)">
              <i class="bi bi-x"></i>
            </button>
          </span>
          <button type="button" class="btn-clear-all-tags" @click="limparSecretarias">
            Limpar Filtro de Secretarias
          </button>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- TABELA DE PARTICIPANTES (COMPACTA & ALTA ESCALA)-->
      <!-- ============================================== -->
      <div class="table-card">
        
        <div class="table-header-box">
          <div class="table-title font-outfit">
            <i class="bi bi-people-fill text-cyan me-2"></i>
            <span>Participantes Cadastrados</span>
            <span class="badge-count">{{ participantesFiltrados.length }}</span>
          </div>

          <div class="table-header-controls">
            <span class="text-muted small me-2">Exibir:</span>
            <select v-model="itensPorPagina" class="select-page-size">
              <option :value="10">10</option>
              <option :value="25">25</option>
              <option :value="50">50</option>
              <option :value="100">100</option>
            </select>
          </div>
        </div>

        <div v-if="loading" class="text-center py-5 text-muted">
          <div class="spinner-border text-cyan mb-3"></div>
          <p class="font-outfit">Sincronizando participantes...</p>
        </div>

        <div v-else-if="!participantesFiltrados.length" class="empty-state-box py-5 text-center">
          <i class="bi bi-inbox fs-1 mb-2 d-block text-muted"></i>
          <p class="text-muted">Nenhum participante encontrado com os filtros aplicados.</p>
        </div>

        <div v-else class="table-responsive">
          <table class="custom-table">
            <thead>
              <tr>
                <th style="width: 50px;">Foto</th>
                <th>Nome / Vínculo</th>
                <th style="width: 140px;">CPF</th>
                <th>Secretaria / Setor</th>
                <th>Lote / Ingresso</th>
                <th>Status no Evento</th>
                <th class="text-end" style="width: 130px;">Ações</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in participantesPaginados" :key="p.id">
                
                <!-- Foto -->
                <td>
                  <div class="avatar-cell" title="Clique para ampliar" @click="p.foto_url && abrirFotoZoom(p)">
                    <img v-if="p.foto_url" :src="p.foto_url" alt="Foto" class="avatar-img" />
                    <div v-else class="avatar-placeholder">
                      <i class="bi bi-person-fill"></i>
                    </div>
                  </div>
                </td>

                <!-- Nome / Vínculo -->
                <td>
                  <div class="participant-compact-name">
                    <strong class="participant-name text-white">{{ p.nome }}</strong>
                    <span class="vinculo-tag-compact">{{ p.vinculo || 'Servidor' }}</span>
                  </div>
                </td>

                <!-- CPF (Sem quebra de linha) -->
                <td>
                  <span class="cpf-badge-compact font-monospace">{{ p.cpf_formatado }}</span>
                </td>

                <!-- Secretaria / Setor -->
                <td>
                  <div class="sec-compact-box">
                    <span class="sec-tag-compact">{{ p.secretaria?.nome || 'Geral' }}</span>
                    <span v-if="p.setor" class="setor-text-compact text-muted">{{ p.setor }}</span>
                  </div>
                </td>

                <!-- Lote / Ingresso -->
                <td>
                  <div class="lote-compact-box">
                    <template v-if="p.ingresso">
                      <span class="badge-lote-compact">{{ p.ingresso.lote_nome }}</span>
                      <span class="token-code-compact font-monospace">
                        {{ p.ingresso.qr_code_token.slice(0, 8) }}...
                      </span>
                    </template>
                    <span v-else class="text-muted small">Sem Ingresso</span>
                  </div>
                </td>

                <!-- Status no Evento -->
                <td>
                  <span class="status-badge-compact" :class="p.situacao_evento?.badge_class">
                    <i :class="p.situacao_evento?.dentro ? 'bi bi-check-circle-fill me-1 text-success' : 'bi bi-geo-alt me-1 text-warning'"></i>
                    <span>{{ p.situacao_evento?.label }}</span>
                  </span>
                </td>

                <!-- Ações -->
                <td class="text-end">
                  <div class="action-buttons-group">
                    <button
                      v-if="p.ingresso"
                      type="button"
                      class="btn-action-icon-compact btn-icon-cyan"
                      title="Ver Ingresso / QR Code"
                      @click="abrirModalIngresso(p)"
                    >
                      <i class="bi bi-qr-code"></i>
                    </button>

                    <button
                      type="button"
                      class="btn-action-icon-compact btn-icon-amber"
                      title="Enviar E-mail com Ingresso"
                      @click="abrirModalEmail(p)"
                    >
                      <i class="bi bi-envelope-fill"></i>
                    </button>

                    <button
                      v-if="p.ingresso && isAdminGeral"
                      type="button"
                      class="btn-action-icon-compact btn-icon-danger"
                      title="Cancelar Ingresso (Apenas Admin Geral)"
                      @click="confirmarCancelarIngresso(p)"
                    >
                      <i class="bi bi-trash-fill"></i>
                    </button>
                  </div>
                </td>

              </tr>
            </tbody>
          </table>
        </div>

        <!-- ============================================== -->
        <!-- RODAPÉ COM PAGINAÇÃO DINÂMICA                  -->
        <!-- ============================================== -->
        <div v-if="participantesFiltrados.length > 0" class="pagination-footer">
          
          <div class="pagination-info">
            <span class="text-muted">Mostrando <strong>{{ infoPaginacao }}</strong></span>
          </div>

          <div class="pagination-buttons">
            <!-- Primeira Página -->
            <button
              type="button"
              class="btn-page-nav"
              :disabled="paginaAtual === 1"
              title="Primeira Página"
              @click="irParaPagina(1)"
            >
              <i class="bi bi-chevron-double-left"></i>
            </button>

            <!-- Página Anterior -->
            <button
              type="button"
              class="btn-page-nav"
              :disabled="paginaAtual === 1"
              title="Página Anterior"
              @click="irParaPagina(paginaAtual - 1)"
            >
              <i class="bi bi-chevron-left"></i>
            </button>

            <!-- Números das Páginas -->
            <button
              v-for="(p, idx) in paginasVisiveis"
              :key="idx"
              type="button"
              class="btn-page-number"
              :class="{ 'active': p === paginaAtual, 'dots': p === '...' }"
              :disabled="p === '...'"
              @click="irParaPagina(p)"
            >
              {{ p }}
            </button>

            <!-- Próxima Página -->
            <button
              type="button"
              class="btn-page-nav"
              :disabled="paginaAtual === totalPaginas"
              title="Próxima Página"
              @click="irParaPagina(paginaAtual + 1)"
            >
              <i class="bi bi-chevron-right"></i>
            </button>

            <!-- Última Página -->
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

    <!-- MODAL FOTO ZOOM -->
    <Modal :show="showModalFoto" :title="fotoZoomNome" icon="bi-image" @close="showModalFoto = false">
      <div class="text-center p-3">
        <img :src="fotoZoomUrl" alt="Foto do Participante" class="zoom-photo-img" />
      </div>
      <template #footer>
        <button type="button" class="btn-action-outline w-100" @click="showModalFoto = false">
          Fechar
        </button>
      </template>
    </Modal>

    <!-- MODAL VER INGRESSO / QR CODE -->
    <Modal
      :show="showModalIngresso"
      title="Ingresso do Participante"
      icon="bi-qr-code"
      @close="showModalIngresso = false"
    >
      <div v-if="participanteIngresso" class="text-center p-3">
        <h4 class="font-outfit text-white mb-2">{{ participanteIngresso.nome }}</h4>
        <p class="text-muted small mb-4">CPF: {{ participanteIngresso.cpf_formatado }}</p>

        <div class="qr-box-preview">
          <img v-if="qrDataUrl" :src="qrDataUrl" alt="QR Code" class="qr-preview-img" />
          <div v-else class="spinner-border text-primary my-4"></div>
        </div>

        <div class="mt-4">
          <span class="badge-lote-compact mb-2">{{ participanteIngresso.ingresso?.lote_nome }}</span>
          <p class="font-monospace text-muted small mt-3">
            Token: <strong>{{ participanteIngresso.ingresso?.qr_code_token }}</strong>
          </p>
        </div>
      </div>

      <template #footer>
        <button type="button" class="btn-action-outline w-100" @click="showModalIngresso = false">
          Fechar
        </button>
      </template>
    </Modal>

    <!-- MODAL ENVIAR E-MAIL -->
    <Modal
      :show="showModalEmail"
      title="Enviar E-mail ao Participante"
      icon="bi-envelope"
      @close="showModalEmail = false"
    >
      <div v-if="participanteEmail" class="email-modal-body p-2">
        <div class="form-group mb-3">
          <label class="form-label text-muted small">Destinatário:</label>
          <div class="recipient-badge">
            <strong class="text-white">{{ participanteEmail.nome }}</strong>
            <span class="text-muted ms-2">&lt;{{ participanteEmail.email }}&gt;</span>
          </div>
        </div>

        <div class="form-group mb-3">
          <label class="form-label text-muted small">Assunto:</label>
          <input v-model="emailAssunto" type="text" class="form-control filter-input" />
        </div>

        <div class="form-group mb-3">
          <label class="form-label text-muted small">Mensagem:</label>
          <textarea v-model="emailMensagem" rows="6" class="form-control filter-input font-monospace"></textarea>
        </div>

        <div v-if="emailResultado" class="alert mt-3" :class="emailResultado.tipo === 'sucesso' ? 'alert-success' : 'alert-danger'">
          {{ emailResultado.msg }}
        </div>
      </div>

      <template #footer>
        <div class="d-flex gap-3 w-100">
          <button type="button" class="btn-action-outline flex-1" @click="showModalEmail = false">
            Cancelar
          </button>
          <button type="button" class="btn-action-glow flex-1" :disabled="enviandoEmail" @click="enviarEmail">
            <span v-if="enviandoEmail" class="spinner-border spinner-border-sm me-2"></span>
            <span>{{ enviandoEmail ? 'Enviando...' : 'Enviar E-mail' }}</span>
          </button>
        </div>
      </template>
    </Modal>

    <!-- MODAL CANCELAR INGRESSO -->
    <Modal
      :show="showModalCancelar"
      title="Cancelar Ingresso"
      icon="bi-exclamation-triangle"
      @close="showModalCancelar = false"
    >
      <div v-if="participanteCancelar" class="p-3 text-center">
        <i class="bi bi-trash3-fill text-danger fs-1 mb-3 d-block"></i>
        <h4 class="font-outfit text-white mb-2">Confirmar Cancelamento</h4>
        <p class="text-muted">
          Deseja realmente cancelar o ingresso de <strong>{{ participanteCancelar.nome }}</strong>?
        </p>
        <p class="text-danger small mt-3">
          A vaga será liberada imediatamente de volta para o lote.
        </p>
      </div>

      <template #footer>
        <div class="d-flex gap-3 w-100">
          <button type="button" class="btn-action-outline flex-1" @click="showModalCancelar = false">
            Manter Ingresso
          </button>
          <button type="button" class="btn-danger flex-1" :disabled="cancelando" @click="executarCancelamento">
            <span v-if="cancelando" class="spinner-border spinner-border-sm me-2"></span>
            <span>{{ cancelando ? 'Cancelando...' : 'Sim, Cancelar' }}</span>
          </button>
        </div>
      </template>
    </Modal>

  </div>
</template>

<style scoped>
.admin-page {
  padding: 32px 0 80px;
}

.admin-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 18px;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.badge-role-tag {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.5px;
  background: rgba(56, 189, 248, 0.12);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.admin-title {
  font-size: clamp(1.6rem, 4vw, 2.1rem);
  font-weight: 800;
  color: #ffffff;
  margin: 0;
  letter-spacing: -0.5px;
}

.admin-subtitle {
  color: var(--text-muted);
  font-size: 0.88rem;
  margin-top: 4px;
}

/* BOTÕES DO CABEÇALHO */
.btn-action-outline {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 9px 18px;
  border-radius: 12px;
  font-size: 0.88rem;
  font-weight: 700;
  color: #e2e8f0;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(12px);
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-action-outline:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.25);
  color: #ffffff;
  transform: translateY(-1px);
}

.btn-action-glow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 9px 20px;
  border-radius: 12px;
  font-size: 0.88rem;
  font-weight: 700;
  color: #ffffff;
  background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
  border: 1px solid rgba(56, 189, 248, 0.4);
  box-shadow: 0 4px 14px rgba(2, 132, 199, 0.35);
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-action-glow:hover {
  background: linear-gradient(135deg, #0369a1 0%, #075985 100%);
  box-shadow: 0 6px 20px rgba(2, 132, 199, 0.5);
  transform: translateY(-1px);
}

.spin-icon {
  animation: spin 1s infinite linear;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ========================================================================== */
/* CARDS DE KPI (REATIVOS E CLICÁVEIS COMO ATALHO)                           */
/* ========================================================================== */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  margin-bottom: 22px;
}

.kpi-card {
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 18px;
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
  cursor: pointer;
  user-select: none;
  transition: all 0.2s ease;
}

.kpi-card:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 255, 255, 0.25);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.45);
}

.kpi-card.kpi-active {
  border-color: rgba(56, 189, 248, 0.6);
  background: rgba(56, 189, 248, 0.08);
  box-shadow: 0 0 20px rgba(56, 189, 248, 0.2);
}

.card-blue { border-left: 4px solid #38bdf8; }
.card-green { border-left: 4px solid #10b981; }
.card-orange { border-left: 4px solid #f59e0b; }

.kpi-icon-box {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  flex-shrink: 0;
}

.bg-blue { background: rgba(56, 189, 248, 0.12); color: #38bdf8; }
.bg-green { background: rgba(16, 185, 129, 0.12); color: #34d399; }
.bg-orange { background: rgba(245, 158, 11, 0.12); color: #fbbf24; }

.kpi-info {
  display: flex;
  flex-direction: column;
}

.kpi-label {
  font-size: 0.74rem;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 700;
  letter-spacing: 0.5px;
}

.kpi-value {
  font-size: 1.85rem;
  font-weight: 900;
  color: #ffffff;
  line-height: 1.1;
  margin: 1px 0;
}

.kpi-sublabel {
  font-size: 0.74rem;
  color: var(--text-muted);
}

/* ========================================================================== */
/* FILTROS & MULTI-SELECT DE SECRETARIAS                                     */
/* ========================================================================== */
.filter-card {
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  padding: 16px 20px;
  border-radius: 16px;
  margin-bottom: 22px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}

.filter-grid {
  display: grid;
  grid-template-columns: 1.8fr 1.6fr 1.1fr 1.1fr;
  gap: 12px;
}

@media (max-width: 992px) {
  .filter-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 576px) {
  .filter-grid {
    grid-template-columns: 1fr;
    gap: 10px;
  }
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 14px;
  color: #64748b;
  font-size: 0.95rem;
}

.filter-input {
  background: rgba(0, 0, 0, 0.45) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: #ffffff !important;
  padding: 10px 14px 10px 42px !important;
  border-radius: 10px !important;
  font-size: 0.88rem !important;
  height: 44px;
}

.filter-input:focus {
  border-color: rgba(56, 189, 248, 0.5) !important;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.15) !important;
}

.btn-clear-search {
  position: absolute;
  right: 12px;
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 1rem;
}

.filter-select {
  background: rgba(0, 0, 0, 0.45) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: #ffffff !important;
  padding: 10px 14px !important;
  border-radius: 10px !important;
  font-size: 0.88rem !important;
  height: 44px;
  cursor: pointer;
}

.filter-select:focus {
  border-color: rgba(56, 189, 248, 0.5) !important;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.15) !important;
}

.filter-select option {
  background: #0f172a;
  color: #ffffff;
}

/* MULTI-SELECT DROPDOWN STYLING */
.multiselect-box {
  position: relative;
}

.btn-multiselect-toggle {
  width: 100%;
  height: 44px;
  background: rgba(0, 0, 0, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #ffffff;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 0.88rem;
  display: flex;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
}

.btn-multiselect-toggle:hover {
  border-color: rgba(56, 189, 248, 0.4);
}

.btn-multiselect-toggle.has-selection {
  border-color: rgba(56, 189, 248, 0.5);
  background: rgba(56, 189, 248, 0.08);
}

.multiselect-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 170px;
}

.badge-selection-count {
  background: #0284c7;
  color: #ffffff;
  font-size: 0.72rem;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: 999px;
  margin-left: 8px;
}

.toggle-icon {
  font-size: 0.75rem;
  color: #94a3b8;
  transition: transform 0.2s ease;
}

.toggle-icon.rotate {
  transform: rotate(180deg);
}

.multiselect-dropdown-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  width: 320px;
  max-width: 90vw;
  background: #0f172a;
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 14px;
  box-shadow: 0 14px 35px rgba(0, 0, 0, 0.6);
  z-index: 100;
  overflow: hidden;
  backdrop-filter: blur(20px);
  animation: dropdownFade 0.15s ease-out;
}

@keyframes dropdownFade {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: translateY(0); }
}

.dropdown-search-wrapper {
  position: relative;
  padding: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.dropdown-search-icon {
  position: absolute;
  left: 20px;
  top: 50%;
  transform: translateY(-50%);
  color: #64748b;
  font-size: 0.85rem;
}

.dropdown-search-input {
  background: rgba(0, 0, 0, 0.4) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: #ffffff !important;
  padding: 6px 10px 6px 34px !important;
  border-radius: 8px !important;
  font-size: 0.82rem !important;
  height: 34px;
}

.dropdown-actions-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.btn-quick-link {
  background: none;
  border: none;
  color: #38bdf8;
  font-size: 0.76rem;
  font-weight: 700;
  cursor: pointer;
  padding: 2px 4px;
}

.btn-quick-link:hover {
  text-decoration: underline;
}

.dropdown-items-list {
  max-height: 240px;
  overflow-y: auto;
  padding: 6px 0;
}

.dropdown-checkbox-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  cursor: pointer;
  user-select: none;
  font-size: 0.82rem;
  color: #e2e8f0;
  transition: background 0.15s ease;
  margin: 0;
}

.dropdown-checkbox-item:hover {
  background: rgba(56, 189, 248, 0.1);
  color: #ffffff;
}

.dropdown-checkbox-item input[type="checkbox"] {
  accent-color: #0284c7;
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.sec-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sec-count {
  font-size: 0.72rem;
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 6px;
  border-radius: 4px;
}

/* ACTIVE PILLS ROW */
.active-tags-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.active-sec-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(56, 189, 248, 0.12);
  color: #93c5fd;
  border: 1px solid rgba(56, 189, 248, 0.25);
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 0.76rem;
  font-weight: 600;
}

.btn-remove-tag {
  background: none;
  border: none;
  color: #93c5fd;
  cursor: pointer;
  padding: 0;
  font-size: 0.95rem;
  display: flex;
  align-items: center;
}

.btn-remove-tag:hover {
  color: #ffffff;
}

.btn-clear-all-tags {
  background: none;
  border: none;
  color: #f87171;
  font-size: 0.76rem;
  font-weight: 700;
  cursor: pointer;
  padding: 2px 6px;
}

.btn-clear-all-tags:hover {
  text-decoration: underline;
}

/* ========================================================================== */
/* TABELA COMPACTA E OTIMIZADA PARA ALTA ESCALA                              */
/* ========================================================================== */
.table-card {
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 18px;
  overflow: hidden;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
}

.table-header-box {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.table-title {
  font-size: 1.1rem;
  font-weight: 800;
  color: #ffffff;
  display: flex;
  align-items: center;
}

.badge-count {
  font-size: 0.78rem;
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
  padding: 2px 10px;
  border-radius: 999px;
  font-weight: 800;
  margin-left: 10px;
  border: 1px solid rgba(56, 189, 248, 0.25);
}

.table-header-controls {
  display: flex;
  align-items: center;
}

.select-page-size {
  background: rgba(0, 0, 0, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #ffffff;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 0.82rem;
  cursor: pointer;
}

.custom-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.custom-table th {
  padding: 11px 16px;
  font-size: 0.72rem;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 700;
  letter-spacing: 0.5px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.custom-table td {
  padding: 10px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 0.85rem;
  vertical-align: middle;
}

.custom-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.03);
}

.avatar-cell {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  overflow: hidden;
  background: #000;
  border: 1px solid rgba(255, 255, 255, 0.15);
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease;
}

.avatar-cell:hover {
  transform: scale(1.1);
  border-color: #38bdf8;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  color: #64748b;
}

.participant-compact-name {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.participant-name {
  font-weight: 700;
  font-size: 0.88rem;
  line-height: 1.2;
}

.vinculo-tag-compact {
  display: inline-block;
  font-size: 0.68rem;
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.05);
  padding: 1px 6px;
  border-radius: 4px;
  width: fit-content;
}

.cpf-badge-compact {
  display: inline-block;
  color: #38bdf8;
  font-weight: 700;
  font-size: 0.86rem;
  white-space: nowrap !important;
  letter-spacing: 0.4px;
}

.sec-compact-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sec-tag-compact {
  display: inline-block;
  background: rgba(56, 189, 248, 0.1);
  color: #93c5fd;
  border: 1px solid rgba(56, 189, 248, 0.2);
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.74rem;
  font-weight: 600;
  width: fit-content;
}

.setor-text-compact {
  font-size: 0.72rem;
  color: var(--text-muted);
}

.lote-compact-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.badge-lote-compact {
  display: inline-block;
  background: rgba(245, 158, 11, 0.12);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.2);
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.74rem;
  font-weight: 700;
  width: fit-content;
}

.token-code-compact {
  display: block;
  font-size: 0.68rem;
  color: var(--text-muted);
}

.status-badge-compact {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.74rem;
  font-weight: 700;
  white-space: nowrap;
}

.status-badge-compact.bg-success {
  background: rgba(16, 185, 129, 0.12);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.status-badge-compact.bg-warning {
  background: rgba(245, 158, 11, 0.12);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.action-buttons-group {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.btn-action-icon-compact {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 0.88rem;
  border: 1px solid transparent;
}

.btn-icon-cyan {
  background: rgba(56, 189, 248, 0.1);
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.25);
}

.btn-icon-cyan:hover {
  background: rgba(56, 189, 248, 0.25);
  color: #ffffff;
  transform: translateY(-1px);
}

.btn-icon-amber {
  background: rgba(245, 158, 11, 0.1);
  color: #fbbf24;
  border-color: rgba(245, 158, 11, 0.25);
}

.btn-icon-amber:hover {
  background: rgba(245, 158, 11, 0.25);
  color: #ffffff;
  transform: translateY(-1px);
}

.btn-icon-danger {
  background: rgba(239, 68, 68, 0.1);
  color: #f87171;
  border-color: rgba(239, 68, 68, 0.25);
}

.btn-icon-danger:hover {
  background: rgba(239, 68, 68, 0.25);
  color: #ffffff;
  transform: translateY(-1px);
}

/* ========================================================================== */
/* RODAPÉ COM PAGINAÇÃO                                                       */
/* ========================================================================== */
.pagination-footer {
  padding: 14px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  background: rgba(0, 0, 0, 0.2);
}

.pagination-info {
  font-size: 0.84rem;
}

.pagination-buttons {
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-page-nav,
.btn-page-number {
  min-width: 34px;
  height: 34px;
  padding: 0 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
  font-size: 0.84rem;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.btn-page-nav:hover:not(:disabled),
.btn-page-number:hover:not(:disabled):not(.dots) {
  background: rgba(56, 189, 248, 0.2);
  border-color: rgba(56, 189, 248, 0.4);
  color: #ffffff;
}

.btn-page-number.active {
  background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
  border-color: #38bdf8;
  color: #ffffff;
  box-shadow: 0 0 12px rgba(56, 189, 248, 0.4);
}

.btn-page-number.dots {
  background: none;
  border: none;
  cursor: default;
  color: #64748b;
}

.btn-page-nav:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.zoom-photo-img {
  max-width: 100%;
  max-height: 420px;
  border-radius: 16px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
}

.qr-box-preview {
  background: #ffffff;
  padding: 20px;
  border-radius: 18px;
  display: inline-block;
  margin: 14px auto;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.qr-preview-img {
  width: 210px;
  height: 210px;
}

.recipient-badge {
  background: rgba(0, 0, 0, 0.35);
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.text-cyan { color: #38bdf8 !important; }
.text-end { text-align: right; }
.text-center { text-align: center; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.ms-2 { margin-left: 8px; }
.text-white { color: #ffffff; }
.text-muted { color: #94a3b8; }
.text-success { color: #10b981; }
.text-warning { color: #f59e0b; }
.text-danger { color: #ef4444; }
.flex-1 { flex: 1; }
</style>
