<template>
  <div class="ge-multi-input">
    <div v-for="field in fields" :key="field.name" class="ge-multi-input-row">
      <span class="ge-multi-input-label ge-markdown" v-html="labelHtml(field)" />
      <input
        type="text"
        class="form-control form-control-sm ge-multi-input-control"
        :value="modelValue?.[field.name] || ''"
        :disabled="readonly"
        @input="update(field.name, $event.target.value)"
      />
    </div>
    <CheckResult :result="checkResult" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import CheckResult from '../CheckResult.vue'
import { renderMarkdown } from '../../utils/markdown'

const props = defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue'])

const fields = computed(() => props.question.ui_config?.fields || [])

function update(name, value) {
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}

function labelHtml(field) {
  return renderMarkdown(field.label || field.name || '', { inline: true })
}
</script>
