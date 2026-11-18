<template>
  <div class="ge-fade-in">
    <div class="ge-page-header">
      <h4>Результаты</h4>
      <button type="button" class="btn btn-sm btn-outline-secondary" :disabled="refreshing" @click="refresh">Обновить</button>
      <RouterLink :to="`/admin/tests/${$route.params.id}`" class="btn btn-outline-secondary btn-sm"><AppIcon name="arrow-left" />Назад</RouterLink>
    </div>
    <div v-if="actionError" class="alert alert-danger" role="alert">{{ actionError }}</div>
    <ExamMonitoring ref="monitorPanel" :test-id="testId" :data="monitor.data.value" :stale="monitor.stale.value" :error="monitor.error.value" @refresh="monitor.refresh" />
    <div v-if="error" class="alert alert-danger" role="alert">
      {{ error }} <button class="btn btn-sm btn-outline-danger" :disabled="refreshing" @click="refresh">Повторить</button>
    </div>
    <div v-if="loading" class="text-center py-4"><div class="spinner-border" /></div>
    <div v-else-if="!error && attempts.length === 0" class="text-center py-5 text-muted">Пока никто не проходил этот тест</div>
    <div v-else-if="attempts.length">
      <section class="card mb-4" aria-labelledby="question-summary-title">
        <div class="card-header">
          <h5 id="question-summary-title" class="mb-0">Сводка по заданиям</h5>
          <p v-if="questionSummary.length" class="small text-muted mb-0 mt-1">
            По оценённым ответам из завершённых и проверенных работ. Сначала задания, в которых чаще теряли баллы.
          </p>
        </div>
        <p v-if="!questionSummary.length" class="card-body text-muted mb-0">Пока нет оценённых ответов в проверенных работах.</p>
        <div v-else class="table-responsive">
          <table class="table table-sm align-middle mb-0" aria-labelledby="question-summary-title">
            <thead>
              <tr>
                <th scope="col">Задание</th>
                <th scope="col">Вариант</th>
                <th scope="col" class="text-end">Ниже максимума</th>
                <th scope="col" class="text-end" aria-sort="descending">Доля</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="row in questionSummary" :key="row.question_id">
                <tr>
                  <th scope="row">
                    <button type="button" class="btn btn-link btn-sm p-0 text-start fw-semibold"
                      :aria-expanded="expandedQuestionId === row.question_id"
                      :aria-controls="expandedQuestionId === row.question_id ? `wrong-answers-${row.question_id}` : undefined"
                      @click="toggleQuestion(row.question_id)">
                      <AppIcon name="chevron-down" :class="{ 'ge-expanded-chevron': expandedQuestionId === row.question_id }" />
                      {{ numberedQuestionTitle(row.title, row.order) }}
                    </button>
                  </th>
                  <td>{{ row.variant_title }}</td>
                  <td class="text-end text-nowrap">{{ row.below_max_count }} из {{ row.graded_count }}</td>
                  <td class="text-end text-nowrap">{{ percent.format(row.below_max_count / row.graded_count) }}</td>
                </tr>
                <tr v-if="expandedQuestionId === row.question_id" :id="`wrong-answers-${row.question_id}`">
                  <td colspan="4"><QuestionWrongAnswers :test-id="testId" :question="row" /></td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>
      <div class="d-flex justify-content-end mb-2 gap-2 flex-wrap">
        <select aria-label="Сортировка результатов" v-model="sortBy" class="form-select form-select-sm" style="width:auto">
          <option value="started_at">Сортировка: по времени</option>
          <option value="user_name">Сортировка: по имени</option>
        </select>
        <button class="btn btn-sm btn-outline-secondary" @click="toggleSortDir">
          <AppIcon :name="sortDir === 'asc' ? 'arrow-up' : 'arrow-down'" />{{ sortDir === 'asc' ? 'По возрастанию' : 'По убыванию' }}
        </button>
      </div>
      <div class="table-responsive">
      <table class="table table-hover align-middle">
        <thead><tr><th>Ученик</th><th>Вариант</th><th>GeekExam</th><th>Сеть Guard</th><th>Начало</th><th>Конец</th><th>Результат</th><th></th></tr></thead>
        <tbody>
          <tr v-for="a in sortedAttempts" :key="a.id">
            <td class="fw-semibold">{{ a.user_name }}</td>
            <td>{{ a.variant_title }}</td>
            <td><PresenceStatus :value="monitor.byAttempt.value[a.id]?.exam" channel="exam" :stale="monitor.stale.value" :finished="!!a.finished_at" :enabled="monitor.data.value?.config?.enabled !== false" /></td>
            <td>
              <PresenceStatus :value="monitor.byAttempt.value[a.id]?.guard" channel="guard" :stale="monitor.stale.value" :finished="!!a.finished_at" :enabled="monitor.data.value?.config?.enabled !== false" />
              <button class="btn btn-sm btn-link p-0 mt-1 text-start" @click="monitorPanel.open(a)">
                {{ monitor.byAttempt.value[a.id]?.review_count ? `Проверить: ${monitor.byAttempt.value[a.id].review_count}` : 'Журнал связи' }}
              </button>
            </td>
            <td class="text-muted small">{{ fmt(a.started_at) }}</td>
            <td class="text-muted small">{{ fmt(a.finished_at) || '—' }}</td>
            <td>
              <span v-if="!a.finished_at" class="badge bg-warning text-dark">В процессе</span>
              <span v-else-if="!a.is_checked" class="badge bg-info text-dark">Проверяется</span>
              <span v-else class="ge-score">{{ a.total_points }}/{{ a.max_points }}</span>
            </td>
            <td class="text-end">
              <RouterLink :to="`/admin/attempts/${a.id}`" class="btn btn-sm btn-outline-primary me-1"><AppIcon name="open" />Детали</RouterLink>
              <button v-if="a.finished_at" class="btn btn-sm btn-outline-secondary me-1" :disabled="isRechecking(a.id)" @click="recheck(a)">
                <span v-if="isRechecking(a.id)" class="spinner-border spinner-border-sm me-1" />
                <AppIcon v-else name="retry" />
                {{ isRechecking(a.id) ? 'Запуск...' : 'Перепроверить' }}
              </button>
              <button class="btn btn-sm btn-outline-danger" :disabled="deletingIds.has(a.id)" @click="del(a.id)"><AppIcon name="delete" />Удалить</button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import api from '../../api'
import QuestionWrongAnswers from '../../components/QuestionWrongAnswers.vue'
import ExamMonitoring from '../../components/ExamMonitoring.vue'
import PresenceStatus from '../../components/PresenceStatus.vue'
import { useExamMonitoring } from '../../composables/useExamMonitoring'
import { useResultList } from '../../composables/useResultList'
import { numberedQuestionTitle } from '../../utils/answers'
import { formatDateTime as fmt, parseApiDate } from '../../utils/dates'
const route = useRoute()
const testId = route.params.id
const monitor = useExamMonitoring(testId)
const monitorPanel = ref(null)
const { results, loading, refreshing, error, refresh } = useResultList(
  () => api.getTestResults(testId), `test_${testId}`, { attempts: [], question_summary: [] },
)
const attempts = computed(() => results.value.attempts)
const questionSummary = computed(() => results.value.question_summary)
const percent = new Intl.NumberFormat('ru', { style: 'percent', maximumFractionDigits: 1 })
const expandedQuestionId = ref(null)
const sortBy = ref('started_at')
const sortDir = ref('desc')
const recheckingIds = ref(new Set())
const deletingIds = ref(new Set()), actionError = ref('')

function toggleQuestion(questionId) {
  expandedQuestionId.value = expandedQuestionId.value === questionId ? null : questionId
}

async function del(id) {
  if (deletingIds.value.has(id) || !confirm('Удалить прохождение?')) return
  deletingIds.value.add(id); actionError.value = ''
  try { await api.deleteAttempt(id); results.value.attempts = attempts.value.filter(a => a.id !== id); await refresh() }
  catch (e) { actionError.value = e?.response?.data?.error || 'Не удалось удалить прохождение. Повторите попытку.' }
  finally { deletingIds.value.delete(id) }
}
const isRechecking = (id) => recheckingIds.value.has(id)

function toggleSortDir() {
  sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
}

function setRechecking(id, value) {
  const next = new Set(recheckingIds.value)
  if (value) next.add(id)
  else next.delete(id)
  recheckingIds.value = next
}

async function recheck(attempt) {
  if (isRechecking(attempt.id)) return
  actionError.value = ''
  if (!confirm(`Перепроверить работу ${attempt.user_name}? Баллы по автопроверяемым вопросам будут обновлены.`)) return
  setRechecking(attempt.id, true)
  try {
    await api.recheckAttempt(attempt.id)
    const current = attempts.value.find(a => a.id === attempt.id)
    if (current) { current.is_checked = false; /* Previous points remain visible until the new result. */ }
    await refresh()
  } catch (e) {
    actionError.value = e?.response?.data?.error || 'Не удалось запустить перепроверку работы'
  } finally {
    setRechecking(attempt.id, false)
  }
}

const sortedAttempts = computed(() => {
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...attempts.value].sort((a, b) => {
    if (sortBy.value === 'user_name') {
      return dir * (a.user_name || '').localeCompare(b.user_name || '', 'ru')
    }
    const aTs = parseApiDate(a.started_at)?.getTime() || 0
    const bTs = parseApiDate(b.started_at)?.getTime() || 0
    return dir * (aTs - bTs)
  })
})
</script>

<style scoped>
.ge-expanded-chevron { transform: rotate(180deg); }
</style>
