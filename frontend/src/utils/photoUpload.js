const MAX_FILE_SIZE = 10 * 1024 * 1024
const MAX_JPEG_SIZE = 4 * 1024 * 1024
const MAX_DIMENSION = 1600
const PHOTO_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

export async function preparePhotoUpload(file) {
  if (!PHOTO_TYPES.has(file.type)) {
    throw new Error('Selecione uma foto nos formatos JPG, PNG ou WebP.')
  }
  if (!file.size || file.size > MAX_FILE_SIZE) {
    throw new Error('Selecione uma foto de até 10 MB.')
  }

  const url = URL.createObjectURL(file)
  try {
    const image = await new Promise((resolve, reject) => {
      const photo = new Image()
      photo.onload = () => resolve(photo)
      photo.onerror = () => reject(new Error('Não foi possível abrir esta imagem. Selecione outra foto.'))
      photo.src = url
    })
    if (!image.naturalWidth || !image.naturalHeight) {
      throw new Error('A imagem selecionada é inválida. Selecione outra foto.')
    }

    const scale = Math.min(1, MAX_DIMENSION / Math.max(image.naturalWidth, image.naturalHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Não foi possível preparar a foto neste navegador. Tente outro navegador.')
    // Imagens transparentes recebem fundo branco ao serem convertidas para JPEG.
    context.fillStyle = 'white'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const photo = canvas.toDataURL('image/jpeg', 0.88)
    if (!photo.startsWith('data:image/jpeg;base64,') || atob(photo.split(',')[1]).length > MAX_JPEG_SIZE) {
      throw new Error('Não foi possível reduzir a foto para envio. Selecione uma imagem menor.')
    }
    return photo
  } finally {
    URL.revokeObjectURL(url)
  }
}
