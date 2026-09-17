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
    <div v-if="question.allow_intermediate_check && question.check_type !== 'manual' && !readonly" class="mt-2">
      <button class="btn btn-sm btn-outline-primary" :disabled="checkResult?.check_state === 'checking'" @click="emit('check')">
        <span v-if="checkResult?.check_state === 'checking'" class="spinner-border spinner-border-sm me-1" />
        Проверить
      </button>
    </div>
    <CheckResult :result="checkResult" :max-points="question.max_points" />
  </div>
</template>

<script setup>
import CheckResult from '../CheckResult.vue'
import CodeEditor from '../CodeEditor.vue'
defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue', 'check'])
</script>
