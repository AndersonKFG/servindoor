<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import confetti from 'canvas-confetti'
import { useServerTime } from '../composables/useServerTime'
import { useLoteStatus } from '../composables/useLoteStatus'
import Modal from '../components/Modal.vue'

const router = useRouter()
const { serverClockOffsetMs, calibrarRelogioComServidor, getSynchronizedServerTime } = useServerTime()
const {
  loading,
  hasLote,
  modoFesta,
  lote,
  statusInfo,
  reservasAtivas,
  vagasDisponiveis,
  minhaReservaSegundos,
  minhaReservaExpiraEmMs,
  minhaReservaToken,
  dataAberturaIso,
  dataFestaIso,
  dataFestaFormatada,
  fetchLiveStatus,
  startPolling,
  stopPolling
} = useLoteStatus()

const showModalEmResgate = ref(false)
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
const isState10min = ref(false)

// Estados específicos da Minha Reserva Ativa
const tempoReservaFormatado = ref('')

// Controle de Patrocinador Master (Alternância a cada 15 segundos)
const sponsorIndex = ref(0) // 0 = Servindoor Oficial, 1 = Bradesco
const isSpinning = ref(false)
const isBradescoTheme = computed(() => sponsorIndex.value === 1)
let sponsorTimer = null

// ============================================================================
// CONTINUOUS RIBBON COMET ENGINE (TRAJETÓRIA COMPLETA DE FORA A FORA DA TELA)
// ============================================================================
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

function alternarSponsor() {
  isSpinning.value = true
  setTimeout(() => {
    sponsorIndex.value = sponsorIndex.value === 0 ? 1 : 0
  }, 400)
  setTimeout(() => {
    isSpinning.value = false
  }, 800)
}

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
    const distReserva = minhaReservaExpiraEmMs.value - agora
    if (distReserva > 0) {
      const segRestantes = Math.floor(distReserva / 1000)
      tempoReservaFormatado.value = formatarTempoReserva(segRestantes)
    } else {
      tempoReservaFormatado.value = ''
    }
  } else {
    tempoReservaFormatado.value = ''
  }

  // 2. Cronômetro do Lote ou Modo Festa
  let targetIso = dataAberturaIso.value
  if (modoFesta.value && dataFestaIso.value) {
    targetIso = dataFestaIso.value
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

  const targetDate = new Date(targetIso).getTime()
  const distancia = targetDate - agora

  if (distancia <= 0) {
    // Se o lote estava agendado e o tempo de abertura zerou, transiciona instantaneamente no cliente
    if (statusInfo.value.status_slug === 'agendado' && !modoFesta.value) {
      statusInfo.value.status_slug = 'aberto'
      statusInfo.value.status_label = 'ABERTO'
      statusInfo.value.badge_class = 'bg-success'
      // Sincroniza em segundo plano com o servidor imediatamente, sem esperar os 1.5s do polling
      fetchLiveStatus()
    }

    if (statusInfo.value.status_slug === 'aberto' && !confetesDisparados.value) {
      soltarConfetes()
    }
    isHalo10s.value = false
    isState1min.value = false
    dias.value = '00'
    horas.value = '00'
    minutos.value = '00'
    segundos.value = '00'
    apenasSegundos.value = '00'
    return
  }

  const totalSegundos = Math.floor(distancia / 1000)

  if ([30, 10, 5, 3].includes(totalSegundos) && !checkpointsExecutados[totalSegundos]) {
    checkpointsExecutados[totalSegundos] = true
    if ('vibrate' in navigator) navigator.vibrate(200)
  }

  if (totalSegundos === 0 && !confetesDisparados.value) {
    soltarConfetes()
  }

  if (statusInfo.value.status_slug === 'agendado' && totalSegundos <= 10) {
    isHalo10s.value = true
    isState1min.value = true
    apenasSegundos.value = formatarTempo(totalSegundos)
    return
  } else {
    isHalo10s.value = false
  }

  if (statusInfo.value.status_slug === 'agendado') {
    isState1min.value = totalSegundos <= 60
    isState10min.value = totalSegundos > 60 && totalSegundos <= 600
  } else {
    isState1min.value = false
    isState10min.value = false
  }

  const d = Math.floor(distancia / (1000 * 60 * 60 * 24))
  const h = Math.floor((distancia % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
  const m = Math.floor((distancia % (1000 * 60 * 60)) / (1000 * 60))
  const s = Math.floor((distancia % (1000 * 60)) / 1000)

  dias.value = formatarTempo(d)
  horas.value = formatarTempo(h)
  minutos.value = formatarTempo(m)
  segundos.value = formatarTempo(s)
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

onMounted(async () => {
  await calibrarRelogioComServidor()
  startPolling(1500)
  renderInterval = setInterval(tickMotorRelogio, 100)

  sponsorTimer = setInterval(() => {
    if (!document.hidden) {
      alternarSponsor()
    }
  }, 15000)

  if (cometsCanvasRef.value) {
    canvasCtx = cometsCanvasRef.value.getContext('2d')
    resizeCanvas()
    window.addEventListener('resize', resizeCanvas)
    animFrameId = requestAnimationFrame(renderCometLoop)
  }
})

onUnmounted(() => {
  stopPolling()
  if (renderInterval) {
    clearInterval(renderInterval)
    renderInterval = null
  }
  if (sponsorTimer) {
    clearInterval(sponsorTimer)
    sponsorTimer = null
  }
  if (spawnTimeout) {
    clearTimeout(spawnTimeout)
    spawnTimeout = null
  }
  if (animFrameId) {
    cancelAnimationFrame(animFrameId)
    animFrameId = null
  }
  window.removeEventListener('resize', resizeCanvas)
})

const temReservaAtiva = computed(() => {
  return minhaReservaExpiraEmMs.value && minhaReservaExpiraEmMs.value > getSynchronizedServerTime()
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
  <div :class="['hero-section', { 'theme-bradesco': isBradescoTheme }]">
    
    <!-- 1. LUZES AMBIENTES DINÂMICAS EM MOVIMENTO (MODO SERVINDOOR) -->
    <div class="servindoor-orbs-container" :class="{ 'hidden-orbs': isBradescoTheme }">
      <div class="ambient-glow glow-magenta"></div>
      <div class="ambient-glow glow-cyan"></div>
      <div class="ambient-glow glow-gold"></div>
    </div>

    <!-- 2. CANVAS ENGINE DE COMETAS FLUIDOS E LISOS (MODO BRADESCO MASTER) -->
    <canvas
      ref="cometsCanvasRef"
      class="bradesco-comets-canvas"
      :class="{ 'active-canvas': isBradescoTheme }"
    ></canvas>

    <div class="app-container">
      <div class="hero-center">
        <div :class="[cardClass, 'hero-card-clean']">

          <!-- Badge Superior do Status / Patrocinador Master -->
          <div class="badge-wrapper">
            <!-- SE O USUÁRIO ESTIVER COM RESERVA ATIVA, DESTACA IMEDIATAMENTE -->
            <span v-if="temReservaAtiva" class="vip-badge badge-reserva-ativa">
              <i class="bi bi-hourglass-split me-1 dot-pulse"></i> SUA VAGA ESTÁ RESERVADA ({{ tempoReservaFormatado }})
            </span>
            <span v-else-if="isBradescoTheme" class="vip-badge badge-bradesco-master">
              <i class="bi bi-star-fill text-gold me-1"></i> PATROCINADOR MASTER • BRADESCO
            </span>
            <span v-else-if="statusInfo.status_slug === 'aberto'" class="vip-badge bg-success">
              <i class="bi bi-circle-fill dot-pulse"></i> {{ statusInfo.status_label }}
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

          <!-- Container 3D Flip da Logo (Servindoor / Bradesco Master) -->
          <div
            class="hero-logo-perspective"
            title="Clique para alternar o patrocinador master"
            @click="alternarSponsor"
          >
            <div class="hero-logo-card" :class="{ 'spinning': isSpinning }">
              <!-- Logo 1: Servindoor -->
              <img
                v-show="sponsorIndex === 0"
                src="/images/logo_servindoor_sem-fundo.png?v=2026"
                alt="Servindoor • A Festa do Servidor 2026"
                class="hero-logo-img logo-servindoor"
              />
              <!-- Logo 2: Bradesco -->
              <img
                v-show="sponsorIndex === 1"
                src="/images/logo_bradesco_sem-fundo.png?v=2026"
                alt="Bradesco • Patrocinador Master"
                class="hero-logo-img logo-bradesco"
              />
            </div>
          </div>

          <!-- Título Principal -->
          <h1 class="hero-title font-outfit">
            {{ hasLote && lote ? lote.nome : 'Servindoor 2026' }}
          </h1>

          <p v-if="hasLote && lote && lote.secretaria_nome" class="hero-subtitle">
            <i class="bi bi-building me-1"></i> Exclusivo para servidores: <strong>{{ lote.secretaria_nome }}</strong>
          </p>

          <!-- BLOCO DE CRONÔMETRO DO LOTE / MODO FESTA (SE AGENDADO OU FESTA) -->
          <div v-if="!temReservaAtiva && (statusInfo.status_slug === 'agendado' || modoFesta || !hasLote)" class="clock-wrapper">
            <div v-if="!isHalo10s" class="clock-digits">
              <div class="digit-box">
                <span class="digit-number">{{ dias }}</span>
                <span class="digit-label">Dias</span>
              </div>
              <span class="digit-sep">:</span>
              <div class="digit-box">
                <span class="digit-number">{{ horas }}</span>
                <span class="digit-label">Horas</span>
              </div>
              <span class="digit-sep">:</span>
              <div class="digit-box">
                <span class="digit-number">{{ minutos }}</span>
                <span class="digit-label">Min</span>
              </div>
              <span class="digit-sep">:</span>
              <div class="digit-box">
                <span class="digit-number">{{ segundos }}</span>
                <span class="digit-label">Seg</span>
              </div>
            </div>

            <!-- Modo Halo 10 Segundos -->
            <div v-else class="halo-wrapper">
              <div class="halo-circle">
                <span class="halo-number font-outfit">{{ apenasSegundos }}</span>
                <span class="halo-label">SEGUNDOS</span>
              </div>
            </div>
          </div>

          <!-- Botões de Ação Dinâmicos -->
          <div class="action-buttons-wrapper">
            <!-- 1. Botão de Continuação de Reserva Ativa -->
            <div v-if="temReservaAtiva && lote" class="reserva-action-container">
              <router-link
                :to="'/resgate/' + lote.id"
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
              v-else-if="statusInfo.status_slug === 'aberto' && lote"
              :to="'/resgate/' + lote.id"
              class="btn-vip-mega font-outfit"
            >
              <span>Resgatar Ingresso</span>
              <i class="bi bi-arrow-right-circle-fill"></i>
            </router-link>

            <!-- 3. Botão de Vaga Reservada em Espera -->
            <router-link
              v-else-if="statusInfo.status_slug === 'reservado' && lote"
              :to="'/resgate/' + lote.id"
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
              <i class="bi bi-stars"></i> Liberação em breve! Fique atento ao cronômetro
            </div>
          </div>

          <!-- Rodapé com Chips Informativos -->
          <div v-if="hasLote && lote" class="chips-footer">
            <span class="info-chip">
              <i class="bi bi-ticket-perforated text-success"></i>
              <span>Vagas Livres: <strong class="text-white">{{ vagasDisponiveis }}</strong></span>
            </span>

            <button type="button" class="info-chip-btn" @click="showModalEmResgate = true">
              <i class="bi bi-hourglass-split text-warning"></i>
              <span>Em Resgate: <strong class="text-white">{{ reservasAtivas }}</strong></span>
              <i class="bi bi-question-circle-fill text-warning opacity-75"></i>
            </button>

            <span class="info-chip">
              <i class="bi bi-people-fill text-primary"></i>
              <span>Garantidos: <strong class="text-white">{{ lote.quantidade_resgatada }}</strong> / {{ lote.quantidade_total }}</span>
            </span>

            <span v-if="lote.data_fechamento_formatada" class="info-chip">
              <i class="bi bi-clock-history text-danger"></i>
              <span>Encerra: <strong class="text-white">{{ lote.data_fechamento_formatada }}</strong></span>
            </span>
          </div>

          <div v-else-if="modoFesta" class="chips-footer">
            <span class="info-chip">
              <i class="bi bi-calendar2-check-fill text-primary"></i>
              <span>Data Oficial: <strong class="text-white">30/10/2026</strong></span>
            </span>
            <span class="info-chip">
              <i class="bi bi-clock-fill text-warning"></i>
              <span>Horário: <strong class="text-white">14:00</strong></span>
            </span>
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

    <!-- Modal Informativo: Vagas em Resgate -->
    <Modal
      :show="showModalEmResgate"
      title="Como funcionam as Vagas em Resgate?"
      icon="bi-hourglass-split"
      @close="showModalEmResgate = false"
    >
      <div class="modal-info-box">
        <div class="modal-info-header">
          <i class="bi bi-shield-check text-warning display-icon"></i>
          <div>
            <strong>Garantia de 5 minutos</strong>
            <p class="modal-desc">Quando um servidor clica para resgatar, a vaga fica temporariamente bloqueada para ele preencher os dados.</p>
          </div>
        </div>
      </div>

      <div class="modal-rules-list">
        <div class="rule-item">
          <i class="bi bi-check-circle-fill text-success"></i>
          <span>Se o servidor concluir o resgate com foto dentro do prazo, o ingresso é <strong>garantido</strong>.</span>
        </div>
        <div class="rule-item">
          <i class="bi bi-arrow-repeat text-warning"></i>
          <span>Se o tempo expirar sem conclusão, a vaga volta <strong>imediatamente</strong> para o lote.</span>
        </div>
      </div>

      <template #footer>
        <button type="button" class="btn-primary w-100 font-outfit" @click="showModalEmResgate = false">
          Entendi, continuar acompanhando
        </button>
      </template>
    </Modal>

  </div>
</template>

<style scoped>
.hero-section {
  min-height: calc(100vh - 120px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 0 60px;
  position: relative;
  overflow: hidden;
  background: transparent;
  transition: background 1s ease;
}

/* ========================================================================== */
/* 1. LUZES AMBIENTES DINÂMICAS EM MOVIMENTO (MODO SERVINDOOR)               */
/* ========================================================================== */
.servindoor-orbs-container {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
  transition: opacity 1s cubic-bezier(0.4, 0, 0.2, 1);
  opacity: 1;
}

.servindoor-orbs-container.hidden-orbs {
  opacity: 0;
}

.ambient-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(110px);
  pointer-events: none;
}

.glow-magenta {
  width: 500px;
  height: 500px;
  background: var(--serv-magenta);
  top: -80px;
  left: 5%;
  opacity: 0.32;
  animation: floatMagenta 14s infinite alternate ease-in-out;
}

@keyframes floatMagenta {
  0% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(70px, 60px) scale(1.15); }
  66% { transform: translate(-40px, 90px) scale(0.9); }
  100% { transform: translate(50px, -30px) scale(1.08); }
}

.glow-cyan {
  width: 480px;
  height: 480px;
  background: var(--serv-cyan);
  bottom: -60px;
  right: 5%;
  opacity: 0.28;
  animation: floatCyan 16s infinite alternate ease-in-out;
}

@keyframes floatCyan {
  0% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(-60px, -50px) scale(1.18); }
  66% { transform: translate(50px, -70px) scale(0.88); }
  100% { transform: translate(-40px, 40px) scale(1.12); }
}

.glow-gold {
  width: 320px;
  height: 320px;
  background: var(--serv-amber);
  top: 40%;
  left: 45%;
  opacity: 0.15;
  animation: floatGold 18s infinite alternate ease-in-out;
}

@keyframes floatGold {
  0% { transform: translate(-50%, -50%) scale(0.9); }
  50% { transform: translate(-30%, -60%) scale(1.2); }
  100% { transform: translate(-60%, -40%) scale(1); }
}

/* ========================================================================== */
/* 2. CANVAS DE COMETAS FLUIDOS A 60FPS (MODO BRADESCO MASTER)               */
/* ========================================================================== */
.bradesco-comets-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  opacity: 0;
  transition: opacity 1s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 1;
}

.bradesco-comets-canvas.active-canvas {
  opacity: 1;
}

/* ========================================================================== */
/* TEMA BRADESCO MASTER                                                       */
/* ========================================================================== */
.theme-bradesco .hero-title {
  background: linear-gradient(135deg, #ffffff 0%, #ff8095 50%, #ff1744 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.theme-bradesco .btn-vip-mega {
  background: linear-gradient(135deg, #cc092f 0%, #ff1744 50%, #990000 100%) !important;
  box-shadow: 0 12px 35px rgba(255, 23, 68, 0.6) !important;
  border-color: rgba(255, 255, 255, 0.35) !important;
}

.theme-bradesco .btn-vip-mega:hover {
  background: linear-gradient(135deg, #e6002e 0%, #ff2d55 50%, #b30000 100%) !important;
  box-shadow: 0 18px 50px rgba(255, 23, 68, 0.8) !important;
}

.badge-bradesco-master {
  background: linear-gradient(135deg, rgba(204, 9, 47, 0.5) 0%, rgba(255, 23, 68, 0.3) 100%) !important;
  border: 1px solid rgba(255, 23, 68, 0.75) !important;
  color: #ffffff !important;
  box-shadow: 0 0 18px rgba(255, 23, 68, 0.5);
  animation: pulseGlow 2s infinite ease-in-out;
}

@keyframes pulseGlow {
  0% { transform: scale(1); box-shadow: 0 0 14px rgba(255, 23, 68, 0.4); }
  50% { transform: scale(1.04); box-shadow: 0 0 24px rgba(255, 23, 68, 0.75); }
  100% { transform: scale(1); box-shadow: 0 0 14px rgba(255, 23, 68, 0.4); }
}

/* ========================================================================== */
/* CRONÔMETRO DE MINHA RESERVA ATIVA NA HOME                                 */
/* ========================================================================== */
.badge-reserva-ativa {
  background: linear-gradient(135deg, #d97706 0%, #f59e0b 100%) !important;
  color: #ffffff !important;
  border: 1px solid rgba(255, 255, 255, 0.4) !important;
  box-shadow: 0 0 20px rgba(245, 158, 11, 0.6) !important;
  animation: pulseReserva 1.5s infinite ease-in-out;
}

@keyframes pulseReserva {
  0% { transform: scale(1); box-shadow: 0 0 14px rgba(245, 158, 11, 0.4); }
  50% { transform: scale(1.04); box-shadow: 0 0 24px rgba(245, 158, 11, 0.8); }
  100% { transform: scale(1); box-shadow: 0 0 14px rgba(245, 158, 11, 0.4); }
}

.reserva-action-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.btn-desistir-home-link {
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 0.84rem;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.2s ease;
  display: inline-flex;
  align-items: center;
}

.btn-desistir-home-link:hover {
  color: #f87171;
  text-decoration: underline;
}

/* ========================================================================== */
/* HERO CENTER & LAYOUT LIMPO                                                 */
/* ========================================================================== */
.hero-center {
  max-width: 680px;
  margin: 0 auto;
  position: relative;
  z-index: 10;
}

.hero-card-clean {
  padding: 30px 16px;
  text-align: center;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

.badge-wrapper {
  display: flex;
  justify-content: center;
  margin-bottom: 14px;
}

/* 3D FLIP DA LOGO */
.hero-logo-perspective {
  perspective: 1200px;
  display: flex;
  justify-content: center;
  margin: 6px 0 18px;
  cursor: pointer;
  user-select: none;
}

.hero-logo-card {
  transition: transform 0.8s cubic-bezier(0.34, 1.56, 0.64, 1);
  transform-style: preserve-3d;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hero-logo-card.spinning {
  transform: rotateY(360deg) scale(1.08);
}

.hero-logo-img {
  max-height: 130px;
  max-width: 90%;
  object-fit: contain;
  transition: filter 0.5s ease, transform 0.3s ease;
}

.logo-servindoor {
  filter: drop-shadow(0 8px 25px rgba(217, 70, 239, 0.45));
}

.logo-bradesco {
  filter: drop-shadow(0 8px 25px rgba(255, 23, 68, 0.65));
}

.hero-logo-card:hover .hero-logo-img {
  transform: scale(1.03);
}

.hero-title {
  font-size: clamp(2rem, 5vw, 2.7rem);
  font-weight: 900;
  color: #ffffff;
  margin-bottom: 6px;
  line-height: 1.15;
  transition: all 0.8s ease;
}

.hero-subtitle {
  color: var(--text-muted);
  font-size: 0.92rem;
  margin-bottom: 12px;
}

/* HALO MODE 10s */
.halo-wrapper {
  display: flex;
  justify-content: center;
  margin: 20px 0;
}

.halo-circle {
  width: 140px;
  height: 140px;
  border-radius: 50%;
  border: 4px solid #ef4444;
  box-shadow: 0 0 40px rgba(239, 68, 68, 0.6);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  animation: haloPulse 1s infinite;
}

@keyframes haloPulse {
  0% { transform: scale(1); box-shadow: 0 0 30px rgba(239, 68, 68, 0.4); }
  50% { transform: scale(1.06); box-shadow: 0 0 50px rgba(239, 68, 68, 0.8); }
  100% { transform: scale(1); box-shadow: 0 0 30px rgba(239, 68, 68, 0.4); }
}

.halo-number {
  font-size: 3.8rem;
  font-weight: 900;
  color: #ffffff;
  line-height: 1;
}

.halo-label {
  font-size: 0.65rem;
  font-weight: 800;
  color: #fca5a5;
  letter-spacing: 1px;
}

.action-buttons-wrapper {
  margin-top: 28px;
}

.chips-footer {
  display: flex;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 28px;
  padding-top: 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.modal-info-box {
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 14px;
  padding: 16px;
  margin-bottom: 20px;
}

.modal-info-header {
  display: flex;
  gap: 14px;
  align-items: center;
}

.display-icon {
  font-size: 2rem;
}

.modal-desc {
  font-size: 0.85rem;
  color: #e2e8f0;
  margin-top: 4px;
}

.modal-rules-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
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

.text-gold { color: #fbbf24 !important; }
.w-100 { width: 100%; }
.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.text-white { color: #ffffff; }
.text-warning { color: var(--warning-color); }
.text-success { color: var(--success-color); }
.text-danger { color: var(--danger-color); }
.text-primary { color: var(--primary-accent); }
.opacity-75 { opacity: 0.75; }
.flex-1 { flex: 1; }

@media (max-width: 576px) {
  .hero-logo-img {
    max-height: 90px;
  }
  .hero-title {
    font-size: 1.75rem;
  }
}
</style>
