<template>
  <button v-if="hasStarterCode && !readonly" type="button" class="btn btn-sm btn-outline-secondary mt-2"
    :disabled="code === starterCode" @click="resetToTemplate">
    <AppIcon name="retry" />Вернуть шаблон
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ question: Object, modelValue: Object, readonly: Boolean })
const emit = defineEmits(['update:modelValue'])
const starterCode = computed(() => props.question.ui_config?.starter_code)
const hasStarterCode = computed(() => typeof starterCode.value === 'string')
const code = computed(() => props.modelValue?.code ?? starterCode.value ?? '')
const language = computed(() => props.question.ui_config?.lang || props.question.check_config?.lang || 'python')

function resetToTemplate() {
  if (props.readonly || !hasStarterCode.value || code.value === starterCode.value) return
  if (!confirm('Вернуться к исходному шаблону? Текущие изменения в коде будут заменены.')) return
  emit('update:modelValue', { code: starterCode.value, lang: language.value })
}
</script>
