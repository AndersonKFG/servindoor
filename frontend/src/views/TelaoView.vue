<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import confetti from 'canvas-confetti'

const loading = ref(true)
const status = ref('idle')
const premiosRodada = ref([])
const ultimosGanhadores = ref([])
const candidatosAnimacao = ref([])

const isAnimando = ref(false)
const progresso10s = ref(0)
const candidatosSorteando = ref({})
const imgErrors = ref({})
const avatarErrors = ref({})
const focoIndex = ref(0)

const recentListRef = ref(null)
let isHoveringSidebar = false
let autoScrollAnimId = null

let pollingInterval = null
let animationFrameId = null
let spotlightInterval = null
let roletaStartTime = null

const focoItem = computed(() => {
  if (premiosRodada.value.length === 0) return null
  const idx = Math.max(0, Math.min(premiosRodada.value.length - 1, focoIndex.value))
  return premiosRodada.value[idx]
})

async function fetchLiveTelao() {
  try {
    const res = await fetch('/api/sorteios/live-telao', { cache: 'no-store' })
    if (!res.ok) return
    const data = await res.json()

    const novoStatus = data.status || 'idle'
    const statusAnterior = status.value

    premiosRodada.value = data.premios_rodada || []
    ultimosGanhadores.value = data.ultimos_ganhadores || []
    candidatosAnimacao.value = data.candidatos_animacao || []

    if (novoStatus === 'sorteando') {
      if (!isAnimando.value && statusAnterior !== 'sorteando') {
        status.value = 'sorteando'
        iniciarAnimacaoRoletaLocal(10000)
      }
    } else if (novoStatus === 'finalizado') {
      if (isAnimando.value) {
        // Aguarda os 10s no cliente
      } else {
        status.value = 'finalizado'
        iniciarSpotlight()
      }
    } else if (novoStatus === 'idle') {
      pararAnimacao()
      status.value = 'idle'
    } else {
      status.value = novoStatus
    }

    loading.value = false
  } catch (err) {
    console.warn('Erro atualizando telão:', err)
  }
}

function iniciarAnimacaoRoletaLocal(duracao = 10000) {
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
      finalizarERevelar()
    }
  }

  tickRoleta()
}

function finalizarERevelar() {
  isAnimando.value = false
  if (animationFrameId) cancelAnimationFrame(animationFrameId)
  status.value = 'finalizado'
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
  pararSpotlight()
  if (premiosRodada.value.length > 1) {
    spotlightInterval = setInterval(() => {
      focoIndex.value = (focoIndex.value + 1) % premiosRodada.value.length
    }, 5500)
  }
}

function selecionarFoco(idx) {
  focoIndex.value = idx
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

    <div class="stage-container">
      <main class="main-stage">
        <header class="telao-header">
          <div class="telao-branding">
            <span class="brand-tag font-outfit">FESTA DO SERVIDOR 2026</span>
            <h1 class="brand-title font-outfit">SERVINDOOR</h1>
          </div>

          <div class="status-banner font-outfit">
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
        <div v-if="status === 'finalizado' && focoItem" class="spotlight-stage">
          <!-- QUADRADO VERMELHO: GRANDE FOCO -->
          <div class="spotlight-card-focus">
            <div class="spotlight-top-bar font-outfit">
              <span class="spotlight-badge-cat">
                {{ focoItem.categoria === 'categoria_1' ? 'CATEGORIA GERAL' : 'EIXO SETORIAL' }}
              </span>
              <span class="spotlight-badge-eixo">
                {{ focoItem.eixo_nome || 'TODOS OS PRESENTES' }}
              </span>
              <span class="spotlight-step-tag" v-if="premiosRodada.length > 1">
                {{ focoIndex + 1 }} de {{ premiosRodada.length }}
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
                      <i class="bi bi-shield-lock me-1"></i> {{ focoItem.ganhador?.cpf }}
                    </span>
                    <span class="spotlight-sec font-outfit">
                      <i class="bi bi-building me-1"></i> {{ focoItem.ganhador?.secretaria }}
                    </span>
                  </div>
                </div>
              </div>

              <div class="spotlight-center-divider">
                <div class="spotlight-line"></div>
                <div class="spotlight-center-icon"><i class="bi bi-stars"></i></div>
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

          <!-- MINIATURAS ABAIXO (LARANJA, AZUL, VERDE...) -->
          <div v-if="premiosRodada.length > 1" class="spotlight-thumbnails-tray">
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
                {{ item.categoria === 'categoria_1' ? 'CATEGORIA GERAL' : 'EIXO SETORIAL' }}
              </span>
              <span class="badge-eixo">
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
                    <i class="bi bi-person-check-fill me-1"></i> SERVIDOR
                  </span>
                  <h2 class="live-nome font-outfit">{{ getNomeServidor(item) }}</h2>
                  <div v-if="status === 'sorteando'" class="status-roleta-tag font-outfit">
                    <span class="pulse-dot"></span> Sorteando ao vivo...
                  </div>
                  <div v-else class="status-espera-tag font-outfit">Aguardando sorteio...</div>
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
          <div class="idle-icon-sphere"><i class="bi bi-stars"></i></div>
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
        class="sidebar-stage"
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
  background: #050811;
  background-image: 
    radial-gradient(circle at 15% 20%, rgba(6, 182, 212, 0.1) 0%, transparent 55%),
    radial-gradient(circle at 85% 80%, rgba(168, 85, 247, 0.12) 0%, transparent 55%),
    radial-gradient(circle at 50% 50%, rgba(15, 23, 42, 0.85) 0%, #050811 100%);
  color: #ffffff;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  user-select: none;
  font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
}

.btn-fullscreen-toggle {
  position: absolute;
  top: 14px;
  right: 14px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #94a3b8;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 100;
  opacity: 0.3;
  transition: all 0.2s ease;
}
.btn-fullscreen-toggle:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.2);
  color: #ffffff;
}

.stage-container {
  display: grid;
  grid-template-columns: 1fr 330px;
  height: 100vh;
  width: 100%;
  overflow: hidden;
}

.main-stage {
  display: flex;
  flex-direction: column;
  padding: 16px 24px 20px 24px;
  height: 100vh;
  position: relative;
  overflow: hidden;
}

.telao-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}

.telao-branding {
  display: flex;
  flex-direction: column;
}
.brand-tag {
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 2px;
  color: #38bdf8;
}
.brand-title {
  font-size: 1.55rem;
  font-weight: 900;
  letter-spacing: -0.5px;
  margin: 0;
  background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.status-banner {
  font-size: 0.88rem;
  font-weight: 800;
  letter-spacing: 0.5px;
}
.banner-sorteando {
  background: rgba(239, 68, 68, 0.2);
  border: 1px solid #ef4444;
  color: #fca5a5;
  padding: 6px 18px;
  border-radius: 999px;
}
.pulse-banner {
  animation: pulseGlow 1s infinite alternate;
}
@keyframes pulseGlow {
  from { box-shadow: 0 0 10px rgba(239, 68, 68, 0.4); }
  to { box-shadow: 0 0 25px rgba(239, 68, 68, 0.85); transform: scale(1.02); }
}

.banner-finalizado {
  background: rgba(245, 158, 11, 0.2);
  border: 1px solid #f59e0b;
  color: #fde68a;
  padding: 6px 18px;
  border-radius: 999px;
  box-shadow: 0 0 20px rgba(245, 158, 11, 0.35);
}
.banner-preparando {
  background: rgba(6, 182, 212, 0.15);
  border: 1px solid #06b6d4;
  color: #67e8f9;
  padding: 6px 18px;
  border-radius: 999px;
}
.banner-idle {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8;
  padding: 6px 18px;
  border-radius: 999px;
}

.progress-10s-container {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.progress-10s-bar {
  height: 100%;
  background: linear-gradient(90deg, #38bdf8, #ef4444);
  box-shadow: 0 0 15px rgba(239, 68, 68, 0.8);
  transition: width 0.04s linear;
}

/* ========================================================================== */
/* SPOTLIGHT (QUADRADO VERMELHO EM FOCO + MINIATURAS ABAIXO)                  */
/* ========================================================================== */
.spotlight-stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 16px;
  min-height: 0;
}

.spotlight-card-focus {
  flex: 1;
  background: rgba(15, 23, 42, 0.92);
  backdrop-filter: blur(25px);
  -webkit-backdrop-filter: blur(25px);
  border: 3px solid #ef4444; /* Borda vermelha do foco */
  border-radius: 24px;
  box-shadow: 0 0 45px rgba(239, 68, 68, 0.4), 0 20px 50px rgba(0, 0, 0, 0.8);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

.spotlight-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  background: rgba(11, 15, 25, 0.95);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-size: 0.82rem;
  font-weight: 800;
  letter-spacing: 1px;
}
.spotlight-badge-cat { color: #fbbf24; }
.spotlight-badge-eixo { color: #38bdf8; }
.spotlight-step-tag {
  background: rgba(239, 68, 68, 0.2);
  color: #fca5a5;
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 0.75rem;
}

.spotlight-body {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 24px 32px;
  gap: 28px;
}

.spotlight-col-servidor {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 24px;
}

.spotlight-circle-servidor-box {
  position: relative;
  width: 140px;
  height: 140px;
  border-radius: 50%;
  border: 5px solid #38bdf8;
  box-shadow: 0 0 35px rgba(56, 189, 248, 0.85);
  overflow: hidden;
  background: #0b1220;
  flex-shrink: 0;
  animation: winnerPulse 2s infinite ease-in-out;
}
@keyframes winnerPulse {
  0% { box-shadow: 0 0 20px rgba(56, 189, 248, 0.6); }
  50% { box-shadow: 0 0 45px rgba(56, 189, 248, 1); transform: scale(1.02); }
  100% { box-shadow: 0 0 20px rgba(56, 189, 248, 0.6); }
}

.spotlight-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.spotlight-avatar-placeholder {
  font-size: 3.8rem;
  color: #38bdf8;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
.spotlight-trophy-badge {
  position: absolute;
  bottom: 0;
  right: 0;
  background: #fbbf24;
  color: #000;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  box-shadow: 0 0 15px rgba(251, 191, 36, 0.8);
}

.spotlight-info-servidor {
  display: flex;
  flex-direction: column;
}
.meta-tag-cyan {
  font-size: 0.78rem;
  font-weight: 800;
  color: #38bdf8;
  letter-spacing: 1px;
}
.spotlight-name {
  font-size: 2.1rem;
  font-weight: 900;
  color: #ffffff;
  margin: 4px 0 8px 0;
  line-height: 1.15;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.9);
}
.spotlight-pills-servidor {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.spotlight-cpf {
  font-size: 1.25rem;
  font-weight: 900;
  color: #38bdf8;
  letter-spacing: 1px;
}
.spotlight-sec {
  font-size: 1rem;
  color: #cbd5e1;
  font-weight: 700;
}

.spotlight-center-divider {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  height: 100%;
  justify-content: center;
}
.spotlight-line {
  width: 2px;
  height: 50px;
  background: linear-gradient(180deg, transparent, rgba(255, 255, 255, 0.2), transparent);
}
.spotlight-center-icon {
  font-size: 1.8rem;
  color: #fbbf24;
  animation: rotateSparkle 6s linear infinite;
}
@keyframes rotateSparkle {
  0% { transform: rotate(0deg) scale(1); }
  50% { transform: rotate(180deg) scale(1.15); }
  100% { transform: rotate(360deg) scale(1); }
}

.spotlight-col-premio {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 24px;
}

.spotlight-circle-premio-box {
  width: 140px;
  height: 140px;
  border-radius: 50%;
  border: 5px solid #ef4444;
  box-shadow: 0 0 35px rgba(239, 68, 68, 0.85);
  overflow: hidden;
  background: #180d16;
  flex-shrink: 0;
}
.spotlight-prize-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.spotlight-prize-placeholder {
  font-size: 3.5rem;
  color: #ef4444;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.spotlight-info-premio {
  display: flex;
  flex-direction: column;
}
.meta-tag-red {
  font-size: 0.78rem;
  font-weight: 800;
  color: #f87171;
  letter-spacing: 1px;
}
.spotlight-prize-title {
  font-size: 1.85rem;
  font-weight: 900;
  color: #ffffff;
  margin: 4px 0 6px 0;
  line-height: 1.15;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.9);
}
.spotlight-prize-desc {
  font-size: 0.88rem;
  color: #94a3b8;
  line-height: 1.35;
  margin: 0;
}

.spotlight-thumbnails-tray {
  display: flex;
  gap: 14px;
  height: 82px;
  flex-shrink: 0;
  overflow-x: auto;
  padding-bottom: 2px;
}
.spotlight-thumbnails-tray::-webkit-scrollbar { display: none; }

.mini-card-thumb {
  flex: 1;
  min-width: 170px;
  max-width: 260px;
  background: rgba(15, 23, 42, 0.8);
  border-radius: 14px;
  border: 2px solid rgba(255, 255, 255, 0.12);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  position: relative;
  transition: all 0.25s ease;
  text-align: left;
}
.mini-card-thumb:hover {
  transform: translateY(-3px);
  background: rgba(30, 41, 59, 0.9);
}
.thumb-c1 { border-color: #f97316; }
.thumb-c2 { border-color: #06b6d4; }
.thumb-c3 { border-color: #10b981; }
.thumb-c4 { border-color: #a855f7; }

.mini-card-thumb.thumb-active {
  box-shadow: 0 0 20px currentColor;
  transform: scale(1.04);
  z-index: 5;
}
.mini-thumb-active-pin {
  position: absolute;
  top: -14px;
  left: 50%;
  transform: translateX(-50%);
  color: #ffffff;
  font-size: 1.1rem;
}

.mini-thumb-circles {
  position: relative;
  width: 48px;
  height: 48px;
  flex-shrink: 0;
}
.mini-circle {
  position: absolute;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0f172a;
}
.mini-circle img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.mini-servidor {
  top: 0;
  left: 0;
  border: 2px solid #38bdf8;
  z-index: 2;
}
.mini-premio {
  bottom: 0;
  right: 0;
  border: 2px solid #ef4444;
  z-index: 3;
}

.mini-thumb-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.mini-user {
  font-size: 0.8rem;
  color: #ffffff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mini-prize {
  font-size: 0.72rem;
  color: #fbbf24;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ========================================================================== */
/* MODO ROLETA / PREPARANDO (GRID DA BANDEJA)                                  */
/* ========================================================================== */
.cards-grid-tray {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
  align-content: center;
}

.card-sorteio-live {
  background: rgba(15, 23, 42, 0.9);
  border: 1.5px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: all 0.3s ease;
}
.card-sorteando-live { border-color: rgba(56, 189, 248, 0.5); }

.card-body-live {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 10px 14px;
  gap: 8px;
  flex: 1;
}

.row-live-servidor,
.row-live-premio {
  display: flex;
  align-items: center;
  gap: 12px;
}
.row-live-premio {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding-top: 8px;
  justify-content: space-between;
}

.circle-box-live {
  width: 68px;
  height: 68px;
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0b1220;
  flex-shrink: 0;
}
.circle-servidor-live {
  border: 3px solid #38bdf8;
  box-shadow: 0 0 14px rgba(56, 189, 248, 0.4);
}
.circle-premio-live {
  border: 3px solid #ef4444;
  box-shadow: 0 0 14px rgba(239, 68, 68, 0.4);
}
.circle-photo-live {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.circle-placeholder-live {
  font-size: 1.6rem;
  color: #94a3b8;
}

.info-live-servidor,
.info-live-premio {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.live-nome {
  font-size: 1rem;
  font-weight: 800;
  color: #ffffff;
  margin: 1px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.live-premio-nome {
  font-size: 0.95rem;
  font-weight: 800;
  color: #ffffff;
  margin: 1px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ========================================================================== */
/* SIDEBAR ROXA                                                              */
/* ========================================================================== */
.sidebar-stage {
  background: rgba(12, 10, 24, 0.95);
  border-left: 2px solid rgba(168, 85, 247, 0.35); /* Borda roxa conforme desenho */
  box-shadow: -10px 0 35px rgba(168, 85, 247, 0.15);
  padding: 16px 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 100vh;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(168, 85, 247, 0.2);
  flex-shrink: 0;
}
.sidebar-title-box { display: flex; align-items: center; }
.text-purple-accent { color: #c084fc; }
.sidebar-title {
  font-size: 0.88rem;
  font-weight: 800;
  letter-spacing: 1px;
  margin: 0;
  color: #f3e8ff;
}
.pending-pill {
  font-size: 0.68rem;
  background: rgba(168, 85, 247, 0.2);
  color: #d8b4fe;
  border: 1px solid rgba(168, 85, 247, 0.4);
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 700;
}

.recent-list-scrollable {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  flex: 1;
  padding-right: 2px;
  -ms-overflow-style: none;
  scrollbar-width: none;
}
.recent-list-scrollable::-webkit-scrollbar { display: none; }

.recent-card-purple {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(168, 85, 247, 0.2);
  border-radius: 12px;
  transition: all 0.2s ease;
  flex-shrink: 0;
}
.recent-card-purple:hover {
  background: rgba(168, 85, 247, 0.1);
  border-color: rgba(168, 85, 247, 0.45);
}

.recent-avatar-purple {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  overflow: hidden;
  background: #0f172a;
  border: 2px solid #c084fc;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.recent-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.recent-placeholder {
  color: #94a3b8;
  font-size: 1.2rem;
}

.recent-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.recent-name {
  font-size: 0.82rem;
  color: #ffffff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.recent-cpf-badge {
  font-size: 0.7rem;
  color: #c084fc;
  font-weight: 700;
}
.recent-prize {
  font-size: 0.74rem;
  color: #fbbf24;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.recent-sec {
  font-size: 0.68rem;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-badge-pending {
  font-size: 0.65rem;
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.3);
  padding: 3px 6px;
  border-radius: 6px;
  font-weight: 700;
  white-space: nowrap;
}

.no-recent {
  color: #94a3b8;
  font-size: 0.82rem;
  text-align: center;
  margin-top: 30px;
  padding: 12px;
}

.idle-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
}
.idle-icon-sphere {
  width: 76px;
  height: 76px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.25) 0%, rgba(15, 23, 42, 0.8) 100%);
  border: 2px solid rgba(56, 189, 248, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2.2rem;
  color: #38bdf8;
  margin-bottom: 16px;
  box-shadow: 0 0 25px rgba(56, 189, 248, 0.3);
}
.idle-title {
  font-size: 2.2rem;
  font-weight: 900;
  margin-bottom: 4px;
}
.idle-subtitle {
  font-size: 1.05rem;
  font-weight: 700;
  color: #f59e0b;
  margin-bottom: 16px;
}
.idle-hint {
  font-size: 0.85rem;
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.05);
  padding: 6px 16px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.anulado-overlay-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  background: rgba(239, 68, 68, 0.95);
  color: #ffffff;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 800;
  z-index: 20;
}

@media (max-width: 1024px) {
  .stage-container { grid-template-columns: 1fr; }
  .sidebar-stage { display: none; }
}
</style>
