<template>
  <div>
    <div v-if="question.ui_config?.layout === 'cards'" class="ge-choice-cards">
      <fieldset v-for="(item, i) in items" :key="item.value ?? i" class="ge-choice-card">
        <legend class="ge-markdown-inline" v-html="markdownInline(item.label)" />
        <label v-for="option in options" :key="option.value" class="ge-choice-option" :class="cellClass(i, option.value)">
          <input type="radio" :name="`q${question.id}_${i}`" :checked="answers[i] === option.value" :disabled="readonly"
            @change="setAnswer(i, option.value)" />
          <span class="ge-markdown-inline" v-html="markdownInline(option.label)" />
          <span v-if="hasCorrectAnswer(i) && correct[i] === option.value" class="small fw-semibold">✓ Правильный ответ</span>
          <span v-if="readonly && answers[i] === option.value" class="small">Ваш ответ</span>
        </label>
      </fieldset>
    </div>
    <table v-else class="table table-bordered">
      <thead>
        <tr>
          <th><span class="ge-markdown-inline" v-html="markdownInline(itemHeader)" /></th>
          <th v-for="option in options" :key="option.value" class="text-center" style="width:140px">
            <span class="ge-markdown-inline" v-html="markdownInline(option.label)" />
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(item, i) in items" :key="item.value ?? i">
          <td>
            <span v-if="hasCorrectAnswer(i)">
              <span v-if="answers[i] === correct[i]">✅</span>
              <span v-else>❌</span>
            </span>
            <span class="ge-markdown-inline" v-html="markdownInline(item.label)" />
          </td>
          <td
            v-for="option in options"
            :key="option.value"
            class="text-center"
            :class="cellClass(i, option.value)"
            :style="readonly ? '' : 'cursor:pointer'"
            @click="!readonly && setAnswer(i, option.value)"
          >
            <input
              type="radio"
              :name="`q${question.id}_${i}`"
              :checked="answers[i] === option.value"
              :disabled="readonly"
            />
            <div v-if="hasCorrectAnswer(i) && correct[i] === option.value" class="small fw-semibold mt-1">
              ✓ Правильный ответ
            </div>
            <div v-if="readonly && answers[i] === option.value" class="small mt-1">Ваш ответ</div>
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

const items = computed(() => props.question.ui_config?.items || [])
const options = computed(() => props.question.ui_config?.options || [])
const itemHeader = computed(() => props.question.ui_config?.item_header || 'Пример')
const correct = computed(() => props.question.check_config?.correct || null)

const answers = computed(() => {
  const saved = props.modelValue?.answers
  if (saved && saved.length === items.value.length) return saved
  return items.value.map(() => null)
})

function setAnswer(i, value) {
  const arr = [...answers.value]
  arr[i] = value
  emit('update:modelValue', { answers: arr })
}

function markdownInline(source) {
  return renderMarkdown(source, { inline: true })
}

function cellClass(i, value) {
  if (hasCorrectAnswer(i) && correct.value[i] === value) return 'table-success'
  if (answers.value[i] !== value) return ''
  if (hasCorrectAnswer(i)) return 'table-danger'
  return 'table-primary'
}

function hasCorrectAnswer(i) {
  return props.readonly && Array.isArray(correct.value) && i < correct.value.length
    && options.value.some(option => option.value === correct.value[i])
}
</script>

<style scoped>
.ge-choice-cards { display: grid; gap: 1.25rem; }
.ge-choice-card { border: 1px solid #d9dfe7; border-radius: .6rem; padding: 1rem; min-width: 0; }
.ge-choice-card legend { float: none; width: auto; font-size: 1rem; font-weight: 600; padding: 0 .35rem; }
.ge-choice-option { display: flex; align-items: baseline; gap: .65rem; border-radius: .35rem; padding: .55rem .65rem; cursor: pointer; }
.ge-choice-option input { flex-shrink: 0; }
.ge-choice-option:focus-within { outline: 2px solid #376cce; }
.ge-choice-option.table-primary { background: #e5efff; }
.ge-choice-option.table-success { background: #d6eedf; }
.ge-choice-option.table-danger { background: #f9dddd; }
</style>
