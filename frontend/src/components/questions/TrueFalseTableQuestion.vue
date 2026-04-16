<template>
  <div>
    <table class="table table-bordered">
      <thead>
        <tr>
          <th>Утверждение</th>
          <th class="text-center" style="width:100px">Верно</th>
          <th class="text-center" style="width:100px">Неверно</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(stmt, i) in statements" :key="i">
          <td>
            <span v-if="readonly && correct">
              <span v-if="answers[i] === correct[i]">✅</span>
              <span v-else>❌</span>
            </span>
            {{ stmt }}
          </td>
          <td
            class="text-center"
            :class="cellClass(i, true)"
            :style="readonly ? '' : 'cursor:pointer'"
            @click="!readonly && setAnswer(i, true)"
          >
            <input type="radio" :name="`q${question.id}_${i}`"
              :checked="answers[i] === true" :disabled="readonly" />
          </td>
          <td
            class="text-center"
            :class="cellClass(i, false)"
            :style="readonly ? '' : 'cursor:pointer'"
            @click="!readonly && setAnswer(i, false)"
          >
            <input type="radio" :name="`q${question.id}_${i}`"
              :checked="answers[i] === false" :disabled="readonly" />
          </td>
        </tr>
      </tbody>
    </table>
    <CheckResult :result="checkResult" />
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import CheckResult from '../CheckResult.vue'

const props = defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue'])

const statements = computed(() => props.question.ui_config?.statements || [])
const correct = computed(() => props.question.check_config?.correct || null)

// Default all to false
const answers = computed(() => {
  const saved = props.modelValue?.answers
  if (saved && saved.length === statements.value.length) return saved
  return statements.value.map(() => false)
})

// Emit defaults on mount if no value saved yet
watch(statements, (stmts) => {
  if (!props.modelValue?.answers && stmts.length && !props.readonly) {
    emit('update:modelValue', { answers: stmts.map(() => false) })
  }
}, { immediate: true })

function setAnswer(i, val) {
  const arr = [...answers.value]
  arr[i] = val
  emit('update:modelValue', { answers: arr })
}

function cellClass(i, val) {
  if (answers.value[i] !== val) return ''
  // In readonly mode: show green if correct, red if wrong
  if (props.readonly && correct.value) {
    return correct.value[i] === val ? 'table-success' : 'table-danger'
  }
  // During answering: highlight selected
  return val === true ? 'table-success' : 'table-danger'
}
</script>
