export function limparCPF(cpf) {
  if (!cpf) return ''
  const digitos = String(cpf).replace(/\D/g, '')
  if (!digitos) return ''
  return digitos.padStart(11, '0').slice(-11)
}

export function formatarCPF(cpf) {
  const c = limparCPF(cpf)
  if (c.length === 11) {
    return `${c.slice(0, 3)}.${c.slice(3, 6)}.${c.slice(6, 9)}-${c.slice(9)}`
  }
  return cpf || ''
}

export function mascararCPF(cpf) {
  const c = limparCPF(cpf)
  if (c.length === 11) {
    return `${c.slice(0, 3)}.***.***-${c.slice(9)}`
  }
  return cpf || ''
}

export function validarCPFMatematico(cpf) {
  const c = limparCPF(cpf)
  if (c.length !== 11) return false
  if (/^(\d)\1{10}$/.test(c)) return false

  let soma = 0
  for (let i = 0; i < 9; i++) {
    soma += parseInt(c[i], 10) * (10 - i)
  }
  let resto = (soma * 10) % 11
  let d1 = resto === 10 ? 0 : resto
  if (d1 !== parseInt(c[9], 10)) return false

  soma = 0
  for (let i = 0; i < 10; i++) {
    soma += parseInt(c[i], 10) * (11 - i)
  }
  resto = (soma * 10) % 11
  let d2 = resto === 10 ? 0 : resto
  if (d2 !== parseInt(c[10], 10)) return false

  return true
}
