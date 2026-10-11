<script setup>
defineProps({
  title: {
    type: String,
    required: true
  },
  value: {
    type: [Number, String],
    default: 0
  },
  subtitle: {
    type: String,
    default: ''
  },
  icon: {
    type: String,
    default: ''
  },
  variant: {
    type: String,
    default: 'cyan'
  },
  badgeText: {
    type: String,
    default: ''
  },
  badgePulse: {
    type: Boolean,
    default: false
  },
  clickable: {
    type: Boolean,
    default: false
  },
  active: {
    type: Boolean,
    default: false
  }
})

defineEmits(['click'])
</script>

<template>
  <div
    :class="[
      'kpi-card',
      'kpi-card-' + variant,
      {
        'kpi-card-clickable': clickable,
        'kpi-card-active': active
      }
    ]"
    @click="$emit('click', $event)"
  >
    <div :class="['kpi-icon-box', 'bg-' + variant + '-subtle', 'text-' + variant]">
      <slot name="icon">
        <i v-if="icon" :class="icon"></i>
      </slot>
    </div>

    <div class="kpi-content">
      <span class="kpi-label">{{ title }}</span>
      <div :class="['kpi-value font-outfit', 'text-' + variant]">
        <span>{{ value }}</span>
        <span v-if="badgeText" :class="['kpi-badge', { 'kpi-badge-pulse': badgePulse }]">
          {{ badgeText }}
        </span>
        <span v-else-if="badgePulse" class="pulse-dot"></span>
      </div>
      <span v-if="subtitle" class="kpi-desc">
        {{ subtitle }}
      </span>
    </div>
  </div>
</template>
