<template>
  <div>
    <div v-for="field in fields" :key="field.name" class="d-flex align-items-center gap-2 mb-2">
      <label class="form-label mb-0 text-nowrap" style="min-width:60px">{{ field.label }}</label>
      <input
        type="text"
        class="form-control form-control-sm"
        style="max-width:120px"
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

const props = defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue'])

const fields = computed(() => props.question.ui_config?.fields || [])

function update(name, value) {
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}
</script>
