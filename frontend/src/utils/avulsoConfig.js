export const vinculos = ['Efetivo', 'Comissionado', 'Contrato Temporário', 'Estagiário', 'Terceirizado', 'Prestador de Serviço', 'Aposentado']

export function novaConfiguracaoAvulso() {
  return {
    temporizado: true,
    exige_validacao: true,
    campos: Object.fromEntries(['secretaria_id', 'setor', 'vinculo'].map(campo => [campo, { modo: 'livre', valor: '' }]))
  }
}
