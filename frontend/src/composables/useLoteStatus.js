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

export function getDeviceId() {
  const storageKey = 'servindoor_device_id'
  try {
    const cached = localStorage.getItem(storageKey)
    if (cached) return cached
  } catch {}

  let deviceId = ''
  try {
    deviceId = crypto.randomUUID()
  } catch {
    deviceId = `device-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
  }

  try {
    localStorage.setItem(storageKey, deviceId)
  } catch {}
  return deviceId
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
  let isSSEActive = false

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
    const restanteReservaMs = data.minha_reserva_milissegundos == null
      ? NaN
      : Number(data.minha_reserva_milissegundos)
    const restantePeloServidorMs = data.minha_reserva_expira_em_ms == null || data.server_time_ms == null
      ? NaN
      : Number(data.minha_reserva_expira_em_ms) - Number(data.server_time_ms)
    minhaReservaExpiraEmMs.value = Number.isFinite(restanteReservaMs) && restanteReservaMs >= 0
      ? Date.now() + restanteReservaMs
      : Number.isFinite(restantePeloServidorMs) && restantePeloServidorMs >= 0
        ? Date.now() + restantePeloServidorMs
        : data.minha_reserva_expira_em_ms
    minhaReservaToken.value = data.minha_reserva_token
    loading.value = false
  }

  let eventSource = null
  const sseConnected = ref(false)
  const sseConnectionError = ref(false)

  function connectSSE() {
    if (typeof window === 'undefined' || !window.EventSource) {
      sseConnected.value = false
      sseConnectionError.value = true
      loading.value = false
      return
    }
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
        sseConnectionError.value = false
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
          const tipoReserva = ['reserva_criada', 'reserva_liberada', 'resgate_concluido'].includes(data.tipo)
          const loteAtualId = lote.value?.id || lotePrevisaoId.value

          const eventVersion = Number(event.lastEventId || data.state_version || 0)
          if (eventVersion) {
            if (lastStateVersion.value && eventVersion <= Number(lastStateVersion.value)) return
            lastStateVersion.value = eventVersion
          }

          // Mudanças administrativas podem alterar qual lote a Home deve exibir.
          // Reabre o stream para receber um novo snapshot consolidado via SSE.
          if (!loteIdParam && data.tipo === 'LOTE_ATUALIZADO' &&
            (data.nome || data.deletado || data.importado || data.restaurado)) {
            connectSSE()
            return
          }

          // O stream entrega eventos de todos os lotes. Em uma tela vinculada a
          // um lote específico, ignora eventos de outros lotes.
          if (loteIdParam && data.lote_id && String(data.lote_id) !== String(loteIdParam)) return

          // Na home, alterações de reserva em lotes que não estão sendo exibidos
          // não afetam o estado atual.
          if (!loteIdParam && data.lote_id && loteAtualId && String(data.lote_id) !== String(loteAtualId)) {
            return
          }
          // 1. Sincronização direta de reserva para o próprio dispositivo em tempo real (<5ms)
          const correspondeAoNavegador = (data.device_id && data.device_id === myFp) ||
            (data.token_reserva && data.token_reserva === minhaReservaToken.value)
          const correspondeAoFingerprint = data.device_fingerprint && data.device_fingerprint === myFp
          if (correspondeAoNavegador || correspondeAoFingerprint) {
            if (data.tipo === 'reserva_criada') {
              if (correspondeAoNavegador) minhaReservaToken.value = data.token_reserva
              minhaReservaSegundos.value = data.segundos_restantes
              const restanteReservaMs = Number(data.milissegundos_restantes)
              minhaReservaExpiraEmMs.value = Number.isFinite(restanteReservaMs) && restanteReservaMs >= 0
                ? Date.now() + restanteReservaMs
                : data.expira_em_ms
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
              pode_resgatar: data.pode_resgatar ?? statusInfo.value.pode_resgatar,
              segundos_para_abrir: data.segundos_para_abrir || 0
            }
          }

          // As alterações de reserva carregam o status público recalculado no
          // próprio evento SSE.
          if (tipoReserva && data.status_slug) {
            statusInfo.value.segundos_para_abrir = data.segundos_para_abrir || 0
          }
        } catch (e) {
          console.warn('Erro ao processar stream event:', e)
        }
      }

      eventSource.addEventListener('LOTE_ATUALIZADO', handleStreamEvent)
      eventSource.addEventListener('RESERVA_ATUALIZADA', handleStreamEvent)

      eventSource.onerror = () => {
        sseConnected.value = false
        sseConnectionError.value = true
        loading.value = false
        // EventSource faz a reconexão automaticamente. Não iniciar polling HTTP.
      }
    } catch (e) {
      console.warn('Erro ao inicializar SSE:', e)
      sseConnected.value = false
      sseConnectionError.value = true
      loading.value = false
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
      // Aba em segundo plano: fecha a conexão SSE para economizar rede/bateria.
      disconnectSSE()
    } else {
      // Aba voltou a ficar ativa/visível: reconecta SSE e sincroniza
      if (isSSEActive) {
        connectSSE()
      }
    }
  }

  function startSSE() {
    stopSSE()
    isSSEActive = true
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange)
    }

    // A Home recebe o snapshot inicial e todas as atualizações pelo próprio SSE.
    connectSSE()
  }

  function stopSSE() {
    isSSEActive = false
    disconnectSSE()
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
    startSSE,
    stopSSE,
    sseConnected,
    sseConnectionError
  }
}
