<script setup>
import { computed, onMounted, ref } from 'vue'
import Modal from '../components/Modal.vue'
import KpiCard from '../components/KpiCard.vue'
import RecordPager from '../components/RecordPager.vue'
import DocumentPreview from '../components/DocumentPreview.vue'
import { useConfirm } from '../composables/useConfirm'

const { confirmModal } = useConfirm()
const documents = ref([])
const settings = ref({ require_on_redemption: false, voluntary_enabled: false, communications_enabled: false, token_days: 30 })
const dashboard = ref({})
const error = ref('')
const message = ref('')
const busy = ref(false)
const loading = ref(true)
const selected = ref(null)
const emailPreview = ref(null)
const upload = ref({ kind: 'terms', title: '', version: '', notes: '' })
const file = ref(null)
const uploadInput = ref(null)
const termsId = ref('')
const privacyId = ref('')
const confirmation = ref('')
const tab = ref('communications')
const page = ref(1)
const records = ref({ items: [], total: 0 })
const pendingOnly = ref(false)
const published = computed(() => documents.value.filter(doc => doc.status === 'published'))
const pairReady = computed(() => termsId.value && privacyId.value)
const formatDate = value => value ? new Date(value).toLocaleString('pt-BR') : '—'
const kindLabel = kind => kind === 'terms' ? 'Termos de Uso' : 'Política de Privacidade'
const statusLabel = status => ({ draft: 'Rascunho', published: 'Publicado', archived: 'Arquivado / substituído',
  pending: 'Pendente', queued: 'Enfileirado', sending: 'Em envio', sent: 'Enviado ao SMTP', failed: 'Falha',
  confirmed: 'Concordância registrada', ineligible: 'Sem e-mail elegível', uncertain: 'Envio incerto — conferir provedor' })[status] || status
const auditLabel = action => ({ document_drafted: 'Rascunho cadastrado', document_published: 'Documento publicado',
  document_archived: 'Documento arquivado', settings_updated: 'Configurações alteradas',
  campaign_authorized: 'Disparo autorizado', communication_retry: 'Reenvio solicitado', test_email_requested: 'Teste solicitado' })[action] || action
const indicators = computed(() => [
  ['Participantes anteriores', dashboard.value.total || 0, 'bi bi-people-fill', 'cyan'],
  ['Elegíveis com e-mail', dashboard.value.eligible || 0, 'bi bi-person-check-fill', 'blue'],
  ['Comunicações pendentes', dashboard.value.pending || 0, 'bi bi-envelope-exclamation-fill', 'warning'],
  ['Na fila', dashboard.value.queued || 0, 'bi bi-hourglass-split', 'blue'],
  ['E-mails enviados', dashboard.value.sent || 0, 'bi bi-send-check-fill', 'emerald'],
  ['Falhas', dashboard.value.failed || 0, 'bi bi-x-circle-fill', 'danger'],
  ['Envios para reconciliação', dashboard.value.uncertain || 0, 'bi bi-arrow-repeat', 'warning'],
  ['Confirmações da versão atual', dashboard.value.confirmed || 0, 'bi bi-patch-check-fill', 'emerald'],
  ['Sem confirmação atual', dashboard.value.without_confirmation || 0, 'bi bi-person-dash-fill', 'warning'],
  ['Percentual confirmado', `${dashboard.value.percentage || 0}%`, 'bi bi-percent', 'cyan']
])

async function api(path, options = {}) {
  const headers = { 'X-Legal-Action': '1', ...(options.headers || {}) }
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const res = await fetch(`/api/admin/legal/${path}`, { ...options, headers, credentials: 'same-origin', cache: 'no-store' })
  const data = await res.json()
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Não foi possível concluir a operação.')
  return data
}
async function loadRecords(nextPage = 1) {
  page.value = nextPage
  records.value = await api(`${tab.value}?page=${page.value}${tab.value === 'communications' && pendingOnly.value ? '&status=pending' : ''}`)
}
async function refresh() {
  const [docs, controls, metrics] = await Promise.all([api('documents'), api('settings'), api('dashboard')])
  documents.value = docs
  settings.value = controls
  dashboard.value = metrics
  if (!docs.some(doc => doc.id === Number(termsId.value) && doc.status === 'published')) termsId.value = docs.find(doc => doc.kind === 'terms' && doc.status === 'published')?.id || ''
  if (!docs.some(doc => doc.id === Number(privacyId.value) && doc.status === 'published')) privacyId.value = docs.find(doc => doc.kind === 'privacy' && doc.status === 'published')?.id || ''
  await loadRecords(page.value)
}
async function run(action, success = '') {
  if (busy.value) return
  busy.value = true
  error.value = ''
  message.value = ''
  try { await action(); message.value = success }
  catch (err) { error.value = err.message }
  finally { busy.value = false }
}
async function saveDraft() {
  await run(async () => {
    if (!file.value) throw new Error('Escolha um arquivo PDF ou DOCX de até 5 MB.')
    const data = new FormData()
    for (const [key, value] of Object.entries(upload.value)) data.append(key, value)
    data.append('file', file.value)
    await api('documents', { method: 'POST', body: data })
    upload.value = { kind: upload.value.kind, title: '', version: '', notes: '' }
    file.value = null
    if (uploadInput.value) uploadInput.value.value = ''
    await refresh()
  }, 'Rascunho privado cadastrado. Revise o arquivo antes de publicar.')
}
async function documentAction(doc, action) {
  if (!(await confirmModal({ title: action === 'publish' ? 'Publicar documento aprovado' : 'Arquivar documento',
    message: action === 'publish' ? `Publicar ${doc.title}, versão ${doc.version}? Esta versão se tornará imutável. Publicar não ativa o aceite nem envia comunicados.` : `Arquivar ${doc.title}, versão ${doc.version}?`,
    confirmText: action === 'publish' ? 'Publicar versão aprovada' : 'Arquivar' }))) return
  await run(async () => { await api(`documents/${doc.id}/${action}`, { method: 'POST' }); await refresh() }, 'Documento atualizado.')
}
async function saveSettings() {
  if (!(await confirmModal({ title: 'Salvar controles legais', message: 'Os controles selecionados afetam os novos resgates e a disponibilidade de comunicações. Confirma as configurações?', confirmText: 'Salvar configurações' }))) return
  await run(async () => { await api('settings', { method: 'PUT', body: JSON.stringify(settings.value) }); await refresh() }, 'Configurações salvas.')
}
function pair() { return { terms_id: Number(termsId.value), privacy_id: Number(privacyId.value) } }
async function previewEmail() {
  await run(async () => { emailPreview.value = await api('email-preview', { method: 'POST', body: JSON.stringify(pair()) }) })
}
async function testEmail() {
  if (!(await confirmModal({ title: 'Enviar e-mail de teste', message: 'Enviar uma mensagem para o e-mail cadastrado na sua conta de Super Administrador?', confirmText: 'Enviar teste' }))) return
  await run(async () => { const result = await api('email-test', { method: 'POST', body: JSON.stringify(pair()) }); message.value = result.message })
}
async function sendCampaign() {
  if (!(await confirmModal({ title: 'Autorizar disparo aos participantes anteriores',
    message: `O público será congelado com os participantes elegíveis. O envio ocorrerá em lotes pela fila. A ausência de confirmação não afeta ingressos. Confirma o disparo?`, confirmText: 'Autorizar disparo' }))) return
  await run(async () => {
    await api('campaigns', { method: 'POST', body: JSON.stringify({ ...pair(), confirmation: confirmation.value }) })
    confirmation.value = ''
    await refresh()
  }, 'Campanha autorizada. Acompanhe o processamento na tabela de comunicações.')
}
async function retry(row) {
  if (!(await confirmModal({ title: 'Solicitar reenvio', message: 'Gerar um novo link e reenviar para o e-mail cadastrado? O link anterior será invalidado.', confirmText: 'Reenviar' }))) return
  await run(async () => { await api(`communications/${row.id}/retry`, { method: 'POST' }); await refresh() }, 'Reenvio solicitado.')
}
async function changeTab(value) {
  tab.value = value
  await run(() => loadRecords())
}
onMounted(async () => { await run(refresh); loading.value = false })
</script>

<template>
  <div class="app-container workspace-stack">
    <header class="workspace-toolbar">
      <div><h1 class="page-title font-quattrocento">Documentos Legais</h1><p class="text-muted">Gestão exclusiva do Super Administrador.</p></div>
      <button class="btn-secondary" :disabled="busy" @click="run(refresh)"><i class="bi bi-arrow-clockwise"></i> Atualizar</button>
    </header>
    <p v-if="error" class="availability-control" role="alert">{{ error }}</p>
    <p v-if="message" class="availability-control" role="status">{{ message }}</p>
    <p v-if="loading" role="status">Carregando central…</p>
    <template v-else>
      <div class="metric-grid"><KpiCard v-for="[title, value, icon, variant] in indicators" :key="title" :title="title" :value="value" :icon="icon" :variant="variant" /></div>
      <section class="availability-control">
        <h2>Versões atualmente publicadas</h2>
        <p v-if="!published.length">Nenhum documento publicado. Os arquivos em rascunho são privados.</p>
        <p v-for="doc in published" :key="doc.id">{{ kindLabel(doc.kind) }}: <strong>{{ doc.version }}</strong> · {{ formatDate(doc.published_at) }}</p>
        <p class="availability-control__description">A concordância com os Termos é contratual. A Política de Privacidade é apresentada separadamente e não representa consentimento genérico para o tratamento de dados.</p>
      </section>

      <form class="filter-card workspace-stack" @submit.prevent="saveDraft">
        <h2>Cadastrar nova versão como rascunho</h2>
        <div class="filter-grid">
          <label class="form-group">Tipo<select v-model="upload.kind" class="form-select" aria-label="Tipo"><option value="terms">Termos de Uso</option><option value="privacy">Política de Privacidade</option></select></label>
          <label class="form-group">Título<input v-model="upload.title" class="form-control" maxlength="200" required /></label>
          <label class="form-group">Versão<input v-model="upload.version" class="form-control" maxlength="50" required placeholder="Ex.: 1.0" /></label>
          <label class="form-group">Arquivo PDF ou DOCX (até 5 MB)<input ref="uploadInput" type="file" class="form-control" accept=".pdf,.docx" required @change="file = $event.target.files[0]" /></label>
        </div>
        <label class="form-group">Observações administrativas<textarea v-model="upload.notes" class="form-control form-control--multiline" maxlength="4000" rows="3"></textarea></label>
        <button class="btn-primary" :disabled="busy">Salvar rascunho privado</button>
      </form>

      <section class="table-card">
        <div class="table-header-box"><h2 class="table-title">Documentos e versões anteriores</h2></div>
        <div class="table-scroll"><table class="custom-table custom-table--versioned">
          <thead><tr><th>Documento</th><th>Versão</th><th>Estado</th><th>Publicação / responsável</th><th class="table-heading--actions">Ações</th></tr></thead>
          <tbody>
            <tr v-for="doc in documents" :key="doc.id">
              <td><div class="table-user-cell"><strong class="table-user-name">{{ doc.title }}</strong><span class="table-user-sub">{{ kindLabel(doc.kind) }}</span><small class="table-user-sub">{{ doc.notes }}</small></div></td>
              <td><span class="table-code-pill">{{ doc.version }}</span></td><td><span class="table-tag table-tag--status" :class="{ 'table-tag--success': doc.status === 'published', 'table-tag--warning': doc.status === 'draft' }">{{ statusLabel(doc.status) }}</span></td>
              <td><div class="table-status-cell"><span>{{ formatDate(doc.published_at) }}<br /><small v-if="doc.published_by" class="table-user-sub">Administrador #{{ doc.published_by }}</small></span></div></td>
              <td><div class="table-actions-cell">
                <button class="btn-action-icon btn-action-icon--cyan" title="Visualizar documento" @click="selected = doc"><i class="bi bi-eye"></i></button>
                <a :href="doc.file_url + '?download=true'" class="btn-action-icon btn-action-icon--blue" title="Baixar documento"><i class="bi bi-download"></i></a>
                <button v-if="doc.status === 'draft'" class="btn-action-icon btn-action-icon--emerald" :disabled="busy" title="Publicar versão aprovada" @click="documentAction(doc, 'publish')"><i class="bi bi-check2-circle"></i></button>
                <button v-if="doc.status !== 'archived'" class="btn-action-icon btn-action-icon--amber" :disabled="busy" title="Arquivar documento" @click="documentAction(doc, 'archive')"><i class="bi bi-archive"></i></button>
              </div></td>
            </tr>
            <tr v-if="!documents.length"><td colspan="5">Nenhum documento cadastrado.</td></tr>
          </tbody>
        </table></div>
      </section>

      <form class="filter-card workspace-stack" @submit.prevent="saveSettings">
        <h2>Controles independentes</h2>
        <label class="choice-row"><input v-model="settings.require_on_redemption" type="checkbox" /><span>Exigir aceite nos novos resgates</span></label>
        <label class="choice-row"><input v-model="settings.voluntary_enabled" type="checkbox" /><span>Disponibilizar confirmação voluntária para participantes anteriores</span></label>
        <label class="choice-row"><input v-model="settings.communications_enabled" type="checkbox" /><span>Habilitar envio de comunicados legais</span></label>
        <label class="form-group">Validade dos novos links (dias)<input v-model.number="settings.token_days" class="form-control" type="number" min="1" max="180" required /></label>
        <p class="text-muted">Publicar documentos não ativa estes controles. Habilitar comunicados permite processar campanhas já autorizadas; o primeiro disparo exige a confirmação abaixo.</p>
        <button class="btn-primary" :disabled="busy">Salvar controles</button>
      </form>

      <section class="filter-card workspace-stack">
        <h2>Comunicar publicação</h2>
        <p>Elegíveis com e-mail: {{ dashboard.eligible || 0 }}. O disparo ignora quem já confirmou os Termos selecionados. O teste usa exclusivamente o e-mail da sua conta.</p>
        <div class="filter-grid">
          <label class="form-group">Termos publicados<select v-model="termsId" class="form-select" aria-label="Termos publicados"><option value="">Selecione</option><option v-for="doc in published.filter(doc => doc.kind === 'terms')" :key="doc.id" :value="doc.id">{{ doc.title }} · {{ doc.version }}</option></select></label>
          <label class="form-group">Política publicada<select v-model="privacyId" class="form-select" aria-label="Política publicada"><option value="">Selecione</option><option v-for="doc in published.filter(doc => doc.kind === 'privacy')" :key="doc.id" :value="doc.id">{{ doc.title }} · {{ doc.version }}</option></select></label>
        </div>
        <div class="document-links"><button class="btn-secondary" :disabled="busy || !pairReady" @click="previewEmail">Pré-visualizar e-mail</button><button class="btn-secondary" :disabled="busy || !pairReady" @click="testEmail">Enviar teste para minha conta</button></div>
        <label class="form-group">Para autorizar o disparo, digite AUTORIZAR ENVIO<input v-model="confirmation" class="form-control" autocomplete="off" /></label>
        <button class="btn-primary" :disabled="busy || !pairReady || confirmation !== 'AUTORIZAR ENVIO'" @click="sendCampaign">Autorizar campanha</button>
        <p class="text-muted">Enviado significa aceito pelo servidor SMTP. Não indica leitura, entrega confirmada ou concordância. Repetir a autorização do mesmo par de versões não duplica a campanha.</p>
      </section>

      <section class="table-card">
        <div class="table-header-box workspace-toolbar">
          <div class="document-links"><button v-for="item in [['communications', 'Comunicações'], ['acceptances', 'Histórico de aceites'], ['history', 'Auditoria']]" :key="item[0]" class="btn-secondary" :aria-pressed="tab === item[0]" :disabled="busy" @click="changeTab(item[0])">{{ item[1] }}</button></div>
          <label v-if="tab === 'communications'" class="choice-row"><input v-model="pendingOnly" type="checkbox" @change="run(() => loadRecords())" /><span>Sem confirmação</span></label>
        </div>
        <div class="table-scroll"><table class="custom-table">
          <thead v-if="tab === 'communications'"><tr><th>Participante</th><th>Documentos</th><th>Comunicação</th><th>Concordância</th><th class="table-heading--actions">Ações</th></tr></thead>
          <thead v-else-if="tab === 'acceptances'"><tr><th>Participante</th><th>Termos / política</th><th>Data UTC / método</th><th>Conteúdo aceito</th></tr></thead>
          <thead v-else><tr><th>Data</th><th>Responsável</th><th>Ação</th><th>Detalhes</th></tr></thead>
          <tbody>
            <tr v-for="row in records.items" :key="row.id">
              <template v-if="tab === 'communications'">
                <td><div class="table-user-cell"><strong>{{ row.nome }}</strong><small>{{ row.email }}</small></div></td>
                <td>Termos #{{ row.terms_id }} / Política #{{ row.privacy_id }}</td>
                <td><div class="table-status-cell"><span>{{ statusLabel(row.status) }}<br /><small>{{ row.attempts || 0 }} tentativas · {{ formatDate(row.sent_at) }}</small><p v-if="row.error">{{ row.error }}</p></span></div></td>
                <td>{{ row.confirmed_at ? formatDate(row.confirmed_at) : 'Pendente — ingresso preservado' }}</td>
                <td><div class="table-actions-cell"><button v-if="!row.confirmed_at && row.status !== 'uncertain'" class="btn-action-icon btn-action-icon--amber" title="Reenviar falha ou link expirado" :disabled="busy" @click="retry(row)"><i class="bi bi-arrow-repeat"></i></button></div></td>
              </template>
              <template v-else-if="tab === 'acceptances'">
                <td><div class="table-user-cell">{{ row.name }}<small>#{{ row.user_id }}</small></div></td>
                <td>Termos #{{ row.terms_id }} / Política #{{ row.privacy_id }}</td>
                <td>{{ row.accepted_at }}<br />{{ row.method }} · {{ row.operation }}</td>
                <td class="document-fingerprint">Termos: {{ row.terms_hash }}<br />Política disponibilizada: {{ row.privacy_hash }}</td>
              </template>
              <template v-else><td>{{ formatDate(row.created_at) }}</td><td>#{{ row.actor_id }}</td><td>{{ auditLabel(row.action) }}</td><td class="document-fingerprint">{{ row.details }}</td></template>
            </tr>
            <tr v-if="!records.items.length"><td colspan="5">Nenhum registro.</td></tr>
          </tbody>
        </table></div>
        <RecordPager :page="page" :total="records.total" @change="value => run(() => loadRecords(value))" />
      </section>
    </template>
    <Modal :show="!!selected" title="Revisão do documento" icon="bi bi-file-earmark-text" max-width="1120px" @close="selected = null">
      <div v-if="selected" class="modal-content-stack">
        <div class="modal-section modal-section--flush"><DocumentPreview :document="selected" embedded /></div>
      </div>
      <template #footer>
        <div class="modal-footer-grid modal-footer-grid--end"><button class="btn-secondary" @click="selected = null">Fechar revisão</button></div>
      </template>
    </Modal>
    <Modal :show="!!emailPreview" title="Pré-visualização do comunicado" max-width="900px" @close="emailPreview = null">
      <div v-if="emailPreview" class="modal-content-stack">
        <div class="modal-section modal-section--flush"><h2 class="modal-section-heading">{{ emailPreview.subject }}</h2><iframe :srcdoc="emailPreview.html" sandbox class="document-preview" title="E-mail de exemplo" referrerpolicy="no-referrer"></iframe></div>
      </div>
      <template #footer>
        <div class="modal-footer-grid modal-footer-grid--end"><button class="btn-secondary" @click="emailPreview = null">Fechar pré-visualização</button></div>
      </template>
    </Modal>
  </div>
</template>
