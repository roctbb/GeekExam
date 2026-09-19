<template>
  <div>
    <div class="ge-matrices">
      <MatrixDisplay v-if="ui.source_matrix" :values="ui.source_matrix" label="Исходная матрица" :grayscale="ui.grayscale" />
      <MatrixDisplay v-if="ui.kernel" :values="ui.kernel" label="Ядро фильтра" :divisor="ui.kernel_divisor" />
      <div class="ge-matrix-answer">
        <div class="fw-semibold mb-2">{{ ui.answer_label || 'Матрица результата' }}</div>
        <table class="ge-matrix-input" aria-label="Матрица ответа">
          <tbody><tr v-for="(row, r) in values" :key="r">
            <td v-for="(value, c) in row" :key="c">
              <input type="text" inputmode="decimal" class="form-control" :value="value" :disabled="readonly"
                :aria-label="`Строка ${r + 1}, столбец ${c + 1}`"
                @input="updateCell(r, c, $event.target.value)" @paste="paste($event, r, c)" />
            </td>
          </tr></tbody>
        </table>
        <p v-if="!readonly" class="small text-muted mt-2 mb-0">Tab — следующая ячейка. Можно вставить строку или всю матрицу.</p>
        <p v-if="pasteError" class="small text-danger" role="alert">{{ pasteError }}</p>
      </div>
    </div>
    <div v-if="ui.fields?.length" class="mt-3">
      <label v-for="field in ui.fields" :key="field.name" class="ge-matrix-field">
        <span>{{ field.label || field.name }}</span>
        <input type="text" inputmode="decimal" class="form-control form-control-sm" :value="modelValue?.fields?.[field.name] ?? ''"
          :disabled="readonly" @input="updateField(field.name, $event.target.value)" />
      </label>
    </div>
    <div v-if="readonly && question.check_config?.matrix" class="mt-3">
      <MatrixDisplay :values="question.check_config.matrix" label="Правильная матрица" />
      <p v-for="field in ui.fields || []" :key="field.name" class="small mt-2 mb-0">
        {{ field.label || field.name }}: <strong>{{ question.check_config.fields?.[field.name] }}</strong>
      </p>
    </div>
    <CheckResult :result="checkResult" :max-points="question.max_points" />
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import MatrixDisplay from '../MatrixDisplay.vue'
import CheckResult from '../CheckResult.vue'
import { matrixValues, pasteMatrix } from '../../utils/matrix'
const props = defineProps({ question: Object, modelValue: Object, readonly: Boolean, checkResult: Object })
const emit = defineEmits(['update:modelValue'])
const ui = computed(() => props.question.ui_config || {})
const values = computed(() => matrixValues(props.modelValue?.matrix, ui.value.size))
const pasteError = ref('')
function updateCell(r, c, value) {
  if (props.readonly) return
  const matrix = matrixValues(props.modelValue?.matrix, ui.value.size)
  matrix[r][c] = value
  pasteError.value = ''
  emit('update:modelValue', { ...props.modelValue, matrix })
}
function updateField(name, value) {
  if (props.readonly) return
  emit('update:modelValue', { ...props.modelValue, matrix: values.value, fields: { ...props.modelValue?.fields, [name]: value } })
}
function paste(event, r, c) {
  if (props.readonly) return
  const text = event.clipboardData?.getData('text/plain') || ''
  if (!/[\s;\[\]]/.test(text.trim())) return
  event.preventDefault()
  const matrix = pasteMatrix(props.modelValue?.matrix, ui.value.size, r, c, text)
  pasteError.value = matrix ? '' : 'Данные не помещаются в матрицу. Вставьте прямоугольную таблицу начиная с нужной ячейки.'
  if (matrix) emit('update:modelValue', { ...props.modelValue, matrix })
}
</script>
<style scoped>
.ge-matrices { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 2rem; }
.ge-matrix-answer { max-width: 100%; overflow-x: auto; }
.ge-matrix-input { border-collapse: separate; border-spacing: 4px; }
.ge-matrix-input input { min-width: 4rem; width: 5rem; text-align: center; font-variant-numeric: tabular-nums; }
.ge-matrix-field { display: flex; align-items: center; flex-wrap: wrap; gap: 1rem; margin-bottom: .75rem; }
.ge-matrix-field input { width: 8rem; }
</style>
