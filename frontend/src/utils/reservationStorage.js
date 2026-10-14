const TOKEN_PREFIX = 'festa_reserva_token_'
const CURRENT_TOKEN_KEY = 'festa_reserva_token_atual'

export function getTabReservationToken(loteId = null, storage = globalThis.sessionStorage) {
  try {
    return storage.getItem(loteId ? TOKEN_PREFIX + loteId : CURRENT_TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function clearTabReservationToken(loteId, storage = globalThis.sessionStorage) {
  try {
    const token = storage.getItem(TOKEN_PREFIX + loteId)
    storage.removeItem(TOKEN_PREFIX + loteId)
    if (token && storage.getItem(CURRENT_TOKEN_KEY) === token) storage.removeItem(CURRENT_TOKEN_KEY)
  } catch {}
}

export function saveTabReservationToken(loteId, token, storage = globalThis.sessionStorage) {
  if (!token) return clearTabReservationToken(loteId, storage)
  try {
    storage.setItem(TOKEN_PREFIX + loteId, token)
    storage.setItem(CURRENT_TOKEN_KEY, token)
  } catch {}
}
