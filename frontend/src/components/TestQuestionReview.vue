<template>
  <section class="ge-question-review mb-4" aria-labelledby="question-review-title">
    <div class="card">
      <div class="card-body">
        <div class="d-flex align-items-start justify-content-between gap-2 flex-wrap mb-3">
          <div>
            <h5 id="question-review-title" class="mb-1">Как ответили на задания</h5>
            <p v-if="hasWorks" class="small text-muted mb-0">
              Доли от завершённых работ по заданию. Сверху — задания с большей долей ошибок и пропусков.
            </p>
          </div>
          <div v-if="hasWorks" class="d-flex flex-wrap gap-3 small">
            <span><span class="ge-ratio-swatch ge-ratio-swatch-correct" aria-hidden="true" />Верно</span>
            <span title="Ответ, за который начислили меньше максимума"><span class="ge-ratio-swatch ge-ratio-swatch-incorrect" aria-hidden="true" />С ошибкой</span>
            <span><span class="ge-ratio-swatch ge-ratio-swatch-skipped" aria-hidden="true" />Пропустили</span>
            <span v-if="hasUngraded"><span class="ge-ratio-swatch ge-ratio-swatch-ungraded" aria-hidden="true" />Без оценки</span>
          </div>
        </div>
        <p v-if="!hasWorks" class="text-muted mb-0">Пока нет завершённых работ.</p>
        <div v-else role="group" aria-label="Задания по доле ошибок и пропусков">
          <button v-for="group in rankedGroups" :key="group.order" type="button" class="ge-ratio-row"
            :aria-pressed="selected?.order === group.order" :aria-label="`${questionTitle(group)} — ${countsLabel(group)}`"
            aria-controls="question-review-variants" @click="selectedOrder = group.order">
            <span class="ge-ratio-title">{{ questionTitle(group) }}</span>
            <span class="ge-ratio-distribution">
              <AnswerRatioBar :correct="group.correct_count" :incorrect="group.incorrect_count"
                :skipped="group.skipped_count" :ungraded="group.ungraded_count" />
              <span v-if="workCount(group)" class="ge-ratio-caption">{{ otherCounts(group) }}</span>
            </span>
            <span class="ge-ratio-value">{{ resultLabel(group) }}</span>
          </button>
          <div class="ge-ratio-axis" aria-hidden="true">
            <div class="ge-ratio-ticks">
              <span v-for="tick in [0, 25, 50, 75, 100]" :key="tick">{{ tick }}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <section v-if="selected" id="question-review-variants" class="mt-3" aria-labelledby="question-review-selection">
      <div class="d-flex align-items-center justify-content-between gap-2 flex-wrap mb-3">
        <div>
          <h5 id="question-review-selection" class="mb-1" aria-live="polite">{{ questionTitle(selected) }}</h5>
          <p class="small text-muted mb-0">{{ countsLabel(selected) }}</p>
        </div>
        <button type="button" class="btn btn-sm btn-outline-primary" :aria-expanded="showAnswers"
          :aria-controls="selected.variants.map(variant => `question-review-answers-${variant.question_id}`).join(' ')"
          @click="showAnswers = !showAnswers">
          {{ showAnswers ? 'Скрыть ответы' : 'Показать ответы' }}
        </button>
      </div>

      <p v-if="loading" class="text-muted small" role="status">Загружаем условия заданий…</p>
      <div v-if="error" class="alert alert-danger" role="alert">
        Не удалось загрузить условия заданий.
        <button type="button" class="btn btn-sm btn-outline-danger" @click="retry++">Повторить загрузку условий</button>
      </div>
      <div class="ge-review-variants">
        <article v-for="row in selected.variants" :key="row.question_id" class="card ge-review-variant">
          <div class="card-body">
            <div class="d-flex align-items-baseline justify-content-between gap-2 flex-wrap mb-2">
              <h6 class="mb-0">{{ row.variant_title }}</h6>
              <span class="small text-muted">{{ workCountLabel(row) }}</span>
            </div>
            <AnswerRatioBar :correct="row.correct_count" :incorrect="row.incorrect_count"
              :skipped="row.skipped_count" :ungraded="row.ungraded_count" />
            <p class="small text-muted mt-1 mb-3">{{ countsLabel(row) }}</p>

            <template v-if="definitions[row.question_id]">
              <p v-if="row.title !== selected.title" class="fw-semibold mb-2">{{ row.title }}</p>
              <MarkdownBody :source="definitions[row.question_id].body || ''" compact />
              <pre v-if="definitions[row.question_id].ui_config?.starter_code" class="ge-code mb-3"><code>{{ definitions[row.question_id].ui_config.starter_code }}</code></pre>
              <div v-if="questionComponents[definitions[row.question_id].type]" class="table-responsive">
                <component :is="questionComponents[definitions[row.question_id].type]"
                  :question="questionCondition(definitions[row.question_id])" readonly />
              </div>
            </template>

            <div :id="`question-review-answers-${row.question_id}`" :hidden="!showAnswers" class="ge-review-answers">
              <template v-if="showAnswers">
                <ExpectedAnswer v-if="definitions[row.question_id]" :question="definitions[row.question_id]" />
                <QuestionWrongAnswers :test-id="testId" :question="row" />
              </template>
            </div>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import api from '../api'
import AnswerRatioBar from './AnswerRatioBar.vue'
import ExpectedAnswer from './ExpectedAnswer.vue'
import MarkdownBody from './MarkdownBody.vue'
import QuestionWrongAnswers from './QuestionWrongAnswers.vue'
import ChoiceTableQuestion from './questions/ChoiceTableQuestion.vue'
import InteractiveQuestion from './questions/InteractiveQuestion.vue'
import MatrixInputQuestion from './questions/MatrixInputQuestion.vue'
import MultiInputQuestion from './questions/MultiInputQuestion.vue'
import TrueFalseTableQuestion from './questions/TrueFalseTableQuestion.vue'
import { numberedQuestionTitle } from '../utils/answers'

const props = defineProps({
  testId: { type: [String, Number], required: true },
  groups: { type: Array, default: () => [] },
})
const questionComponents = {
  choice_table: ChoiceTableQuestion,
  interactive: InteractiveQuestion,
  matrix_input: MatrixInputQuestion,
  multi_input: MultiInputQuestion,
  true_false_table: TrueFalseTableQuestion,
}
const selectedOrder = ref(null)
const showAnswers = ref(false)
const definitions = ref({})
const loading = ref(false)
const error = ref(false)
const retry = ref(0)

const ratedCount = row => row.correct_count + row.incorrect_count + row.skipped_count
const workCount = row => ratedCount(row) + row.ungraded_count
const missed = row => row.incorrect_count + row.skipped_count
const missedRate = row => ratedCount(row) ? missed(row) / workCount(row) : -1
const outcomeKeys = ['correct_count', 'incorrect_count', 'skipped_count', 'ungraded_count']
const rankedGroups = computed(() => props.groups.map(group => {
  const totals = Object.fromEntries(outcomeKeys.map(key => [
    key, group.variants.reduce((sum, row) => sum + row[key], 0),
  ]))
  return { ...group, ...totals }
}).sort((a, b) => missedRate(b) - missedRate(a) || missed(b) - missed(a) || a.order - b.order))
const hasWorks = computed(() => rankedGroups.value.some(group => workCount(group) > 0))
const hasUngraded = computed(() => rankedGroups.value.some(group => group.ungraded_count > 0))
const selected = computed(() => hasWorks.value
  ? rankedGroups.value.find(group => group.order === selectedOrder.value) ?? rankedGroups.value[0]
  : null)
const questionTitle = group => numberedQuestionTitle(group.title, group.order)
const workPlural = new Intl.PluralRules('ru')

function otherCounts(row) {
  const counts = [`${row.incorrect_count} с ошибкой`, `Пропустили ${row.skipped_count}`]
  if (row.ungraded_count) counts.push(`${row.ungraded_count} без оценки`)
  return counts.join(' · ')
}

function countsLabel(row) {
  if (!workCount(row)) return 'Нет завершённых работ'
  return `${row.correct_count} верно · ${otherCounts(row)}`
}

function workCountLabel(row) {
  const count = workCount(row)
  const unit = { one: 'работа', few: 'работы', many: 'работ', other: 'работ' }[workPlural.select(count)]
  return `${count} ${unit}`
}

function resultLabel(row) {
  const total = workCount(row)
  if (!total) return 'Нет работ'
  if (!ratedCount(row)) return 'Без оценки'
  const percent = Math.round(row.correct_count * 100 / total)
  return `${row.correct_count} из ${total} верно · ${percent}%`
}

function questionCondition(question) {
  return { ...question, check_config: showAnswers.value && question.type === 'matrix_input' ? question.check_config : {} }
}

watch(() => selected.value?.order, order => {
  selectedOrder.value = order ?? null
  showAnswers.value = false
})

watch([() => selected.value?.order, retry], async ([order], _, onCleanup) => {
  definitions.value = {}
  error.value = false
  loading.value = false
  if (order == null) return

  const controller = new AbortController()
  onCleanup(() => controller.abort())
  loading.value = true
  try {
    const { data } = await api.getQuestionReview(props.testId, order, controller.signal)
    if (!controller.signal.aborted) {
      definitions.value = Object.fromEntries(data.questions.map(question => [question.id, question]))
    }
  } catch {
    if (!controller.signal.aborted) error.value = true
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>

<style scoped>
.ge-question-review {
  --answer-ratio-correct: #267e6b;
  --answer-ratio-incorrect: #c26236;
  --answer-ratio-skipped: #a7b4c5;
  --answer-ratio-ungraded: #7c6cb2;
  --ratio-columns: minmax(0, 1.1fr) minmax(0, 2fr) 9.8rem;
}
[data-bs-theme="dark"] .ge-question-review {
  --answer-ratio-correct: #56bfa5;
  --answer-ratio-incorrect: #ed9a6d;
  --answer-ratio-skipped: #7d8ea5;
  --answer-ratio-ungraded: #a696de;
}
.ge-ratio-swatch { display: inline-block; width: .65rem; height: .65rem; border-radius: .15rem; margin-right: .35rem; }
.ge-ratio-swatch-correct { background: var(--answer-ratio-correct); }
.ge-ratio-swatch-incorrect { background: var(--answer-ratio-incorrect); }
.ge-ratio-swatch-skipped { background: var(--answer-ratio-skipped); }
.ge-ratio-swatch-ungraded { background: var(--answer-ratio-ungraded); }
.ge-ratio-row,
.ge-ratio-axis {
  display: grid;
  grid-template-columns: var(--ratio-columns);
  gap: .75rem;
  align-items: center;
  padding-inline: .75rem;
}
.ge-ratio-row {
  width: 100%;
  min-height: 3.25rem;
  padding-block: .5rem;
  border: 0;
  border-radius: var(--ge-radius-control);
  background: transparent;
  color: var(--ge-text);
  text-align: start;
  overflow-wrap: anywhere;
}
.ge-ratio-row:is(:hover, [aria-pressed="true"]) { background: var(--ge-primary-soft); }
.ge-ratio-row[aria-pressed="true"] { box-shadow: inset 3px 0 var(--ge-primary); }
.ge-ratio-row[aria-pressed="true"] .ge-ratio-title { color: var(--ge-primary); font-weight: 600; }
.ge-ratio-row:focus-visible { outline: 2px solid var(--ge-primary); outline-offset: 2px; }
.ge-ratio-distribution { display: grid; gap: .25rem; }
.ge-ratio-caption { font-size: var(--ge-font-meta); color: var(--ge-muted); }
.ge-ratio-value { justify-self: end; white-space: nowrap; font-size: var(--ge-font-meta); font-weight: 600; }
.ge-ratio-value, .ge-ratio-axis { font-variant-numeric: tabular-nums; }
.ge-ratio-axis {
  margin-top: .25rem;
  font-size: .75rem;
  color: var(--ge-muted);
}
.ge-ratio-ticks { display: flex; grid-column: 2; justify-content: space-between; }
.ge-review-variants { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.ge-review-variant { --answer-ratio-height: .45rem; min-width: 0; }
.ge-review-answers:not([hidden]) { border-top: 1px solid var(--ge-border); padding-top: .75rem; margin-top: .75rem; }
@media (max-width: 767px) {
  .ge-review-variants { grid-template-columns: minmax(0, 1fr); }
  .ge-ratio-row { grid-template-columns: minmax(0, 1fr) auto; gap: .25rem .5rem; min-height: 3rem; }
  .ge-ratio-distribution { grid-row: 2; grid-column: 1 / -1; --answer-ratio-height: .65rem; }
  .ge-ratio-value { grid-row: 1; grid-column: 2; }
  .ge-ratio-axis { grid-template-columns: minmax(0, 1fr); }
  .ge-ratio-ticks { grid-column: 1; }
}
</style>
