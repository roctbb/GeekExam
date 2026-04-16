<template>
  <div>
    <textarea v-if="question.ui_config?.multiline"
      class="form-control"
      rows="4"
      :value="modelValue?.text || ''"
      :disabled="readonly"
      @input="emit('update:modelValue', { text: $event.target.value })"
    />
    <input v-else
      type="text"
      class="form-control"
      :value="modelValue?.text || ''"
      :disabled="readonly"
      @input="emit('update:modelValue', { text: $event.target.value })"
    />
    <CheckResult :result="checkResult" />
  </div>
</template>

<script setup>
import CheckResult from '../CheckResult.vue'
defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue'])
</script>
