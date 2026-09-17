<template>
  <div>
    <CodeEditor v-if="question.ui_config?.multiline"
      :key="question.id"
      :rows="question.ui_config?.rows || 4"
      :model-value="modelValue?.text ?? ''"
      :language="question.ui_config?.lang || ''"
      :label="question.title || 'Текст ответа'"
      :placeholder="question.ui_config?.placeholder || ''"
      :readonly="readonly"
      @update:model-value="emit('update:modelValue', { text: $event })"
    />
    <input v-else
      type="text"
      class="form-control"
      :value="modelValue?.text || ''"
      :disabled="readonly"
      @input="emit('update:modelValue', { text: $event.target.value })"
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
