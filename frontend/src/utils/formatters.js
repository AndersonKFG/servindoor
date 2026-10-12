export function formatarCpf(cpf) {
  if (!cpf) return ''
  const digits = String(cpf).replace(/\D/g, '')
  if (digits.length !== 11) return cpf
  return digits.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4')
}

export function mascararCpf(cpf) {
  if (!cpf) return ''
  const digits = String(cpf).replace(/\D/g, '')
  if (digits.length !== 11) return cpf
  return `${digits.slice(0, 3)}.***.***-${digits.slice(9)}`
}

export function formatarTelefone(telefone) {
  if (!telefone) return '-'
  const digits = String(telefone).replace(/\D/g, '')
  if (digits.length === 11) {
    return digits.replace(/(\d{2})(\d{5})(\d{4})/, '($1) $2-$3')
  }
  if (digits.length === 10) {
    return digits.replace(/(\d{2})(\d{4})(\d{4})/, '($1) $2-$3')
  }
  return telefone
}

export function formatarData(dataIso) {
  if (!dataIso) return '-'
  try {
    const localizado = paraDatetimeLocalSp(dataIso)
    if (!localizado) return dataIso
    const [data, hora] = localizado.split('T')
    const [ano, mes, dia] = data.split('-')
    return `${dia}/${mes}/${ano} às ${hora}`
  } catch {
    return dataIso
  }
}

function lerInstanteSp(valor) {
  if (valor instanceof Date || typeof valor === 'number') return new Date(valor)
  const iso = String(valor).trim().replace(' ', 'T')
  // Textos já formatados e datas de calendário não devem ser reinterpretados.
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(iso)) return null
  // Compatibilidade com metadados locais antigos que não incluíam o offset.
  const temFuso = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso)
  return new Date(temFuso ? iso : `${iso}-03:00`)
}

export function formatarDataHoraSp(dataIso) {
  if (!dataIso) return '-'
  const data = lerInstanteSp(dataIso)
  if (!data || isNaN(data.getTime())) return dataIso
  return data.toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })
}

export function paraDatetimeLocalSp(dataIso) {
  if (!dataIso) return ''
  const data = lerInstanteSp(dataIso)
  if (!data || isNaN(data.getTime())) return ''
  const partes = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(data)
  const campos = Object.fromEntries(partes.map(({ type, value }) => [type, value]))
  return `${campos.year}-${campos.month}-${campos.day}T${campos.hour}:${campos.minute}`
}

export function formatarDataApenas(dataIso) {
  if (!dataIso) return '-'
  try {
    const calendario = String(dataIso).match(/^(\d{4})-(\d{2})-(\d{2})$/)
    if (calendario) return `${calendario[3]}/${calendario[2]}/${calendario[1]}`
    const localizado = paraDatetimeLocalSp(dataIso)
    if (!localizado) return dataIso
    const [ano, mes, dia] = localizado.split('T')[0].split('-')
    return `${dia}/${mes}/${ano}`
  } catch {
    return dataIso
  }
}
export function formatarDataNascimento(dataStr) {
  if (!dataStr) return 'Não informada'
  const trimmed = String(dataStr).trim()
  if (!trimmed) return 'Não informada'

  // Converte YYYY-MM-DD (com ou sem timestamp ISO) para DD-MM-YYYY
  const matchIso = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (matchIso) {
    const [, ano, mes, dia] = matchIso
    return `${dia}-${mes}-${ano}`
  }

  // Converte DD/MM/YYYY ou DD-MM-YYYY para DD-MM-YYYY
  const matchBr = trimmed.match(/^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})/)
  if (matchBr) {
    const [, dia, mes, ano] = matchBr
    return `${dia.padStart(2, '0')}-${mes.padStart(2, '0')}-${ano}`
  }

  return trimmed
}
