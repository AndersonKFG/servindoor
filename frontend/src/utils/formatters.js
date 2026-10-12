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
    const d = new Date(dataIso)
    if (isNaN(d.getTime())) return dataIso
    const dia = String(d.getDate()).padStart(2, '0')
    const mes = String(d.getMonth() + 1).padStart(2, '0')
    const ano = d.getFullYear()
    const hora = String(d.getHours()).padStart(2, '0')
    const min = String(d.getMinutes()).padStart(2, '0')
    return `${dia}/${mes}/${ano} às ${hora}:${min}`
  } catch {
    return dataIso
  }
}

export function formatarDataHoraSp(dataIso) {
  if (!dataIso) return '-'
  const data = new Date(dataIso)
  if (isNaN(data.getTime())) return dataIso
  return data.toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })
}

export function paraDatetimeLocalSp(dataIso) {
  if (!dataIso) return ''
  const data = new Date(dataIso)
  if (isNaN(data.getTime())) return ''
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
    const d = new Date(dataIso)
    if (isNaN(d.getTime())) return dataIso
    const dia = String(d.getDate()).padStart(2, '0')
    const mes = String(d.getMonth() + 1).padStart(2, '0')
    const ano = d.getFullYear()
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
