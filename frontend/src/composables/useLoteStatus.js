/**
 * Converte data/hora para timestamp absoluto (ms) forçando estritamente o fuso America/Sao_Paulo (-03:00).
 * Imuniza a interface mesmo se o cliente estiver em UTC ou qualquer outro fuso horário.
 */
export function parseSaoPauloTimeToMs(isoStr, epochMs) {
  if (typeof epochMs === 'number' && !isNaN(epochMs) && epochMs > 0) {
    return epochMs
  }
  if (!isoStr || typeof isoStr !== 'string') return 0

  const trimmed = isoStr.trim()
  if (trimmed.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(trimmed)) {
    return new Date(trimmed).getTime()
  }
  return new Date(`${trimmed}-03:00`).getTime()
}

import { ref, onMounted, onUnmounted } from 'vue'
import { useServerTime } from './useServerTime'

export function getDeviceFingerprint() {
  try {
    const cached = localStorage.getItem('servindoor_device_fp')
    if (cached) return cached
  } catch {}

  let fp = ''
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    let renderer = ''
    if (gl) {
      const dbg = gl.getExtension('WEBGL_debug_renderer_info')
      if (dbg) {
        // Remove prefixos como ANGLE (...) para manter equivalência entre navegadores
        const rawRenderer = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || ''
        renderer = rawRenderer.replace(/ANGLE\s*\((.*)\)/i, '$1').trim()
      }
    }
    const raw = [
      screen.width,
      screen.height,
      screen.colorDepth,
      navigator.hardwareConcurrency || 4,
      Intl.DateTimeFormat().resolvedOptions().timeZone || '',
      renderer
    ].join('###')

    let hash = 0
    for (let i = 0; i < raw.length; i++) {
      hash = ((hash << 5) - hash) + raw.charCodeAt(i)
      hash |= 0
    }
    fp = 'hw_' + Math.abs(hash).toString(36)
  } catch {
    fp = 'hw_fallback_' + screen.width + 'x' + screen.height
  }

  try {
    localStorage.setItem('servindoor_device_fp', fp)
  } catch {}
  return fp
}

export function useLoteStatus(loteIdParam = null) {
  const { calibrarComResposta, getSynchronizedServerTime } = useServerTime()

  // Limpa cache antigo se houver para garantir dados frescos do backend
  try { sessionStorage.removeItem('servindoor_live_status_cache') } catch {}

  const loading = ref(true)
  const hasLote = ref(false)
  const modoFesta = ref(false)
  const lote = ref(null)
  const statusInfo = ref({
    status_slug: 'carregando',
    status_label: 'CARREGANDO...',
    badge_class: 'bg-secondary',
    segundos_para_abrir: 0
  })
  // Contadores numéricos omitidos intencionalmente por privacidade/segurança pública
  const minhaReservaSegundos = ref(null)
  const minhaReservaExpiraEmMs = ref(null)
  const minhaReservaToken = ref(null)
  const dataAberturaIso = ref(null)
  const dataFechamentoIso = ref(null)
  const dataFestaIso = ref('2026-10-30T12:00:00')
  const dataFestaFormatada = ref('30/10/2026 às 12:00')
  const temLoteComPrevisao = ref(false)
  const lotePrevisaoId = ref(null)
  const lotePrevisaoAberturaIso = ref(null)
  const loteEncerradoRecente = ref(null)

  const lastStateVersion = ref(null)
  let pollingTimer = null
  let isPollingActive = false
  let isFetching = false
  let pendingFetch = false

  function aplicarDadosCompletos(data) {
    if (!data) return

    if (data.state_version) {
      lastStateVersion.value = data.state_version
    }

    // Sincronização contínua de relógio a partir do timestamp oficial do servidor
    if (data.server_time_ms) {
      calibrarComResposta(data.server_time_ms, Date.now() - 20, Date.now())
    }

    // Proteção anti-regressão de transição para o lote com fuso America/Sao_Paulo obrigatório:
    const isoAbertura = data.data_abertura_iso || data.lote_previsao_abertura_iso
    const msAberturaRaw = data.data_abertura_ms || data.lote_previsao_abertura_ms
    if (data.status_slug === 'agendado' && (isoAbertura || msAberturaRaw)) {
      const aberturaMs = parseSaoPauloTimeToMs(isoAbertura, msAberturaRaw)
      const nowMs = getSynchronizedServerTime()
      if (aberturaMs > 0 && nowMs >= aberturaMs) {
        data.status_slug = 'aberto'
        data.status_label = 'RESGATE LIBERADO'
        data.badge_class = 'bg-success'
        data.pode_resgatar = true
        data.segundos_para_abrir = 0
      }
    }

    hasLote.value = data.has_lote
    modoFesta.value = data.modo_festa
    statusInfo.value = {
      status_slug: data.status_slug,
      status_label: data.status_label,
      badge_class: data.badge_class,
      segundos_para_abrir: data.segundos_para_abrir || 0
    }

    if (data.has_lote) {
      lote.value = {
        id: data.id,
        nome: data.nome,
        secretaria_nome: data.secretaria_nome,
        data_fechamento_formatada: data.data_fechamento_formatada,
        data_fechamento_iso: data.data_fechamento_iso
      }
      dataFechamentoIso.value = data.data_fechamento_iso || null
      dataAberturaIso.value = data.data_abertura_iso
    } else if (lotePrevisaoId.value && data.status_slug === 'aberto') {
      if (!lote.value) {
        lote.value = {
          id: lotePrevisaoId.value,
          nome: 'Lote Oficial',
          secretaria_nome: null,
          data_fechamento_formatada: null,
          data_fechamento_iso: null
        }
      }
    } else {
      lote.value = null
      dataFestaIso.value = data.data_festa_iso || '2026-10-30T12:00:00'
      dataFestaFormatada.value = data.data_festa_formatada || '30/10/2026 às 12:00'
    }

    temLoteComPrevisao.value = !!data.tem_lote_com_previsao
    lotePrevisaoId.value = data.lote_previsao_id || (data.has_lote ? data.id : null)
    lotePrevisaoAberturaIso.value = data.lote_previsao_abertura_iso || null
    loteEncerradoRecente.value = data.lote_encerrado_recente || null
    if (data.data_festa_iso) dataFestaIso.value = data.data_festa_iso
    if (data.data_festa_formatada) dataFestaFormatada.value = data.data_festa_formatada

    minhaReservaSegundos.value = data.minha_reserva_segundos
    minhaReservaExpiraEmMs.value = data.minha_reserva_expira_em_ms
    minhaReservaToken.value = data.minha_reserva_token
    loading.value = false
  }

  async function fetchLiveStatus() {
    if (isFetching) {
      pendingFetch = true
      return
    }
    isFetching = true
    try {
      const deviceFp = getDeviceFingerprint()
      const base = loteIdParam ? `/api/lote/live-status?lote_id=${loteIdParam}&device_fingerprint=${deviceFp}` : `/api/lote/live-status?device_fingerprint=${deviceFp}`
      const t0 = Date.now()
      const res = await fetch(base, { 
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { 'X-Device-Fingerprint': deviceFp }
      })
      const t1 = Date.now()
      if (!res.ok) return
      const data = await res.json()

      if (data.state_version) {
        lastStateVersion.value = data.state_version
      }

      // Calibração de altíssima precisão NTP de relógio com tempo de ida e volta (RTT)
      if (data.server_time_ms) {
        calibrarComResposta(data.server_time_ms, t0, t1)
      }
      aplicarDadosCompletos(data)
    } catch (e) {
      console.warn('Erro ao atualizar live status:', e)
    } finally {
      isFetching = false
      if (pendingFetch) {
        pendingFetch = false
        fetchLiveStatus()
      }
    }
  }

  async function scheduleNextPoll() {
    if (!isPollingActive) return
    if (typeof document !== 'undefined' && document.hidden) {
      return
    }

    // Se o canal SSE estiver conectado e ativo, NÃO FAZ POLLING PERIÓDICO (Zero HTTP requests)
    if (sseConnected.value) {
      if (pollingTimer) {
        clearTimeout(pollingTimer)
        pollingTimer = null
      }
      return
    }

    // Fallback passivo somente se SSE estiver desconectado
    await fetchLiveStatus()
    if (!isPollingActive || sseConnected.value) return

    if (pollingTimer) clearTimeout(pollingTimer)
    pollingTimer = setTimeout(scheduleNextPoll, 45000)
  }

  let eventSource = null
  const sseConnected = ref(false)

  function connectSSE() {
    if (typeof window === 'undefined' || !window.EventSource) return
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }

    try {
      const myDeviceFp = getDeviceFingerprint()
      let streamUrl = `/api/lote/stream?device_fingerprint=${myDeviceFp}`
      if (loteIdParam) streamUrl += `&lote_id=${loteIdParam}`
      if (lastStateVersion.value) streamUrl += `&last_version=${lastStateVersion.value}`

      eventSource = new EventSource(streamUrl)

      eventSource.addEventListener('conectado', (event) => {
        sseConnected.value = true
        // SSE ativo e saudável: cancela qualquer polling pendente
        if (pollingTimer) {
          clearTimeout(pollingTimer)
          pollingTimer = null
        }
      })

      // Reconclia o estado consolidado lido no servidor no momento da conexão
      function handleConsolidatedState(event) {
        try {
          const data = JSON.parse(event.data)
          aplicarDadosCompletos(data)
        } catch (e) {
          console.warn('Erro ao processar ESTADO_CONSOLIDADO SSE:', e)
        }
      }

      eventSource.addEventListener('ESTADO_CONSOLIDADO', handleConsolidatedState)
      eventSource.addEventListener('ESTADO_INICIAL', handleConsolidatedState)

      function handleStreamEvent(event) {
        try {
          const data = JSON.parse(event.data)
          const myFp = getDeviceFingerprint()

          // O stream entrega eventos de todos os lotes. Em uma tela vinculada a
          // um lote específico, ignora eventos de outros lotes.
          if (loteIdParam && data.lote_id && String(data.lote_id) !== String(loteIdParam)) return

          if (data.state_version) {
            lastStateVersion.value = data.state_version
          }

          // 1. Sincronização direta de reserva para o próprio dispositivo em tempo real (<5ms)
          if ((data.device_id && data.device_id === myFp) || (data.token_reserva && data.token_reserva === minhaReservaToken.value)) {
            if (data.tipo === 'reserva_criada') {
              minhaReservaToken.value = data.token_reserva
              minhaReservaExpiraEmMs.value = data.expira_em_ms
              minhaReservaSegundos.value = data.segundos_restantes
            } else if (data.tipo === 'reserva_liberada' || data.tipo === 'resgate_concluido') {
              minhaReservaToken.value = null
              minhaReservaExpiraEmMs.value = null
              minhaReservaSegundos.value = 0
            }
          }



          // 3. Se a data de abertura mudou (adiamento ou antecipação instantânea no painel):
          if (data.data_abertura_iso) {
            dataAberturaIso.value = data.data_abertura_iso
            lotePrevisaoAberturaIso.value = data.data_abertura_iso
          }
          if (data.data_fechamento_iso) {
            dataFechamentoIso.value = data.data_fechamento_iso
            if (lote.value) lote.value.data_fechamento_iso = data.data_fechamento_iso
          }

          // 4. Se o lote mudou de status geral:
          if (data.status_slug) {
            statusInfo.value = {
              status_slug: data.status_slug,
              status_label: data.status_label || statusInfo.value.status_label,
              badge_class: data.badge_class || statusInfo.value.badge_class,
              segundos_para_abrir: data.segundos_para_abrir || 0
            }
          }

          // Muitos produtores publicam somente o fato ocorrido (ex.: reserva
          // concluída), sem incluir o status recalculado. Reconsulta o snapshot
          // para atualizar esgotamento, pausa e encerramento em todas as abas.
          if (data.lote_id || !loteIdParam) {
            fetchLiveStatus().catch(() => {})
          }
        } catch (e) {
          console.warn('Erro ao processar stream event:', e)
        }
      }

      eventSource.addEventListener('LOTE_ATUALIZADO', handleStreamEvent)
      eventSource.addEventListener('RESERVA_ATUALIZADA', handleStreamEvent)

      eventSource.onerror = () => {
        sseConnected.value = false
        // Se a conexão SSE cair, agenda fallback de checagem passiva (a cada 45s) enquanto o navegador reconecta
        if (isPollingActive && !pollingTimer && typeof document !== 'undefined' && !document.hidden) {
          pollingTimer = setTimeout(scheduleNextPoll, 45000)
        }
      }
    } catch (e) {
      console.warn('Erro ao inicializar SSE:', e)
    }
  }

  function disconnectSSE() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
      sseConnected.value = false
    }
  }

  function handleVisibilityChange() {
    if (typeof document === 'undefined') return
    if (document.hidden) {
      // Aba em segundo plano: cancela o timer de polling e fecha conexão SSE para economizar rede/bateria
      if (pollingTimer) {
        clearTimeout(pollingTimer)
        pollingTimer = null
      }
      disconnectSSE()
    } else {
      // Aba voltou a ficar ativa/visível: reconecta SSE e sincroniza
      if (isPollingActive) {
        connectSSE()
        if (pollingTimer) {
          clearTimeout(pollingTimer)
          pollingTimer = null
        }
        fetchLiveStatus().catch(() => {})
      }
    }
  }

  async function startPolling() {
    stopPolling()
    isPollingActive = true
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange)
    }
    
    // 1. O navegador faz a requisição inicial buscando os dados necessários e sincronizando o relógio
    await fetchLiveStatus()
    
    // 2. Após isso, a conexão para conhecimento e atualização contínua vem a partir do SSE
    // (com envio de last_version para garantir que nenhum adiamento ocorrido durante a transição seja perdido)
    connectSSE()
  }

  function stopPolling() {
    isPollingActive = false
    disconnectSSE()
    if (pollingTimer) {
      clearTimeout(pollingTimer)
      pollingTimer = null
    }
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }

  return {
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
    parseSaoPauloTimeToMs,
    fetchLiveStatus,
    startPolling,
    stopPolling,
    sseConnected
  }
}
