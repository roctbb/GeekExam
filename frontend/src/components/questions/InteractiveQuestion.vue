<template>
  <div>
    <component
      v-if="component"
      :is="component"
      :question="question"
      :modelValue="modelValue"
      :readonly="readonly"
      @update:modelValue="emit('update:modelValue', $event)"
    />
    <div v-else class="alert alert-warning">
      Интерактивный компонент "{{ question.ui_config?.component }}" не найден.
    </div>
    <CheckResult :result="checkResult" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import CheckResult from '../CheckResult.vue'
import { interactiveComponents } from '../interactiveRegistry'

const props = defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue'])

const component = computed(() => interactiveComponents[props.question.ui_config?.component] || null)
</script>
