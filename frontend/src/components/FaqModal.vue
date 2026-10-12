<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useAuth } from '../composables/useAuth'
import { useToast } from '../composables/useToast'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue'])

const { isAdminGeral } = useAuth()
const { toast } = useToast()

const faqs = ref([])
const loading = ref(false)
const searchTerm = ref('')
const activeId = ref(null)

// Estados de Edição Administrativa (Admin Geral)
const showForm = ref(false)
const isEditing = ref(false)
const saving = ref(false)
const deletingId = ref(null)

const formData = ref({
  id: null,
  pergunta: '',
  resposta: '',
  ordem: 1,
  ativo: true
})

function fecharModal() {
  cancelarForm()
  emit('update:modelValue', false)
}

async function carregarFaqs() {
  loading.value = true
  try {
    const res = await fetch('/api/faq', { cache: 'no-store' })
    if (res.ok) {
      const data = await res.json()
      faqs.value = data.itens || []
      // Por padrão, se houver itens e nenhum estiver aberto, abre o primeiro
      if (faqs.value.length > 0 && activeId.value === null) {
        activeId.value = faqs.value[0].id
      }
    }
  } catch (err) {
    // Erro silencioso
  } finally {
    loading.value = false
  }
}

watch(() => props.modelValue, (val) => {
  if (val) {
    carregarFaqs()
  } else {
    cancelarForm()
  }
})

const faqsFiltradas = computed(() => {
  if (!searchTerm.value.trim()) return faqs.value
  const termo = searchTerm.value.toLowerCase().trim()
  return faqs.value.filter(item => 
    item.pergunta.toLowerCase().includes(termo) ||
    item.resposta.toLowerCase().includes(termo)
  )
})

function toggleAccordion(id) {
  activeId.value = activeId.value === id ? null : id
}

// -------------------------------------------------------------
// FLUXO ADMINISTRATIVO: CRIAR, EDITAR E EXCLUIR PERGUNTAS
// -------------------------------------------------------------
function abrirCriar() {
  const proximaOrdem = faqs.value.length > 0 
    ? Math.max(...faqs.value.map(f => f.ordem || 0)) + 1 
    : 1

  formData.value = {
    id: null,
    pergunta: '',
    resposta: '',
    ordem: proximaOrdem,
    ativo: true
  }
  isEditing.value = false
  showForm.value = true
}

function abrirEditar(item) {
  formData.value = {
    id: item.id,
    pergunta: item.pergunta,
    resposta: item.resposta,
    ordem: item.ordem,
    ativo: item.ativo
  }
  isEditing.value = true
  showForm.value = true
}

function cancelarForm() {
  showForm.value = false
  formData.value = {
    id: null,
    pergunta: '',
    resposta: '',
    ordem: 1,
    ativo: true
  }
}

async function salvarPergunta() {
  const pergunta = formData.value.pergunta.trim()
  const resposta = formData.value.resposta.trim()

  if (!pergunta) {
    toast.error('Informe o título da pergunta.')
    return
  }
  if (!resposta) {
    toast.error('Informe a resposta da pergunta.')
    return
  }

  saving.value = true
  try {
    const url = isEditing.value ? `/api/faq/${formData.value.id}` : '/api/faq'
    const method = isEditing.value ? 'PUT' : 'POST'

    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pergunta,
        resposta,
        ordem: parseInt(formData.value.ordem) || 0,
        ativo: formData.value.ativo
      })
    })

    const data = await res.json()

    if (!res.ok) {
      toast.error(data.detail || 'Não foi possível salvar a pergunta.')
      return
    }

    toast.success(isEditing.value ? 'Pergunta atualizada com sucesso!' : 'Nova pergunta adicionada com sucesso!')
    cancelarForm()
    await carregarFaqs()
  } catch (err) {
    toast.error('Erro de conexão ao salvar a pergunta.')
  } finally {
    saving.value = false
  }
}

async function excluirPergunta(id) {
  if (!confirm('Tem certeza de que deseja excluir esta pergunta da FAQ?')) {
    return
  }

  deletingId.value = id
  try {
    const res = await fetch(`/api/faq/${id}`, { method: 'DELETE' })
    if (!res.ok) {
      const data = await res.json()
      toast.error(data.detail || 'Erro ao excluir pergunta.')
      return
    }

    toast.success('Pergunta excluída com sucesso!')
    if (activeId.value === id) activeId.value = null
    await carregarFaqs()
  } catch (err) {
    toast.error('Erro de conexão ao excluir pergunta.')
  } finally {
    deletingId.value = null
  }
}

function formatarLinksTexto(texto) {
  if (!texto) return ''
  const regex = /(https?:\/\/[^\s]+|servindoor\.com\.br\/meu-ingresso)/gi
  return texto.replace(regex, (match) => {
    let url = match.startsWith('http') ? match : `https://${match}`
    return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="faq-inline-link">${match}</a>`
  })
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="modelValue" class="faq-modal-overlay" @click.self="fecharModal">
        <div class="faq-modal-container">
          
          <!-- Cabeçalho do Modal -->
          <div class="faq-modal-header">
            <div class="faq-title-group">
              <div class="faq-badge-tag font-outfit">
                <i class="bi bi-question-circle-fill me-1"></i> TIRE SUAS DÚVIDAS
              </div>
              <h2 class="faq-title font-outfit">Perguntas Frequentes</h2>
              <p class="faq-subtitle">
                Orientações oficiais sobre o resgate de ingressos, foto e regras da festa.
              </p>
            </div>

            <div class="faq-header-actions">
              <span v-if="isAdminGeral" class="badge-admin-tag font-outfit">
                <i class="bi bi-shield-lock-fill me-1"></i> Admin Geral
              </span>
              <button
                type="button"
                class="btn-close-custom"
                title="Fechar"
                @click="fecharModal"
              >
                <i class="bi bi-x-lg"></i>
              </button>
            </div>
          </div>

          <!-- Barra de Ações Administrativas e Busca -->
          <div class="faq-toolbar">
            <div class="faq-search-wrap">
              <i class="bi bi-search search-icon"></i>
              <input
                v-model="searchTerm"
                type="text"
                class="faq-search-input"
                placeholder="Buscar dúvida, palavra-chave ou regra..."
              />
              <button
                v-if="searchTerm"
                type="button"
                class="btn-clear-search"
                @click="searchTerm = ''"
              >
                <i class="bi bi-x-circle-fill"></i>
              </button>
            </div>

            <!-- Botão Adicionar Pergunta (Apenas Admin Geral) -->
            <button
              v-if="isAdminGeral && !showForm"
              type="button"
              class="btn-admin-add font-outfit"
              @click="abrirCriar"
            >
              <i class="bi bi-plus-circle-fill me-1"></i> Nova Pergunta
            </button>
          </div>

          <!-- FORMULÁRIO DE CRIAÇÃO / EDIÇÃO DIRETO NO MODAL (ADMIN GERAL) -->
          <div v-if="showForm && isAdminGeral" class="faq-admin-form-card">
            <div class="form-header-bar">
              <span class="form-title font-outfit">
                <i :class="isEditing ? 'bi bi-pencil-square text-cyan' : 'bi bi-plus-circle-fill text-success'" class="me-2"></i>
                {{ isEditing ? 'Editar Pergunta da FAQ' : 'Nova Pergunta para a FAQ' }}
              </span>
              <button type="button" class="btn-cancel-mini" @click="cancelarForm">
                <i class="bi bi-x me-1"></i> Cancelar
              </button>
            </div>

            <form @submit.prevent="salvarPergunta" class="form-body-grid">
              <div class="form-row">
                <label class="form-label" for="faq-pergunta">Pergunta / Título:</label>
                <input
                  id="faq-pergunta"
                  v-model="formData.pergunta"
                  type="text"
                  class="form-control-custom"
                  placeholder="Ex: Como funciona o resgate dos ingressos?"
                  required
                />
              </div>

              <div class="form-row">
                <label class="form-label" for="faq-resposta">Resposta / Explicação:</label>
                <textarea
                  id="faq-resposta"
                  v-model="formData.resposta"
                  rows="4"
                  class="form-control-custom textarea-custom"
                  placeholder="Ex: Após o lote abrir, cada servidor poderá resgatar 1 ingresso por CPF..."
                  required
                ></textarea>
              </div>

              <div class="form-row-flex">
                <div class="form-field-ordem">
                  <label class="form-label" for="faq-ordem">Ordem de Exibição:</label>
                  <input
                    id="faq-ordem"
                    v-model.number="formData.ordem"
                    type="number"
                    min="1"
                    max="999"
                    class="form-control-custom w-auto text-center font-monospace"
                  />
                </div>

                <div class="form-field-switch">
                  <label class="switch-label">
                    <input v-model="formData.ativo" type="checkbox" class="switch-input" />
                    <span class="switch-slider"></span>
                    <span class="switch-text">{{ formData.ativo ? 'Pergunta Ativa' : 'Pergunta Oculta' }}</span>
                  </label>
                </div>
              </div>

              <div class="form-actions-row">
                <button
                  type="submit"
                  class="btn-save-faq font-outfit"
                  :disabled="saving"
                >
                  <span v-if="!saving">
                    <i class="bi bi-check-circle-fill me-1"></i> {{ isEditing ? 'Salvar Alterações' : 'Adicionar Pergunta' }}
                  </span>
                  <span v-else>
                    <i class="bi bi-hourglass-split me-1"></i> Salvando...
                  </span>
                </button>
                <button
                  type="button"
                  class="btn-cancel-faq font-outfit"
                  @click="cancelarForm"
                >
                  Cancelar
                </button>
              </div>
            </form>
          </div>

          <!-- Corpo do Modal: Lista de Perguntas Frequentes (Accordion) -->
          <div class="faq-modal-body">
            
            <div v-if="loading" class="faq-loading-box">
              <div class="spinner-border text-cyan mb-2"></div>
              <p class="text-muted small">Carregando perguntas frequentes...</p>
            </div>

            <div v-else-if="faqsFiltradas.length === 0" class="faq-empty-box">
              <i class="bi bi-search text-muted fs-2 mb-2"></i>
              <p class="text-white mb-1">Nenhuma pergunta encontrada para sua busca.</p>
              <p class="text-muted small">Tente outras palavras-chave ou limpe a busca.</p>
            </div>

            <div v-else class="faq-accordion-list">
              <div
                v-for="(item, index) in faqsFiltradas"
                :key="item.id"
                class="faq-card"
                :class="{ 
                  'faq-card-active': activeId === item.id,
                  'faq-card-inativo': !item.ativo
                }"
              >
                <!-- Cabeçalho da Pergunta -->
                <div
                  class="faq-card-header"
                  @click="toggleAccordion(item.id)"
                >
                  <div class="faq-q-left">
                    <span class="faq-num font-outfit">{{ index + 1 }}</span>
                    <span class="faq-question-title font-outfit">{{ item.pergunta }}</span>
                    <span v-if="!item.ativo" class="badge-oculto font-outfit">Oculta</span>
                  </div>

                  <div class="faq-q-right">
                    <!-- Controles Rápidos de Administrador Geral -->
                    <div v-if="isAdminGeral" class="admin-quick-actions" @click.stop>
                      <button
                        type="button"
                        class="btn-admin-icon"
                        title="Editar pergunta"
                        @click.stop="abrirEditar(item)"
                      >
                        <i class="bi bi-pencil-fill"></i>
                      </button>
                      <button
                        type="button"
                        class="btn-admin-icon text-danger"
                        title="Excluir pergunta"
                        :disabled="deletingId === item.id"
                        @click.stop="excluirPergunta(item.id)"
                      >
                        <i v-if="deletingId === item.id" class="spinner-border spinner-border-sm"></i>
                        <i v-else class="bi bi-trash3-fill"></i>
                      </button>
                    </div>

                    <i
                      class="bi bi-chevron-down faq-chevron"
                      :class="{ 'rotate-180': activeId === item.id }"
                    ></i>
                  </div>
                </div>

                <!-- Conteúdo Expandido da Resposta -->
                <div v-show="activeId === item.id" class="faq-card-answer">
                  <div class="faq-answer-inner">
                    <div class="answer-icon-col">
                      <i class="bi bi-chat-left-quote-fill text-cyan"></i>
                    </div>
                    <div
                      class="answer-text"
                      v-html="formatarLinksTexto(item.resposta)"
                    ></div>
                  </div>
                </div>

              </div>
            </div>

          </div>

          <!-- Rodapé do Modal -->
          <div class="faq-modal-footer">
            <div class="footer-help-tip">
              <i class="bi bi-info-circle-fill text-cyan me-2"></i>
              <span>Ainda tem dúvidas? Acompanhe as orientações no Canal do WhatsApp.</span>
            </div>
            <button type="button" class="btn-close-footer font-outfit" @click="fecharModal">
              Fechar FAQ
            </button>
          </div>

        </div>
      </div>
    </Transition>
  </Teleport>
</template>
