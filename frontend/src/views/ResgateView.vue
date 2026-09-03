<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useServerTime } from '../composables/useServerTime'
import WebcamCapture from '../components/WebcamCapture.vue'
import Modal from '../components/Modal.vue'

const route = useRoute()
const router = useRouter()
const { calibrarRelogioComServidor, getSynchronizedServerTime } = useServerTime()

const loteId = route.params.loteId
const loading = ref(true)
const lote = ref(null)
const secretarias = ref([])
const tokenReserva = ref('')
const reservaExpiraEmMs = ref(null)
const tempoRestanteSegundos = ref(300)

// Form fields
// Estado de Seleção Amigável de Data de Nascimento (Ano -> Mês -> Dia)
const nascAno = ref('')
const nascMes = ref('')
const nascDia = ref('')

const anoAtual = new Date().getFullYear() // 2026
const anoMaximo = anoAtual - 18 // 2008 (mínimo 18 anos)
const anoMinimo = 1930

const anosDisponiveis = computed(() => {
  const lista = []
  for (let a = anoMaximo; a >= anoMinimo; a--) {
    lista.push(a)
  }
  return lista
})

const meses = [
  { valor: '01', nome: 'Janeiro' },
  { valor: '02', nome: 'Fevereiro' },
  { valor: '03', nome: 'Março' },
  { valor: '04', nome: 'Abril' },
  { valor: '05', nome: 'Maio' },
  { valor: '06', nome: 'Junho' },
  { valor: '07', nome: 'Julho' },
  { valor: '08', nome: 'Agosto' },
  { valor: '09', nome: 'Setembro' },
  { valor: '10', nome: 'Outubro' },
  { valor: '11', nome: 'Novembro' },
  { valor: '12', nome: 'Dezembro' }
]

const diasDisponiveis = computed(() => {
  let totalDias = 31
  const m = parseInt(nascMes.value)
  const a = parseInt(nascAno.value)

  if ([4, 6, 9, 11].includes(m)) {
    totalDias = 30
  } else if (m === 2) {
    if (a) {
      const isLeap = (a % 4 === 0 && a % 100 !== 0) || (a % 400 === 0)
      totalDias = isLeap ? 29 : 28
    } else {
      totalDias = 29
    }
  }

  const lista = []
  for (let d = 1; d <= totalDias; d++) {
    lista.push(d < 10 ? '0' + d : String(d))
  }
  return lista
})

function sincronizarDataNascimento() {
  if (nascAno.value && nascMes.value && nascDia.value) {
    form.value.data_nascimento = `${nascAno.value}-${nascMes.value}-${nascDia.value}`
  } else {
    form.value.data_nascimento = ''
  }
}

watch([nascAno, nascMes], () => {
  if (nascDia.value && diasDisponiveis.value.length > 0) {
    const maxDia = diasDisponiveis.value[diasDisponiveis.value.length - 1]
    if (parseInt(nascDia.value) > parseInt(maxDia)) {
      nascDia.value = maxDia
    }
  }
  sincronizarDataNascimento()
})

watch(nascDia, () => {
  sincronizarDataNascimento()
})

watch(() => form.value.data_nascimento, (val) => {
  if (val && val.includes('-')) {
    const parts = val.split('-')
    if (parts.length === 3) {
      nascAno.value = parts[0]
      nascMes.value = parts[1]
      nascDia.value = parts[2]
    }
  }
})

const form = ref({
  cpf: '',
  data_nascimento: '',
  nome: '',
  secretaria_id: '',
  setor: '',
  vinculo: 'Efetivo / Concursado',
  telefone: '',
  email: '',
  foto_base64: ''
})

// ============================================================================
// PERSISTÊNCIA AUTOMÁTICA DE RASCUNHO (Dentro dos 5 minutos de reserva)
// ============================================================================
const DRAFT_STORAGE_PREFIX = 'festa_resgate_draft_'

function salvarRascunhoFormulario() {
  try {
    const temDados = form.value.cpf || form.value.nome || form.value.telefone || form.value.email || nascAno.value || form.value.foto_base64
    if (!temDados) return

    const rascunho = {
      cpf: form.value.cpf,
      data_nascimento: form.value.data_nascimento,
      nascAno: nascAno.value,
      nascMes: nascMes.value,
      nascDia: nascDia.value,
      nome: form.value.nome,
      secretaria_id: form.value.secretaria_id,
      setor: form.value.setor,
      vinculo: form.value.vinculo,
      telefone: form.value.telefone,
      email: form.value.email,
      foto_base64: form.value.foto_base64,
      salvoEm: Date.now()
    }
    localStorage.setItem(DRAFT_STORAGE_PREFIX + loteId, JSON.stringify(rascunho))
  } catch (e) {
    console.warn('Erro ao salvar rascunho local:', e)
  }
}

function restaurarRascunhoFormulario() {
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_PREFIX + loteId)
    if (!raw) return false

    const draft = JSON.parse(raw)
    // Se o rascunho foi salvo há mais de 10 minutos, descarta
    if (Date.now() - (draft.salvoEm || 0) > 10 * 60 * 1000) {
      limparRascunhoFormulario()
      return false
    }

    if (draft.cpf) form.value.cpf = draft.cpf
    if (draft.nome) form.value.nome = draft.nome
    if (draft.secretaria_id) form.value.secretaria_id = draft.secretaria_id
    if (draft.setor) form.value.setor = draft.setor
    if (draft.vinculo) form.value.vinculo = draft.vinculo
    if (draft.telefone) form.value.telefone = draft.telefone
    if (draft.email) form.value.email = draft.email
    if (draft.foto_base64) form.value.foto_base64 = draft.foto_base64

    if (draft.nascAno) nascAno.value = draft.nascAno
    if (draft.nascMes) nascMes.value = draft.nascMes
    if (draft.nascDia) nascDia.value = draft.nascDia
    if (draft.data_nascimento) form.value.data_nascimento = draft.data_nascimento

    if (draft.cpf && draft.cpf.replace(/\D/g, '').length === 11) {
      validarCpfServidor(draft.cpf)
    }
    return true
  } catch (e) {
    console.warn('Erro ao restaurar rascunho:', e)
    return false
  }
}

function limparRascunhoFormulario() {
  try {
    localStorage.removeItem(DRAFT_STORAGE_PREFIX + loteId)
  } catch (e) {
    // Ignore
  }
}

watch(
  () => [
    form.value.cpf,
    form.value.nome,
    form.value.secretaria_id,
    form.value.setor,
    form.value.vinculo,
    form.value.telefone,
    form.value.email,
    form.value.foto_base64,
    nascAno.value,
    nascMes.value,
    nascDia.value
  ],
  () => {
    salvarRascunhoFormulario()
  }
)

const submitting = ref(false)
const errorMessage = ref('')
const showModalTempo = ref(false)
const showModalExpirado = ref(false)
const modalFeedback = ref({
  show: false,
  titulo: 'Resgate Interrompido',
  subtitulo: 'Este lote foi temporariamente pausado ou encerrado pela administração do evento.',
  icone: 'bi-pause-circle-fill',
  corIcone: 'text-warning',
  btnTexto: 'Voltar à Página Inicial',
  btnIcone: 'bi-house-door'
})
const showModalDesistir = ref(false)
const showModalDesistidaOutroNavegador = ref(false)
const desistindo = ref(false)

// Estados de validação de CPF em tempo real
const validandoCpf = ref(false)
const cpfStatus = ref(null) // { valido: boolean, msg: string }

// Estado de validação de idade
const idadeInvalida = computed(() => {
  if (!form.value.data_nascimento) return false
  const [ano, mes, dia] = form.value.data_nascimento.split('-').map(Number)
  if (!ano || !mes || !dia) return false
  const dataNasc = new Date(ano, mes - 1, dia)
  const hoje = new Date()
  let idade = hoje.getFullYear() - dataNasc.getFullYear()
  const m = hoje.getMonth() - dataNasc.getMonth()
  if (m < 0 || (m === 0 && hoje.getDate() < dataNasc.getDate())) {
    idade--
  }
  return idade < 18
})

let timerInterval = null
let statusPollInterval = null
let debounceCpfTimer = null

// Geração de Hardware Device Fingerprint
function getDeviceFingerprint() {
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    let renderer = ''
    if (gl) {
      const dbg = gl.getExtension('WEBGL_debug_renderer_info')
      if (dbg) {
        renderer = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || ''
      }
    }
    const raw = [
      screen.width,
      screen.height,
      screen.colorDepth,
      navigator.hardwareConcurrency || 4,
      navigator.deviceMemory || 4,
      Intl.DateTimeFormat().resolvedOptions().timeZone || '',
      renderer
    ].join('###')

    let hash = 0
    for (let i = 0; i < raw.length; i++) {
      hash = ((hash << 5) - hash) + raw.charCodeAt(i)
      hash |= 0
    }
    return 'hw_' + Math.abs(hash).toString(36)
  } catch {
    return 'hw_fallback_' + screen.width + 'x' + screen.height
  }
}

// Validação matemática oficial do CPF (módulo 11 com 2 dígitos verificadores)
function validarCpfMatematico(cpf) {
  const clean = (cpf || '').replace(/\D/g, '')
  if (clean.length !== 11) return false
  if (/^(\d)\1{10}$/.test(clean)) return false

  let soma = 0
  for (let i = 0; i < 9; i++) {
    soma += parseInt(clean.charAt(i), 10) * (10 - i)
  }
  let resto = (soma * 10) % 11
  let d1 = resto === 10 ? 0 : resto
  if (d1 !== parseInt(clean.charAt(9), 10)) return false

  soma = 0
  for (let i = 0; i < 10; i++) {
    soma += parseInt(clean.charAt(i), 10) * (11 - i)
  }
  resto = (soma * 10) % 11
  let d2 = resto === 10 ? 0 : resto
  if (d2 !== parseInt(clean.charAt(10), 10)) return false

  return true
}

// Formatação de CPF
function formatCPF(val) {
  const digits = val.replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 3) return digits
  if (digits.length <= 6) return `${digits.slice(0, 3)}.${digits.slice(3)}`
  if (digits.length <= 9) return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6)}`
  return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`
}

// Validação de CPF em segundo plano ao atingir 11 dígitos
async function validarCpfNoServidor(digits) {
  try {
    validandoCpf.value = true
    cpfStatus.value = null
    const res = await fetch(`/api/resgate/validar-cpf?cpf=${digits}`)
    const data = await res.json()

    if (!data.valido) {
      cpfStatus.value = {
        valido: false,
        msg: data.mensagem
      }
      errorMessage.value = data.mensagem
    } else {
      cpfStatus.value = {
        valido: true,
        msg: 'CPF apto para resgate!'
      }
      if (errorMessage.value === 'Esse CPF já possui um ingresso.' || errorMessage.value === 'Não é possível resgatar para esse CPF.' || errorMessage.value === 'CPF inválido. Verifique os números digitados.') {
        errorMessage.value = ''
      }
      if (data.usuario_existente) {
        if (!form.value.nome && data.nome) form.value.nome = data.nome
        if (!form.value.data_nascimento && data.data_nascimento) form.value.data_nascimento = data.data_nascimento
        if (!form.value.telefone && data.telefone) form.value.telefone = formatPhone(data.telefone)
        if (!form.value.email && data.email) form.value.email = data.email
        if (!form.value.secretaria_id && data.secretaria_id) form.value.secretaria_id = data.secretaria_id
        if (!form.value.setor && data.setor) form.value.setor = data.setor
        if (!form.value.vinculo && data.vinculo) form.value.vinculo = data.vinculo
      }
    }
  } catch (err) {
    console.error('Erro na validação do CPF:', err)
  } finally {
    validandoCpf.value = false
  }
}

function onCpfInput(e) {
  form.value.cpf = formatCPF(e.target.value)
  const digits = form.value.cpf.replace(/\D/g, '')

  if (debounceCpfTimer) clearTimeout(debounceCpfTimer)

  if (digits.length === 11) {
    // 1. Checagem matemática imediata no cliente
    if (!validarCpfMatematico(digits)) {
      cpfStatus.value = {
        valido: false,
        msg: 'CPF inválido. Verifique os números digitados.'
      }
      errorMessage.value = 'CPF inválido. Verifique os números digitados.'
      return
    }

    // 2. Consulta em segundo plano no servidor para equipe e unicidade
    debounceCpfTimer = setTimeout(() => {
      validarCpfNoServidor(digits)
    }, 150)
  } else {
    cpfStatus.value = null
  }
}

function formatPhone(val) {
  const digits = val.replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 2) return digits ? `(${digits}` : ''
  if (digits.length <= 7) return `(${digits.slice(0, 2)}) ${digits.slice(2)}`
  return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`
}

function onPhoneInput(e) {
  form.value.telefone = formatPhone(e.target.value)
}

function updateCountdown() {
  if (!reservaExpiraEmMs.value) return
  const agora = getSynchronizedServerTime()
  const dist = reservaExpiraEmMs.value - agora

  if (dist <= 0) {
    tempoRestanteSegundos.value = 0
    limparRascunhoFormulario()
    showModalExpirado.value = true
    if (timerInterval) clearInterval(timerInterval)
    return
  }

  tempoRestanteSegundos.value = Math.max(0, Math.floor(dist / 1000))
}

// Polling do status da reserva (sincronização cross-browser)
async function verificarStatusReservaServidor() {
  if (!tokenReserva.value || submitting.value) return
  try {
    const res = await fetch(`/api/resgate/status-reserva?token_reserva=${tokenReserva.value}`)
    if (!res.ok) return
    const data = await res.json()

    if (data.status === 'desistida' || (!data.ativa && data.motivo === 'desistida')) {
      if (timerInterval) clearInterval(timerInterval)
      if (statusPollInterval) clearInterval(statusPollInterval)
      showModalDesistir.value = false
      showModalDesistidaOutroNavegador.value = true
      return
    }

    if (data.status === 'expirada' && data.motivo === 'tempo_esgotado') {
      if (timerInterval) clearInterval(timerInterval)
      if (statusPollInterval) clearInterval(statusPollInterval)
      limparRascunhoFormulario()
    showModalExpirado.value = true
      return
    }

    if (data.expira_em_ms) {
      reservaExpiraEmMs.value = data.expira_em_ms
    }
  } catch (err) {
    console.warn('Polling status reserva erro:', err)
  }
}

const displayTimer = computed(() => {
  const m = Math.floor(tempoRestanteSegundos.value / 60)
  const s = tempoRestanteSegundos.value % 60
  return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`
})

const displayTimerInline = computed(() => {
  const m = Math.floor(tempoRestanteSegundos.value / 60)
  const s = tempoRestanteSegundos.value % 60
  return `${m < 10 ? '0' : ''}${m}m ${s < 10 ? '0' : ''}${s}s`
})

const isTimerCritical = computed(() => tempoRestanteSegundos.value <= 60)

async function carregarDadosResgate() {
  try {
    loading.value = true
    await calibrarRelogioComServidor()

    const deviceFp = getDeviceFingerprint()

    const res = await fetch(`/api/resgate/${loteId}?device_fingerprint=${deviceFp}`, {
      headers: {
        'Accept': 'application/json',
        'X-Device-Fingerprint': deviceFp
      }
    })

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}))
      const codigo = errData.codigo || errData.code || ''
      const msgTexto = (typeof errData.detail === 'object' ? errData.detail?.mensagem : errData.detail) || errData.mensagem || 'Não foi possível reservar uma vaga no lote.'
      errorMessage.value = msgTexto

      if (codigo === 'esgotado' || msgTexto.includes('já foram resgatados') || msgTexto.includes('Esgotado')) {
        modalFeedback.value = {
          show: true,
          titulo: 'Ingressos Esgotados!',
          subtitulo: 'Todos os ingressos deste lote já foram resgatados por outros participantes. Fique atento aos próximos lotes!',
          icone: 'bi-ticket-detailed-fill',
          corIcone: 'text-danger',
          btnTexto: 'Voltar à Página Inicial',
          btnIcone: 'bi-house-door'
        }
      } else if (codigo === 'em_preenchimento' || msgTexto.includes('preenchimento') || msgTexto.includes('outros servidores')) {
        modalFeedback.value = {
          show: true,
          titulo: 'Vagas em Preenchimento!',
          subtitulo: 'No momento, todas as vagas restantes estão sendo preenchidas por outros servidores no tempo limite de 5 minutos. Se alguém desistir ou o tempo expirar, a vaga voltará automaticamente para a tela inicial!',
          icone: 'bi-hourglass-split',
          corIcone: 'text-warning',
          btnTexto: 'Acompanhar na Página Inicial',
          btnIcone: 'bi-arrow-repeat'
        }
      } else if (msgTexto.includes('pausado') || msgTexto.includes('inativo')) {
        modalFeedback.value = {
          show: true,
          titulo: 'Lote Pausado',
          subtitulo: msgTexto,
          icone: 'bi-pause-circle-fill',
          corIcone: 'text-warning',
          btnTexto: 'Voltar à Página Inicial',
          btnIcone: 'bi-house-door'
        }
      } else if (msgTexto.includes('encerrado')) {
        modalFeedback.value = {
          show: true,
          titulo: 'Lote Encerrado',
          subtitulo: msgTexto,
          icone: 'bi-archive-fill',
          corIcone: 'text-secondary',
          btnTexto: 'Voltar à Página Inicial',
          btnIcone: 'bi-house-door'
        }
      } else {
        modalFeedback.value = {
          show: true,
          titulo: 'Aviso de Resgate',
          subtitulo: msgTexto,
          icone: 'bi-exclamation-triangle-fill',
          corIcone: 'text-warning',
          btnTexto: 'Voltar à Página Inicial',
          btnIcone: 'bi-house-door'
        }
      }

      loading.value = false
      return
    }

    const dataRes = await res.json()
    if (dataRes.token_reserva) {
      tokenReserva.value = dataRes.token_reserva
    }
    if (dataRes.reserva_expira_em_ms) {
      reservaExpiraEmMs.value = dataRes.reserva_expira_em_ms
    }
    if (dataRes.tempo_restante_segundos) {
      tempoRestanteSegundos.value = dataRes.tempo_restante_segundos
    }

    const statusRes = await fetch("/api/lote/live-status?lote_id=" + loteId, { cache: 'no-store' })
    if (statusRes.ok) {
      const st = await statusRes.json()
      if (!st.has_lote || st.status_slug === 'esgotado') {
        modalFeedback.value = {
          show: true,
          titulo: 'Ingressos Esgotados!',
          subtitulo: 'Todos os ingressos deste lote já foram resgatados por outros participantes.',
          icone: 'bi-ticket-detailed-fill',
          corIcone: 'text-danger',
          btnTexto: 'Voltar à Página Inicial',
          btnIcone: 'bi-house-door'
        }
        loading.value = false
        return
      }
      if (st.status_slug === 'pausado') {
        modalFeedback.value = {
          show: true,
          titulo: 'Lote Pausado',
          subtitulo: 'Este lote foi temporariamente pausado pela administração do evento.',
          icone: 'bi-pause-circle-fill',
          corIcone: 'text-warning',
          btnTexto: 'Voltar à Página Inicial',
          btnIcone: 'bi-house-door'
        }
        loading.value = false
        return
      }
      if (st.status_slug === 'encerrado') {
        modalFeedback.value = {
          show: true,
          titulo: 'Lote Encerrado',
          subtitulo: 'O período de resgate deste lote já foi encerrado.',
          icone: 'bi-archive-fill',
          corIcone: 'text-secondary',
          btnTexto: 'Voltar à Página Inicial',
          btnIcone: 'bi-house-door'
        }
        loading.value = false
        return
      }
      lote.value = {
        id: st.id,
        nome: st.nome,
        secretaria_nome: st.secretaria_nome
      }
    }

    try {
      const secRes = await fetch('/api/secretarias')
      if (secRes.ok) {
        secretarias.value = await secRes.json()
      }
    } catch {
      // Fallback
    }

    if (secretarias.value.length === 0) {
      secretarias.value = [
        { id: 1, nome: 'Secretaria Municipal de Administração' },
        { id: 2, nome: 'Secretaria Municipal de Educação' },
        { id: 3, nome: 'Secretaria Municipal de Saúde' },
        { id: 4, nome: 'Secretaria Municipal de Obras e Serviços Públicos' },
        { id: 5, nome: 'Secretaria Municipal de Finanças e Fazenda' },
        { id: 6, nome: 'Secretaria Municipal de Assistência Social' },
        { id: 7, nome: 'Gabinete do Prefeito' },
        { id: 8, nome: 'Outra Secretaria / Geral' }
      ]
    }

    restaurarRascunhoFormulario()
    updateCountdown()
    timerInterval = setInterval(updateCountdown, 1000)
    statusPollInterval = setInterval(verificarStatusReservaServidor, 1500)
    loading.value = false
  } catch (err) {
    console.error('Erro ao carregar resgate:', err)
    errorMessage.value = 'Erro ao inicializar formulário de resgate.'
    loading.value = false
  }
}

// Desistir da vaga reservada
async function executarDesistencia() {
  limparRascunhoFormulario()
  if (!tokenReserva.value) {
    router.push('/')
    return
  }
  try {
    desistindo.value = true
    const formData = new FormData()
    formData.append('token_reserva', tokenReserva.value)
    await fetch('/api/resgate/desistir', {
      method: 'POST',
      body: formData
    })
    showModalDesistir.value = false
    router.push('/')
  } catch (e) {
    router.push('/')
  } finally {
    desistindo.value = false
  }
}

async function handleSubmit() {
  const digits = form.value.cpf.replace(/\D/g, '')
  if (!validarCpfMatematico(digits)) {
    errorMessage.value = 'CPF inválido. Verifique os números digitados.'
    return
  }

  if (cpfStatus.value && !cpfStatus.value.valido) {
    errorMessage.value = cpfStatus.value.msg
    return
  }

  if (idadeInvalida.value) {
    errorMessage.value = 'O resgate de ingressos é permitido exclusivamente para maiores de 18 anos.'
    return
  }

  if (!form.value.foto_base64) {
    errorMessage.value = 'A selfie ao vivo é obrigatória para emissão do ingresso nominal.'
    return
  }

  if (!tokenReserva.value) {
    errorMessage.value = 'Reserva de vaga expirada ou não encontrada. Por favor, recarregue a página.'
    return
  }

  submitting.value = true
  errorMessage.value = ''

  try {
    const formData = new FormData()
    formData.append('token_reserva', tokenReserva.value)
    formData.append('cpf', form.value.cpf)
    formData.append('nome', form.value.nome)
    formData.append('data_nascimento', form.value.data_nascimento)
    formData.append('setor', form.value.setor)
    formData.append('secretaria_id', form.value.secretaria_id || '1')
    formData.append('vinculo', form.value.vinculo)
    formData.append('telefone', form.value.telefone)
    formData.append('email', form.value.email)
    formData.append('foto_base64', form.value.foto_base64)

    const res = await fetch("/api/resgate/" + loteId, {
      method: 'POST',
      headers: { 'Accept': 'application/json, text/html' },
      body: formData
    })

    if (res.redirected) {
      const targetUrl = new URL(res.url)
      if (targetUrl.pathname.startsWith('/sucesso/')) {
        const id = targetUrl.pathname.split('/').pop()
        router.push('/sucesso/' + id)
        return
      }
      window.location.href = res.url
      return
    }

    if (!res.ok) {
      const text = await res.text()
      try {
        const json = JSON.parse(text)
        errorMessage.value = json.detail || 'Erro ao processar resgate do ingresso.'
        if (json.detail === 'Você desistiu desta vaga por outro navegador.') {
          showModalDesistidaOutroNavegador.value = true
        }
      } catch {
        errorMessage.value = 'Não foi possível concluir o resgate. Verifique seus dados.'
      }
      submitting.value = false
      return
    }

    const data = await res.json()
    if (data.ingresso_id) {
      limparRascunhoFormulario()
      router.push('/sucesso/' + data.ingresso_id)
      return
    }
    if (data.redirect_url) {
      limparRascunhoFormulario()
      router.push(data.redirect_url)
      return
    }
  } catch (e) {
    console.error('Erro no envio:', e)
    errorMessage.value = 'Falha de conexão com o servidor. Tente novamente.'
    submitting.value = false
  }
}

onMounted(() => {
  carregarDadosResgate()
})

onUnmounted(() => {
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
  if (statusPollInterval) {
    clearInterval(statusPollInterval)
    statusPollInterval = null
  }
  if (debounceCpfTimer) {
    clearTimeout(debounceCpfTimer)
    debounceCpfTimer = null
  }
})
</script>

<template>
  <div class="resgate-page">
    <div class="app-container">
      
      <!-- Barra Flutuante Superior do Tempo Reservado (Acompanha a rolagem da tela) -->
      <div class="sticky-timer-bar" :class="{ 'timer-critical': isTimerCritical }">
        <div class="timer-info-left">
          <span class="timer-pill" :class="{ 'critical': isTimerCritical }">
            <i class="bi bi-hourglass-split"></i>
            <span class="font-outfit">{{ displayTimer }}</span>
          </span>
          <span class="timer-text">
            Sua vaga está garantida por <strong class="text-warning">{{ displayTimerInline }}</strong>
          </span>
        </div>

        <div class="timer-actions-right">
          <button type="button" class="btn-timer-help" @click="showModalTempo = true">
            <i class="bi bi-question-circle-fill me-1"></i> <span class="help-label">Ajuda</span>
          </button>
          <button type="button" class="btn-desistir-top" @click="showModalDesistir = true">
            <i class="bi bi-x-circle me-1"></i> <span>Desistir</span>
          </button>
        </div>
      </div>

      <!-- Espaçador para a barra flutuante fixa -->
      <div class="sticky-timer-spacer"></div>

      <div class="form-wrapper">
        <div class="vip-card form-card">
          
          <!-- Cabeçalho do Formulário -->
          <div class="form-header">
            <span v-if="lote" class="vip-badge bg-primary mb-2">
              <i class="bi bi-ticket-perforated-fill me-1"></i> {{ lote.nome }}
            </span>
            <h2 class="form-title font-outfit">Preencha seus Dados</h2>
            <p class="form-subtitle">Complete as informações para emitir seu ingresso nominal e exclusivo.</p>
          </div>

          <!-- Mensagem de Erro Geral -->
          <div v-if="errorMessage" class="alert-box-danger">
            <i class="bi bi-exclamation-octagon-fill me-2 fs-5 flex-shrink-0"></i>
            <span>{{ errorMessage }}</span>
          </div>

          <form @submit.prevent="handleSubmit">

            <!-- SEÇÃO 1: IDENTIFICAÇÃO DO SERVIDOR -->
            <div class="form-section">
              <h3 class="section-title font-outfit">
                <i class="bi bi-person-badge text-primary me-2"></i> 1. Identificação do Servidor
              </h3>

              <div class="form-grid">
                <!-- CPF COM VALIDAÇÃO EM SEGUNDO PLANO -->
                <div class="form-group">
                  <div class="d-flex justify-content-between align-items-center mb-1">
                    <label class="form-label mb-0" for="cpf">CPF <span class="text-danger">*</span></label>
                    <span v-if="validandoCpf" class="text-info small">
                      <span class="spinner-border spinner-border-sm me-1"></span> Verificando...
                    </span>
                  </div>

                  <div class="input-with-icon">
                    <input
                      id="cpf"
                      v-model="form.cpf"
                      type="tel"
                      inputmode="numeric"
                      class="form-control"
                      :class="{ 'is-invalid': cpfStatus && !cpfStatus.valido, 'is-valid': cpfStatus && cpfStatus.valido }"
                      placeholder="000.000.000-00"
                      maxlength="14"
                      required
                      @input="onCpfInput"
                    />
                    <i v-if="cpfStatus && !cpfStatus.valido" class="bi bi-x-circle-fill text-danger validation-icon"></i>
                    <i v-else-if="cpfStatus && cpfStatus.valido" class="bi bi-check-circle-fill text-success validation-icon"></i>
                  </div>

                  <!-- Mensagens de validação do CPF -->
                  <div v-if="cpfStatus && !cpfStatus.valido" class="text-danger small mt-1 fw-bold">
                    <i class="bi bi-exclamation-triangle-fill me-1"></i> {{ cpfStatus.msg }}
                  </div>
                  <div v-else-if="cpfStatus && cpfStatus.valido" class="text-success small mt-1">
                    <i class="bi bi-check-circle me-1"></i> {{ cpfStatus.msg }}
                  </div>
                  <span v-else class="form-text">Digite os 11 dígitos do CPF.</span>
                </div>

                <!-- DATA DE NASCIMENTO AMIGÁVEL (ANO -> MÊS -> DIA) -->
                <div class="form-group">
                  <label class="form-label">
                    Data de Nascimento <span class="text-danger">*</span>
                  </label>

                  <div class="date-select-grid">
                    <!-- 1. ANO PRIMEIRO -->
                    <div class="select-col col-ano">
                      <select
                        id="nasc-ano"
                        v-model="nascAno"
                        class="form-select date-select"
                        required
                        aria-label="Ano de Nascimento"
                      >
                        <option value="" disabled>Ano</option>
                        <option v-for="a in anosDisponiveis" :key="a" :value="String(a)">
                          {{ a }}
                        </option>
                      </select>
                    </div>

                    <!-- 2. MÊS SEGUNDO -->
                    <div class="select-col col-mes">
                      <select
                        id="nasc-mes"
                        v-model="nascMes"
                        class="form-select date-select"
                        :disabled="!nascAno"
                        required
                        aria-label="Mês de Nascimento"
                      >
                        <option value="" disabled>Mês</option>
                        <option v-for="m in meses" :key="m.valor" :value="m.valor">
                          {{ m.valor }} - {{ m.nome }}
                        </option>
                      </select>
                    </div>

                    <!-- 3. DIA TERCEIRO -->
                    <div class="select-col col-dia">
                      <select
                        id="nasc-dia"
                        v-model="nascDia"
                        class="form-select date-select"
                        :disabled="!nascMes"
                        required
                        aria-label="Dia de Nascimento"
                      >
                        <option value="" disabled>Dia</option>
                        <option v-for="d in diasDisponiveis" :key="d" :value="d">
                          {{ d }}
                        </option>
                      </select>
                    </div>
                  </div>

                  <!-- Alerta de validação de idade -->
                  <div v-if="idadeInvalida" class="text-danger small mt-1 fw-bold">
                    <i class="bi bi-shield-x me-1"></i> Resgate permitido apenas para maiores de 18 anos.
                  </div>
                  <div v-else-if="form.data_nascimento" class="text-success small mt-1">
                    <i class="bi bi-check-circle me-1"></i> Data selecionada: {{ nascDia }}/{{ nascMes }}/{{ nascAno }}
                  </div>
                  <span v-else class="form-text">Selecione o Ano, depois o Mês e o Dia.</span>
                </div>

                <!-- NOME COMPLETO -->
                <div class="form-group col-span-2">
                  <label class="form-label" for="nome">Nome Completo <span class="text-danger">*</span></label>
                  <input
                    id="nome"
                    v-model="form.nome"
                    type="text"
                    class="form-control"
                    placeholder="Digite seu nome completo oficial"
                    required
                  />
                </div>
              </div>
            </div>

            <!-- SEÇÃO 2: DADOS FUNCIONAIS -->
            <div class="form-section">
              <h3 class="section-title font-outfit">
                <i class="bi bi-building text-primary me-2"></i> 2. Dados Funcionais
              </h3>

              <div class="form-grid">
                <div class="form-group col-span-2">
                  <label class="form-label" for="secretaria">Secretaria / Órgão <span class="text-danger">*</span></label>
                  <select id="secretaria" v-model="form.secretaria_id" class="form-select" required>
                    <option value="" disabled>Selecione sua secretaria oficial</option>
                    <option v-for="sec in secretarias" :key="sec.id" :value="sec.id">
                      {{ sec.nome }}{{ sec.sigla ? ' (' + sec.sigla + ')' : '' }}
                    </option>
                  </select>
                </div>

                <div class="form-group">
                  <label class="form-label" for="setor">Setor / Local de Trabalho <span class="text-danger">*</span></label>
                  <input
                    id="setor"
                    v-model="form.setor"
                    type="text"
                    class="form-control"
                    placeholder="Ex: Recursos Humanos, Recepção..."
                    required
                  />
                </div>

                <div class="form-group">
                  <label class="form-label" for="vinculo">Vínculo <span class="text-danger">*</span></label>
                  <select id="vinculo" v-model="form.vinculo" class="form-select" required>
                    <option value="Efetivo / Concursado">Efetivo / Concursado</option>
                    <option value="Comissionado">Comissionado</option>
                    <option value="Contrato Temporário">Contrato Temporário</option>
                    <option value="Estagiário">Estagiário</option>
                    <option value="Prestador de Serviço">Prestador de Serviço</option>
                    <option value="Aposentado">Aposentado</option>
                  </select>
                </div>
              </div>
            </div>

            <!-- SEÇÃO 3: CONTATO -->
            <div class="form-section">
              <h3 class="section-title font-outfit">
                <i class="bi bi-envelope text-primary me-2"></i> 3. Contato
              </h3>

              <div class="form-grid">
                <div class="form-group">
                  <label class="form-label" for="telefone">WhatsApp / Telefone <span class="text-danger">*</span></label>
                  <input
                    id="telefone"
                    v-model="form.telefone"
                    type="tel"
                    inputmode="tel"
                    class="form-control"
                    placeholder="(00) 00000-0000"
                    maxlength="15"
                    required
                    @input="onPhoneInput"
                  />
                </div>

                <div class="form-group">
                  <label class="form-label" for="email">E-mail <span class="text-danger">*</span></label>
                  <input
                    id="email"
                    v-model="form.email"
                    type="email"
                    class="form-control"
                    placeholder="seu.email@exemplo.com"
                    required
                  />
                </div>
              </div>
            </div>

            <!-- SEÇÃO 4: SELFIE AO VIVO -->
            <div class="form-section">
              <h3 class="section-title font-outfit">
                <i class="bi bi-camera-fill text-primary me-2"></i> 4. Validação Facial Obrigatória (Selfie ao Vivo)
              </h3>
              <p class="section-desc">
                Para garantir a segurança e a validação na portaria, tire uma foto sua agora mesmo através da câmera do seu aparelho.
              </p>

              <WebcamCapture v-model="form.foto_base64" />
            </div>

            <!-- BOTÕES DE AÇÃO: CONCLUIR OU DESISTIR -->
            <div class="submit-wrapper">
              <button
                type="submit"
                class="btn-vip-mega font-outfit"
                :disabled="submitting || !form.foto_base64 || (cpfStatus && !cpfStatus.valido) || idadeInvalida"
              >
                <span v-if="!submitting">Concluir e Garantir Ingresso</span>
                <span v-else>Processando Ingresso...</span>
                <i v-if="!submitting" class="bi bi-check-circle-fill"></i>
                <i v-else class="bi bi-arrow-repeat spin"></i>
              </button>

              <button
                type="button"
                class="btn-desistir-link"
                @click="showModalDesistir = true"
              >
                <i class="bi bi-x-circle me-1"></i> Desistir da vaga e voltar à página inicial
              </button>
            </div>

          </form>

        </div>
      </div>
    </div>

    <!-- Modal Informativo do Tempo -->
    <Modal
      :show="showModalTempo"
      title="Tempo de Reserva da Vaga"
      icon="bi-hourglass-split"
      icon-color="text-warning"
      @close="showModalTempo = false"
    >
      <div class="modal-info-box">
        <p class="text-light mb-0">
          Ao clicar em "Resgatar Ingresso", o sistema <strong>reserva uma vaga exclusivamente para você por 5 minutos</strong>, garantindo que ninguém pegue seu lugar enquanto você preenche seus dados e tira a selfie.
        </p>
      </div>

      <div class="modal-rules-list">
        <div class="rule-item">
          <i class="bi bi-check-circle-fill text-success"></i>
          <div>
            <strong class="text-white">Se você concluir dentro do tempo:</strong>
            <p>Seu ingresso estará garantido com seu QR Code único.</p>
          </div>
        </div>
        <div class="rule-item">
          <i class="bi bi-arrow-counterclockwise text-warning"></i>
          <div>
            <strong class="text-white">Se o tempo expirar:</strong>
            <p>A vaga será automaticamente liberada para outros servidores que estiverem aguardando.</p>
          </div>
        </div>
      </div>

      <template #footer>
        <button type="button" class="btn-primary w-100" @click="showModalTempo = false">
          Entendido, vou preencher!
        </button>
      </template>
    </Modal>

    <!-- Modal: Confirmar Desistência da Vaga -->
    <Modal
      :show="showModalDesistir"
      title="Desistir da Vaga Reservada?"
      icon="bi-exclamation-triangle"
      icon-color="text-warning"
      :max-width="'460px'"
      @close="showModalDesistir = false"
    >
      <div class="text-center py-2">
        <p class="text-white mb-2">
          Tem certeza de que deseja liberar sua vaga reservada?
        </p>
        <p class="text-muted small">
          Ela voltará imediatamente para o lote e poderá ser resgatada por outro servidor na tela inicial.
        </p>
      </div>
      <template #footer>
        <div class="d-flex gap-2 w-100">
          <button type="button" class="btn-secondary flex-1" @click="showModalDesistir = false">
            Continuar Preenchendo
          </button>
          <button type="button" class="btn-danger flex-1" :disabled="desistindo" @click="executarDesistencia">
            <span v-if="desistindo" class="spinner-border spinner-border-sm me-1"></span>
            <span>{{ desistindo ? 'Liberando...' : 'Sim, Desistir' }}</span>
          </button>
        </div>
      </template>
    </Modal>

    <!-- Modal: Desistência por Outro Navegador -->
    <Modal
      :show="showModalDesistidaOutroNavegador"
      title="Vaga Cancelada"
      icon="bi-x-circle-fill"
      icon-color="text-warning"
      :max-width="'460px'"
      @close="router.push('/')"
    >
      <div class="text-center py-2">
        <i class="bi bi-shield-x text-warning fs-1 mb-2 d-block"></i>
        <h4 class="text-white font-outfit mb-2">
          Você desistiu desta vaga por outro navegador.
        </h4>
        <p class="text-muted small">
          A sua vaga reservada foi liberada no sistema e este formulário não é mais válido.
        </p>
      </div>
      <template #footer>
        <router-link to="/" class="btn-primary w-100 font-outfit">
          <i class="bi bi-house-door me-1"></i> Voltar ao Início
        </router-link>
      </template>
    </Modal>

    <!-- Modal: Tempo Limite Expirado -->
    <Modal
      :show="showModalExpirado"
      title="Tempo Limite Expirado!"
      icon="bi-alarm-fill"
      icon-color="text-danger"
      :max-width="'460px'"
      @close="router.push('/')"
    >
      <div class="text-center py-2">
        <p class="text-muted">
          Infelizmente o tempo de 5 minutos para preenchimento se esgotou e sua vaga foi devolvida para a fila pública.
        </p>
      </div>
      <template #footer>
        <router-link to="/" class="btn-primary w-100">
          <i class="bi bi-arrow-repeat me-1"></i> Tentar Novamente na Página Inicial
        </router-link>
      </template>
    </Modal>

    <!-- Modal Dinâmico de Feedback do Resgate (Esgotado, Em Preenchimento, Pausado, Encerrado) -->
    <Modal
      :show="modalFeedback.show"
      :title="modalFeedback.titulo"
      :icon="modalFeedback.icone"
      :icon-color="modalFeedback.corIcone"
      :max-width="'480px'"
      @close="router.push('/')"
    >
      <div class="text-center py-2">
        <p class="text-muted font-outfit" style="font-size: 0.95rem; line-height: 1.5;">
          {{ modalFeedback.subtitulo }}
        </p>
      </div>
      <template #footer>
        <router-link to="/" class="btn-primary w-100">
          <i :class="['bi', modalFeedback.btnIcone, 'me-1']"></i> {{ modalFeedback.btnTexto }}
        </router-link>
      </template>
    </Modal>

  </div>
</template>

<style scoped>
.resgate-page {
  padding: 24px 0 48px;
}

.sticky-timer-bar {
  position: fixed;
  top: 68px;
  left: 50%;
  transform: translateX(-50%);
  width: calc(100% - 32px);
  max-width: 860px;
  z-index: 990;
  background: rgba(15, 23, 42, 0.96);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(245, 158, 11, 0.45);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6), 0 0 20px rgba(245, 158, 11, 0.2);
  border-radius: 16px;
  padding: 10px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  transition: all 0.3s ease;
}

.sticky-timer-spacer {
  height: 64px;
  margin-bottom: 14px;
}

/* Data de Nascimento: Grid Amigável Ano -> Mês -> Dia */
.date-select-grid {
  display: flex;
  gap: 8px;
}

.col-ano {
  flex: 1.1;
}

.col-mes {
  flex: 1.5;
}

.col-dia {
  flex: 0.9;
}

.date-select {
  padding: 10px 8px;
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  color: #ffffff;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
  transition: all 0.2s ease;
}

.date-select:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  background: rgba(15, 23, 42, 0.6);
}

.date-select:focus {
  border-color: var(--primary-accent);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
  outline: none;
}

.sticky-timer-bar.timer-critical {
  border-color: rgba(239, 68, 68, 0.6);
  box-shadow: 0 10px 30px rgba(0,0,0,0.5), 0 0 25px rgba(239, 68, 68, 0.3);
}

.timer-info-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.timer-pill {
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.45);
  color: #fbbf24;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 0.95rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.timer-pill.critical {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.5);
  color: #f87171;
}

.timer-text {
  color: var(--text-main);
  font-size: 0.85rem;
  font-weight: 600;
}

.timer-actions-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.btn-timer-help {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #e2e8f0;
  font-size: 0.78rem;
  font-weight: 600;
  border-radius: 999px;
  padding: 6px 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-timer-help:hover {
  background: rgba(255, 255, 255, 0.18);
  color: #ffffff;
}

.btn-desistir-top {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.35);
  color: #f87171;
  font-size: 0.78rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 6px 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-desistir-top:hover {
  background: rgba(239, 68, 68, 0.25);
  color: #ffffff;
}

.form-wrapper {
  max-width: 680px;
  margin: 0 auto;
}

.form-card {
  padding: 36px 30px;
}

.form-header {
  text-align: center;
  margin-bottom: 28px;
}

.form-title {
  font-size: 1.85rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 6px;
}

.form-subtitle {
  color: var(--text-muted);
  font-size: 0.9rem;
}

.alert-box-danger {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #fca5a5;
  border-radius: 12px;
  padding: 14px 18px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  font-size: 0.9rem;
}

.input-with-icon {
  position: relative;
  display: flex;
  align-items: center;
}

.validation-icon {
  position: absolute;
  right: 14px;
  font-size: 1.1rem;
}

.form-control.is-invalid {
  border-color: #ef4444 !important;
  box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.2) !important;
}

.form-control.is-valid {
  border-color: #10b981 !important;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2) !important;
}

.form-section {
  margin-bottom: 28px;
}

.section-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: #f1f5f9;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 8px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
}

.section-desc {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-bottom: 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.col-span-2 {
  grid-column: span 2;
}

.submit-wrapper {
  margin-top: 36px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.btn-desistir-link {
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 0.86rem;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.2s ease;
  display: inline-flex;
  align-items: center;
}

.btn-desistir-link:hover {
  color: #f87171;
  text-decoration: underline;
}

.spin {
  animation: spin 1s infinite linear;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.modal-info-box {
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 16px;
}

.modal-rules-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 0.85rem;
  color: var(--text-muted);
}

.rule-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.rule-item i {
  font-size: 1.1rem;
  margin-top: 2px;
}

.w-100 { width: 100%; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.mb-2 { margin-bottom: 8px; }
.fs-5 { font-size: 1.25rem; }
.text-danger { color: var(--danger-color); }
.text-warning { color: var(--warning-color); }
.text-success { color: var(--success-color); }
.text-primary { color: var(--primary-accent); }
.text-white { color: #ffffff; }
.flex-1 { flex: 1; }

@media (max-width: 576px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .col-span-2 {
    grid-column: span 1;
  }
  .form-card {
    padding: 24px 16px;
  }
}
@media (max-width: 640px) {
  .sticky-timer-bar {
    top: 58px;
    width: calc(100% - 16px);
    padding: 8px 12px;
    border-radius: 12px;
  }
  .sticky-timer-spacer {
    height: 56px;
    margin-bottom: 10px;
  }
  .timer-text {
    display: none;
  }
  .btn-timer-help .help-label {
    display: none;
  }
  .date-select-grid {
    gap: 6px;
  }
  .date-select {
    padding: 9px 6px;
    font-size: 0.82rem;
  }
}
</style>
