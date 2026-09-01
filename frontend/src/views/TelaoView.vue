<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import confetti from 'canvas-confetti'

const loading = ref(true)
const ultimoGanhador = ref(null)
const ultimosGanhadores = ref([])
const totalPresentes = ref(0)
const candidatosAnimacao = ref([])

// Estados da Animação de Sorteio
const isAnimando = ref(false)
const candidatoAtual = ref(null)
const ultimoGanhadorId = ref(null)

let pollingInterval = null
let animationTimeout = null
let animationInterval = null

async function fetchLiveTelao() {
  try {
    const res = await fetch('/api/sorteios/live-telao', { cache: 'no-store' })
    if (!res.ok) return
    const data = await res.json()

    ultimosGanhadores.value = data.ultimos_ganhadores || []
    totalPresentes.value = data.total_presentes || 0
    candidatosAnimacao.value = data.candidatos_animacao || []

    const novoUltimo = data.ultimo_ganhador
    
    // Detecta se houve um novo sorteio
    if (novoUltimo && novoUltimo.ganhador_id !== ultimoGanhadorId.value) {
      if (ultimoGanhadorId.value !== null) {
        // Dispara animação épica de revelação
        dispararAnimacaoRoleta(novoUltimo)
      } else {
        // Primeira carga
        ultimoGanhador.value = novoUltimo
        ultimoGanhadorId.value = novoUltimo.ganhador_id
      }
    }

    loading.value = false
  } catch (err) {
    console.warn('Erro atualizando telão:', err)
  }
}

function dispararAnimacaoRoleta(novoGanhador) {
  isAnimando.value = true
  const candidatos = candidatosAnimacao.value.length > 0 ? candidatosAnimacao.value : [
    { nome: 'Servidor Municipal', foto_url: null, secretaria: 'Prefeitura' }
  ]

  let count = 0
  const maxIterations = 35
  let speed = 60

  function proximoFrame() {
    candidatoAtual.value = candidatos[Math.floor(Math.random() * candidatos.length)]
    count++

    if (count < maxIterations) {
      if (count > 20) speed += 18
      animationTimeout = setTimeout(proximoFrame, speed)
    } else {
      // Finaliza e revela o ganhador oficial
      ultimoGanhador.value = novoGanhador
      ultimoGanhadorId.value = novoGanhador.ganhador_id
      isAnimando.value = false
      soltarSuperConfetes()
    }
  }

  proximoFrame()
}

function soltarSuperConfetes() {
  confetti({
    particleCount: 150,
    spread: 100,
    origin: { y: 0.5 }
  })
  setTimeout(() => {
    confetti({
      particleCount: 100,
      angle: 60,
      spread: 70,
      origin: { x: 0, y: 0.7 }
    })
    confetti({
      particleCount: 100,
      angle: 120,
      spread: 70,
      origin: { x: 1, y: 0.7 }
    })
  }, 400)
}

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {})
  } else {
    document.exitFullscreen().catch(() => {})
  }
}

onMounted(() => {
  fetchLiveTelao()
  pollingInterval = setInterval(fetchLiveTelao, 1200)
})

onUnmounted(() => {
  if (pollingInterval) clearInterval(pollingInterval)
  if (animationTimeout) clearTimeout(animationTimeout)
  if (animationInterval) clearInterval(animationInterval)
})
</script>

<template>
  <div class="telao-stage">
    
    <!-- Botão Oculto de Tela Cheia no Canto Superior -->
    <button type="button" class="btn-fullscreen-toggle" title="Alternar Tela Cheia" @click="toggleFullscreen">
      <i class="bi bi-arrows-fullscreen"></i>
    </button>

    <div class="stage-container">
      
      <!-- PALCO PRINCIPAL (GANHADOR EM DESTAQUE) -->
      <main class="main-stage">
        
        <!-- ESTADO 1: ANIMAÇÃO DE ROLETA (SORTEIO EM ANDAMENTO) -->
        <div v-if="isAnimando" class="roleta-overlay">
          <div class="roleta-badge font-outfit">
            <i class="bi bi-stars me-2"></i> SORTEANDO GANHADOR...
          </div>

          <div class="roleta-card">
            <div class="roleta-photo-box">
              <img
                v-if="candidatoAtual?.foto_url"
                :src="candidatoAtual.foto_url"
                alt="Sorteando"
                class="roleta-photo"
              />
              <div v-else class="photo-placeholder">
                <i class="bi bi-person-fill"></i>
              </div>
            </div>
            <h2 class="roleta-name font-outfit">{{ candidatoAtual?.nome || 'Processando...' }}</h2>
            <span class="roleta-sec">{{ candidatoAtual?.secretaria || 'Prefeitura Municipal' }}</span>
          </div>
        </div>

        <!-- ESTADO 2: GANHADOR DEFINIDO -->
        <div v-else-if="ultimoGanhador" class="winner-presentation">
          
          <div class="winner-header">
            <span class="category-pill font-outfit">
              <i class="bi bi-trophy-fill me-1"></i>
              {{ ultimoGanhador.categoria === 'categoria_1' ? 'SORTEIO GERAL • CATEGORIA 1' : 'SORTEIO DE EIXO • CATEGORIA 2' }}
            </span>
            
            <!-- NOME DO SERVIDOR ACIMA DA FOTO -->
            <h1 class="winner-servant-name font-outfit">
              {{ ultimoGanhador.servidor.nome }}
            </h1>
            
            <p class="winner-org">
              <i class="bi bi-building me-1"></i>
              <strong>{{ ultimoGanhador.servidor.secretaria?.nome || 'Servidor Municipal' }}</strong>
              <span v-if="ultimoGanhador.servidor.setor"> &bull; {{ ultimoGanhador.servidor.setor }}</span>
            </p>
          </div>

          <!-- BLOCO UNIFICADO: FOTO DO SERVIDOR + FOTO DO PRÊMIO COLADA ABAIXO -->
          <div class="stage-combo-card">
            
            <!-- FOTO DO SERVIDOR -->
            <div class="servant-photo-frame">
              <img
                v-if="ultimoGanhador.servidor.foto_url"
                :src="ultimoGanhador.servidor.foto_url"
                :alt="ultimoGanhador.servidor.nome"
                class="servant-img"
              />
              <div v-else class="servant-img-placeholder">
                <i class="bi bi-person-fill"></i>
              </div>
              <span class="badge-ganhador-tag font-outfit">PARABÉNS!</span>
            </div>

            <!-- FOTO E NOME DO PRÊMIO COLADOS LOGO ABAIXO -->
            <div class="prize-attached-box">
              <div class="prize-photo-small-frame">
                <img
                  v-if="ultimoGanhador.premio.foto_url"
                  :src="ultimoGanhador.premio.foto_url"
                  :alt="ultimoGanhador.premio.nome"
                  class="prize-img"
                />
                <div v-else class="prize-img-placeholder">
                  <i class="bi bi-gift-fill"></i>
                </div>
              </div>

              <div class="prize-info-box">
                <span class="prize-label font-outfit">PRÊMIO SORTEADO</span>
                <h3 class="prize-name font-outfit">{{ ultimoGanhador.premio.nome }}</h3>
                <p v-if="ultimoGanhador.premio.descricao" class="prize-desc">
                  {{ ultimoGanhador.premio.descricao }}
                </p>
              </div>
            </div>

          </div>

        </div>

        <!-- ESTADO 3: NENHUM GANHADOR AINDA -->
        <div v-else class="idle-stage">
          <div class="idle-icon-box">
            <i class="bi bi-balloon-heart-fill"></i>
          </div>
          <h1 class="idle-title font-outfit">SERVINDOOR 2026</h1>
          <p class="idle-subtitle font-outfit">O GRANDE SORTEIO DE PRÊMIOS COMEÇARÁ EM BREVE</p>
          <div class="idle-chip">
            <i class="bi bi-people-fill me-2 text-primary"></i>
            <span>{{ totalPresentes }} servidores presentes no evento</span>
          </div>
        </div>

      </main>

      <!-- BARRA LATERAL: ÚLTIMOS GANHADORES -->
      <aside class="sidebar-stage">
        <div class="sidebar-header">
          <i class="bi bi-clock-history text-warning me-2"></i>
          <h3 class="sidebar-title font-outfit">ÚLTIMOS SORTEADOS</h3>
        </div>

        <div class="recent-list">
          <div
            v-for="item in ultimosGanhadores"
            :key="item.ganhador_id"
            class="recent-card"
          >
            <div class="recent-avatar">
              <img v-if="item.servidor_foto" :src="item.servidor_foto" alt="Foto" class="recent-img" />
              <div v-else class="recent-placeholder"><i class="bi bi-person"></i></div>
            </div>

            <div class="recent-info">
              <strong class="recent-name font-outfit">{{ item.servidor_nome }}</strong>
              <span class="recent-prize">
                <i class="bi bi-gift-fill text-warning me-1"></i> {{ item.premio_nome }}
              </span>
              <span class="recent-sec">{{ item.secretaria_nome }}</span>
            </div>

            <span class="recent-time">{{ item.data_sorteio }}</span>
          </div>

          <div v-if="ultimosGanhadores.length === 0" class="no-recent">
            <i class="bi bi-hourglass-split me-1"></i> Aguardando primeiros sorteios...
          </div>
        </div>
      </aside>

    </div>

  </div>
</template>

<style scoped>
/* TELÃO FULLSCREEN ESTILO PALCO VIP */
.telao-stage {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  background: #060911;
  background-image: 
    radial-gradient(circle at 30% 20%, rgba(59, 130, 246, 0.15) 0%, transparent 60%),
    radial-gradient(circle at 80% 80%, rgba(245, 158, 11, 0.12) 0%, transparent 50%),
    radial-gradient(circle at 50% 50%, rgba(15, 23, 42, 0.6) 0%, #060911 100%);
  color: #ffffff;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  user-select: none;
}

.btn-fullscreen-toggle {
  position: absolute;
  top: 16px;
  right: 16px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--text-muted);
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 100;
  opacity: 0.2;
  transition: opacity 0.2s ease, background 0.2s ease;
}

.btn-fullscreen-toggle:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.15);
  color: #ffffff;
}

.stage-container {
  display: grid;
  grid-template-columns: 1fr 360px;
  height: 100vh;
  width: 100%;
}

/* PALCO PRINCIPAL */
.main-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 48px;
  height: 100%;
  position: relative;
}

/* APRESENTAÇÃO DO GANHADOR */
.winner-presentation {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  max-width: 780px;
  width: 100%;
  animation: winnerEntry 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes winnerEntry {
  from { opacity: 0; transform: scale(0.85) translateY(20px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.winner-header {
  margin-bottom: 20px;
}

.category-pill {
  display: inline-flex;
  align-items: center;
  background: rgba(245, 158, 11, 0.2);
  border: 1px solid rgba(245, 158, 11, 0.5);
  color: #fbbf24;
  font-size: 0.95rem;
  font-weight: 800;
  padding: 6px 18px;
  border-radius: 999px;
  letter-spacing: 1px;
  margin-bottom: 12px;
  box-shadow: 0 0 20px rgba(245, 158, 11, 0.3);
}

.winner-servant-name {
  font-size: 3.4rem;
  font-weight: 900;
  color: #ffffff;
  letter-spacing: -1px;
  line-height: 1.1;
  text-shadow: 0 4px 20px rgba(0, 0, 0, 0.8), 0 0 35px rgba(255, 255, 255, 0.3);
  margin-bottom: 6px;
}

.winner-org {
  font-size: 1.25rem;
  color: #94a3b8;
  margin-bottom: 0;
}

/* COMBO CARD (FOTO DO SERVIDOR + PRÊMIO COLADO) */
.stage-combo-card {
  background: rgba(17, 24, 39, 0.85);
  border: 2px solid rgba(255, 255, 255, 0.15);
  border-radius: 28px;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.6), 0 0 50px rgba(59, 130, 246, 0.25);
  width: 100%;
  max-width: 620px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.servant-photo-frame {
  position: relative;
  width: 100%;
  height: 310px;
  background: #000000;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.servant-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.servant-img-placeholder {
  font-size: 6rem;
  color: #475569;
}

.badge-ganhador-tag {
  position: absolute;
  top: 14px;
  right: 14px;
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: #000000;
  font-size: 0.85rem;
  font-weight: 900;
  padding: 6px 14px;
  border-radius: 999px;
  letter-spacing: 1px;
  box-shadow: 0 4px 15px rgba(245, 158, 11, 0.5);
}

/* PRÊMIO COLADO LOGO ABAIXO */
.prize-attached-box {
  background: rgba(15, 23, 42, 0.95);
  border-top: 2px solid rgba(245, 158, 11, 0.4);
  padding: 18px 24px;
  display: flex;
  align-items: center;
  gap: 20px;
  text-align: left;
}

.prize-photo-small-frame {
  width: 86px;
  height: 86px;
  border-radius: 16px;
  background: #0b0f19;
  border: 1px solid rgba(255, 255, 255, 0.2);
  overflow: hidden;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.prize-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.prize-img-placeholder {
  font-size: 2.2rem;
  color: #fbbf24;
}

.prize-info-box {
  flex: 1;
}

.prize-label {
  display: block;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
  color: #fbbf24;
  letter-spacing: 1.5px;
  margin-bottom: 2px;
}

.prize-name {
  font-size: 1.6rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 2px;
}

.prize-desc {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-bottom: 0;
}

/* ROLETA / ANIMAÇÃO */
.roleta-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.roleta-badge {
  background: rgba(239, 68, 68, 0.2);
  border: 1px solid rgba(239, 68, 68, 0.5);
  color: #f87171;
  font-size: 1.2rem;
  font-weight: 900;
  padding: 8px 24px;
  border-radius: 999px;
  letter-spacing: 2px;
  margin-bottom: 24px;
  animation: pulse 1s infinite alternate;
}

.roleta-card {
  background: rgba(17, 24, 39, 0.9);
  border: 2px solid rgba(59, 130, 246, 0.6);
  box-shadow: 0 0 50px rgba(59, 130, 246, 0.4);
  border-radius: 24px;
  padding: 36px 48px;
  width: 440px;
  text-align: center;
}

.roleta-photo-box {
  width: 180px;
  height: 180px;
  border-radius: 50%;
  overflow: hidden;
  margin: 0 auto 20px;
  border: 4px solid var(--primary-accent);
  background: #000;
}

.roleta-photo {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.roleta-name {
  font-size: 2rem;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 4px;
}

.roleta-sec {
  color: var(--text-muted);
  font-size: 1rem;
}

/* ESTADO IDLE / ESPERA */
.idle-stage {
  text-align: center;
}

.idle-icon-box {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  background: rgba(59, 130, 246, 0.15);
  border: 2px solid rgba(59, 130, 246, 0.4);
  margin: 0 auto 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 3rem;
  color: var(--primary-accent);
  box-shadow: 0 0 40px rgba(59, 130, 246, 0.3);
}

.idle-title {
  font-size: 3.5rem;
  font-weight: 900;
  letter-spacing: -0.5px;
  margin-bottom: 8px;
}

.idle-subtitle {
  font-size: 1.3rem;
  color: #fbbf24;
  letter-spacing: 2px;
  margin-bottom: 28px;
}

.idle-chip {
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 8px 20px;
  border-radius: 999px;
  font-size: 1rem;
  color: var(--text-muted);
}

/* SIDEBAR ÚLTIMOS GANHADORES */
.sidebar-stage {
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-left: 1px solid rgba(255, 255, 255, 0.08);
  height: 100vh;
  padding: 24px 20px;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  display: flex;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 16px;
}

.sidebar-title {
  font-size: 1.05rem;
  font-weight: 800;
  letter-spacing: 1px;
  color: #ffffff;
  margin-bottom: 0;
}

.recent-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
}

.recent-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  position: relative;
  transition: transform 0.2s ease;
}

.recent-avatar {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  overflow: hidden;
  background: #000;
  border: 1px solid rgba(255, 255, 255, 0.2);
  flex-shrink: 0;
}

.recent-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.recent-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
}

.recent-info {
  flex: 1;
  min-width: 0;
}

.recent-name {
  display: block;
  font-size: 0.9rem;
  font-weight: 700;
  color: #ffffff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-prize {
  display: block;
  font-size: 0.78rem;
  color: #fbbf24;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-sec {
  display: block;
  font-size: 0.7rem;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-time {
  font-size: 0.7rem;
  color: #64748b;
  font-family: monospace;
}

.no-recent {
  text-align: center;
  padding: 40px 16px;
  color: #64748b;
  font-size: 0.85rem;
}

.me-1 { margin-right: 4px; }
.me-2 { margin-right: 8px; }
.text-warning { color: #fbbf24; }
.text-primary { color: var(--primary-accent); }

@keyframes pulse {
  from { opacity: 0.7; transform: scale(0.98); }
  to { opacity: 1; transform: scale(1.02); }
}

@media (max-width: 992px) {
  .stage-container {
    grid-template-columns: 1fr;
  }
  .sidebar-stage {
    display: none;
  }
  .winner-servant-name {
    font-size: 2.4rem;
  }
}
</style>
