<template>
  <div class="ge-multi-input">
    <div v-if="question.ui_config?.layout === 'table'" class="table-responsive">
      <table class="table table-bordered align-middle">
        <thead><tr><th scope="col">{{ question.ui_config.row_header || 'Группа' }}</th>
          <th v-for="column in question.ui_config.columns" :key="column" scope="col">{{ column }}</th>
        </tr></thead>
        <tbody><tr v-for="row in question.ui_config.rows" :key="row.label">
          <th scope="row">{{ row.label }}</th>
          <td v-for="name in row.fields" :key="name">
            <input type="text" class="form-control form-control-sm" :aria-label="fieldLabel(name)" :value="modelValue?.[name] ?? ''"
              :disabled="readonly" @input="update(name, $event.target.value)" />
          </td>
        </tr></tbody>
      </table>
    </div>
    <div v-for="field in standaloneFields" :key="field.name" class="ge-multi-input-row">
      <span class="ge-multi-input-label ge-markdown" v-html="labelHtml(field)" />
      <select v-if="field.options" class="form-select form-select-sm ge-multi-input-control"
        :aria-label="field.label || field.name" :value="modelValue?.[field.name] ?? ''" :disabled="readonly"
        @change="update(field.name, $event.target.value)">
        <option disabled value="">Выберите ответ</option>
        <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
      <input v-else
        type="text"
        :aria-label="field.label || field.name"
        class="form-control form-control-sm ge-multi-input-control"
        :value="modelValue?.[field.name] ?? ''"
        :disabled="readonly"
        @input="update(field.name, $event.target.value)"
      />
    </div>
    <CheckResult :result="checkResult" :max-points="question.max_points" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import CheckResult from '../CheckResult.vue'
import { renderMarkdown } from '../../utils/markdown'

const props = defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue'])

const fields = computed(() => props.question.ui_config?.fields || [])

const standaloneFields = computed(() => {
  const grouped = props.question.ui_config?.layout === 'table'
    ? (props.question.ui_config.rows || []).flatMap(row => row.fields) : []
  return fields.value.filter(field => !grouped.includes(field.name))
})
function fieldLabel(name) { return fields.value.find(field => field.name === name)?.label || name }

function update(name, value) {
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}

function labelHtml(field) {
  return renderMarkdown(field.label || field.name || '', { inline: true })
}
</script>

<style scoped>
select.ge-multi-input-control { width: 12rem; max-width: 100%; }
</style>
