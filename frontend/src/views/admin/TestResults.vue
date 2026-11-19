<template>
  <div class="ge-fade-in">
    <div class="ge-page-header">
      <h4>Результаты</h4>
      <div class="d-flex gap-2">
        <RouterLink :to="`/admin/tests/${testId}/question-review`" class="btn btn-outline-primary btn-sm"><AppIcon name="results" />Сводка по заданиям</RouterLink>
        <IconAction icon="retry" label="Обновить" :busy="refreshing" @click="refresh" />
        <RouterLink :to="`/admin/tests/${testId}`" class="btn btn-outline-secondary btn-sm"><AppIcon name="arrow-left" />Назад</RouterLink>
      </div>
    </div>
    <div v-if="actionError" class="alert alert-danger" role="alert">{{ actionError }}</div>
    <ExamMonitoring ref="monitorPanel" :test-id="testId" :data="monitor.data.value" :stale="monitor.stale.value" :error="monitor.error.value" @refresh="monitor.refresh" />
    <div v-if="error" class="alert alert-danger" role="alert">
      {{ error }} <button class="btn btn-sm btn-outline-danger" :disabled="refreshing" @click="refresh">Повторить</button>
    </div>
    <div v-if="loading" class="text-center py-4"><div class="spinner-border" /></div>
    <div v-else-if="!error && attempts.length === 0" class="text-center py-5 text-muted">Пока никто не проходил этот тест</div>
    <div v-else-if="attempts.length">
      <div class="d-flex justify-content-end mb-2 gap-2 flex-wrap">
        <select aria-label="Сортировка результатов" v-model="sortBy" class="form-select form-select-sm" style="width:auto">
          <option value="started_at">Сортировка: по времени</option>
          <option value="user_name">Сортировка: по имени</option>
        </select>
        <IconAction :icon="sortDir === 'asc' ? 'arrow-up' : 'arrow-down'" :label="sortDirectionLabel" @click="toggleSortDir" />
      </div>
      <div class="table-responsive">
      <table class="table table-hover align-middle">
        <thead><tr><th>Ученик</th><th>Вариант</th><th v-if="showExamColumn">GeekExam</th><th v-if="showGuardColumn">Сеть Guard</th><th>Начало</th><th>Конец</th><th>Результат</th><th aria-label="Действия"></th></tr></thead>
        <tbody>
          <tr v-for="a in sortedAttempts" :key="a.id">
            <td class="fw-semibold">{{ a.user_name }}</td>
            <td>{{ a.variant_title }}</td>
            <td v-if="showExamColumn">
              <PresenceStatus v-if="isActiveAttempt(a)" :value="monitor.byAttempt.value[a.id]?.exam"
                channel="exam" :stale="monitor.stale.value" :enabled="monitor.data.value?.config?.enabled !== false" />
            </td>
            <td v-if="showGuardColumn">
              <PresenceStatus v-if="isGuardAttempt(a) || (!a.finished_at && guardRequired)"
                :value="monitor.byAttempt.value[a.id]?.guard" channel="guard" :stale="monitor.stale.value" :finished="!!a.finished_at" :enabled="monitor.data.value?.config?.enabled !== false" />
              <span v-else class="text-muted">—</span>
            </td>
            <td class="text-muted small">{{ fmt(a.started_at) }}</td>
            <td class="text-muted small">{{ fmt(a.finished_at) || '—' }}</td>
            <td>
              <span v-if="!a.finished_at" class="badge bg-warning text-dark">В процессе</span>
              <span v-else-if="!a.is_checked" class="badge bg-info text-dark">Проверяется</span>
              <span v-else class="ge-score">{{ a.total_points }}/{{ a.max_points }}</span>
            </td>
            <td class="text-end">
              <div class="ge-row-actions">
                <IconAction v-if="isGuardAttempt(a)" icon="history" :label="journalLabel(a)" aria-haspopup="dialog"
                  :tone="reviewCount(a) ? 'warning' : 'neutral'" :count="reviewCount(a)" @click="monitorPanel.open(a)" />
                <IconAction icon="open" label="Детали" tone="primary" :to="`/admin/attempts/${a.id}`" />
                <IconAction v-if="a.finished_at" icon="retry" :label="isRechecking(a.id) ? 'Запуск перепроверки…' : 'Перепроверить'"
                  :busy="isRechecking(a.id)" @click="recheck(a)" />
                <IconAction icon="delete" label="Удалить" tone="danger" :busy="deletingIds.has(a.id)" @click="del(a.id)" />
              </div>
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
import ExamMonitoring from '../../components/ExamMonitoring.vue'
import PresenceStatus from '../../components/PresenceStatus.vue'
import { useExamMonitoring } from '../../composables/useExamMonitoring'
import { useResultList } from '../../composables/useResultList'
import { formatDateTime as fmt, parseApiDate } from '../../utils/dates'
const route = useRoute()
const testId = route.params.id
const monitor = useExamMonitoring(testId)
const monitorPanel = ref(null)
const { results: attempts, loading, refreshing, error, refresh } = useResultList(
  () => api.getTestAttempts(testId), `test_${testId}`,
)
const sortBy = ref('started_at')
const sortDir = ref('desc')
const sortDirectionLabel = computed(() => sortDir.value === 'asc'
  ? 'По возрастанию. Переключить на сортировку по убыванию'
  : 'По убыванию. Переключить на сортировку по возрастанию')
const showExamColumn = computed(() => attempts.value.some(isActiveAttempt))
const guardRequired = computed(() => monitor.data.value?.config?.require_guard === true)
const showGuardColumn = computed(() => guardRequired.value || attempts.value.some(isGuardAttempt))

function isActiveAttempt(attempt) {
  return !attempt.finished_at && monitor.byAttempt.value[attempt.id]?.exam?.state !== 'finished'
}

function isGuardAttempt(attempt) {
  return monitor.byAttempt.value[attempt.id]?.guard_admitted === true
}
function reviewCount(attempt) {
  return monitor.byAttempt.value[attempt.id]?.review_count || 0
}
function journalLabel(attempt) {
  const count = reviewCount(attempt)
  return count ? `Журнал связи · К проверке ${count}` : 'Журнал связи'
}
const recheckingIds = ref(new Set())
const deletingIds = ref(new Set()), actionError = ref('')

async function del(id) {
  if (deletingIds.value.has(id) || !confirm('Удалить прохождение?')) return
  deletingIds.value.add(id); actionError.value = ''
  try { await api.deleteAttempt(id); attempts.value = attempts.value.filter(a => a.id !== id); await refresh() }
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
