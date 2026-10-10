<template>
  <div>
    <CodeEditor
      :key="question.id"
      :rows="question.ui_config?.rows || 12"
      :model-value="modelValue?.code ?? question.ui_config?.starter_code ?? ''"
      :language="question.ui_config?.lang || question.check_config?.lang || 'python'"
      :label="question.title || 'Код решения'"
      :readonly="readonly"
      @update:model-value="emit('update:modelValue', { code: $event, lang: question.ui_config?.lang || question.check_config?.lang || 'python' })"
    />
    <CheckResult :result="checkResult" :max-points="question.max_points" />
  </div>
</template>

<script setup>
import CheckResult from '../CheckResult.vue'
import CodeEditor from '../CodeEditor.vue'
defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue'])
</script>
