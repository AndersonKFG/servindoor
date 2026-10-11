<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  modelValue: {
    type: [String, Number, Array],
    default: ''
  },
  options: {
    type: Array,
    default: () => []
  },
  placeholder: {
    type: String,
    default: 'Selecione...'
  },
  multiple: {
    type: Boolean,
    default: false
  },
  searchable: {
    type: Boolean,
    default: false
  },
  searchPlaceholder: {
    type: String,
    default: 'Buscar opção...'
  },
  icon: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue', 'change'])

const isOpen = ref(false)
const searchQuery = ref('')
const dropdownRef = ref(null)

const normalizedOptions = computed(() => {
  return props.options.map(opt => {
    if (typeof opt === 'object' && opt !== null) {
      return {
        value: opt.id !== undefined ? opt.id : opt.value,
        label: opt.nome || opt.label || opt.nome_completo || String(opt.value),
        icon: opt.icon || '',
        count: opt.count !== undefined ? opt.count : null
      }
    }
    return {
      value: opt,
      label: String(opt),
      icon: '',
      count: null
    }
  })
})

const filteredOptions = computed(() => {
  if (!searchQuery.value.trim()) return normalizedOptions.value
  const q = searchQuery.value.toLowerCase().trim()
  return normalizedOptions.value.filter(opt => opt.label.toLowerCase().includes(q))
})

const currentLabel = computed(() => {
  if (props.multiple) {
    const selected = Array.isArray(props.modelValue) ? props.modelValue : []
    if (selected.length === 0) return props.placeholder
    if (selected.length === 1) {
      const match = normalizedOptions.value.find(o => o.value === selected[0])
      return match ? match.label : props.placeholder
    }
    return `${props.placeholder}: ${selected.length} selecionados`
  }
  const match = normalizedOptions.value.find(o => o.value === props.modelValue)
  return match ? match.label : props.placeholder
})

function toggleDropdown() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    searchQuery.value = ''
  }
}

function closeDropdown() {
  isOpen.value = false
}

function selectOption(opt) {
  if (props.multiple) {
    const current = Array.isArray(props.modelValue) ? [...props.modelValue] : []
    const idx = current.indexOf(opt.value)
    if (idx >= 0) {
      current.splice(idx, 1)
    } else {
      current.push(opt.value)
    }
    emit('update:modelValue', current)
    emit('change', current)
  } else {
    emit('update:modelValue', opt.value)
    emit('change', opt.value)
    closeDropdown()
  }
}

function selectAll() {
  const allValues = filteredOptions.value.map(o => o.value)
  emit('update:modelValue', allValues)
  emit('change', allValues)
}

function clearAll() {
  emit('update:modelValue', [])
  emit('change', [])
}

function isSelected(val) {
  if (props.multiple) {
    return Array.isArray(props.modelValue) && props.modelValue.includes(val)
  }
  return props.modelValue === val
}

function handleKeyDown(e) {
  if (e.key === 'Escape' && isOpen.value) {
    closeDropdown()
  }
}

function handleClickOutside(e) {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target)) {
    closeDropdown()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div ref="dropdownRef" class="custom-dropdown-container">
    <button
      type="button"
      class="custom-dropdown-trigger"
      :class="{ 'is-open': isOpen }"
      @click="toggleDropdown"
    >
      <i v-if="icon" :class="[icon, 'trigger-leading-icon']"></i>
      <span class="trigger-label">{{ currentLabel }}</span>
      <span
        v-if="multiple && Array.isArray(modelValue) && modelValue.length > 0"
        class="badge-count"
      >
        {{ modelValue.length }}
      </span>
      <i class="bi bi-chevron-down trigger-chevron" :class="{ 'rotate': isOpen }"></i>
    </button>

    <div v-if="isOpen" class="custom-dropdown-menu">
      <div v-if="searchable" class="dropdown-search-box">
        <i class="bi bi-search search-icon"></i>
        <input
          v-model="searchQuery"
          type="text"
          class="dropdown-search-input"
          :placeholder="searchPlaceholder"
          @click.stop
        />
      </div>

      <div v-if="multiple" class="dropdown-actions-row">
        <button type="button" class="btn-quick-link" @click.stop="selectAll">
          Selecionar Todas
        </button>
        <button
          v-if="Array.isArray(modelValue) && modelValue.length > 0"
          type="button"
          class="btn-quick-link text-danger"
          @click.stop="clearAll"
        >
          Limpar ({{ modelValue.length }})
        </button>
      </div>

      <div class="dropdown-options-list">
        <div
          v-for="opt in filteredOptions"
          :key="opt.value"
          class="dropdown-option-item"
          :class="{ 'is-selected': isSelected(opt.value) }"
          @click="selectOption(opt)"
        >
          <input
            v-if="multiple"
            type="checkbox"
            :checked="isSelected(opt.value)"
            class="option-checkbox"
            @click.stop="selectOption(opt)"
          />
          <i v-if="opt.icon" :class="[opt.icon, 'option-icon']"></i>
          <span class="option-text">{{ opt.label }}</span>
          <span v-if="opt.count !== null" class="option-count">{{ opt.count }}</span>
          <i
            v-if="!multiple && isSelected(opt.value)"
            class="bi bi-check2 selected-check"
          ></i>
        </div>

        <div v-if="filteredOptions.length === 0" class="dropdown-empty-message">
          Nenhuma opção encontrada
        </div>
      </div>
    </div>
  </div>
</template>
