<template>
  <div>
    <textarea
      class="form-control font-monospace ge-code-editor"
      rows="12"
      :value="modelValue?.code || question.ui_config?.starter_code || ''"
      :disabled="readonly"
      @input="emit('update:modelValue', { code: $event.target.value, lang: question.ui_config?.lang || 'python' })"
      spellcheck="false"
    />
    <div v-if="question.allow_intermediate_check && !readonly" class="mt-2">
      <button class="btn btn-sm btn-outline-primary" :disabled="checkResult?.check_state === 'checking'" @click="emit('check')">
        <span v-if="checkResult?.check_state === 'checking'" class="spinner-border spinner-border-sm me-1" />
        Проверить
      </button>
    </div>
    <CheckResult :result="checkResult" />
  </div>
</template>

<script setup>
import CheckResult from '../CheckResult.vue'
defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue', 'check'])
</script>
