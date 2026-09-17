<template>
  <section v-if="rows.length || hasReference" class="ge-expected-answer mb-3 p-3 border rounded bg-light">
    <div class="small fw-semibold mb-1">Ожидаемый ответ</div>
    <div v-if="rows.length">
      <div v-for="(row, index) in rows" :key="index" class="mt-1">
        <template v-if="rows.length > 1">
          <span class="ge-markdown-inline" v-html="markdownInline(row.label)" />:
        </template>
        <strong v-if="row.markdown" class="ge-markdown-inline" v-html="markdownInline(row.value)" />
        <span v-else class="ge-answer-text">{{ displayValue(row.value) }}</span>
      </div>
    </div>
    <MarkdownBody v-else-if="question.check_type === 'ai'" :source="String(config.answer)" compact />
    <div v-else class="ge-answer-text">{{ displayValue(config.answer) }}</div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import MarkdownBody from './MarkdownBody.vue'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps({ question: { type: Object, required: true } })
const config = computed(() => props.question.check_config || {})
const hasReference = computed(() => config.value.answer !== undefined && config.value.answer !== null)
const rows = computed(() => {
  const ui = props.question.ui_config || {}
  if (props.question.type === 'multi_input' && config.value.answers) {
    return Object.entries(config.value.answers).map(([name, value]) => ({
      label: ui.fields?.find(field => field.name === name)?.label || name, value,
    }))
  }
  if (!Array.isArray(config.value.correct)) return []
  return config.value.correct.flatMap((value, index) => {
    if (value === null || value === undefined) return []
    if (props.question.type === 'choice_table') {
      return [{
        label: ui.items?.[index]?.label || `Строка ${index + 1}`,
        value: ui.options?.find(option => option.value === value)?.label ?? String(value),
        markdown: true,
      }]
    }
    if (props.question.type === 'true_false_table' && typeof value === 'boolean') {
      return [{ label: ui.statements?.[index] || `Утверждение ${index + 1}`, value: value ? 'Верно' : 'Неверно' }]
    }
    return []
  })
})

function displayValue(value) { return value === '' ? '(пустой ответ)' : String(value ?? '—') }
function markdownInline(value) { return renderMarkdown(String(value), { inline: true }) }
</script>
