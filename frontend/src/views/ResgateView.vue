<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useServerTime } from '../composables/useServerTime'
import { getDeviceFingerprint, getDeviceId } from '../composables/useLoteStatus'
import { getTabReservationToken, saveTabReservationToken, clearTabReservationToken } from '../utils/reservationStorage'
import WebcamCapture from '../components/WebcamCapture.vue'
import Modal from '../components/Modal.vue'
import ExclusiveLotAccess from '../components/ExclusiveLotAccess.vue'

const route = useRoute()
const router = useRouter()
const { calibrarComResposta, getSynchronizedServerTime } = useServerTime()

const hiddenToken = route.params.hiddenToken || ''
const avulso = !!hiddenToken
let loteId = route.params.loteId
const autorizacaoAvulso = ref('')
const senhaAvulso = ref('')
const senhaNecessaria = ref(false)
const acessoInvalidado = ref(false)
const confirmacaoAvulso = ref(null)
const configAvulso = ref(null)
let avulsoPoll = null
const temporizado = computed(() => !avulso || configAvulso.value?.temporizado !== false)
const campoTravado = nome => avulso && configAvulso.value?.campos?.[nome]?.modo === 'fixo'

async function requisicaoResgate(url, options = {}) {
  if (!avulso) return fetch(url, options)
  const parsed = new URL(url, window.location.origin)
  let acao
  if (parsed.pathname.endsWith('/reservar')) acao = 'iniciar'
  else if (parsed.pathname.endsWith('/resgate-confirmado')) acao = 'confirmacao'
  else acao = parsed.pathname.split('/').pop()
  const headers = new Headers(options.headers || {})
  headers.set('X-Lote-Acesso', autorizacaoAvulso.value)
  const response = await fetch(`/api/avulso/${hiddenToken}/${acao}${parsed.search}`, { ...options, headers, cache: 'no-store' })
  if (response.status === 403 || response.status === 404) {
    acessoInvalidado.value = true
    errorMessage.value = 'O acesso foi invalidado. Reabra o link para iniciar um novo formulário.'
  }
  return response
}

function reiniciarAvulso() {
  limparRascunhoFormulario()
  limparEnvioPendente()
  if (autorizacaoAvulso.value && !acessoInvalidado.value) {
    if (timerInterval) clearInterval(timerInterval)
    if (avulsoPoll) clearInterval(avulsoPoll)
    if (debounceCpfTimer) clearTimeout(debounceCpfTimer)
    confirmacaoAvulso.value = null
    tokenReserva.value = ''
    reservaExpiraEmMs.value = null
    cpfStatus.value = null
    nascAno.value = ''
    nascMes.value = ''
    nascDia.value = ''
    form.value = { cpf: '', data_nascimento: '', nome: '', secretaria_id: '', setor: '',
      vinculo: 'Efetivo', telefone: '', email: '', foto_base64: '' }
    errorMessage.value = ''
    showModalExpirado.value = false
    modalFeedback.value.show = false
    carregarDadosResgate()
    return
  }
  window.location.reload()
}

async function autorizarAvulso() {
  const res = await fetch(`/api/avulso/${hiddenToken}/acesso`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ senha: senhaAvulso.value }), cache: 'no-store'
  })
  const data = await res.json()
  if (!res.ok) {
    senhaNecessaria.value = !!data.senha_necessaria
    errorMessage.value = data.senha_necessaria && !senhaAvulso.value ? '' : (data.detail || 'Link indisponível.')
    return false
  }
  loteId = data.id
  lote.value = data
  configAvulso.value = data.config
  autorizacaoAvulso.value = data.autorizacao
  senhaAvulso.value = ''
  senhaNecessaria.value = false
  errorMessage.value = ''
  tokenReserva.value = getTabReservationToken(loteId) || ''
  return true
}
const loading = ref(true)
const lote = ref(null)
const secretarias = ref([])
const buscaSecretaria = ref('')
const showModalSecretaria = ref(false)
const tokenReserva = ref('')
try {
  if (route.query.nova !== '1') {
    tokenReserva.value = String(route.query.token_reserva || getTabReservationToken(loteId))
  }
} catch {}
watch(tokenReserva, token => {
  saveTabReservationToken(loteId, token)
}, { immediate: true })
const reservaExpiraEmMs = ref(null)
const tempoRestanteSegundos = ref(0)
const COOKIE_PRAZO_RESERVA = 'festa_reserva_prazo'

function apagarCookiePrazoReserva() {
  if (typeof document === 'undefined') return
  const secure = window.location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${COOKIE_PRAZO_RESERVA}=; Max-Age=0; Path=/; SameSite=Lax${secure}`
}

function aplicarPrazoReservaDaStream(data) {
  const expiraEmMs = Number(data?.minha_reserva_expira_em_ms ?? data?.expira_em_ms)
  const serverTimeMs = Number(data?.server_time_ms)
  if (!Number.isFinite(expiraEmMs) || !Number.isFinite(serverTimeMs) || expiraEmMs <= 0) return false

  const recebidoEmMs = Date.now()
  calibrarComResposta(serverTimeMs, recebidoEmMs, recebidoEmMs)
  const restanteMs = expiraEmMs - serverTimeMs
  const prazoLocalMs = getSynchronizedServerTime() + Math.max(0, restanteMs)
  reservaExpiraEmMs.value = prazoLocalMs
  tempoRestanteSegundos.value = Math.max(0, Math.ceil(restanteMs / 1000))
  return true
}

const form = ref({
  cpf: '',
  data_nascimento: '',
  nome: '',
  secretaria_id: '',
  setor: '',
  vinculo: 'Efetivo',
  telefone: '',
  email: '',
  foto_base64: ''
})

function normalizarBuscaSecretaria(valor) {
  return String(valor || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('pt-BR')
    .trim()
}

const secretariasSelecionaveis = computed(() => secretarias.value.filter(sec => {
  const nome = normalizarBuscaSecretaria(sec.nome)
  return !/(^|\s)eixos?(\s|$)/.test(nome) && !/(^|\s)consultorias?(\s|$)/.test(nome)
}))

const secretariasFiltradas = computed(() => {
  const consulta = normalizarBuscaSecretaria(buscaSecretaria.value)
  if (!consulta) return secretariasSelecionaveis.value
  return secretariasSelecionaveis.value.filter(sec =>
    normalizarBuscaSecretaria(sec.nome).includes(consulta) ||
    normalizarBuscaSecretaria(sec.sigla).includes(consulta)
  )
})

const secretariaSelecionada = computed(() =>
  secretariasSelecionaveis.value.find(sec => String(sec.id) === String(form.value.secretaria_id)) || null
)

function selecionarSecretaria(sec) {
  form.value.secretaria_id = String(sec.id)
  buscaSecretaria.value = ''
  showModalSecretaria.value = false
}



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



// ============================================================================
// PERSISTÊNCIA AUTOMÁTICA DE RASCUNHO (Dentro dos 5 minutos de reserva)
// ============================================================================
const DRAFT_STORAGE_PREFIX = 'festa_resgate_draft_'
const PENDING_STORAGE_KEY = `festa_resgate_envio_pendente_${loteId}`
const envioPendente = ref(null)

function payloadDeEnvioCompleto(payload) {
  return ['cpf', 'nome', 'data_nascimento', 'secretaria_id', 'setor', 'vinculo', 'telefone', 'email', 'foto_base64']
    .every(field => typeof payload?.[field] === 'string' && payload[field].length > 0)
}

function registrarEnvioPendente(payload) {
  // O rascunho guarda uma única cópia da foto. Enquanto o resultado é incerto,
  // alterações na tela não substituem os dados que serão reenviados.
  salvarRascunhoFormulario(true)
  envioPendente.value = { token: tokenReserva.value, cpf: payload.cpf, payload: { ...payload }, completo: payloadDeEnvioCompleto(payload) }
  try {
    sessionStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify({
      token: tokenReserva.value, cpf: payload.cpf, salvoEm: Date.now()
    }))
  } catch {}
}

function limparEnvioPendente() {
  envioPendente.value = null
  try { sessionStorage.removeItem(PENDING_STORAGE_KEY) } catch {}
}

function restaurarEnvioPendente() {
  try {
    const metadata = JSON.parse(sessionStorage.getItem(PENDING_STORAGE_KEY) || 'null')
    if (typeof metadata?.token !== 'string' || !metadata.token || typeof metadata.cpf !== 'string'
      || !Number.isFinite(metadata.salvoEm) || Date.now() - metadata.salvoEm > 24 * 60 * 60 * 1000) {
      limparEnvioPendente()
      return false
    }
    // Bloqueia a validação automática de CPF durante a recuperação: um envio
    // já salvo pode ter criado a solicitação que essa validação detectaria.
    envioPendente.value = { token: metadata.token, cpf: metadata.cpf, payload: null, completo: false }
    tokenReserva.value = metadata.token
    restaurarRascunhoFormulario()
    form.value.cpf = metadata.cpf
    envioPendente.value.payload = { ...form.value }
    envioPendente.value.completo = payloadDeEnvioCompleto(form.value)
    errorMessage.value = 'O último envio está sem confirmação. Clique em Verificar Envio para recuperar o resultado com os mesmos dados.'
    return true
  } catch {
    limparEnvioPendente()
    return false
  }
}

function salvarRascunhoFormulario(forcar = false) {
  if (envioPendente.value && forcar !== true) return
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
    sessionStorage.setItem(DRAFT_STORAGE_PREFIX + loteId, JSON.stringify(rascunho))
  } catch (e) {
    console.warn('Erro ao salvar rascunho local:', e)
  }
}

function restaurarRascunhoFormulario() {
  try {
    const raw = sessionStorage.getItem(DRAFT_STORAGE_PREFIX + loteId)
    if (!raw) return false

    const draft = JSON.parse(raw)
    // Se o rascunho foi salvo há mais de 10 minutos, descarta
    if (!envioPendente.value && Date.now() - (draft.salvoEm || 0) > 10 * 60 * 1000) {
      limparRascunhoFormulario(false)
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

    if (!envioPendente.value && draft.cpf && draft.cpf.replace(/\D/g, '').length === 11) {
      validarCpfNoServidor(draft.cpf.replace(/\D/g, ''))
    }
    return true
  } catch (e) {
    console.warn('Erro ao restaurar rascunho:', e)
    return false
  }
}

function limparRascunhoFormulario(limparToken = true) {
  try {
    sessionStorage.removeItem(DRAFT_STORAGE_PREFIX + loteId)
    if (limparToken) clearTabReservationToken(loteId)
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
let debounceCpfTimer = null

let resgateEventSource = null
let modalSseStatus = false
const receivedPrivateEvents = new Set()

function atualizarStatusLote(data) {
  if (!data || (data.lote_id && String(data.lote_id) !== String(loteId))) return
  if (submitting.value || envioPendente.value) return

  const status = data.status_slug
  if (!status) return

  if (status === 'aberto' || status === 'reservado') {
    if (modalSseStatus) {
      modalFeedback.value.show = false
      modalSseStatus = false
    }
    return
  }

  const feedbackPorStatus = {
    agendado: {
      titulo: 'Abertura do Lote Alterada',
      subtitulo: 'O período de resgate ainda não começou. Volte à página inicial para acompanhar a nova abertura.',
      icone: 'bi-clock-history',
      corIcone: 'text-warning'
    },
    esgotado: {
      titulo: 'Ingressos Esgotados!',
      subtitulo: 'Todos os ingressos deste lote já foram resgatados por outros participantes.',
      icone: 'bi-ticket-detailed-fill',
      corIcone: 'text-danger'
    },
    pausado: {
      titulo: 'Lote Pausado',
      subtitulo: 'Este lote foi temporariamente pausado pela administração do evento.',
      icone: 'bi-pause-circle-fill',
      corIcone: 'text-warning'
    },
    encerrado: {
      titulo: 'Lote Encerrado',
      subtitulo: 'O período de resgate deste lote já foi encerrado.',
      icone: 'bi-archive-fill',
      corIcone: 'text-secondary'
    }
  }
  const feedback = feedbackPorStatus[status]
  if (!feedback || (modalFeedback.value.show && !modalSseStatus)) return

  modalFeedback.value = {
    show: true,
    ...feedback,
    btnTexto: 'Voltar à Página Inicial',
    btnIcone: 'bi-house-door'
  }
  modalSseStatus = true
}

function aplicarEstadoConsolidadoDaStream(data) {
  if (!data || (data.id && String(data.id) !== String(loteId))) return
  if (data.has_lote && data.id) {
    lote.value = { id: data.id, nome: data.nome, secretaria_nome: data.secretaria_nome }
  }
  atualizarStatusLote(data)
  if (data.minha_reserva_token === tokenReserva.value) aplicarPrazoReservaDaStream(data)
}

function connectResgateSSE() {
  if (avulso) {
    if (avulsoPoll) clearInterval(avulsoPoll)
    avulsoPoll = setInterval(() => {
      if (!acessoInvalidado.value && !confirmacaoAvulso.value) requisicaoResgate('/status').catch(() => {})
    }, 5000)
    return
  }
  if (typeof window === 'undefined' || !window.EventSource) return
  if (resgateEventSource) {
    resgateEventSource.close()
    resgateEventSource = null
  }
  try {
    const myFp = getDeviceFingerprint()
    resgateEventSource = new EventSource(`/api/lote/stream?device_fingerprint=${myFp}&lote_id=${loteId}&token_reserva=${encodeURIComponent(tokenReserva.value)}`)
    resgateEventSource.addEventListener('ESTADO_CONSOLIDADO', (event) => {
      try {
        aplicarEstadoConsolidadoDaStream(JSON.parse(event.data))
      } catch {}
    })
    resgateEventSource.addEventListener('ESTADO_INICIAL', (event) => {
      try {
        aplicarEstadoConsolidadoDaStream(JSON.parse(event.data))
      } catch {}
    })
    const handleEvent = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.lote_id && String(data.lote_id) !== String(loteId)) return
        if (event.type === 'RESERVA_ATUALIZADA' && data.event_id) {
          if (receivedPrivateEvents.has(data.event_id)) return
          receivedPrivateEvents.add(data.event_id)
          if (receivedPrivateEvents.size > 256) receivedPrivateEvents.delete(receivedPrivateEvents.values().next().value)
        }
        const reservaDesteDispositivo = data.token_reserva && data.token_reserva === tokenReserva.value
        atualizarStatusLote(data)
        if (data.tipo === 'reserva_criada' && reservaDesteDispositivo && !envioPendente.value) {
          if (data.token_reserva) tokenReserva.value = data.token_reserva
          aplicarPrazoReservaDaStream(data)
        }
        // Se a reserva deste token específico for liberada ou concluída em outra aba/janela:
        if (
          (data.tipo === 'reserva_liberada' || data.tipo === 'resgate_concluido') &&
          tokenReserva.value &&
          reservaDesteDispositivo &&
          !desistindo.value &&
          !submitting.value &&
          !envioPendente.value &&
          !modalFeedback.value.show
        ) {
          if (data.tipo === 'resgate_concluido') {
            router.push('/')
            return
          }
          if (data.motivo === 'desistencia') {
            if (timerInterval) clearInterval(timerInterval)
            showModalDesistir.value = false
            showModalDesistidaOutroNavegador.value = true
          }
        }
      } catch {}
    }
    resgateEventSource.addEventListener('LOTE_ATUALIZADO', handleEvent)
    resgateEventSource.addEventListener('RESERVA_ATUALIZADA', handleEvent)
  } catch {}
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
  if (submitting.value || envioPendente.value) return
  try {
    validandoCpf.value = true
    cpfStatus.value = null
    const tokenParam = tokenReserva.value ? `&token_reserva=${encodeURIComponent(tokenReserva.value)}` : ''
    const res = await requisicaoResgate(`/api/resgate/validar-cpf?cpf=${digits}${tokenParam}`)
    const data = await res.json()
    if (submitting.value || envioPendente.value) return

    if (!data.valido) {
      cpfStatus.value = {
        valido: false,
        msg: data.mensagem
      }
      errorMessage.value = data.mensagem

      // Caso o CPF já possua ingresso resgatado ou solicitação ativa:
      if (
        data.tipo_erro === 'ingresso_existente' ||
        data.tipo_erro === 'solicitacao_existente' ||
        (data.mensagem && data.mensagem.includes('Já foi realizado um resgate'))
      ) {
        if (timerInterval) clearInterval(timerInterval)
        limparRascunhoFormulario()
        form.value.cpf = ''

        // Libera a sessão de reserva deste dispositivo/token no backend imediatamente
        if (tokenReserva.value) {
          const tok = tokenReserva.value
          tokenReserva.value = ''
          const formData = new FormData()
          formData.append('token_reserva', tok)
          requisicaoResgate('/api/resgate/desistir', { method: 'POST', body: formData }).catch(() => {})
        }

        showModalDesistidaOutroNavegador.value = false
        showModalDesistir.value = false
        modalFeedback.value = {
          show: true,
          titulo: 'Aviso de Resgate',
          subtitulo: data.mensagem || 'Já foi realizado um resgate para este CPF.',
          icone: 'bi-exclamation-triangle-fill',
          corIcone: 'text-warning',
          btnTexto: avulso ? 'Cadastrar outro participante' : 'Voltar à Página Inicial',
          btnIcone: avulso ? 'bi-person-plus' : 'bi-house-door'
        }
        return
      }

    } else {
      const msgSucesso = data.mensagem || (data.nome_preview ? `CPF identificado: ${data.nome_preview}` : 'CPF apto para resgate!')
      cpfStatus.value = {
        valido: true,
        msg: msgSucesso
      }
      if (errorMessage.value === 'Já foi realizado um resgate para este CPF' || errorMessage.value === 'Esse CPF já possui um ingresso.' || errorMessage.value === 'Não é possível resgatar para esse CPF.' || errorMessage.value === 'CPF inválido. Verifique os números digitados.') {
        errorMessage.value = ''
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

    // 2. Consulta em segundo plano para elegibilidade e ingresso já emitido
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
    // O servidor pode ter confirmado o cadastro mesmo se a resposta se perdeu.
    // A expiração não deve apagar o material necessário para recuperá-lo.
    if (submitting.value || envioPendente.value) return
    apagarCookiePrazoReserva()
    limparRascunhoFormulario()
    showModalExpirado.value = true
    if (timerInterval) clearInterval(timerInterval)
    return
  }

  tempoRestanteSegundos.value = Math.max(0, Math.floor(dist / 1000))
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
    if (avulso && !autorizacaoAvulso.value && !await autorizarAvulso()) {
      loading.value = false
      return
    }

    if (restaurarEnvioPendente()) {
      if (await consultarConfirmacaoPendente()) return
      connectResgateSSE()
      try {
        const secRes = await requisicaoResgate('/api/secretarias')
        if (secRes.ok) secretarias.value = await secRes.json()
      } catch {}
      if (!envioPendente.value.completo) {
        errorMessage.value = 'O envio ainda está sem confirmação e o rascunho não está completo neste navegador. Preencha novamente os campos e a foto; Verificar Envio recupera a confirmação antes de tentar reenviar.'
      }
      loading.value = false
      return
    }

    if (route.query.nova === '1') limparRascunhoFormulario()
    const deviceFp = getDeviceFingerprint()
    const deviceId = getDeviceId()
    const res = await requisicaoResgate(`/api/lote/${loteId}/reservar?device_fingerprint=${encodeURIComponent(deviceFp)}&device_id=${encodeURIComponent(deviceId)}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'X-Device-Fingerprint': deviceFp,
        'X-Device-ID': deviceId,
        'X-Reserva-Token': tokenReserva.value
      }
    })

    if (!res.ok) {
      limparRascunhoFormulario()
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
    if (avulso) {
      configAvulso.value = dataRes.config
      lote.value = dataRes
      if (temporizado.value) aplicarPrazoReservaDaStream(dataRes)
    }
    if (dataRes.token_reserva) {
      tokenReserva.value = dataRes.token_reserva
    }
    if (route.query.nova === '1' || route.query.token_reserva) {
      await router.replace({ path: route.path, query: { ...route.query, nova: undefined, token_reserva: undefined } })
    }
    connectResgateSSE()
    try {
      const secRes = await requisicaoResgate('/api/secretarias')
      if (secRes.ok) {
        secretarias.value = await secRes.json()
      }
    } catch {
      // Fallback
    }



    restaurarRascunhoFormulario()
    if (avulso) {
      for (const [campo, regra] of Object.entries(configAvulso.value.campos)) {
        if (regra.modo !== 'livre') form.value[campo] = regra.valor
      }
    }
    updateCountdown()
    timerInterval = setInterval(updateCountdown, 1000)
    loading.value = false
  } catch (err) {
    // Erro tratado na UI
    errorMessage.value = 'Erro ao inicializar formulário de resgate.'
    loading.value = false
  }
}

function fecharModalFeedback() {
  modalFeedback.value.show = false
  limparRascunhoFormulario()
  if (avulso) { reiniciarAvulso(); return }
  router.push('/')
}

// Desistir da vaga reservada
async function executarDesistencia() {
  if (submitting.value || envioPendente.value) {
    showModalDesistir.value = false
    errorMessage.value = 'Verifique o resultado do envio antes de desistir. Seu cadastro pode já ter sido confirmado.'
    return
  }
  limparRascunhoFormulario()
  if (!tokenReserva.value) {
    router.push('/')
    return
  }
  try {
    desistindo.value = true
    const formData = new FormData()
    formData.append('token_reserva', tokenReserva.value)
    const res = await requisicaoResgate('/api/resgate/desistir', {
      method: 'POST',
      body: formData
    })
    if (res.ok) apagarCookiePrazoReserva()
    showModalDesistir.value = false
    if (avulso) { reiniciarAvulso(); return }
    router.push('/')
  } catch (e) {
    router.push('/')
  } finally {
    desistindo.value = false
  }
}

function validarFormularioParaEnvio() {
  if (!form.value.secretaria_id) {
    errorMessage.value = 'Selecione sua secretaria ou órgão para continuar.'
    document.getElementById('secretaria-selector-button')?.focus()
    return false
  }

  const digits = form.value.cpf.replace(/\D/g, '')
  if (!validarCpfMatematico(digits)) {
    errorMessage.value = 'CPF inválido. Verifique os números digitados.'
    return false
  }

  if (cpfStatus.value && !cpfStatus.value.valido) {
    errorMessage.value = cpfStatus.value.msg
    return false
  }

  if (idadeInvalida.value) {
    errorMessage.value = 'O resgate de ingressos é permitido exclusivamente para maiores de 18 anos.'
    return false
  }

  if (!form.value.foto_base64) {
    errorMessage.value = 'A foto de identificação é obrigatória. Tire uma foto pela câmera ou envie um arquivo.'
    return false
  }

  if (!tokenReserva.value) {
    errorMessage.value = 'Reserva de vaga expirada ou não encontrada. Por favor, recarregue a página.'
    return false
  }
  return true
}

function finalizarEnvioConfirmado(data) {
  const target = data?.redirect_url || (data?.ingresso_id ? '/sucesso/' + data.ingresso_id : null)
  if (!target || data?.sucesso === false) return false
  limparEnvioPendente()
  apagarCookiePrazoReserva()
  limparRascunhoFormulario()
  if (avulso) {
    confirmacaoAvulso.value = data
    if (timerInterval) clearInterval(timerInterval)
    if (avulsoPoll) clearInterval(avulsoPoll)
    return true
  }
  router.push(target)
  return true
}

async function consultarConfirmacaoPendente() {
  if (!envioPendente.value) return false
  const token = encodeURIComponent(envioPendente.value.token)
  const cpf = encodeURIComponent(envioPendente.value.cpf.replace(/\D/g, ''))
  try {
    const response = await requisicaoResgate(`/api/lote/${loteId}/resgate-confirmado?token_reserva=${token}&cpf=${cpf}`, {
      headers: { 'Accept': 'application/json' }, cache: 'no-store', credentials: 'same-origin'
    })
    if (response.ok) return finalizarEnvioConfirmado(await response.json())
  } catch {}
  return false
}

async function handleSubmit() {
  if (submitting.value) return
  const recuperandoEnvio = !!envioPendente.value
  if (!recuperandoEnvio) {
    if (!validarFormularioParaEnvio()) return
    registrarEnvioPendente(form.value)
  }

  submitting.value = true
  errorMessage.value = ''

  try {
    if (recuperandoEnvio) {
      if (await consultarConfirmacaoPendente()) return
      if (!envioPendente.value.completo) {
        form.value.cpf = envioPendente.value.cpf
        if (!validarFormularioParaEnvio() || !payloadDeEnvioCompleto(form.value)) {
          errorMessage.value = 'Não foi possível recuperar a confirmação. Complete novamente os campos e a foto para reenviar com a mesma identificação.'
          return
        }
        registrarEnvioPendente(form.value)
      }
    }
    const formData = new FormData()
    const payload = envioPendente.value.payload
    formData.append('token_reserva', envioPendente.value.token)
    formData.append('cpf', payload.cpf)
    formData.append('nome', payload.nome)
    formData.append('data_nascimento', payload.data_nascimento)
    formData.append('setor', payload.setor)
    formData.append('secretaria_id', payload.secretaria_id || '1')
    formData.append('vinculo', payload.vinculo)
    formData.append('telefone', payload.telefone)
    formData.append('email', payload.email)
    formData.append('foto_base64', payload.foto_base64)

    const res = await requisicaoResgate(`/api/lote/${loteId}/resgatar`, {
      method: 'POST',
      headers: { 'Accept': 'application/json, text/html' },
      body: formData
    })

    if (res.redirected) {
      const targetUrl = new URL(res.url)
      if (targetUrl.pathname.startsWith('/sucesso/')) {
        const id = targetUrl.pathname.split('/').pop()
        limparEnvioPendente()
        limparRascunhoFormulario()
        apagarCookiePrazoReserva()
        router.push('/sucesso/' + id)
        return
      }
      window.location.href = res.url
      return
    }

    if (!res.ok) {
      if (res.status >= 500 || res.status === 408 || res.status === 429) {
        errorMessage.value = 'Não foi possível confirmar o resultado. Clique em Verificar Envio para reenviar os mesmos dados com segurança.'
        return
      }
      limparEnvioPendente()
      const text = await res.text()
      try {
        const json = JSON.parse(text)
        errorMessage.value = (typeof json.detail === 'string' ? json.detail : json.detail?.mensagem) || 'Erro ao processar resgate do ingresso.'
        if (json.detail === 'Você desistiu desta vaga por outro navegador.') {
          showModalDesistidaOutroNavegador.value = true
        }
      } catch {
        errorMessage.value = 'Não foi possível concluir o resgate. Verifique seus dados.'
      }
      return
    }

    const data = await res.json()
    if (finalizarEnvioConfirmado(data)) return
    errorMessage.value = 'O servidor não retornou uma confirmação. Clique em Verificar Envio para recuperar o resultado.'
  } catch (e) {
    errorMessage.value = 'A conexão falhou antes da confirmação. Clique em Verificar Envio: seus dados e a identificação do envio foram preservados.'
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  carregarDadosResgate()
})

onUnmounted(() => {
  if (avulsoPoll) clearInterval(avulsoPoll)
  if (resgateEventSource) {
    resgateEventSource.close()
    resgateEventSource = null
  }
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
  if (debounceCpfTimer) {
    clearTimeout(debounceCpfTimer)
    debounceCpfTimer = null
  }
})
</script>


<template>
  <div :class="{ 'resgate-page': !avulso || autorizacaoAvulso }">
    <ExclusiveLotAccess
      v-if="avulso && !autorizacaoAvulso"
      v-model="senhaAvulso"
      :loading="loading"
      :requires-password="senhaNecessaria"
      :error-message="errorMessage"
      @submit="carregarDadosResgate"
    />
    <div v-else class="app-container">
      
      <!-- Barra Flutuante Superior do Tempo Reservado (Acompanha a rolagem da tela) -->
      <div v-if="temporizado && (!avulso || autorizacaoAvulso) && !confirmacaoAvulso" class="sticky-timer-bar" :class="{ 'timer-critical': isTimerCritical }">
        <div class="timer-info-left">
          <span class="timer-pill" :class="{ 'critical': isTimerCritical }">
            <i class="bi bi-hourglass-split"></i>
            <span class="font-outfit">{{ displayTimer }}</span>
          </span>
          <span class="timer-text">
            <template v-if="envioPendente">Aguardando a confirmação do envio.</template>
            <template v-else>Sua vaga está garantida por <strong class="text-warning">{{ displayTimerInline }}</strong></template>
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
      <div v-if="temporizado && !confirmacaoAvulso" class="sticky-timer-spacer"></div>

      <div class="form-wrapper">
        <div class="vip-card form-card">
          
          <!-- Cabeçalho do Formulário -->
          <div class="form-header">
            <span v-if="lote" class="vip-badge bg-primary">
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

          <section v-if="avulso && !temporizado && !confirmacaoAvulso" class="modal-section"><p>Este formulário não tem cronômetro. A vaga será confirmada somente no envio, conforme a disponibilidade do lote.</p></section>
          <section v-if="avulso && acessoInvalidado" class="modal-section"><button type="button" class="btn-primary" @click="reiniciarAvulso">Reabrir link e reiniciar</button></section>
          <section v-if="confirmacaoAvulso" class="modal-hero-card">
            <h3>{{ confirmacaoAvulso.status === 'aprovado' ? 'Ingresso aprovado' : 'Cadastro recebido' }}</h3>
            <p>{{ confirmacaoAvulso.mensagem }}</p>
            <p>Protocolo: VAL-{{ String(confirmacaoAvulso.solicitacao_id).padStart(6, '0') }}</p>
            <button type="button" class="btn-primary" @click="reiniciarAvulso">Cadastrar outro participante</button>
          </section>

          <form v-if="!avulso || (autorizacaoAvulso && !acessoInvalidado && !confirmacaoAvulso)" @submit.prevent="handleSubmit">

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
                  <label class="form-label" for="secretaria-selector-button">Secretaria / Órgão <span class="text-danger">*</span></label>
                  <button
                    id="secretaria-selector-button"
                    :disabled="campoTravado('secretaria_id')"
                    type="button"
                    class="secretaria-select-trigger"
                    aria-haspopup="dialog"
                    :aria-expanded="showModalSecretaria"
                    @click="showModalSecretaria = true"
                  >
                    <i class="bi bi-building" aria-hidden="true"></i>
                    <span class="secretaria-trigger-copy">
                      <strong>{{ secretariaSelecionada?.nome || 'Selecionar secretaria' }}</strong>
                      <small v-if="secretariaSelecionada?.sigla">{{ secretariaSelecionada.sigla }}</small>
                      <small v-else-if="!secretariaSelecionada">Toque aqui para escolher seu órgão</small>
                    </span>
                    <i class="bi bi-chevron-down secretaria-trigger-chevron" aria-hidden="true"></i>
                  </button>
                  <div v-if="secretariaSelecionada" class="secretaria-selected-summary" aria-live="polite">
                    <i class="bi bi-check-circle-fill" aria-hidden="true"></i>
                    <span>Órgão selecionado</span>
                  </div>
                </div>

                <div class="form-group">
                  <label class="form-label" for="setor">Setor / Local de Trabalho <span class="text-danger">*</span></label>
                  <input
                    id="setor"
                    :readonly="campoTravado('setor')"
                    v-model="form.setor"
                    type="text"
                    class="form-control"
                    placeholder="Ex: Recursos Humanos, Recepção..."
                    required
                  />
                </div>

                <div class="form-group">
                  <label class="form-label" for="vinculo">Vínculo <span class="text-danger">*</span></label>
                  <select id="vinculo" v-model="form.vinculo" class="form-select" :disabled="campoTravado('vinculo')" required>
                    <option value="Efetivo">Efetivo</option>
                    <option value="Comissionado">Comissionado</option>
                    <option value="Contrato Temporário">Contrato Temporário</option>
                    <option value="Estagiário">Estagiário</option>
                    <option value="Terceirizado">Terceirizado</option>
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

            <!-- SEÇÃO 4: FOTO DE IDENTIFICAÇÃO -->
            <div class="form-section">
              <h3 class="section-title font-outfit">
                <i class="bi bi-camera-fill text-primary me-2"></i> 4. Foto de Identificação Obrigatória
              </h3>
              <p class="section-desc">
                Para sua identificação na portaria, tire uma foto pela câmera ou envie uma foto sua já salva no computador ou celular. Escolha uma imagem nítida, com o rosto visível e sem outras pessoas.
              </p>

              <WebcamCapture v-model="form.foto_base64" allow-upload />
            </div>

            <!-- BOTÕES DE AÇÃO: CONCLUIR OU DESISTIR -->
            <div class="submit-wrapper">
              <button
                type="submit"
                class="btn-vip-mega font-outfit"
                :formnovalidate="!!envioPendente"
                :disabled="submitting || (!envioPendente && (!form.foto_base64 || (cpfStatus && !cpfStatus.valido) || idadeInvalida))"
              >
                <span v-if="!submitting">{{ envioPendente ? 'Verificar Envio' : 'Concluir e Garantir Ingresso' }}</span>
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
          Ao clicar em "Resgatar Ingresso", o sistema <strong>reserva uma vaga exclusivamente para você por 5 minutos</strong>, garantindo que ninguém pegue seu lugar enquanto você preenche seus dados e tira ou envia sua foto.
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

    <!-- Modal de seleção de Secretaria / Órgão -->
    <Modal
      :show="showModalSecretaria"
      title="Selecionar Secretaria / Órgão"
      icon="bi-building"
      icon-color="text-primary"
      :max-width="'720px'"
      @close="showModalSecretaria = false"
    >
      <div class="secretaria-modal-picker">
        <div class="secretaria-picker-search secretaria-modal-search">
          <i class="bi bi-search" aria-hidden="true"></i>
          <input
            id="secretaria-busca"
            v-model="buscaSecretaria"
            type="search"
            class="form-control secretaria-search-input"
            placeholder="Pesquise pelo nome ou pela sigla"
            autocomplete="off"
            aria-label="Pesquisar secretaria ou órgão"
          />
        </div>

        <div v-if="secretariasFiltradas.length" class="secretaria-results" role="listbox" aria-label="Secretarias e órgãos disponíveis">
          <button
            v-for="sec in secretariasFiltradas"
            :key="sec.id"
            type="button"
            class="secretaria-result-option"
            :class="{ 'is-selected': String(form.secretaria_id) === String(sec.id) }"
            role="option"
            :aria-selected="String(form.secretaria_id) === String(sec.id)"
            @click="selecionarSecretaria(sec)"
          >
            <span class="secretaria-result-copy">
              <strong>{{ sec.nome }}</strong>
              <small v-if="sec.sigla">{{ sec.sigla }}</small>
            </span>
            <i v-if="String(form.secretaria_id) === String(sec.id)" class="bi bi-check-circle-fill" aria-hidden="true"></i>
          </button>
        </div>
        <p v-else class="secretaria-no-results" role="status">
          Nenhum órgão encontrado. Confira a escrita ou tente pela sigla.
        </p>
      </div>
    </Modal>

    <!-- Modal Dinâmico de Feedback do Resgate (Esgotado, Em Preenchimento, Pausado, Encerrado, Já Resgatado) -->
    <Modal
      :show="modalFeedback.show"
      :title="modalFeedback.titulo"
      :icon="modalFeedback.icone"
      :icon-color="modalFeedback.corIcone"
      :max-width="'480px'"
      @close="fecharModalFeedback"
    >
      <div class="text-center py-2">
        <p class="text-muted font-outfit" style="font-size: 0.95rem; line-height: 1.5;">
          {{ modalFeedback.subtitulo }}
        </p>
      </div>
      <template #footer>
        <button type="button" class="btn-primary w-100" @click="fecharModalFeedback">
          <i :class="['bi', modalFeedback.btnIcone, 'me-1']"></i> {{ modalFeedback.btnTexto }}
        </button>
      </template>
    </Modal>

  </div>
</template>

<style scoped>
.resgate-page {
  padding: var(--space-xl) 0 calc(var(--space-xl) * 2);
}
</style>
