import { ref } from 'vue'

const serverClockOffsetMs = ref(0)
const isCalibrated = ref(false)

export function useServerTime() {
  async function calibrarRelogioComServidor() {
    try {
      // Faz até 3 medições rápidas e escolhe a de menor latência (algoritmo NTP)
      let melhorOffset = null
      let menorRtt = Infinity

      for (let i = 0; i < 3; i++) {
        const t0 = performance.now()
        const clientDate = Date.now()
        const resp = await fetch('/api/time?t=' + clientDate, { cache: 'no-store' })
        if (!resp.ok) continue
        const data = await resp.json()
        const t1 = performance.now()
        const clientDateAfter = Date.now()

        const rtt = t1 - t0
        if (rtt < menorRtt) {
          menorRtt = rtt
          const oneWayDelay = rtt / 2
          melhorOffset = (data.server_time_ms + oneWayDelay) - clientDateAfter
        }
      }

      if (melhorOffset !== null) {
        serverClockOffsetMs.value = Math.round(melhorOffset)
        isCalibrated.value = true
        console.log(`[TimeSync NTP] Relógio calibrado! Desvio corrigido: ${serverClockOffsetMs.value}ms (Latência: ${Math.round(menorRtt)}ms)`)
      }
    } catch (e) {
      console.warn('Sync NTP ignorado:', e)
    }
  }

  function calibrarComResposta(serverTimeMs, reqStartMs, resEndMs) {
    if (!serverTimeMs) return
    const rtt = Math.max(0, resEndMs - reqStartMs)
    const oneWayDelay = rtt / 2
    const offset = Math.round((serverTimeMs + oneWayDelay) - resEndMs)

    if (!isCalibrated.value || Math.abs(offset - serverClockOffsetMs.value) > 400) {
      serverClockOffsetMs.value = offset
      isCalibrated.value = true
      console.log(`[TimeSync Live] Ajustado via LiveStatus! Desvio corrigido: ${serverClockOffsetMs.value}ms`)
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
