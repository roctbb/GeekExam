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
            <span v-if="hasCorrectAnswer(i)">
              <span v-if="answers[i] === correct[i]">✅</span>
              <span v-else>❌</span>
            </span>
            <span class="ge-markdown-inline" v-html="markdownInline(stmt)" />
          </td>
          <td
            class="text-center"
            :class="cellClass(i, true)"
            :style="readonly ? '' : 'cursor:pointer'"
            @click="!readonly && setAnswer(i, true)"
          >
            <input type="radio" :name="`q${question.id}_${i}`"
              :checked="answers[i] === true" :disabled="readonly" />
            <div v-if="hasCorrectAnswer(i) && correct[i] === true" class="small fw-semibold mt-1">✓ Правильный ответ</div>
            <div v-if="readonly && answers[i] === true" class="small mt-1">Ваш ответ</div>
          </td>
          <td
            class="text-center"
            :class="cellClass(i, false)"
            :style="readonly ? '' : 'cursor:pointer'"
            @click="!readonly && setAnswer(i, false)"
          >
            <input type="radio" :name="`q${question.id}_${i}`"
              :checked="answers[i] === false" :disabled="readonly" />
            <div v-if="hasCorrectAnswer(i) && correct[i] === false" class="small fw-semibold mt-1">✓ Правильный ответ</div>
            <div v-if="readonly && answers[i] === false" class="small mt-1">Ваш ответ</div>
          </td>
        </tr>
      </tbody>
    </table>
    <CheckResult :result="checkResult" :max-points="question.max_points" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import CheckResult from '../CheckResult.vue'
import { renderMarkdown } from '../../utils/markdown'

const props = defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue'])

const statements = computed(() => props.question.ui_config?.statements || [])
const correct = computed(() => props.question.check_config?.correct || null)

const answers = computed(() => statements.value.map((_, i) => props.modelValue?.answers?.[i] ?? null))

function setAnswer(i, val) {
  const arr = [...answers.value]
  arr[i] = val
  emit('update:modelValue', { answers: arr })
}

function markdownInline(source) {
  return renderMarkdown(source, { inline: true })
}

function hasCorrectAnswer(i) {
  return props.readonly && Array.isArray(correct.value) && typeof correct.value[i] === 'boolean'
}

function cellClass(i, val) {
  if (hasCorrectAnswer(i) && correct.value[i] === val) return 'table-success'
  if (answers.value[i] !== val) return ''
  return hasCorrectAnswer(i) ? 'table-danger' : 'table-primary'
}
</script>
