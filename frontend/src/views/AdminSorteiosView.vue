<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import Modal from '../components/Modal.vue'

const router = useRouter()
const activeTab = ref('mesa')

const loading = ref(true)
const premios = ref([])
const totalPresentes = ref(0)
const eixos = ref([])
const todasSecretarias = ref([])
const historicoGanhadores = ref([])

const showModalNovoPremio = ref(false)
const showModalEditarPremio = ref(false)
const showModalEixo = ref(false)
const showModalAnular = ref(false)
const showModalSucessoSorteio = ref(false)

const sorteioResultado = ref(null)
const sorteandoId = ref(null)
const ganhadorAnulando = ref(null)
const motivoAnulacao = ref('Servidor ausente no momento do sorteio')

const premioForm = ref({
  id: null,
  nome: '',
  descricao: '',
  categoria: 'categoria_1',
  eixo_id: '0',
  quantidade: 1,
  foto_base64: '',
  foto_preview: ''
})

const eixoForm = ref({
  id: null,
  nome: '',
  descricao: '',
  secretarias_selecionadas: []
})

let pollInterval = null

async function carregarDados(silent = false) {
  try {
    if (!silent) loading.value = true
    const resPremios = await fetch('/api/sorteios/premios')
    if (resPremios.ok) {
      const dataP = await resPremios.json()
      premios.value = dataP.premios || []
      totalPresentes.value = dataP.total_presentes || 0
    }

    const resEixos = await fetch('/api/sorteios/eixos')
    if (resEixos.ok) {
      const dataE = await resEixos.json()
      eixos.value = dataE.eixos || []
      todasSecretarias.value = dataE.todas_secretarias || []
    }

    const resTelao = await fetch('/api/sorteios/live-telao')
    if (resTelao.ok) {
      const dataT = await resTelao.json()
      const todos = []
      if (dataT.ultimo_ganhador) {
        todos.push({
          id: dataT.ultimo_ganhador.ganhador_id,
          servidor_nome: dataT.ultimo_ganhador.servidor.nome,
          servidor_cpf: dataT.ultimo_ganhador.servidor.cpf,
          secretaria_nome: dataT.ultimo_ganhador.servidor.secretaria?.nome || 'Geral',
          premio_nome: dataT.ultimo_ganhador.premio.nome,
          categoria: dataT.ultimo_ganhador.categoria === 'categoria_1' ? 'Cat 1 (Geral)' : 'Cat 2 (Eixo)',
          data_sorteio: new Date(dataT.ultimo_ganhador.data_sorteio).toLocaleString('pt-BR')
        })
      }
      if (dataT.ultimos_ganhadores) {
        dataT.ultimos_ganhadores.forEach(g => {
          todos.push({
            id: g.ganhador_id,
            servidor_nome: g.servidor_nome,
            servidor_cpf: '***',
            secretaria_nome: g.secretaria_nome,
            premio_nome: g.premio_nome,
            categoria: 'Cat 1 (Geral)',
            data_sorteio: g.data_sorteio
          })
        })
      }
      historicoGanhadores.value = todos
    }

    if (!silent) loading.value = false
  } catch (err) {
    if (!silent) console.error('Erro carregando dados:', err)
    if (!silent) loading.value = false
  }
}

async function handleSortear(p) {
  if (p.disponiveis <= 0) return
  if (!confirm('Deseja realizar o sorteio de "' + p.nome + '" agora? O telão será sincronizado instantaneamente!')) return

  sorteandoId.value = p.id
  try {
    const res = await fetch('/api/sorteios/executar/' + p.id, { method: 'POST' })
    const data = await res.json()

    if (!res.ok) {
      alert(data.detail || 'Erro ao realizar sorteio.')
      sorteandoId.value = null
      return
    }

    sorteioResultado.value = data
    showModalSucessoSorteio.value = true
    await carregarDados()
  } catch (e) {
    console.error('Erro ao sortear:', e)
  } finally {
    sorteandoId.value = null
  }
}

function abrirAnulacao(g) {
  ganhadorAnulando.value = g
  motivoAnulacao.value = 'Servidor ausente no momento do sorteio'
  showModalAnular.value = true
}

async function confirmarAnulacao() {
  if (!ganhadorAnulando.value) return
  try {
    const formData = new FormData()
    formData.append('motivo', motivoAnulacao.value)

    const res = await fetch('/api/sorteios/anular/' + ganhadorAnulando.value.id, {
      method: 'POST',
      body: formData
    })

    if (res.ok) {
      showModalAnular.value = false
      await carregarDados()
    } else {
      const d = await res.json()
      alert(d.detail || 'Erro ao anular.')
    }
  } catch (e) {
    console.error('Erro anulando:', e)
  }
}

function abrirNovoPremio() {
  premioForm.value = {
    id: null,
    nome: '',
    descricao: '',
    categoria: 'categoria_1',
    eixo_id: eixos.value.length > 0 ? String(eixos.value[0].id) : '0',
    quantidade: 1,
    foto_base64: '',
    foto_preview: ''
  }
  showModalNovoPremio.value = true
}

function abrirEditarPremio(p) {
  premioForm.value = {
    id: p.id,
    nome: p.nome,
    descricao: p.descricao || '',
    categoria: p.categoria,
    eixo_id: p.eixo_id ? String(p.eixo_id) : '0',
    quantidade: p.quantidade,
    foto_base64: '',
    foto_preview: p.foto_url || ''
  }
  showModalEditarPremio.value = true
}

function onFotoPremioChange(e) {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    premioForm.value.foto_base64 = reader.result
    premioForm.value.foto_preview = reader.result
  }
  reader.readAsDataURL(file)
}

async function handleSalvarPremio(isEdit = false) {
  try {
    const formData = new FormData()
    formData.append('nome', premioForm.value.nome)
    formData.append('descricao', premioForm.value.descricao)
    formData.append('categoria', premioForm.value.categoria)
    formData.append('eixo_id', premioForm.value.eixo_id)
    formData.append('quantidade', premioForm.value.quantidade)
    if (premioForm.value.foto_base64) {
      formData.append('foto_base64', premioForm.value.foto_base64)
    }

    const url = isEdit ? '/api/sorteios/premios/' + premioForm.value.id : '/api/sorteios/premios'
    const method = isEdit ? 'PUT' : 'POST'

    const res = await fetch(url, { method, body: formData })
    if (res.ok) {
      showModalNovoPremio.value = false
      showModalEditarPremio.value = false
      await carregarDados()
    } else {
      const d = await res.json()
      alert(d.detail || 'Erro ao salvar prêmio.')
    }
  } catch (e) {
    console.error('Erro salvando premio:', e)
  }
}

async function handleExcluirPremio(pId) {
  if (!confirm('Deseja realmente excluir este prêmio?')) return
  try {
    const res = await fetch('/api/sorteios/premios/' + pId, { method: 'DELETE' })
    if (res.ok) {
      await carregarDados()
    } else {
      const d = await res.json()
      alert(d.detail || 'Não foi possível excluir.')
    }
  } catch (e) {
    console.error('Erro excluindo:', e)
  }
}

function abrirNovoEixo() {
  eixoForm.value = {
    id: null,
    nome: '',
    descricao: '',
    secretarias_selecionadas: []
  }
  showModalEixo.value = true
}

function abrirEditarEixo(e) {
  eixoForm.value = {
    id: e.id,
    nome: e.nome,
    descricao: e.descricao || '',
    secretarias_selecionadas: e.secretarias.map(s => s.id)
  }
  showModalEixo.value = true
}

function toggleSecretariaNoEixo(secId) {
  const idx = eixoForm.value.secretarias_selecionadas.indexOf(secId)
  if (idx > -1) {
    eixoForm.value.secretarias_selecionadas.splice(idx, 1)
  } else {
    eixoForm.value.secretarias_selecionadas.push(secId)
  }
}

async function handleSalvarEixo() {
  try {
    const formData = new FormData()
    formData.append('nome', eixoForm.value.nome)
    formData.append('descricao', eixoForm.value.descricao)
    formData.append('secretaria_ids', eixoForm.value.secretarias_selecionadas.join(','))
    if (eixoForm.value.id) {
      formData.append('eixo_id', eixoForm.value.id)
    }

    const res = await fetch('/api/sorteios/eixos', { method: 'POST', body: formData })
    if (res.ok) {
      showModalEixo.value = false
      await carregarDados()
    } else {
      const d = await res.json()
      alert(d.detail || 'Erro ao salvar eixo.')
    }
  } catch (e) {
    console.error('Erro salvando eixo:', e)
  }
}

async function handleExcluirEixo(eixoId) {
  if (!confirm('Deseja realmente excluir este eixo?')) return
  try {
    const res = await fetch('/api/sorteios/eixos/' + eixoId, { method: 'DELETE' })
    if (res.ok) {
      await carregarDados()
    }
  } catch (e) {
    console.error('Erro excluindo eixo:', e)
  }
}

function abrirTelaoEmNovaJanela() {
  window.open('/telao', '_blank')
}

onMounted(() => {
  carregarDados()
})
</script>
<template>
  <div class="admin-sorteios-page">
    <div class="app-container">
      
      <div class="page-header-row">
        <div>
          <span class="vip-badge bg-primary mb-2">
            <i class="bi bi-trophy-fill me-1"></i> Central de Sorteios
          </span>
          <h1 class="page-title font-outfit">Gestão e Mesa de Sorteios</h1>
          <p class="page-subtitle">Controle de prêmios, eixos temáticos e execução em tempo real.</p>
        </div>

        <div class="header-btns">
          <button type="button" class="btn-telao-pop font-outfit" @click="abrirTelaoEmNovaJanela">
            <i class="bi bi-display-fill me-1"></i> Abrir Telão de Projeção
          </button>
        </div>
      </div>

      <div class="tabs-nav-bar">
        <button
          type="button"
          :class="['tab-btn font-outfit', { active: activeTab === 'mesa' }]"
          @click="activeTab = 'mesa'"
        >
          <i class="bi bi-dice-5-fill me-1"></i> Mesa de Sorteio ao Vivo
        </button>

        <button
          type="button"
          :class="['tab-btn font-outfit', { active: activeTab === 'premios' }]"
          @click="activeTab = 'premios'"
        >
          <i class="bi bi-gift-fill me-1"></i> Gestão de Prêmios ({{ premios.length }})
        </button>

        <button
          type="button"
          :class="['tab-btn font-outfit', { active: activeTab === 'eixos' }]"
          @click="activeTab = 'eixos'"
        >
          <i class="bi bi-diagram-3-fill me-1"></i> Eixos & Secretarias ({{ eixos.length }})
        </button>

        <button
          type="button"
          :class="['tab-btn font-outfit', { active: activeTab === 'historico' }]"
          @click="activeTab = 'historico'"
        >
          <i class="bi bi-clock-history me-1"></i> Histórico de Ganhadores
        </button>
      </div>

      <!-- ABA 1: MESA DE SORTEIO -->
      <div v-if="activeTab === 'mesa'" class="tab-pane">
        <div class="deck-top-bar">
          <span class="badge-presentes">
            <i class="bi bi-person-check-fill text-success me-1"></i>
            <strong>{{ totalPresentes }}</strong> servidores presentes na festa
          </span>
          <button type="button" class="btn-secondary btn-sm" @click="carregarDados">
            <i class="bi bi-arrow-repeat me-1"></i> Atualizar Presenças
          </button>
        </div>

        <div class="prizes-grid">
          <div
            v-for="p in premios"
            :key="p.id"
            class="prize-card-live"
            :class="{ 'prize-completed': p.disponiveis === 0 }"
          >
            <div class="prize-card-photo-box">
              <img v-if="p.foto_url" :src="p.foto_url" alt="Prêmio" class="prize-card-img" />
              <div v-else class="prize-placeholder"><i class="bi bi-gift-fill"></i></div>
              
              <span :class="['cat-badge font-outfit', p.categoria === 'categoria_1' ? 'cat-1' : 'cat-2']">
                {{ p.categoria === 'categoria_1' ? 'Cat 1 (Geral)' : 'Cat 2 (' + (p.eixo_nome || 'Eixo') + ')' }}
              </span>
            </div>

            <div class="prize-card-content">
              <h3 class="prize-card-title font-outfit">{{ p.nome }}</h3>
              <p v-if="p.descricao" class="prize-card-desc">{{ p.descricao }}</p>

              <div class="prize-metrics-row">
                <div class="metric-pill">
                  <span class="m-k">Cotas:</span>
                  <strong class="m-v">{{ p.quantidade_sorteada }} / {{ p.quantidade }}</strong>
                </div>
                <div class="metric-pill">
                  <span class="m-k">Elegíveis:</span>
                  <strong class="m-v text-success">{{ p.elegiveis_presentes }}</strong>
                </div>
              </div>

              <div class="prize-card-action">
                <button
                  v-if="p.disponiveis > 0"
                  type="button"
                  class="btn-sortear font-outfit"
                  :disabled="sorteandoId === p.id || p.elegiveis_presentes === 0"
                  @click="handleSortear(p)"
                >
                  <i class="bi bi-stars me-1"></i>
                  <span v-if="sorteandoId === p.id">Sorteando...</span>
                  <span v-else-if="p.elegiveis_presentes === 0">Sem Elegíveis</span>
                  <span v-else>REALIZAR SORTEIO</span>
                </button>

                <div v-else class="btn-completed font-outfit">
                  <i class="bi bi-check-all me-1"></i> Sorteio Concluído
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="premios.length === 0" class="empty-box">
          <i class="bi bi-gift text-muted fs-1 mb-2"></i>
          <p class="text-muted">Nenhum prêmio cadastrado. Vá até a aba <strong>Gestão de Prêmios</strong>.</p>
        </div>
      </div>

      <!-- ABA 2: CRUD PRÊMIOS -->
      <div v-if="activeTab === 'premios'" class="tab-pane">
        <div class="tab-actions-header">
          <h3 class="font-outfit text-white fw-bold mb-0">Lista de Prêmios Cadastrados</h3>
          <button type="button" class="btn-primary font-outfit" @click="abrirNovoPremio">
            <i class="bi bi-plus-circle-fill me-1"></i> Cadastrar Novo Prêmio
          </button>
        </div>

        <div class="vip-glass-card table-card">
          <div class="table-responsive">
            <table class="custom-table">
              <thead>
                <tr>
                  <th>Foto</th>
                  <th>Prêmio</th>
                  <th>Categoria</th>
                  <th>Eixo Vinculado</th>
                  <th>Cotas</th>
                  <th class="text-end">Ações</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="premios.length === 0">
                  <td colspan="6" class="text-center py-4 text-muted">Nenhum prêmio cadastrado.</td>
                </tr>
                <tr v-for="p in premios" :key="p.id">
                  <td style="width: 60px;">
                    <div class="table-thumb">
                      <img v-if="p.foto_url" :src="p.foto_url" alt="Foto" class="thumb-img" />
                      <div v-else class="thumb-empty"><i class="bi bi-gift"></i></div>
                    </div>
                  </td>
                  <td>
                    <strong class="text-white">{{ p.nome }}</strong>
                    <span v-if="p.descricao" class="d-block small text-subtle">{{ p.descricao }}</span>
                  </td>
                  <td>
                    <span :class="['cat-badge font-outfit', p.categoria === 'categoria_1' ? 'cat-1' : 'cat-2']">
                      {{ p.categoria_label }}
                    </span>
                  </td>
                  <td>
                    <span v-if="p.eixo_nome" class="sec-tag">{{ p.eixo_nome }}</span>
                    <span v-else class="text-subtle">Geral (Todos)</span>
                  </td>
                  <td>
                    <strong class="text-white">{{ p.quantidade_sorteada }} / {{ p.quantidade }}</strong>
                  </td>
                  <td class="text-end">
                    <button type="button" class="btn-action-icon" title="Editar Prêmio" @click="abrirEditarPremio(p)">
                      <i class="bi bi-pencil-fill text-info"></i>
                    </button>
                    <button
                      type="button"
                      class="btn-action-icon"
                      title="Excluir Prêmio"
                      :disabled="p.quantidade_sorteada > 0"
                      @click="handleExcluirPremio(p.id)"
                    >
                      <i class="bi bi-trash-fill text-danger"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ABA 3: CRUD EIXOS -->
      <div v-if="activeTab === 'eixos'" class="tab-pane">
        <div class="tab-actions-header">
          <div>
            <h3 class="font-outfit text-white fw-bold mb-1">Eixos Temáticos de Secretarias</h3>
            <p class="text-muted small mb-0">Agrupe secretarias para os sorteios exclusivos da Categoria 2.</p>
          </div>
          <button type="button" class="btn-primary font-outfit" @click="abrirNovoEixo">
            <i class="bi bi-diagram-3 me-1"></i> Criar Novo Eixo
          </button>
        </div>

        <div class="eixos-grid">
          <div v-for="e in eixos" :key="e.id" class="vip-glass-card eixo-card">
            <div class="eixo-header">
              <div>
                <h4 class="eixo-title font-outfit">{{ e.nome }}</h4>
                <p v-if="e.descricao" class="eixo-desc">{{ e.descricao }}</p>
              </div>
              <div class="eixo-actions">
                <button type="button" class="btn-action-icon" title="Editar Eixo" @click="abrirEditarEixo(e)">
                  <i class="bi bi-pencil-fill text-info"></i>
                </button>
                <button type="button" class="btn-action-icon" title="Excluir Eixo" @click="handleExcluirEixo(e.id)">
                  <i class="bi bi-trash-fill text-danger"></i>
                </button>
              </div>
            </div>

            <div class="eixo-secretarias-list">
              <span class="sec-label font-outfit">Secretarias Associadas ({{ e.secretarias_count }}):</span>
              <div class="sec-chips-box">
                <span v-for="s in e.secretarias" :key="s.id" class="sec-chip">
                  <i class="bi bi-building me-1"></i> {{ s.nome }}
                </span>
                <span v-if="e.secretarias.length === 0" class="text-subtle small">
                  Nenhuma secretaria vinculada. Clique em editar para vincular.
                </span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="eixos.length === 0" class="empty-box">
          <i class="bi bi-diagram-3 text-muted fs-1 mb-2"></i>
          <p class="text-muted">Nenhum eixo cadastrado. Clique em <strong>Criar Novo Eixo</strong>.</p>
        </div>
      </div>

      <!-- ABA 4: HISTÓRICO -->
      <div v-if="activeTab === 'historico'" class="tab-pane">
        <div class="tab-actions-header">
          <h3 class="font-outfit text-white fw-bold mb-0">Histórico de Ganhadores</h3>
          <button type="button" class="btn-secondary btn-sm" @click="carregarDados">
            <i class="bi bi-arrow-repeat me-1"></i> Atualizar
          </button>
        </div>

        <div class="vip-glass-card table-card">
          <div class="table-responsive">
            <table class="custom-table">
              <thead>
                <tr>
                  <th>Servidor</th>
                  <th>Secretaria</th>
                  <th>Prêmio Conquistado</th>
                  <th>Categoria</th>
                  <th>Data/Hora</th>
                  <th class="text-end">Ação</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="historicoGanhadores.length === 0">
                  <td colspan="6" class="text-center py-4 text-muted">Nenhum sorteio registrado ainda.</td>
                </tr>
                <tr v-for="g in historicoGanhadores" :key="g.id">
                  <td>
                    <strong class="text-white">{{ g.servidor_nome }}</strong>
                    <span class="d-block small text-subtle font-monospace">{{ g.servidor_cpf }}</span>
                  </td>
                  <td><span class="sec-tag">{{ g.secretaria_nome }}</span></td>
                  <td><strong class="text-warning">{{ g.premio_nome }}</strong></td>
                  <td><span class="cat-badge cat-1">{{ g.categoria }}</span></td>
                  <td><span class="small text-light">{{ g.data_sorteio }}</span></td>
                  <td class="text-end">
                    <button
                      type="button"
                      class="btn-danger-sm"
                      title="Anular Sorteio (Servidor Ausente)"
                      @click="abrirAnulacao(g)"
                    >
                      <i class="bi bi-x-circle me-1"></i> Anular
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

    </div>

    <!-- MODAL PRÊMIO -->
    <Modal
      :show="showModalNovoPremio || showModalEditarPremio"
      :title="showModalEditarPremio ? 'Editar Prêmio' : 'Cadastrar Novo Prêmio'"
      icon="bi-gift-fill"
      @close="showModalNovoPremio = false; showModalEditarPremio = false;"
    >
      <form @submit.prevent="handleSalvarPremio(showModalEditarPremio)">
        <div class="form-group">
          <label class="form-label">Nome do Prêmio *</label>
          <input v-model="premioForm.nome" type="text" class="form-control" placeholder="Ex: Smart TV 55 4K" required />
        </div>

        <div class="form-group">
          <label class="form-label">Descrição</label>
          <input v-model="premioForm.descricao" type="text" class="form-control" placeholder="Ex: Modelo 2026 com Bluetooth" />
        </div>

        <div class="form-grid-2">
          <div class="form-group">
            <label class="form-label">Categoria *</label>
            <select v-model="premioForm.categoria" class="form-select" required>
              <option value="categoria_1">Categoria 1 (Geral)</option>
              <option value="categoria_2">Categoria 2 (Eixo Setorial)</option>
            </select>
          </div>

          <div class="form-group" v-if="premioForm.categoria === 'categoria_2'">
            <label class="form-label">Eixo Vinculado *</label>
            <select v-model="premioForm.eixo_id" class="form-select" required>
              <option value="0" disabled>Selecione o Eixo</option>
              <option v-for="e in eixos" :key="e.id" :value="String(e.id)">
                {{ e.nome }}
              </option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Quantidade *</label>
            <input v-model="premioForm.quantidade" type="number" min="1" class="form-control" required />
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Foto do Prêmio</label>
          <input type="file" accept="image/*" class="form-control" @change="onFotoPremioChange" />
          <div v-if="premioForm.foto_preview" class="photo-preview-box mt-2">
            <img :src="premioForm.foto_preview" alt="Preview" class="preview-img" />
          </div>
        </div>

        <div class="modal-footer-box">
          <button type="button" class="btn-secondary" @click="showModalNovoPremio = false; showModalEditarPremio = false;">Cancelar</button>
          <button type="submit" class="btn-primary">Salvar Prêmio</button>
        </div>
      </form>
    </Modal>

    <!-- MODAL EIXO -->
    <Modal
      :show="showModalEixo"
      :title="eixoForm.id ? 'Editar Eixo Temático' : 'Criar Novo Eixo'"
      icon="bi-diagram-3-fill"
      @close="showModalEixo = false"
    >
      <form @submit.prevent="handleSalvarEixo">
        <div class="form-group">
          <label class="form-label">Nome do Eixo *</label>
          <input v-model="eixoForm.nome" type="text" class="form-control" placeholder="Ex: Eixo Saúde e Bem-Estar" required />
        </div>

        <div class="form-group">
          <label class="form-label">Descrição</label>
          <input v-model="eixoForm.descricao" type="text" class="form-control" placeholder="Ex: Secretarias do setor da saúde" />
        </div>

        <div class="form-group">
          <label class="form-label">Secretarias que pertencem a este Eixo:</label>
          <div class="secretarias-checkbox-grid">
            <div
              v-for="s in todasSecretarias"
              :key="s.id"
              :class="['sec-check-item', { selected: eixoForm.secretarias_selecionadas.includes(s.id) }]"
              @click="toggleSecretariaNoEixo(s.id)"
            >
              <i :class="['bi', eixoForm.secretarias_selecionadas.includes(s.id) ? 'bi-check-square-fill text-primary' : 'bi-square']"></i>
              <span>{{ s.nome }}</span>
            </div>
          </div>
        </div>

        <div class="modal-footer-box">
          <button type="button" class="btn-secondary" @click="showModalEixo = false">Cancelar</button>
          <button type="submit" class="btn-primary">Salvar Eixo</button>
        </div>
      </form>
    </Modal>

    <!-- MODAL ANULAR -->
    <Modal
      :show="showModalAnular"
      title="Anular Sorteio"
      icon="bi-exclamation-triangle-fill"
      icon-color="text-danger"
      @close="showModalAnular = false"
    >
      <div v-if="ganhadorAnulando">
        <p class="text-light">
          Deseja anular o sorteio de <strong>{{ ganhadorAnulando.servidor_nome }}</strong> para o prêmio <strong>{{ ganhadorAnulando.premio_nome }}</strong>?
        </p>
        <div class="form-group">
          <label class="form-label">Motivo da Anulação</label>
          <input v-model="motivoAnulacao" type="text" class="form-control" required />
        </div>
      </div>
      <template #footer>
        <button type="button" class="btn-secondary" @click="showModalAnular = false">Cancelar</button>
        <button type="button" class="btn-danger" @click="confirmarAnulacao">Confirmar Anulação</button>
      </template>
    </Modal>

    <!-- MODAL SUCESSO -->
    <Modal
      :show="showModalSucessoSorteio"
      title="Sorteio Realizado com Sucesso!"
      icon="bi-trophy-fill"
      icon-color="text-warning"
      @close="showModalSucessoSorteio = false"
    >
      <div v-if="sorteioResultado" class="text-center py-3">
        <i class="bi bi-stars text-warning display-4 mb-2"></i>
        <h3 class="font-outfit text-white fw-bold mb-1">{{ sorteioResultado.servidor_nome }}</h3>
        <p class="text-warning fs-5 fw-bold mb-2">{{ sorteioResultado.premio_nome }}</p>
        <p class="text-muted small">O telão foi sincronizado e está exibindo a comemoração oficial.</p>
      </div>
      <template #footer>
        <button type="button" class="btn-primary w-100 font-outfit" @click="showModalSucessoSorteio = false">
          Continuar
        </button>
      </template>
    </Modal>

  </div>
</template>

<style scoped>
.admin-sorteios-page {
  padding: 24px 0 60px;
}

.page-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}

.page-title {
  font-size: clamp(1.6rem, 4vw, 2.1rem);
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.page-subtitle {
  color: var(--text-muted);
  font-size: 0.88rem;
}

.btn-telao-pop {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  border: 1px solid rgba(245, 158, 11, 0.6);
  color: #000000 !important;
  font-weight: 800;
  font-size: 0.95rem;
  padding: 10px 20px;
  border-radius: 12px;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(245, 158, 11, 0.4);
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.btn-telao-pop:hover {
  transform: translateY(-2px);
  filter: brightness(1.1);
  box-shadow: 0 6px 25px rgba(245, 158, 11, 0.6);
}

/* ABAS / TABS */
.tabs-nav-bar {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 28px;
  overflow-x: auto;
  padding-bottom: 6px;
}

.tab-btn {
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-muted);
  font-weight: 700;
  font-size: 0.92rem;
  padding: 10px 18px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.tab-btn:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.05);
}

.tab-btn.active {
  color: #ffffff;
  background: var(--serv-gradient);
  border-color: rgba(255, 255, 255, 0.2);
  box-shadow: 0 4px 15px rgba(217, 70, 239, 0.35);
}

.deck-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

.badge-presentes {
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.35);
  color: #34d399;
  padding: 8px 16px;
  border-radius: 999px;
  font-size: 0.9rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
}

/* CARDS DE PRÊMIOS */
.prizes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.prize-card-live {
  background: var(--bg-card);
  border: 1px solid var(--border-glass);
  border-radius: 20px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: all 0.25s ease;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}

.prize-card-live:hover {
  border-color: rgba(6, 182, 212, 0.4);
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5);
  transform: translateY(-2px);
}

.prize-card-live.prize-completed {
  opacity: 0.7;
}

.prize-card-photo-box {
  position: relative;
  width: 100%;
  height: 180px;
  background: #050811;
  display: flex;
  align-items: center;
  justify-content: center;
}

.prize-card-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.prize-placeholder {
  font-size: 3.5rem;
  color: #475569;
}

.cat-badge {
  font-size: 0.74rem;
  font-weight: 800;
  padding: 4px 10px;
  border-radius: 999px;
  letter-spacing: 0.5px;
  display: inline-flex;
  align-items: center;
}

.cat-1 {
  background: rgba(6, 182, 212, 0.2);
  color: #22d3ee;
  border: 1px solid rgba(6, 182, 212, 0.4);
}

.cat-2 {
  background: rgba(245, 158, 11, 0.2);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.4);
}

.prize-card-content {
  padding: 20px;
  display: flex;
  flex-direction: column;
  flex: 1;
}

.prize-card-title {
  font-size: 1.2rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.prize-card-desc {
  font-size: 0.82rem;
  color: var(--text-muted);
  margin-bottom: 14px;
}

.prize-metrics-row {
  display: flex;
  gap: 8px;
  margin-bottom: 18px;
}

.metric-pill {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 0.75rem;
  flex: 1;
}

.m-k {
  display: block;
  color: var(--text-subtle);
  font-size: 0.7rem;
  text-transform: uppercase;
  font-weight: 700;
}

.m-v {
  font-size: 1rem;
  font-weight: 800;
  color: #ffffff;
}

.btn-sortear {
  background: var(--serv-gradient);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #ffffff;
  font-weight: 800;
  font-size: 1rem;
  padding: 12px;
  border-radius: 12px;
  width: 100%;
  cursor: pointer;
  box-shadow: 0 4px 15px rgba(217, 70, 239, 0.35);
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.btn-sortear:hover:not(:disabled) {
  background: var(--serv-gradient-hover);
  transform: translateY(-2px);
  box-shadow: 0 6px 22px rgba(245, 158, 11, 0.45);
}

.btn-sortear:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-completed {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text-muted);
  font-weight: 700;
  padding: 12px;
  border-radius: 12px;
  text-align: center;
}

.tab-actions-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

/* EIXOS */
.eixos-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 20px;
}

.eixo-card {
  padding: 24px;
}

.eixo-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.eixo-title {
  font-size: 1.3rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.eixo-desc {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-bottom: 0;
}

.eixo-actions {
  display: flex;
  gap: 6px;
}

.sec-label {
  display: block;
  font-size: 0.76rem;
  text-transform: uppercase;
  color: var(--text-subtle);
  font-weight: 700;
  margin-bottom: 8px;
}

.sec-chips-box {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sec-chip {
  background: rgba(6, 182, 212, 0.12);
  border: 1px solid rgba(6, 182, 212, 0.3);
  color: #67e8f9;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.sec-tag {
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.3);
  color: #fde047;
  font-size: 0.78rem;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
}

.secretarias-checkbox-grid {
  max-height: 220px;
  overflow-y: auto;
  display: grid;
  grid-template-columns: 1fr;
  gap: 6px;
  padding-right: 6px;
}

.sec-check-item {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: all 0.15s ease;
}

.sec-check-item:hover, .sec-check-item.selected {
  background: rgba(6, 182, 212, 0.15);
  border-color: rgba(6, 182, 212, 0.35);
  color: #ffffff;
}

.table-thumb {
  width: 46px;
  height: 46px;
  border-radius: 10px;
  overflow: hidden;
  background: #000;
  border: 1px solid rgba(255, 255, 255, 0.15);
}

.thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumb-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  font-size: 1.2rem;
}

.photo-preview-box {
  width: 100px;
  height: 100px;
  border-radius: 12px;
  overflow: hidden;
  border: 2px solid var(--primary-accent);
}

.preview-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.empty-box {
  text-align: center;
  padding: 60px 20px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px dashed rgba(255, 255, 255, 0.1);
  border-radius: 20px;
}

.text-end { text-align: right; }
.w-100 { width: 100%; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.mb-0 { margin-bottom: 0; }
.mb-1 { margin-bottom: 4px; }
.mb-2 { margin-bottom: 8px; }
.mt-2 { margin-top: 8px; }
.text-danger { color: #ef4444; }
.text-warning { color: #f59e0b; }
.text-success { color: #10b981; }
.text-info { color: #38bdf8; }
.text-white { color: #ffffff; }
.text-subtle { color: var(--text-subtle); }
</style>