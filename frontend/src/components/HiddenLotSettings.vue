<script setup>
import { vinculos } from '../utils/avulsoConfig'

defineProps({
  config: { type: Object, required: true },
  secretarias: { type: Array, default: () => [] }
})
const campos = [{ nome: 'secretaria_id', label: 'Secretaria' }, { nome: 'setor', label: 'Setor' }, { nome: 'vinculo', label: 'Vínculo' }]
</script>

<template>
  <section class="modal-section">
    <div class="modal-info-grid">
      <label class="modal-field-card">
        <input v-model="config.temporizado" type="checkbox" /> Reservar vaga por cinco minutos
      </label>
      <label class="modal-field-card">
        <input v-model="config.exige_validacao" type="checkbox" /> Exigir análise do superadministrador
      </label>
    </div>
    <p class="text-subtle small">Sem prazo, a vaga é consumida somente no envio. Sem análise, o ingresso é aprovado e enviado por e-mail automaticamente.</p>
  </section>
  <section class="modal-section">
    <h3>Preenchimento dos campos</h3>
    <div v-for="campo in campos" :key="campo.nome" class="modal-field-card mb-3">
      <label :for="`avulso-modo-${campo.nome}`" class="form-label">{{ campo.label }}</label>
      <select :id="`avulso-modo-${campo.nome}`" v-model="config.campos[campo.nome].modo" class="form-select">
        <option value="livre">Livre</option>
        <option value="preenchido">Pré-preenchido e editável</option>
        <option value="fixo">Pré-preenchido e travado</option>
      </select>
      <template v-if="config.campos[campo.nome].modo !== 'livre'">
        <label :for="`avulso-valor-${campo.nome}`" class="form-label mt-2">Valor obrigatório</label>
        <select v-if="campo.nome === 'secretaria_id'" :id="`avulso-valor-${campo.nome}`" v-model="config.campos[campo.nome].valor" class="form-select" required>
          <option value="">Selecione uma secretaria</option>
          <option v-for="sec in secretarias" :key="sec.id" :value="String(sec.id)">{{ sec.nome }}</option>
        </select>
        <select v-else-if="campo.nome === 'vinculo'" :id="`avulso-valor-${campo.nome}`" v-model="config.campos[campo.nome].valor" class="form-select" required>
          <option value="">Selecione um vínculo</option>
          <option v-for="vinculo in vinculos" :key="vinculo" :value="vinculo">{{ vinculo }}</option>
        </select>
        <input v-else :id="`avulso-valor-${campo.nome}`" v-model="config.campos[campo.nome].valor" class="form-control" maxlength="200" required />
      </template>
    </div>
    <p class="text-subtle small">Todos os demais campos e a foto continuam obrigatórios.</p>
  </section>
</template>
