<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import confetti from 'canvas-confetti'

const loading = ref(true)
const status = ref('idle')
const premiosRodada = ref([])
const ultimosGanhadores = ref([])
const ultimosGanhadoresStaged = ref([])
const ultimaRodadaConcluidaTs = ref(0)
const candidatosAnimacao = ref([])

const isAnimando = ref(false)
const progresso10s = ref(0)
const candidatosSorteando = ref({})
const imgErrors = ref({})
const avatarErrors = ref({})
const focoIndex = ref(0)
const progressoTransicao = ref(0)
const exibindoHistoricoCompleto = ref(false)
const transicaoPausada = ref(false)
const sidebarOculta = ref(false)
const painelRecentesOculto = computed(() => sidebarOculta.value || status.value === 'sorteando')

const recentListRef = ref(null)
let isHoveringSidebar = false
let autoScrollAnimId = null

let pollingInterval = null
let animationFrameId = null
let spotlightInterval = null
let spotlightStartTime = 0
let roletaStartTime = null
const DURACAO_TRANSICAO_MS = 5000

const focoItem = computed(() => {
  const lista = exibindoHistoricoCompleto.value
    ? ultimosGanhadores.value.map((item) => ({
        item_id: item.ganhador_id,
        categoria: item.categoria?.startsWith('Categoria 1') ? 'categoria_1' : 'categoria_2',
        eixo_nome: item.secretaria_nome,
        premio_nome: item.premio_nome,
        premio_foto: item.premio_foto,
        ganhador: {
          ganhador_id: item.ganhador_id,
          nome: item.servidor_nome,
          cpf: item.servidor_cpf,
          foto_url: item.servidor_foto,
          secretaria: item.secretaria_nome
        }
      }))
    : premiosRodada.value
  if (lista.length === 0) return null
  const idx = Math.max(0, Math.min(lista.length - 1, focoIndex.value))
  return lista[idx]
})

async function fetchLiveTelao() {
  try {
    const res = await fetch('/api/sorteios/live-telao', { cache: 'no-store' })
    if (!res.ok) return
    const data = await res.json()

    const novoStatus = data.status || 'idle'
    const statusAnterior = status.value

    premiosRodada.value = data.premios_rodada || []
    ultimosGanhadoresStaged.value = data.ultimos_ganhadores || []
    candidatosAnimacao.value = data.candidatos_animacao || []

    // Atualiza ultimosGanhadores apenas se não estiver no meio da animação
    if (!isAnimando.value && novoStatus !== 'sorteando') {
      ultimosGanhadores.value = ultimosGanhadoresStaged.value
    }

    const rodadaTs = data.timestamp_inicio || 0

    if (novoStatus === 'sorteando') {
      // Evita o glitch: se esta mesma rodada já foi finalizada neste navegador, não reinicia a animação!
      if (rodadaTs && rodadaTs === ultimaRodadaConcluidaTs.value) {
        status.value = 'finalizado'
      } else if (!isAnimando.value) {
        status.value = 'sorteando'
        const duracaoTotal = data.duracao_ms || 10000
        const decorrido = rodadaTs ? Math.max(0, Date.now() - rodadaTs) : 0
        const tempoRestante = Math.max(1000, duracaoTotal - decorrido)
        iniciarAnimacaoRoletaLocal(tempoRestante, rodadaTs)
      }
    } else if (novoStatus === 'finalizado') {
      if (isAnimando.value) {
        // Aguarda o término da animação local
      } else {
        status.value = 'finalizado'
        ultimosGanhadores.value = ultimosGanhadoresStaged.value
        if (statusAnterior !== 'finalizado') iniciarSpotlight()
      }
    } else if (novoStatus === 'idle') {
      if (statusAnterior !== 'idle' || isAnimando.value) pararAnimacao()
      ultimaRodadaConcluidaTs.value = 0
      status.value = 'idle'
      ultimosGanhadores.value = ultimosGanhadoresStaged.value
    } else {
      status.value = novoStatus
    }

    loading.value = false
  } catch (err) {
    console.warn('Erro atualizando telão:', err)
  }
}

function iniciarAnimacaoRoletaLocal(duracao = 10000, rodadaTs = 0) {
  isAnimando.value = true
  pararSpotlight()
  roletaStartTime = Date.now()
  progresso10s.value = 0

  const listaCandidatos = candidatosAnimacao.value.length > 0 ? candidatosAnimacao.value : [
    { id: 1, nome: 'Servidor Municipal', foto_url: null, secretaria: 'Prefeitura' }
  ]

  function tickRoleta() {
    const now = Date.now()
    const elapsed = now - roletaStartTime
    const progressRatio = Math.min(1, elapsed / duracao)
    progresso10s.value = progressRatio * 100

    if (elapsed < duracao && isAnimando.value) {
      premiosRodada.value.forEach((item) => {
        const idxRand = Math.floor(Math.random() * listaCandidatos.length)
        candidatosSorteando.value[item.item_id] = listaCandidatos[idxRand]
      })

      let delay = 35
      const restante = duracao - elapsed
      if (restante < 3500) {
        const fator = 1 - (restante / 3500)
        delay = 35 + Math.pow(fator, 2) * 230
      }

      setTimeout(() => {
        if (isAnimando.value) {
          animationFrameId = requestAnimationFrame(tickRoleta)
        }
      }, delay)
    } else {
      progresso10s.value = 100
      finalizarERevelar(rodadaTs)
    }
  }

  tickRoleta()
}

function finalizarERevelar(rodadaTs = 0) {
  isAnimando.value = false
  if (rodadaTs) {
    ultimaRodadaConcluidaTs.value = rodadaTs
  }
  if (animationFrameId) cancelAnimationFrame(animationFrameId)
  status.value = 'finalizado'
  // Revela os novos ganhadores nos últimos sorteados sincronizado com o fim da animação
  ultimosGanhadores.value = ultimosGanhadoresStaged.value
  soltarSuperConfetes()
  focoIndex.value = 0
  iniciarSpotlight()
}

function pararAnimacao() {
  isAnimando.value = false
  if (animationFrameId) cancelAnimationFrame(animationFrameId)
  pararSpotlight()
  candidatosSorteando.value = {}
  progresso10s.value = 0
}

function iniciarSpotlight() {
  iniciarSpotlightComProgresso(false)
}

function iniciarSpotlightComProgresso(retomar) {
  pararSpotlight()
  const quantidade = exibindoHistoricoCompleto.value ? ultimosGanhadores.value.length : premiosRodada.value.length
  if (!transicaoPausada.value && quantidade > 1) {
    if (!retomar) progressoTransicao.value = 0
    spotlightStartTime = Date.now() - (progressoTransicao.value / 100) * DURACAO_TRANSICAO_MS
    spotlightInterval = setInterval(() => {
      const decorrido = Date.now() - spotlightStartTime
      progressoTransicao.value = Math.min(100, (decorrido / DURACAO_TRANSICAO_MS) * 100)
      if (decorrido >= DURACAO_TRANSICAO_MS) {
        focoIndex.value = (focoIndex.value + 1) % quantidade
        progressoTransicao.value = 0
        spotlightStartTime = Date.now()
      }
    }, 50)
  }
}

function alternarPausaTransicao() {
  transicaoPausada.value = !transicaoPausada.value
  if (transicaoPausada.value) pararSpotlight()
  else iniciarSpotlightComProgresso(true)
}

function selecionarFoco(idx) {
  exibindoHistoricoCompleto.value = false
  focoIndex.value = idx
  iniciarSpotlight()
}

function alternarReproducaoHistorico() {
  if (exibindoHistoricoCompleto.value) {
    exibindoHistoricoCompleto.value = false
    focoIndex.value = 0
    iniciarSpotlight()
    return
  }
  if (ultimosGanhadores.value.length === 0) return
  pararSpotlight()
  exibindoHistoricoCompleto.value = true
  focoIndex.value = 0
  iniciarSpotlight()
}

function pararSpotlight() {
  if (spotlightInterval) {
    clearInterval(spotlightInterval)
    spotlightInterval = null
  }
}

function soltarSuperConfetes() {
  confetti({ particleCount: 180, spread: 120, origin: { y: 0.4 } })
  setTimeout(() => {
    confetti({ particleCount: 140, angle: 60, spread: 80, origin: { x: 0.1, y: 0.55 } })
    confetti({ particleCount: 140, angle: 120, spread: 80, origin: { x: 0.9, y: 0.55 } })
  }, 450)
}

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {})
  } else {
    document.exitFullscreen().catch(() => {})
  }
}

function startAutoScrollSidebar() {
  if (autoScrollAnimId) cancelAnimationFrame(autoScrollAnimId)
  let lastTs = performance.now()
  function step(ts) {
    const el = recentListRef.value
    const delta = ts - lastTs
    lastTs = ts

    if (el && !isHoveringSidebar) {
      if (el.scrollHeight > el.clientHeight) {
        el.scrollTop += (delta / 1000) * 24
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 2) {
          isHoveringSidebar = true
          setTimeout(() => {
            if (el) el.scrollTop = 0
            isHoveringSidebar = false
          }, 1800)
        }
      }
    }
    autoScrollAnimId = requestAnimationFrame(step)
  }
  autoScrollAnimId = requestAnimationFrame(step)
}

function getFotoServidor(item) {
  if (isAnimando.value) {
    return candidatosSorteando.value[item.item_id]?.foto_url || null
  }
  return item.ganhador?.foto_url || null
}

function getNomeServidor(item) {
  if (isAnimando.value) {
    return candidatosSorteando.value[item.item_id]?.nome || 'Sorteando...'
  }
  if (item.ganhador) {
    return item.ganhador.nome
  }
  return 'Aguardando Sorteio'
}

onMounted(() => {
  fetchLiveTelao()
  pollingInterval = setInterval(fetchLiveTelao, 1000)
  nextTick(() => { startAutoScrollSidebar() })
})

onUnmounted(() => {
  if (pollingInterval) clearInterval(pollingInterval)
  if (autoScrollAnimId) cancelAnimationFrame(autoScrollAnimId)
  pararAnimacao()
})
</script>


<template>
  <div class="telao-stage">
    <button type="button" class="btn-fullscreen-toggle" title="Alternar Tela Cheia" @click="toggleFullscreen">
      <i class="bi bi-arrows-fullscreen"></i>
    </button>

    <div class="stage-container" :class="{ 'sidebar-collapsed': painelRecentesOculto }">
      <main class="main-stage">
        <header class="telao-header">
          <div class="telao-branding">
            <span class="brand-tag font-outfit">FESTA DO SERVIDOR 2026</span>
            <h1 class="brand-title font-outfit">SERVINDOOR</h1>
          </div>

          <div class="status-banner font-outfit">
            <div class="telao-header-actions">
            <button
              v-if="status !== 'sorteando' && ultimosGanhadores.length > 0"
              type="button"
              class="btn-history-playback"
              :aria-pressed="exibindoHistoricoCompleto"
              @click="alternarReproducaoHistorico"
            >
              <i :class="['bi', exibindoHistoricoCompleto ? 'bi-stop-fill' : 'bi-play-fill']"></i>
              <span>{{ exibindoHistoricoCompleto ? 'Parar exibição' : 'Exibir últimos sorteados' }}</span>
            </button>
            <button
              v-if="status !== 'sorteando' && (exibindoHistoricoCompleto ? ultimosGanhadores.length : (status === 'finalizado' ? premiosRodada.length : 0)) > 1"
              type="button"
              class="btn-history-playback btn-history-pause"
              :aria-pressed="transicaoPausada"
              :title="transicaoPausada ? 'Retomar transição automática' : 'Pausar transição automática'"
              @click="alternarPausaTransicao"
            >
              <i :class="['bi', transicaoPausada ? 'bi-play-fill' : 'bi-pause-fill']"></i>
              <span>{{ transicaoPausada ? 'Retomar' : 'Pausar' }}</span>
            </button>
            <button
              type="button"
              class="btn-toggle-sidebar"
              :aria-expanded="!painelRecentesOculto"
              aria-controls="recent-drawers-panel"
              :disabled="status === 'sorteando'"
              :title="status === 'sorteando' ? 'Histórico recolhido durante o sorteio' : painelRecentesOculto ? 'Expandir últimos sorteados' : 'Recolher últimos sorteados'"
              @click="sidebarOculta = !sidebarOculta"
            >
              <i :class="['bi', painelRecentesOculto ? 'bi-layout-sidebar-inset' : 'bi-layout-sidebar-inset-reverse']"></i>
              <span>{{ status === 'sorteando' ? 'Últimos sorteados' : painelRecentesOculto ? 'Últimos sorteados' : 'Recolher histórico' }}</span>
            </button>
            </div>
            <span v-if="status === 'sorteando'" class="banner-sorteando pulse-banner">
              <i class="bi bi-stars me-2"></i> SORTEIO AO VIVO NO TELÃO • 10s
            </span>
            <span v-else-if="status === 'finalizado'" class="banner-finalizado">
              <i class="bi bi-trophy-fill me-2 text-warning"></i> PARABÉNS AOS CONTEMPLADOS!
            </span>
            <span v-else-if="status === 'preparando'" class="banner-preparando">
              <i class="bi bi-gift-fill me-2 text-info"></i> PRÊMIOS NA MESA ({{ premiosRodada.length }})
            </span>
            <span v-else class="banner-idle">
              <i class="bi bi-broadcast me-2 text-primary"></i> AGUARDANDO INÍCIO DA RODADA
            </span>
          </div>
        </header>

        <div v-if="status === 'sorteando'" class="progress-10s-container">
          <div class="progress-10s-bar" :style="{ width: progresso10s + '%' }"></div>
        </div>

        <!-- MODO 1: SPOTLIGHT / FOCO (CONFORME DESENHO DO USUÁRIO) -->
        <div v-if="status !== 'sorteando' && (status === 'finalizado' || exibindoHistoricoCompleto) && focoItem" class="spotlight-stage">
          <!-- QUADRADO VERMELHO: GRANDE FOCO -->
          <Transition name="winner-slide" mode="out-in">
          <div :key="`${exibindoHistoricoCompleto ? 'history' : 'round'}-${focoItem.item_id}`" class="spotlight-card-focus">
            <div class="spotlight-top-bar font-outfit">
              <span class="spotlight-badge-cat">
                {{ focoItem.categoria === 'categoria_1' ? 'CATEGORIA GERAL' : 'EIXO SETORIAL' }}
              </span>
              <span class="spotlight-badge-eixo">
                {{ focoItem.eixo_nome || 'TODOS OS PRESENTES' }}
              </span>
              <span class="spotlight-step-tag" v-if="(exibindoHistoricoCompleto ? ultimosGanhadores.length : premiosRodada.length) > 1">
                <span>{{ focoIndex + 1 }} de {{ exibindoHistoricoCompleto ? ultimosGanhadores.length : premiosRodada.length }}</span>
                <span
                  class="spotlight-transition-track"
                  role="progressbar"
                  :aria-valuenow="Math.round(progressoTransicao)"
                  aria-valuemin="0"
                  aria-valuemax="100"
                  aria-label="Tempo até o próximo ganhador"
                >
                  <span class="spotlight-transition-fill" :style="{ width: progressoTransicao + '%' }"></span>
                </span>
              </span>
            </div>

            <div class="spotlight-body">
              <div class="spotlight-col-servidor">
                <div class="spotlight-circle-servidor-box">
                  <img
                    v-if="focoItem.ganhador?.foto_url && !avatarErrors[focoItem.item_id]"
                    :src="focoItem.ganhador.foto_url"
                    alt="Servidor"
                    class="spotlight-avatar-img"
                    @error="avatarErrors[focoItem.item_id] = true"
                  />
                  <div v-else class="spotlight-avatar-placeholder">
                    <i class="bi bi-person-fill"></i>
                  </div>
                  <div class="spotlight-trophy-badge"><i class="bi bi-trophy-fill"></i></div>
                </div>

                <div class="spotlight-info-servidor">
                  <span class="meta-tag-cyan font-outfit">
                    <i class="bi bi-person-check-fill me-1"></i> SERVIDOR CONTEMPLADO
                  </span>
                  <h2 class="spotlight-name font-outfit">
                    {{ focoItem.ganhador ? focoItem.ganhador.nome : 'Servidor' }}
                  </h2>
                  <div class="spotlight-pills-servidor">
                    <span class="spotlight-cpf font-outfit">
                      <i class="bi bi-shield-lock" aria-hidden="true"></i>
                      <strong>CPF</strong>
                      <span>{{ focoItem.ganhador?.cpf }}</span>
                    </span>
                    <span class="spotlight-sec font-outfit">
                      <i class="bi bi-building" aria-hidden="true"></i>
                      <strong>Secretaria</strong>
                      <span>{{ focoItem.ganhador?.secretaria }}</span>
                    </span>
                  </div>
                </div>
              </div>

              <div class="spotlight-center-divider">
                <div class="spotlight-line"></div>
                <div class="spotlight-center-icon">
                  <img src="/images/logo_servindoor_sem-fundo.png" alt="Servindoor" class="spotlight-center-logo" />
                </div>
                <div class="spotlight-line"></div>
              </div>

              <div class="spotlight-col-premio">
                <div class="spotlight-circle-premio-box">
                  <img
                    v-if="focoItem.premio_foto && !imgErrors[focoItem.item_id]"
                    :src="focoItem.premio_foto"
                    alt="Prêmio"
                    class="spotlight-prize-img"
                    @error="imgErrors[focoItem.item_id] = true"
                  />
                  <div v-else class="spotlight-prize-placeholder">
                    <i class="bi bi-gift-fill"></i>
                  </div>
                </div>

                <div class="spotlight-info-premio">
                  <span class="meta-tag-red font-outfit">
                    <i class="bi bi-award-fill me-1"></i> PRÊMIO CONQUISTADO
                  </span>
                  <h3 class="spotlight-prize-title font-outfit">
                    {{ focoItem.premio_nome }}
                  </h3>
                  <p v-if="focoItem.premio_descricao" class="spotlight-prize-desc">
                    {{ focoItem.premio_descricao }}
                  </p>
                </div>
              </div>
            </div>

            <div v-if="focoItem.ganhador?.anulado" class="anulado-overlay-badge font-outfit">
              <i class="bi bi-x-octagon-fill me-1"></i> SORTEIO ANULADO (REABERTO)
            </div>
          </div>
          </Transition>

          <!-- MINIATURAS ABAIXO (LARANJA, AZUL, VERDE...) -->
          <div v-if="!exibindoHistoricoCompleto && premiosRodada.length > 1" class="spotlight-thumbnails-tray">
            <button
              v-for="(item, idx) in premiosRodada"
              :key="item.item_id"
              type="button"
              class="mini-card-thumb"
              :class="{
                'thumb-active': focoIndex === idx,
                'thumb-c1': idx % 4 === 0,
                'thumb-c2': idx % 4 === 1,
                'thumb-c3': idx % 4 === 2,
                'thumb-c4': idx % 4 === 3
              }"
              @click="selecionarFoco(idx)"
            >
              <div class="mini-thumb-circles">
                <div class="mini-circle mini-servidor">
                  <img v-if="item.ganhador?.foto_url" :src="item.ganhador.foto_url" alt="" />
                  <i v-else class="bi bi-person-fill"></i>
                </div>
                <div class="mini-circle mini-premio">
                  <img v-if="item.premio_foto" :src="item.premio_foto" alt="" />
                  <i v-else class="bi bi-gift-fill"></i>
                </div>
              </div>

              <div class="mini-thumb-text">
                <strong class="mini-user font-outfit">{{ item.ganhador?.nome || 'Servidor' }}</strong>
                <span class="mini-prize font-outfit">{{ item.premio_nome }}</span>
              </div>

              <div v-if="focoIndex === idx" class="mini-thumb-active-pin">
                <i class="bi bi-caret-up-fill"></i>
              </div>
            </button>
          </div>
        </div>

        <!-- MODO 2: ROLETA / PREPARANDO -->
        <div v-else-if="premiosRodada.length > 0" class="cards-grid-tray">
          <div
            v-for="(item) in premiosRodada"
            :key="item.item_id"
            class="card-sorteio-live"
            :class="{ 'card-sorteando-live': status === 'sorteando' }"
          >
            <div class="card-top-badges font-outfit">
              <span class="badge-categoria">
                <i class="bi bi-tag-fill me-1"></i>
                {{ item.categoria === 'categoria_1' ? 'CATEGORIA GERAL' : 'EIXO SETORIAL' }}
              </span>
              <span class="badge-eixo">
                <i class="bi bi-diagram-3-fill me-1"></i>
                {{ item.eixo_nome || 'TODOS OS PRESENTES' }}
              </span>
            </div>

            <div class="card-body-live">
              <div class="row-live-servidor">
                <div class="circle-box-live circle-servidor-live" :class="{ 'circle-spinning': isAnimando }">
                  <img
                    v-if="getFotoServidor(item) && !avatarErrors[item.item_id]"
                    :src="getFotoServidor(item)"
                    alt="Servidor"
                    class="circle-photo-live"
                    @error="avatarErrors[item.item_id] = true"
                  />
                  <div v-else class="circle-placeholder-live"><i class="bi bi-person-fill"></i></div>
                </div>

                <div class="info-live-servidor">
                  <span class="info-tag text-cyan font-outfit">
                    <i class="bi bi-person-check-fill me-1"></i> SERVIDOR PARTICIPANTE
                  </span>
                  <h2 class="live-nome font-outfit">{{ getNomeServidor(item) }}</h2>
                  <div v-if="status === 'sorteando'" class="status-roleta-tag font-outfit">
                    <span class="pulse-dot"></span> Sorteando ao vivo...
                  </div>
                  <div v-else-if="item.ganhador" class="status-ganhador-tag font-outfit">
                    <i class="bi bi-trophy-fill text-warning me-1"></i> {{ item.ganhador.secretaria || 'Contemplado' }}
                  </div>
                  <div v-else class="status-espera-tag font-outfit">
                    <i class="bi bi-hourglass-split text-warning me-1"></i> Pronto na Mesa de Sorteio
                  </div>
                </div>
              </div>

              <div class="row-live-premio">
                <div class="info-live-premio">
                  <span class="info-tag text-red font-outfit">
                    <i class="bi bi-award-fill me-1"></i> PRÊMIO DA RODADA
                  </span>
                  <h3 class="live-premio-nome font-outfit">{{ item.premio_nome }}</h3>
                </div>

                <div class="circle-box-live circle-premio-live">
                  <img
                    v-if="item.premio_foto && !imgErrors[item.item_id]"
                    :src="item.premio_foto"
                    alt="Prêmio"
                    class="circle-photo-live"
                    @error="imgErrors[item.item_id] = true"
                  />
                  <div v-else class="circle-placeholder-live"><i class="bi bi-gift-fill"></i></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- MODO 3: ESPERA -->
        <div v-else class="idle-stage">
          <div class="idle-icon-sphere">
            <img src="/images/logo_servindoor_sem-fundo.png" alt="Servindoor" class="idle-center-logo" />
          </div>
          <h2 class="idle-title font-outfit">SERVINDOOR 2026</h2>
          <p class="idle-subtitle font-outfit">O GRANDE SORTEIO DE PRÊMIOS COMEÇARÁ EM BREVE</p>
          <div class="idle-hint font-outfit">
            <i class="bi bi-hourglass-split me-1 text-warning"></i>
            Aguardando preparação da próxima rodada pela mesa de sorteio
          </div>
        </div>
      </main>

      <!-- BARRA LATERAL ROXA: NÃO RESGATADOS COM ROLAGEM SUAVE -->
      <aside
        id="recent-drawers-panel"
        class="sidebar-stage"
        :aria-hidden="painelRecentesOculto"
        :inert="painelRecentesOculto"
        @mouseenter="isHoveringSidebar = true"
        @mouseleave="isHoveringSidebar = false"
      >
        <div class="sidebar-header font-outfit">
          <div class="sidebar-title-box">
            <i class="bi bi-clock-history text-purple-accent me-2"></i>
            <h3 class="sidebar-title font-outfit">ÚLTIMOS SORTEADOS</h3>
          </div>
          <span class="pending-pill font-outfit">
            {{ ultimosGanhadores.length }} pendentes
          </span>
        </div>

        <div ref="recentListRef" class="recent-list-scrollable">
          <div
            v-for="item in ultimosGanhadores"
            :key="item.ganhador_id"
            class="recent-card-purple"
          >
            <div class="recent-avatar-purple">
              <img v-if="item.servidor_foto" :src="item.servidor_foto" alt="Foto" class="recent-img" />
              <div v-else class="recent-placeholder"><i class="bi bi-person"></i></div>
            </div>

            <div class="recent-info">
              <strong class="recent-name font-outfit">{{ item.servidor_nome }}</strong>
              <div class="recent-cpf-badge font-outfit">{{ item.servidor_cpf }}</div>
              <span class="recent-prize">
                <i class="bi bi-gift-fill text-warning me-1"></i> {{ item.premio_nome }}
              </span>
              <span class="recent-sec">{{ item.secretaria_nome }}</span>
            </div>

            <span class="recent-badge-pending font-outfit">Aguardando</span>
          </div>

          <div v-if="ultimosGanhadores.length === 0" class="no-recent font-outfit">
            <i class="bi bi-check2-circle text-success me-1"></i>
            Todos os prêmios já foram resgatados!
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.telao-stage {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
}
</style>
