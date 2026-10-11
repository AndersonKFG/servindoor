import { ref } from 'vue'

const serverClockOffsetMs = ref(0)
const isCalibrated = ref(false)

export function useServerTime() {
  async function calibrarRelogioComServidor(force = false) {
    if (isCalibrated.value && !force) return
    try {
      const t0 = performance.now()
      const clientDate = Date.now()
      const resp = await fetch('/api/time?t=' + clientDate, { cache: 'no-store' })
      if (!resp.ok) return
      const data = await resp.json()
      const t1 = performance.now()
      const clientDateAfter = Date.now()

      const rtt = Math.max(0, t1 - t0)
      const oneWayDelay = rtt / 2
      const offset = Math.round((data.server_time_ms + oneWayDelay) - clientDateAfter)

      serverClockOffsetMs.value = offset
      isCalibrated.value = true
    } catch (e) {
      console.warn('Sync NTP ignorado:', e)
    }
  }

  function calibrarComResposta(serverTimeMs, reqStartMs, resEndMs) {
    if (!serverTimeMs) return
    const rtt = Math.max(0, resEndMs - reqStartMs)
    const oneWayDelay = rtt / 2
    const offset = Math.round((serverTimeMs + oneWayDelay) - resEndMs)

    if (!isCalibrated.value || Math.abs(offset - serverClockOffsetMs.value) > 300) {
      serverClockOffsetMs.value = offset
      isCalibrated.value = true
    }
  }

  function getSynchronizedServerTime() {
    return Date.now() + serverClockOffsetMs.value
  }

  return {
    serverClockOffsetMs,
    isCalibrated,
    calibrarRelogioComServidor,
    calibrarComResposta,
    getSynchronizedServerTime
  }
}
