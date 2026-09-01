import { ref } from 'vue'

const serverClockOffsetMs = ref(0)
const isCalibrated = ref(false)

export function useServerTime() {
  async function calibrarRelogioComServidor() {
    try {
      const t0 = performance.now()
      const clientDate = Date.now()
      const resp = await fetch('/api/time?t=' + clientDate, { cache: 'no-store' })
      if (!resp.ok) return
      const data = await resp.json()
      const t1 = performance.now()
      const clientDateAfter = Date.now()

      const rtt = t1 - t0
      const oneWayDelay = rtt / 2
      serverClockOffsetMs.value = (data.server_time_ms + oneWayDelay) - clientDateAfter
      isCalibrated.value = true
    } catch (e) {
      console.warn('Sync NTP ignorado:', e)
    }
  }

  function getSynchronizedServerTime() {
    return Date.now() + serverClockOffsetMs.value
  }

  return {
    serverClockOffsetMs,
    isCalibrated,
    calibrarRelogioComServidor,
    getSynchronizedServerTime
  }
}
