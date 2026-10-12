<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import confetti from 'canvas-confetti'
import { useServerTime } from '../composables/useServerTime'
import { useLoteStatus } from '../composables/useLoteStatus'
import Modal from '../components/Modal.vue'
import FaqModal from '../components/FaqModal.vue'
import SponsorLogos from '../components/SponsorLogos.vue'
import { useAuth } from '../composables/useAuth'

const router = useRouter()
const { serverClockOffsetMs, calibrarRelogioComServidor, getSynchronizedServerTime } = useServerTime()
const {
  loading,
  hasLote,
  modoFesta,
  lote,
  statusInfo,
  minhaReservaSegundos,
  minhaReservaExpiraEmMs,
  minhaReservaToken,
  dataAberturaIso,
  dataFechamentoIso,
  dataFestaIso,
  dataFestaFormatada,
  temLoteComPrevisao,
  lotePrevisaoId,
  lotePrevisaoAberturaIso,
  loteEncerradoRecente,
  startSSE,
  stopSSE,
  sseConnectionError,
  parseSaoPauloTimeToMs
} = useLoteStatus()

const { isAdminGeral } = useAuth()
const showFaqModal = ref(false)
const showModalDesistirHome = ref(false)
const desistindoHome = ref(false)
const confetesDisparados = ref(false)

// Estados de renderização do relógio geral
const dias = ref('00')
const horas = ref('00')
const minutos = ref('00')
const segundos = ref('00')
const apenasSegundos = ref('00')
const isHalo10s = ref(false)
const isState1min = ref(false)
const loteJaAbriuNaSessao = ref(false)
const aberturaNotificada = ref(false)

watch(() => statusInfo.value.status_slug, (slug, previousSlug) => {
  if (slug === 'aberto') {
    loteJaAbriuNaSessao.value = true
    if (previousSlug !== 'aberto') {
      soltarConfetes()
    }
  } else {
    loteJaAbriuNaSessao.value = false
    confetesDisparados.value = false
  }
})
const isState10s = ref(false)
const isState10min = ref(false)
const textoLoteEncerraEm = ref('')

// Estados específicos da Minha Reserva Ativa
const tempoReservaFormatado = ref('')

// Aviso de tempo desde que o lote mais recente encerrou
const textoLoteEncerradoRecente = ref('')
const tempoParaFecharFormatado = ref('')

function formatarContagemFechamento(segundosTotais) {
  if (segundosTotais <= 0) return '00:00:00'
  const h = Math.floor(segundosTotais / 3600)
  const m = Math.floor((segundosTotais % 3600) / 60)
  const s = segundosTotais % 60
  const pad = (n) => (n < 10 ? '0' + n : '' + n)

  if (h >= 24) {
    const d = Math.floor(h / 24)
    const remH = h % 24
    return `${d}d ${pad(remH)}:${pad(m)}:${pad(s)}`
  }
  return `${pad(h)}:${pad(m)}:${pad(s)}`
}

function formatarTempoDecorrido(segundosTotais) {
  const seg = Math.max(0, Math.floor(segundosTotais))
  
  if (seg < 60) {
    const s = seg
    const unidade = s === 1 ? 'segundo' : 'segundos'
    return `O lote mais recente aberto encerrou há ${s} ${unidade} atrás.`
  }
  
  const min = Math.floor(seg / 60)
  if (min < 60) {
    const unidade = min === 1 ? 'minuto' : 'minutos'
    return `O lote mais recente aberto encerrou há ${min} ${unidade} atrás.`
  }
  
  const horas = Math.floor(min / 60)
  if (horas < 24) {
    const unidade = horas === 1 ? 'hora' : 'horas'
    return `O lote mais recente aberto encerrou há ${horas} ${unidade} atrás.`
  }
  
  const dias = Math.floor(horas / 24)
  if (dias < 30) {
    const unidade = dias === 1 ? 'dia' : 'dias'
    return `O lote mais recente aberto encerrou há ${dias} ${unidade} atrás.`
  }

  const meses = Math.floor(dias / 30)
  const unidade = meses === 1 ? 'mês' : 'meses'
  return `O lote mais recente aberto encerrou há ${meses} ${unidade} atrás.`
}

// O tema de patrocínio master foi removido.
const isBradescoTheme = computed(() => false)

// Efeitos visuais legados, mantidos inativos após a remoção do tema de patrocinador.
const cometsCanvasRef = ref(null)
let canvasCtx = null
let animFrameId = null
let activeComets = []
let activeSparks = []
let canvasW = 0
let canvasH = 0
let spawnTimeout = null

class SeamlessCurvedComet {
  constructor(w, h) {
    this.init(w, h)
  }

  init(w, h) {
    const scaleBase = Math.min(Math.max(w / 1200, 0.75), 1.6)

    this.x = w * 0.35 + Math.random() * (w * 0.65)
    this.y = -60 - Math.random() * (h * 0.25)

    this.angle = (136 + Math.random() * 14) * (Math.PI / 180)
    this.curveRate = (Math.random() > 0.45 ? 1 : -1) * (0.0025 + Math.random() * 0.0035)

    this.speed = (15 + Math.random() * 6) * scaleBase

    this.headRadius = (4.5 + Math.random() * 2.5) * scaleBase
    this.glowRadius = this.headRadius * 4.5
    this.maxHistory = Math.floor((50 + Math.random() * 30) * scaleBase)

    this.history = []
    this.opacity = 0
    this.targetOpacity = 0.92 + Math.random() * 0.08
    this.exitedScreen = false
    this.dead = false
  }

  update(w, h) {
    if (!this.exitedScreen) {
      this.angle += this.curveRate
      this.x += Math.cos(this.angle) * this.speed
      this.y += Math.sin(this.angle) * this.speed

      this.history.unshift({ x: this.x, y: this.y })
      if (this.history.length > this.maxHistory) {
        this.history.pop()
      }

      if (Math.random() > 0.45 && activeSparks.length < 40) {
        activeSparks.push({
          x: this.x + (Math.random() - 0.5) * 6,
          y: this.y + (Math.random() - 0.5) * 6,
          vx: (Math.random() - 0.5) * 1.5,
          vy: (Math.random() - 0.5) * 1.5,
          size: Math.random() * 2 + 0.8,
          opacity: 0.85,
          life: 0,
          maxLife: 18 + Math.random() * 12
        })
      }

      if (this.opacity < this.targetOpacity) {
        this.opacity = Math.min(this.targetOpacity, this.opacity + 0.06)
      }

      if (this.x < -80 || this.y > h + 80) {
        this.exitedScreen = true
      }
    } else {
      if (this.history.length > 0) {
        this.history.pop()
        if (this.history.length > 1) {
          this.history.pop()
        }
        this.opacity = Math.max(0, this.opacity - 0.035)
      } else {
        this.dead = true
      }
    }
  }

  draw(ctx) {
    const pts = this.history
    if (this.opacity <= 0 || pts.length < 3) return

    ctx.save()

    const head = pts[0]
    const tail = pts[pts.length - 1]

    const leftPts = []
    const rightPts = []

    for (let i = 0; i < pts.length; i++) {
      const p = pts[i]
      let dx, dy

      if (i < pts.length - 1) {
        dx = p.x - pts[i + 1].x
        dy = p.y - pts[i + 1].y
      } else {
        dx = pts[i - 1].x - p.x
        dy = pts[i - 1].y - p.y
      }

      const len = Math.hypot(dx, dy) || 1
      const nx = -dy / len
      const ny = dx / len

      const progress = i / (pts.length - 1)
      const width = this.headRadius * 1.4 * Math.pow(1 - progress, 0.7)

      leftPts.push({ x: p.x + nx * width, y: p.y + ny * width })
      rightPts.push({ x: p.x - nx * width, y: p.y - ny * width })
    }

    const ribbonGrad = ctx.createLinearGradient(head.x, head.y, tail.x, tail.y)
    ribbonGrad.addColorStop(0, `rgba(255, 35, 80, ${this.opacity * 0.95})`)
    ribbonGrad.addColorStop(0.2, `rgba(255, 23, 68, ${this.opacity * 0.8})`)
    ribbonGrad.addColorStop(0.6, `rgba(204, 9, 47, ${this.opacity * 0.3})`)
    ribbonGrad.addColorStop(1, 'rgba(204, 9, 47, 0)')

    ctx.beginPath()
    ctx.moveTo(leftPts[0].x, leftPts[0].y)

    for (let i = 1; i < leftPts.length - 1; i++) {
      const xc = (leftPts[i].x + leftPts[i + 1].x) / 2
      const yc = (leftPts[i].y + leftPts[i + 1].y) / 2
      ctx.quadraticCurveTo(leftPts[i].x, leftPts[i].y, xc, yc)
    }
    ctx.lineTo(tail.x, tail.y)

    for (let i = rightPts.length - 2; i > 0; i--) {
      const xc = (rightPts[i].x + rightPts[i - 1].x) / 2
      const yc = (rightPts[i].y + rightPts[i - 1].y) / 2
      ctx.quadraticCurveTo(rightPts[i].x, rightPts[i].y, xc, yc)
    }
    ctx.lineTo(rightPts[0].x, rightPts[0].y)
    ctx.closePath()

    ctx.fillStyle = ribbonGrad
    ctx.shadowColor = '#ff1744'
    ctx.shadowBlur = 12
    ctx.fill()

    // Núcleo Laser
    const coreGrad = ctx.createLinearGradient(head.x, head.y, tail.x, tail.y)
    coreGrad.addColorStop(0, `rgba(255, 120, 150, ${this.opacity * 0.9})`)
    coreGrad.addColorStop(0.35, `rgba(255, 45, 85, ${this.opacity * 0.5})`)
    coreGrad.addColorStop(0.8, 'rgba(255, 23, 68, 0)')

    ctx.beginPath()
    ctx.moveTo(head.x, head.y)
    const coreLimit = Math.floor(pts.length * 0.6)
    for (let i = 1; i < coreLimit - 1; i++) {
      const xc = (pts[i].x + pts[i + 1].x) / 2
      const yc = (pts[i].y + pts[i + 1].y) / 2
      ctx.quadraticCurveTo(pts[i].x, pts[i].y, xc, yc)
    }
    ctx.strokeStyle = coreGrad
    ctx.lineWidth = this.headRadius * 0.7
    ctx.stroke()

    // Cabeça
    if (!this.exitedScreen) {
      const auraGrad = ctx.createRadialGradient(
        head.x, head.y, 0,
        head.x, head.y, this.glowRadius
      )
      auraGrad.addColorStop(0, `rgba(255, 45, 85, ${this.opacity * 0.95})`)
      auraGrad.addColorStop(0.3, `rgba(255, 23, 68, ${this.opacity * 0.75})`)
      auraGrad.addColorStop(0.65, `rgba(204, 9, 47, ${this.opacity * 0.3})`)
      auraGrad.addColorStop(1, 'rgba(204, 9, 47, 0)')

      ctx.beginPath()
      ctx.arc(head.x, head.y, this.glowRadius, 0, Math.PI * 2)
      ctx.fillStyle = auraGrad
      ctx.fill()

      ctx.beginPath()
      ctx.arc(head.x, head.y, this.headRadius, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(255, 80, 120, ${this.opacity})`
      ctx.shadowColor = '#ff1744'
      ctx.shadowBlur = 18
      ctx.fill()
    }

    ctx.restore()
  }
}

function resizeCanvas() {
  if (!cometsCanvasRef.value) return
  const canvas = cometsCanvasRef.value
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvasW = window.innerWidth
  canvasH = window.innerHeight
  canvas.width = canvasW * dpr
  canvas.height = canvasH * dpr
  canvas.style.width = canvasW + 'px'
  canvas.style.height = canvasH + 'px'
  if (canvasCtx) {
    canvasCtx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
}

function spawnComet() {
  if (!isBradescoTheme.value || document.hidden) return
  if (activeComets.length < 3) {
    activeComets.push(new SeamlessCurvedComet(canvasW, canvasH))
  }
  const nextSpawn = 700 + Math.random() * 1200
  spawnTimeout = setTimeout(spawnComet, nextSpawn)
}

function renderCometLoop() {
  if (!cometsCanvasRef.value || !canvasCtx) return

  canvasCtx.clearRect(0, 0, canvasW, canvasH)

  if (isBradescoTheme.value && !document.hidden) {
    for (let i = activeComets.length - 1; i >= 0; i--) {
      const c = activeComets[i]
      c.update(canvasW, canvasH)
      c.draw(canvasCtx)
      if (c.dead) {
        activeComets.splice(i, 1)
      }
    }

    for (let i = activeSparks.length - 1; i >= 0; i--) {
      const s = activeSparks[i]
      s.x += s.vx
      s.y += s.vy
      s.life++
      s.opacity = Math.max(0, 1 - (s.life / s.maxLife))
      if (s.opacity <= 0 || s.life >= s.maxLife) {
        activeSparks.splice(i, 1)
        continue
      }
      canvasCtx.beginPath()
      canvasCtx.arc(s.x, s.y, s.size, 0, Math.PI * 2)
      canvasCtx.fillStyle = `rgba(255, 45, 85, ${s.opacity * 0.8})`
      canvasCtx.fill()
    }
  }

  animFrameId = requestAnimationFrame(renderCometLoop)
}

watch(isBradescoTheme, (val) => {
  if (val) {
    activeComets = []
    activeSparks = []
    if (spawnTimeout) clearTimeout(spawnTimeout)
    spawnComet()
  } else {
    activeComets = []
    activeSparks = []
    if (spawnTimeout) {
      clearTimeout(spawnTimeout)
      spawnTimeout = null
    }
    if (canvasCtx && canvasW && canvasH) {
      canvasCtx.clearRect(0, 0, canvasW, canvasH)
    }
  }
})

let renderInterval = null
const checkpointsExecutados = { 30: false, 10: false, 5: false, 3: false }

function soltarConfetes() {
  if (confetesDisparados.value) return
  confetesDisparados.value = true
  confetti({
    particleCount: 100,
    spread: 80,
    origin: { y: 0.6 }
  })
}

function formatarTempo(val) {
  return val < 10 ? '0' + val : '' + val
}

function formatarTempoReserva(seg) {
  const min = Math.floor(seg / 60)
  const s = seg % 60
  if (min > 0) {
    return `${min}m ${s < 10 ? '0' : ''}${s}s`
  }
  return `${s}s`
}

function tickMotorRelogio() {
  const agora = getSynchronizedServerTime()

  // 1. Cronômetro da minha reserva ativa (se houver)
  if (minhaReservaExpiraEmMs.value) {
    const distReserva = minhaReservaExpiraEmMs.value - Date.now()
    if (distReserva > 0) {
      const segRestantes = Math.floor(distReserva / 1000)
      tempoReservaFormatado.value = formatarTempoReserva(segRestantes)
    } else {
      tempoReservaFormatado.value = ''
      minhaReservaExpiraEmMs.value = null
      minhaReservaToken.value = null
      minhaReservaSegundos.value = 0
    }
  } else {
    tempoReservaFormatado.value = ''
  }

  // 2. Atualização da mensagem de lote encerrado recente
  if (!temLoteComPrevisao.value && loteEncerradoRecente.value?.data_encerramento_iso) {
    const dataEncerrado = new Date(loteEncerradoRecente.value.data_encerramento_iso).getTime()
    const diffSegundos = Math.max(0, Math.floor((agora - dataEncerrado) / 1000))
    textoLoteEncerradoRecente.value = formatarTempoDecorrido(diffSegundos)
  } else {
    textoLoteEncerradoRecente.value = ''
  }

  // 2.1. Texto e contagem de encerramento quando o lote estiver aberto
  if (statusInfo.value.status_slug === 'aberto' || loteJaAbriuNaSessao.value) {
    const isoFechamento = lote.value?.data_fechamento_iso || dataFechamentoIso.value
    if (isoFechamento) {
      const targetClose = new Date(isoFechamento).getTime()
      const distClose = targetClose - agora
      if (distClose > 0) {
        const segClose = Math.floor(distClose / 1000)
        tempoParaFecharFormatado.value = formatarContagemFechamento(segClose)
        textoLoteEncerraEm.value = `O lote encerrará em ${tempoParaFecharFormatado.value}.`
      } else {
        tempoParaFecharFormatado.value = '00:00:00'
        textoLoteEncerraEm.value = 'O lote encerrará em instantes.'
      }
    } else {
      tempoParaFecharFormatado.value = ''
      textoLoteEncerraEm.value = 'O lote encerrará ao esgotarem as vagas disponíveis.'
    }
  } else {
    tempoParaFecharFormatado.value = ''
    textoLoteEncerraEm.value = ''
  }

  // 3. Cronômetro:
  // Se houver lote com previsão para abrir: contagem regressiva para abertura deste lote
  // Se não houver lote em previsão: sempre contagem para 30 de outubro às 12h
  let targetIso = null
  let isCountdownToLote = false

  if (temLoteComPrevisao.value && (lotePrevisaoAberturaIso.value || dataAberturaIso.value)) {
    targetIso = lotePrevisaoAberturaIso.value || dataAberturaIso.value
    isCountdownToLote = true
  } else if (hasLote.value && dataAberturaIso.value) {
    targetIso = dataAberturaIso.value
    isCountdownToLote = true
  } else {
    targetIso = dataFestaIso.value || '2026-10-30T12:00:00'
    isCountdownToLote = false
  }

  if (!targetIso) {
    dias.value = '00'
    horas.value = '00'
    minutos.value = '00'
    segundos.value = '00'
    apenasSegundos.value = '00'
    isHalo10s.value = false
    return
  }

  const targetDate = parseSaoPauloTimeToMs(targetIso)
  const distancia = targetDate - agora

  if (distancia <= 0) {
    // O relógio pode promover somente um lote agendado. Não pode reabrir
    // lotes pausados, encerrados ou esgotados após a resposta do servidor.
    if (isCountdownToLote && statusInfo.value.status_slug === 'agendado') {
      loteJaAbriuNaSessao.value = true
      statusInfo.value.status_slug = 'aberto'
      statusInfo.value.status_label = 'RESGATE LIBERADO'
      statusInfo.value.badge_class = 'bg-success'
      statusInfo.value.pode_resgatar = true
      statusInfo.value.segundos_para_abrir = 0
      if (!aberturaNotificada.value) {
        aberturaNotificada.value = true
      }
    }

    if (statusInfo.value.status_slug === 'aberto' && !confetesDisparados.value) {
      soltarConfetes()
    }
    isHalo10s.value = false
    isState1min.value = false
    isState10s.value = false
    return
  }

  // Se a abertura é no futuro, desativa loteJaAbriuNaSessao e reseta a trava de notificação
  loteJaAbriuNaSessao.value = false
  aberturaNotificada.value = false

  // Contagem regressiva precisa com Math.ceil para evitar o estado "00" no cronômetro
  const totalSegundos = Math.ceil(distancia / 1000)

  if (isCountdownToLote) {
    if ([30, 10, 5, 3].includes(totalSegundos) && !checkpointsExecutados[totalSegundos]) {
      checkpointsExecutados[totalSegundos] = true
      if ('vibrate' in navigator) navigator.vibrate(200)
    }

    if (totalSegundos <= 60 && totalSegundos >= 1) {
      isState1min.value = true
      isState10s.value = totalSegundos <= 10
      isHalo10s.value = false
      apenasSegundos.value = formatarTempo(totalSegundos)
      segundos.value = formatarTempo(totalSegundos)
      dias.value = '00'
      horas.value = '00'
      minutos.value = '00'
    } else {
      isState1min.value = false
      isState10s.value = false
      isHalo10s.value = false
    }

    isState10min.value = totalSegundos > 60 && totalSegundos <= 600
  } else {
    isHalo10s.value = false
    isState1min.value = false
    isState10s.value = false
    isState10min.value = false
  }

  if (!isState1min.value) {
    const d = Math.floor(distancia / (1000 * 60 * 60 * 24))
    const h = Math.floor((distancia % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
    const m = Math.floor((distancia % (1000 * 60 * 60)) / (1000 * 60))
    const s = Math.floor((distancia % (1000 * 60)) / 1000)

    dias.value = formatarTempo(d)
    horas.value = formatarTempo(h)
    minutos.value = formatarTempo(m)
    segundos.value = formatarTempo(s)
  }
}

// Desistir da vaga diretamente pela Home
async function desistirVagaPelaHome() {
  if (!minhaReservaToken.value) {
    showModalDesistirHome.value = false
    return
  }
  try {
    desistindoHome.value = true
    const formData = new FormData()
    formData.append('token_reserva', minhaReservaToken.value)
    await fetch('/api/resgate/desistir', {
      method: 'POST',
      body: formData
    })
    minhaReservaExpiraEmMs.value = null
    minhaReservaToken.value = null
    tempoReservaFormatado.value = ''
    try {
      Object.keys(localStorage).filter(k => k.startsWith('festa_resgate_draft_')).forEach(k => localStorage.removeItem(k))
    } catch(e) {}
    showModalDesistirHome.value = false
  } catch (e) {
    console.error('Erro ao desistir:', e)
  } finally {
    desistindoHome.value = false
  }
}

function handleVisibilityHome() {
  if (typeof document === 'undefined') return
  if (document.hidden) {
    if (renderInterval) {
      clearInterval(renderInterval)
      renderInterval = null
    }
  } else {
    if (!renderInterval) {
      tickMotorRelogio()
      renderInterval = setInterval(tickMotorRelogio, 100)
    }
  }
}

onMounted(() => {
  startSSE()
  renderInterval = setInterval(tickMotorRelogio, 100)

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibilityHome)
  }

  if (cometsCanvasRef.value) {
    canvasCtx = cometsCanvasRef.value.getContext('2d')
    resizeCanvas()
    window.addEventListener('resize', resizeCanvas)
    animFrameId = requestAnimationFrame(renderCometLoop)
  }
})

onUnmounted(() => {
  stopSSE()
  if (renderInterval) {
    clearInterval(renderInterval)
    renderInterval = null
  }
  if (spawnTimeout) {
    clearTimeout(spawnTimeout)
    spawnTimeout = null
  }
  if (animFrameId) {
    cancelAnimationFrame(animFrameId)
    animFrameId = null
  }
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', handleVisibilityHome)
  }
  window.removeEventListener('resize', resizeCanvas)
})

const temReservaAtiva = computed(() => {
  return Boolean(
    minhaReservaExpiraEmMs.value &&
    minhaReservaExpiraEmMs.value > Date.now()
  )
})

const isContagemFesta = computed(() => {
  if (loading.value) return false
  return (
    statusInfo.value.status_slug !== 'aberto' &&
    !loteJaAbriuNaSessao.value &&
    !temLoteComPrevisao.value &&
    (modoFesta.value || statusInfo.value.status_slug === 'festa')
  )
})

const tituloPrincipal = computed(() => {
  if (loading.value) {
    return 'Serv indoor 2026'
  }
  if (isContagemFesta.value) {
    return 'A festa iniciará em:'
  }
  return hasLote.value && lote.value ? lote.value.nome : 'Serv indoor 2026'
})

const isSqueezing = ref(false)

const deveExibirWhatsapp = computed(() => {
  if (loading.value) return false
  if (statusInfo.value.status_slug === 'aberto' || loteJaAbriuNaSessao.value) return false
  if (temReservaAtiva.value) return false
  if ((temLoteComPrevisao.value || !isContagemFesta.value) && (isState1min.value || loteJaAbriuNaSessao.value)) return false
  return true
})

watch(deveExibirWhatsapp, (newVal, oldVal) => {
  if (oldVal === true && newVal === false) {
    isSqueezing.value = true
    setTimeout(() => {
      isSqueezing.value = false
    }, 850)
  }
})

const cardClass = computed(() => {
  if (temReservaAtiva.value) return 'state-reserva-ativa'
  if (isHalo10s.value) return 'state-halo-10s'
  if (isState1min.value) return 'state-1min'
  if (isState10min.value) return 'state-10min'
  return ''
})
</script>


<template>
  <div class="hero-section">
    
    <!-- 1. LUZES AMBIENTES DINÂMICAS EM MOVIMENTO (MODO SERVINDOOR) -->
    <div class="servindoor-orbs-container">
      <div class="ambient-glow glow-magenta"></div>
      <div class="ambient-glow glow-cyan"></div>
      <div class="ambient-glow glow-gold"></div>
    </div>

    <div class="app-container">
      <div class="hero-center">
        <div :class="[cardClass, 'hero-card-clean']">

          <!-- Badge superior do status -->
          <div class="badge-wrapper">
            <span v-if="sseConnectionError" class="vip-badge bg-danger">
              <i class="bi bi-wifi-off me-1"></i> NÃO FOI POSSÍVEL CONECTAR AO SSE
            </span>
            <span v-else-if="loading" class="vip-badge badge-loading">
              <span class="dot-pulse-subtle"></span> SINCRONIZANDO...
            </span>
            <!-- SE O USUÁRIO ESTIVER COM RESERVA ATIVA, DESTACA IMEDIATAMENTE -->
            <span v-else-if="temReservaAtiva" class="vip-badge badge-reserva-ativa">
              <i class="bi bi-hourglass-split me-1 dot-pulse"></i> SUA VAGA ESTÁ RESERVADA ({{ tempoReservaFormatado }})
            </span>
            <span v-else-if="statusInfo.status_slug === 'aberto'" class="vip-badge bg-success">
              <i class="bi bi-circle-fill dot-pulse"></i> {{ statusInfo.status_label || 'RESGATE LIBERADO' }}
            </span>
            <span v-else-if="statusInfo.status_slug === 'agendado'" class="vip-badge bg-warning">
              <i class="bi bi-clock-history"></i> {{ statusInfo.status_label }}
            </span>
            <span v-else-if="statusInfo.status_slug === 'pausado'" class="vip-badge bg-secondary">
              <i class="bi bi-pause-circle-fill"></i> {{ statusInfo.status_label }}
            </span>
            <span v-else-if="statusInfo.status_slug === 'esgotado'" class="vip-badge bg-danger">
              <i class="bi bi-x-circle-fill"></i> {{ statusInfo.status_label }}
            </span>
            <span v-else-if="statusInfo.status_slug === 'encerrado'" class="vip-badge bg-secondary">
              <i class="bi bi-archive-fill"></i> {{ statusInfo.status_label }}
            </span>
            <span v-else class="vip-badge">
              <i class="bi bi-balloon-fill"></i> GRANDE EVENTO
            </span>
          </div>

          <!-- Marca principal da festa -->
          <div class="hero-logo-perspective">
            <img
              src="/images/logo_servindoor_sem-fundo.png?v=2026"
              alt="Serv indoor • A Festa do Servidor 2026"
              class="hero-logo-img logo-servindoor"
            />
          </div>

          <!-- Título Principal -->
          <h1 class="hero-title font-quattrocento">
            {{ tituloPrincipal }}
          </h1>

          <p v-if="!isContagemFesta && hasLote && lote && lote.secretaria_nome" class="hero-subtitle">
            <i class="bi bi-building me-1"></i> Exclusivo para servidores: <strong>{{ lote.secretaria_nome }}</strong>
          </p>

          <!-- BLOCO DE CRONÔMETRO DO LOTE / MODO FESTA (SE AGENDADO OU FESTA) -->
          <div
            v-if="!loading && !temReservaAtiva && (statusInfo.status_slug === 'agendado' || isContagemFesta)"
            class="clock-wrapper"
          >
            <div
              class="clock-digits"
              :class="{
                'clock-digits-fire-yellow': isState1min && !isState10s,
                'clock-digits-fire-red': isState10s
              }"
            >
              <!-- Caixa Dias -->
              <div v-if="!isState1min && dias !== '00'" class="digit-box">
                <span class="digit-number">{{ dias }}</span>
                <span class="digit-label">Dias</span>
              </div>
              <span v-if="!isState1min && dias !== '00'" class="digit-sep">:</span>

              <!-- Caixa Horas -->
              <div v-if="!isState1min && horas !== '00'" class="digit-box">
                <span class="digit-number">{{ horas }}</span>
                <span class="digit-label">Horas</span>
              </div>
              <span v-if="!isState1min && horas !== '00'" class="digit-sep">:</span>

              <!-- Caixa Minutos -->
              <div v-if="!isState1min && minutos !== '00'" class="digit-box">
                <span class="digit-number">{{ minutos }}</span>
                <span class="digit-label">Min</span>
              </div>
              <span v-if="!isState1min && minutos !== '00'" class="digit-sep">:</span>

              <!-- Caixa Segundos (A ÚNICA EXIBIDA QUANDO <= 60s) -->
              <div
                class="digit-box digit-box-seconds"
                :class="{
                  'box-fire-yellow': isState1min && !isState10s,
                  'box-fire-red': isState10s
                }"
              >
                <!-- Animação de Fogo Realista (Amarelo nos 60s, Vermelho Intenso nos últimos 10s) -->
                <div v-if="isState1min" class="flame-fx-container" :class="{ 'flame-fx-red': isState10s }">
                  <div class="flame-tongue tongue-center"></div>
                  <div class="flame-tongue tongue-left"></div>
                  <div class="flame-tongue tongue-right"></div>
                  <div class="flame-particles">
                    <span class="ember ember-1"></span>
                    <span class="ember ember-2"></span>
                    <span class="ember ember-3"></span>
                    <span class="ember ember-4"></span>
                  </div>
                </div>

                <span class="digit-number font-outfit">{{ isState1min ? apenasSegundos : segundos }}</span>
                <span class="digit-label">{{ isState1min ? 'SEGUNDOS' : 'Seg' }}</span>
              </div>
            </div>

          </div>

          <!-- Botões de Ação Dinâmicos -->
          <div class="action-buttons-wrapper" :class="{ 'has-split-buttons': deveExibirWhatsapp }">
            <div class="main-action-slot">
              <!-- 0. Skeleton Neutro durante Carregamento -->
              <div v-if="loading" class="btn-vip-skeleton">
                <span class="skeleton-shimmer"></span>
              </div>

              <!-- 1. Botão de Continuação de Reserva Ativa -->
              <div v-else-if="temReservaAtiva && (lote || lotePrevisaoId)" class="reserva-action-container">
              <router-link
                :to="'/resgate/' + (lote?.id || lotePrevisaoId)"
                class="btn-vip-mega btn-reserva-continua font-outfit"
              >
                <span>Continuar Meu Resgate</span>
                <span v-if="tempoReservaFormatado" class="btn-timer-badge font-outfit">
                  {{ tempoReservaFormatado }}
                </span>
                <i class="bi bi-arrow-right-circle-fill"></i>
              </router-link>

              <button
                v-if="minhaReservaToken"
                type="button"
                class="btn-desistir-home-link"
                @click="showModalDesistirHome = true"
              >
                <i class="bi bi-x-circle me-1"></i> Desistir da vaga reservada
              </button>
            </div>

            <!-- 2. Botão de Resgate Aberto -->
            <router-link
              v-else-if="statusInfo.status_slug === 'aberto' && (lote || lotePrevisaoId)"
              :to="'/resgate/' + (lote?.id || lotePrevisaoId)"
              class="btn-vip-mega font-outfit"
            >
              <span>Resgatar Ingresso</span>
              <i class="bi bi-arrow-right-circle-fill"></i>
            </router-link>

            <!-- 3. Botão de Vaga Reservada em Espera -->
            <router-link
              v-else-if="statusInfo.status_slug === 'reservado' && (lote || lotePrevisaoId)"
              :to="'/resgate/' + (lote?.id || lotePrevisaoId)"
              class="btn-vip-mega btn-reserva-continua font-outfit"
            >
              <span>Tentar Vaga em Liberação</span>
              <i class="bi bi-arrow-repeat"></i>
            </router-link>

            <!-- 4. Lote Pausado -->
            <div v-else-if="statusInfo.status_slug === 'pausado'" class="btn-vip-disabled font-outfit">
              <i class="bi bi-pause-circle"></i> Lote Pausado pela Organização
            </div>

            <!-- 5. Lote Encerrado -->
            <div v-else-if="statusInfo.status_slug === 'encerrado'" class="btn-vip-disabled font-outfit">
              <i class="bi bi-clock-history"></i> Lote Encerrado
            </div>

            <!-- 6. Lote Esgotado -->
            <div v-else-if="statusInfo.status_slug === 'esgotado'" class="btn-vip-disabled font-outfit">
              <i class="bi bi-x-circle"></i> Ingressos Esgotados
            </div>

            <!-- 7. Modo Agendado / Contagem Festa -->
            <div v-else-if="statusInfo.status_slug === 'agendado' || modoFesta" class="btn-vip-disabled font-outfit">
              <i class="bi bi-stars"></i> Em breve...
            </div>
          </div>

            <!-- Botão do Canal do WhatsApp -->
            <a
              v-if="deveExibirWhatsapp || isSqueezing"
              href="https://whatsapp.com/channel/0029VbDEW8KBFLgMTmjdco0C"
              target="_blank"
              rel="noopener noreferrer"
              class="btn-whatsapp-channel font-outfit"
              :class="{ 'btn-whatsapp-squeezed': isSqueezing || !deveExibirWhatsapp }"
              title="Acessar Canal Oficial no WhatsApp"
            >
              <i class="bi bi-whatsapp whatsapp-icon"></i>
              <span class="whatsapp-text">Canal do WhatsApp</span>
              <i class="bi bi-box-arrow-up-right whatsapp-ext-icon"></i>
            </a>
          </div>



          <!-- Quando o lote estiver aberto: texto em quanto tempo o lote encerrará -->
          <div
            v-if="statusInfo.status_slug === 'aberto' && textoLoteEncerraEm"
            class="lote-encerrado-aviso-subtle"
          >
            <i class="bi bi-clock-history text-danger me-1"></i>
            <span>{{ textoLoteEncerraEm }}</span>
          </div>

          <!-- Mensagem discreta de lote encerrado recente abaixo do botão -->
          <div v-else-if="textoLoteEncerradoRecente" class="lote-encerrado-aviso-subtle">
            <i class="bi bi-info-circle me-1 opacity-50"></i>
            <span>{{ textoLoteEncerradoRecente }}</span>
          </div>




          <div v-else-if="modoFesta" class="chips-footer">
            <span class="info-chip">
              <i class="bi bi-calendar2-check-fill text-primary"></i>
              <span>Data Oficial: <strong class="text-white">30/10/2026</strong></span>
            </span>
            <span class="info-chip">
              <i class="bi bi-clock-fill text-warning"></i>
              <span>Horário: <strong class="text-white">12:00</strong></span>
            </span>
          </div>

          <SponsorLogos />

          <!-- Botão de Dúvidas Frequentes -->
          <div class="faq-home-trigger-wrap">
            <button
              type="button"
              class="btn-faq-home font-outfit"
              @click="showFaqModal = true"
            >
              <i class="bi bi-question-circle-fill btn-faq-icon"></i>
              <span>Dúvidas Frequentes (FAQ)</span>
              <span v-if="isAdminGeral" class="badge-faq-admin font-outfit">
                <i class="bi bi-pencil-fill me-1"></i> Admin
              </span>
            </button>
          </div>

        </div>
      </div>
    </div>

    <!-- Modal: Confirmar Desistência da Vaga na Home -->
    <Modal
      :show="showModalDesistirHome"
      title="Desistir da Vaga Reservada?"
      icon="bi-exclamation-triangle"
      icon-color="text-warning"
      :max-width="'460px'"
      @close="showModalDesistirHome = false"
    >
      <div class="text-center py-2">
        <p class="text-white mb-2">
          Deseja liberar sua vaga reservada de volta para o lote?
        </p>
        <p class="text-muted small">
          Outro servidor poderá resgatá-la imediatamente.
        </p>
      </div>
      <template #footer>
        <div class="d-flex gap-2 w-100">
          <button type="button" class="btn-secondary flex-1" @click="showModalDesistirHome = false">
            Manter Minha Vaga
          </button>
          <button type="button" class="btn-danger flex-1" :disabled="desistindoHome" @click="desistirVagaPelaHome">
            <span v-if="desistindoHome" class="spinner-border spinner-border-sm me-1"></span>
            <span>{{ desistindoHome ? 'Liberando...' : 'Sim, Desistir' }}</span>
          </button>
        </div>
      </template>
    </Modal>

    <!-- Modal de Perguntas Frequentes (FAQ) -->
    <FaqModal v-model="showFaqModal" />



  </div>
</template>

<style scoped>
.hero-section {
  min-height: calc(100vh - 72px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 30px 0 50px;
  position: relative;
  overflow: hidden;
  background: transparent;
}
</style>
