import { ref, onMounted, onUnmounted } from 'vue'
import { useServerTime } from './useServerTime'

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

export function useLoteStatus(loteIdParam = null) {
  const { calibrarComResposta } = useServerTime()
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
  const reservasAtivas = ref(0)
  const vagasDisponiveis = ref(0)
  const minhaReservaSegundos = ref(null)
  const minhaReservaExpiraEmMs = ref(null)
  const minhaReservaToken = ref(null)
  const dataAberturaIso = ref(null)
  const dataFestaIso = ref('2026-10-30T14:00:00')
  const dataFestaFormatada = ref('30/10/2026 às 14:00')

  let pollingInterval = null

  async function fetchLiveStatus() {
    try {
      const deviceFp = getDeviceFingerprint()
      const base = loteIdParam ? `/api/lote/live-status?lote_id=${loteIdParam}&device_fingerprint=${deviceFp}` : `/api/lote/live-status?device_fingerprint=${deviceFp}`
      const t0 = Date.now()
      const res = await fetch(base, { 
        cache: 'no-store',
        headers: { 'X-Device-Fingerprint': deviceFp }
      })
      const t1 = Date.now()
      if (!res.ok) return
      const data = await res.json()

      // Sincronização contínua de relógio
      if (data.server_time_ms) {
        calibrarComResposta(data.server_time_ms, t0, t1)
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
          quantidade_total: data.quantidade_total,
          quantidade_resgatada: data.quantidade_resgatada,
          data_fechamento_formatada: data.data_fechamento_formatada
        }
        reservasAtivas.value = data.reservas_ativas || 0
        vagasDisponiveis.value = data.vagas_disponiveis || 0
        dataAberturaIso.value = data.data_abertura_iso
      } else {
        lote.value = null
        dataFestaIso.value = data.data_festa_iso || '2026-10-30T14:00:00'
        dataFestaFormatada.value = data.data_festa_formatada || '30/10/2026 às 14:00'
      }

      minhaReservaSegundos.value = data.minha_reserva_segundos
      minhaReservaExpiraEmMs.value = data.minha_reserva_expira_em_ms
      minhaReservaToken.value = data.minha_reserva_token
      loading.value = false
    } catch (e) {
      console.warn('Erro ao atualizar live status:', e)
    }
  }

  function startPolling(intervalMs = 1500) {
    fetchLiveStatus()
    stopPolling()
    pollingInterval = setInterval(fetchLiveStatus, intervalMs)
  }

  function stopPolling() {
    if (pollingInterval) {
      clearInterval(pollingInterval)
      pollingInterval = null
    }
  }

  return {
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
  }
}
