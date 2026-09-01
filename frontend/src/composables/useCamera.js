import { ref } from 'vue'

export function useCamera() {
  const stream = ref(null)
  const isStreaming = ref(false)
  const cameraError = ref(null)
  const capturedPhoto = ref(null)
  const availableCameras = ref([])
  const selectedDeviceId = ref('')
  const isMobile = ref(false)

  // Detecta se é dispositivo móvel (celular / tablet)
  function checkIfMobile() {
    if (typeof navigator === 'undefined') return false
    const ua = navigator.userAgent || ''
    const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua) || (isTouch && window.innerWidth <= 768)
  }

  isMobile.value = checkIfMobile()

  // Lista todos os dispositivos de vídeo disponíveis no aparelho
  async function loadAvailableCameras() {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
        availableCameras.value = []
        return
      }
      const devices = await navigator.mediaDevices.enumerateDevices()
      const videoDevices = devices.filter(d => d.kind === 'videoinput')
      
      availableCameras.value = videoDevices.map((d, idx) => ({
        deviceId: d.deviceId,
        label: d.label || `Câmera ${idx + 1}`
      }))

      if (availableCameras.value.length > 0 && !selectedDeviceId.value) {
        selectedDeviceId.value = availableCameras.value[0].deviceId
      }
    } catch (err) {
      console.warn('Erro ao listar câmeras:', err)
    }
  }

  async function startCamera(videoElement, deviceId = null) {
    cameraError.value = null
    try {
      if (stream.value) {
        stopCamera()
      }

      isMobile.value = checkIfMobile()

      let videoConstraints = {
        width: { ideal: 640 },
        height: { ideal: 640 }
      }

      // Se um deviceId específico foi selecionado (computador com múltiplas câmeras)
      if (deviceId || selectedDeviceId.value) {
        const targetId = deviceId || selectedDeviceId.value
        videoConstraints.deviceId = { exact: targetId }
      } else {
        // No celular, prioriza explicitamente a frontal (user)
        videoConstraints.facingMode = 'user'
      }

      let mediaStream
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
          video: videoConstraints,
          audio: false
        })
      } catch (e) {
        // Fallback genérico se a restrição exata falhar
        mediaStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 640 } },
          audio: false
        })
      }

      stream.value = mediaStream
      if (videoElement) {
        videoElement.srcObject = mediaStream
        await videoElement.play()
        isStreaming.value = true
      }

      // Atualiza a lista de câmeras com os rótulos agora que a permissão foi concedida
      await loadAvailableCameras()

      return true
    } catch (err) {
      console.error('Erro ao acessar a câmera:', err)
      cameraError.value = 'Permissão de câmera negada ou dispositivo não disponível. Por favor, autorize o acesso à câmera no seu navegador.'
      isStreaming.value = false
      return false
    }
  }

  async function switchCamera(videoElement, deviceId) {
    selectedDeviceId.value = deviceId
    return await startCamera(videoElement, deviceId)
  }

  function capturePhoto(videoElement) {
    if (!videoElement || !isStreaming.value) return null
    try {
      const canvas = document.createElement('canvas')
      const width = videoElement.videoWidth || 640
      const height = videoElement.videoHeight || 640
      canvas.width = width
      canvas.height = height

      const ctx = canvas.getContext('2d')
      
      // Se for frontal ou webcam padrão, espelha para visual natural de selfie
      ctx.translate(width, 0)
      ctx.scale(-1, 1)
      ctx.drawImage(videoElement, 0, 0, width, height)

      const base64 = canvas.toDataURL('image/jpeg', 0.88)
      capturedPhoto.value = base64
      return base64
    } catch (e) {
      console.error('Erro ao capturar foto:', e)
      return null
    }
  }

  function resetPhoto() {
    capturedPhoto.value = null
  }

  function stopCamera() {
    if (stream.value) {
      stream.value.getTracks().forEach(track => track.stop())
      stream.value = null
    }
    isStreaming.value = false
  }

  return {
    stream,
    isStreaming,
    cameraError,
    capturedPhoto,
    availableCameras,
    selectedDeviceId,
    isMobile,
    loadAvailableCameras,
    startCamera,
    switchCamera,
    capturePhoto,
    resetPhoto,
    stopCamera
  }
}
