<template>
  <div v-if="store.attempt" class="ge-fade-in">
    <div class="ge-page-header">
      <h4>{{ store.attempt.test_title }}</h4>
      <div class="d-flex align-items-center gap-3">
        <span v-if="timeLeft !== null" class="ge-timer" :class="{ danger: timeLeft < 60 }">
          ⏱ {{ formatTime(timeLeft) }}
        </span>
        <button class="btn btn-danger btn-sm" :disabled="finishing || saveClosed" @click="confirmFinish">{{ finishing ? 'Завершаю…' : 'Завершить' }}</button>
      </div>
    </div>

    <div v-if="saveClosed" class="alert alert-warning" role="alert">
      Тест уже завершён. Последние изменения не сохранены. При необходимости скопируйте ответ перед выходом.
      <button class="btn btn-sm btn-outline-secondary ms-2" @click="openClosedResults">Открыть результаты</button>
    </div>
    <div v-else-if="actionError" class="alert alert-danger" role="alert">{{ actionError }}</div>
    <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
      <span class="small">Отвечено {{ answeredCount }} из {{ store.attempt.questions.length }}</span>
      <span v-if="saveState !== 'idle'" class="small" role="status" :class="saveState === 'error' ? 'text-danger' : 'text-muted'">
        {{ saveState === 'saving' ? 'Сохраняется…' : saveState === 'saved' ? 'Все изменения сохранены' : 'Не удалось сохранить ответ' }}
        <button v-if="saveState === 'error' && !saveClosed" class="btn btn-sm btn-outline-danger ms-2" @click="retrySaves">Повторить сохранение</button>
      </span>
    </div>
    <!-- Progress -->
    <div class="ge-progress">
      <div class="ge-progress-bar" :style="{ width: progressPct + '%' }" />
    </div>

    <!-- Question tabs -->
    <div class="ge-question-tabs">
      <button v-for="(q, i) in store.attempt.questions" type="button" :aria-label="`Вопрос ${i + 1}`" :aria-current="activeTab === i ? 'step' : undefined" :key="q.id"
        class="ge-tab" :class="[activeTab === i ? 'active' : '', tabClass(q)]"
        @click="activeTab = i">
        {{ i + 1 }}
      </button>
    </div>

    <!-- Active question -->
    <div v-if="currentQuestion" class="card mb-3">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span>{{ currentQuestion.title }}</span>
        <span class="badge bg-secondary">{{ currentQuestion.max_points }} б.</span>
      </div>
      <div class="card-body">
        <div :class="{ 'ge-question-split': currentQuestion.type === 'code_input' && currentQuestion.ui_config?.layout === 'split' }">
        <MarkdownBody class="mb-3 ge-question-condition" :source="currentQuestion.body" :copy-code="currentQuestion.type === 'code_input'" />
        <component :is="questionComponent(currentQuestion.type)" :key="currentQuestion.id"
          :question="currentQuestion" :modelValue="currentAnswer.value"
          :readonly="!!store.attempt.finished_at || finishing || saveClosed" :checkResult="currentAnswer"
          @update:modelValue="onAnswerUpdate" @check="onIntermediateCheck" />
        </div>
        <div class="d-flex justify-content-between mt-3">
          <button class="btn btn-outline-secondary btn-sm" :disabled="activeTab === 0" @click="activeTab--">← Назад</button>
          <button class="btn btn-outline-secondary btn-sm" :disabled="activeTab === store.attempt.questions.length - 1" @click="activeTab++">Далее →</button>
        </div>
      </div>
    </div>
  </div>
  <div v-else-if="loadError" class="alert alert-danger" role="alert">{{ loadError }} <button class="btn btn-outline-danger btn-sm" @click="loadAttempt">Повторить</button></div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { io } from 'socket.io-client'
import { useAttemptStore } from '../stores/attempt'
import api from '../api'
import { isQuestionAnswered, scoreStatus } from '../utils/answers'
import { createAnswerSaver } from '../utils/answerSaver'
import MarkdownBody from '../components/MarkdownBody.vue'
import TextInputQuestion from '../components/questions/TextInputQuestion.vue'
import CodeInputQuestion from '../components/questions/CodeInputQuestion.vue'
import TrueFalseTableQuestion from '../components/questions/TrueFalseTableQuestion.vue'
import InteractiveQuestion from '../components/questions/InteractiveQuestion.vue'
import MultiInputQuestion from '../components/questions/MultiInputQuestion.vue'
import MatrixInputQuestion from '../components/questions/MatrixInputQuestion.vue'
import ChoiceTableQuestion from '../components/questions/ChoiceTableQuestion.vue'

const questionComponents = { text_input: TextInputQuestion, code_input: CodeInputQuestion, true_false_table: TrueFalseTableQuestion, interactive: InteractiveQuestion, multi_input: MultiInputQuestion, matrix_input: MatrixInputQuestion, choice_table: ChoiceTableQuestion }

const route = useRoute()
const router = useRouter()
const store = useAttemptStore()
const activeTab = ref(0)
const timeLeft = ref(null)
const finishing = ref(false)
const timeDeadlineMs = ref(null)
let serverClockOffsetMs = 0
let timerInterval = null, timerSyncInterval = null, socket = null
const saveState = ref('idle')
const actionError = ref('')
const loadError = ref('')
const saveClosed = ref(false)
let leaveUnsaved = false
const saver = createAnswerSaver(async (id, value) => {
  try { await api.saveAnswer(id, value) } catch (e) {
    if (e?.response?.status === 422) { saveClosed.value = true; stopTimer() }
    throw e
  }
}, state => { saveState.value = state })
let autoFinishAttempted = false

const currentQuestion = computed(() => store.attempt?.questions[activeTab.value])
const currentAnswer = computed(() => store.answers[currentQuestion.value?.id] || {})

const unansweredNumbers = computed(() => (store.attempt?.questions || [])
  .flatMap((q, i) => isQuestionAnswered(q, store.answers[q.id]?.value) ? [] : [i + 1]))
const answeredCount = computed(() => (store.attempt?.questions.length || 0) - unansweredNumbers.value.length)
const progressPct = computed(() => store.attempt?.questions.length
  ? Math.round(answeredCount.value / store.attempt.questions.length * 100) : 0)

function questionComponent(type) { return questionComponents[type] || TextInputQuestion }

function tabClass(question) {
  const a = store.answers[question.id]
  if (!a) return ''
  if (a.check_state === 'checked') return scoreStatus(a.points, question.max_points).tab
  return isQuestionAnswered(question, a.value) ? 'answered' : ''
}

function formatTime(s) { return `${Math.floor(s/60)}:${(s%60).toString().padStart(2,'0')}` }

function onAnswerUpdate(value) {
  if (finishing.value || saveClosed.value || store.attempt.finished_at) return
  const questionId = currentQuestion.value.id
  const prev = currentAnswer.value

  // Only reset stale check results when the value actually changed.
  // Comparing by JSON handles table/object answers (arrays, dicts).
  const valueChanged = JSON.stringify(prev.value) !== JSON.stringify(value)
  const patch = valueChanged
    ? { value, check_state: 'pending', points: null, check_comment: null }
    : { value }

  store.updateAnswer(questionId, patch)
  if (valueChanged) saver.schedule(prev.id, value)
}

async function onIntermediateCheck() {
  const questionId = currentQuestion.value.id
  const answerId = currentAnswer.value.id
  const prev = { ...currentAnswer.value }

  // Flush any pending debounced save so the checker sees the latest value
  try { await saver.flush() } catch {
    actionError.value = 'Сначала сохраните ответ, затем запустите проверку.'
    return
  }

  // Clear stale points/comment while new check is in flight.
  store.updateAnswer(questionId, { check_state: 'checking', points: null, check_comment: null })
  try {
    await api.checkAnswer(answerId)
  } catch (e) {
    // Roll back optimistic "checking" state when request fails.
    store.updateAnswer(questionId, {
      check_state: prev.check_state ?? 'pending',
      check_comment: prev.check_comment ?? null,
      points: prev.points ?? null,
    })
    alert(e?.response?.data?.error || 'Не удалось запустить промежуточную проверку')
  }
}

async function doFinish() {
  if (finishing.value) return
  finishing.value = true
  actionError.value = ''
  try { await saver.flush() } catch {
    finishing.value = false
    actionError.value = 'Ответы не сохранены. Повторите сохранение перед завершением теста.'
    return
  }
  try {
    await api.finishAttempt(route.params.id)
    stopTimer()
    router.push(`/my-results/${route.params.id}`)
  } catch (e) {
    // 422 means already finished — navigate anyway.
    if (e?.response?.status === 422) {
      stopTimer()
      router.push(`/my-results/${route.params.id}`)
    } else {
      finishing.value = false
      actionError.value = 'Не удалось завершить тест. Попробуйте ещё раз.'
    }
  }
}

async function confirmFinish() {
  if (finishing.value) return
  const skipped = unansweredNumbers.value
  const summary = `Отвечено ${answeredCount.value} из ${store.attempt.questions.length}.`
    + (skipped.length ? `\nНе завершены вопросы № ${skipped.join(', ')}.` : '')
  if (!confirm(`${summary}\nЗавершить тест? Это действие нельзя отменить.`)) return
  await doFinish()
}

async function retrySaves() {
  actionError.value = ''
  try { await saver.flush() } catch {
    actionError.value = 'Не удалось сохранить ответы. Проверьте соединение и повторите.'
  }
}

function beforeUnload(event) {
  if (leaveUnsaved || !saver.hasPending()) return
  event.preventDefault()
  event.returnValue = ''
}

onBeforeRouteLeave(async () => {
  if (leaveUnsaved) return true
  if (!saver.hasPending()) return true
  try { await saver.flush(); return true } catch {
    actionError.value = 'Не удалось сохранить ответы. Повторите сохранение перед выходом.'
    return false
  }
})

function openClosedResults() {
  if (!confirm('Последние изменения не сохранены. Открыть результаты и покинуть эту страницу?')) return
  leaveUnsaved = true
  router.push(`/my-results/${route.params.id}`)
}

function syncTimerFromAttempt(attempt) {
  if (attempt.finished_at) {
    timeLeft.value = null
    timeDeadlineMs.value = null
    return
  }

  if (!attempt.time_deadline_at && attempt.time_left !== null) {
    timeDeadlineMs.value = Date.now() + Math.max(0, attempt.time_left || 0) * 1000
    serverClockOffsetMs = 0
    updateTimeLeft()
    return
  }

  if (!attempt.time_deadline_at) {
    timeLeft.value = null
    timeDeadlineMs.value = null
    return
  }

  const deadlineMs = Date.parse(attempt.time_deadline_at)
  const serverNowMs = Date.parse(attempt.server_time)
  if (Number.isNaN(deadlineMs) || Number.isNaN(serverNowMs)) {
    timeDeadlineMs.value = Date.now() + Math.max(0, attempt.time_left || 0) * 1000
    serverClockOffsetMs = 0
  } else {
    timeDeadlineMs.value = deadlineMs
    serverClockOffsetMs = serverNowMs - Date.now()
  }
  updateTimeLeft()
}

function updateTimeLeft() {
  if (!timeDeadlineMs.value || finishing.value) return
  const serverNowMs = Date.now() + serverClockOffsetMs
  const remaining = Math.max(0, Math.ceil((timeDeadlineMs.value - serverNowMs) / 1000))
  timeLeft.value = remaining
  if (remaining === 0 && !autoFinishAttempted) { autoFinishAttempted = true; doFinish() }
}

async function refreshTimer() {
  if (!store.attempt || !timeDeadlineMs.value || finishing.value) return
  try {
    const { data } = await api.getAttempt(route.params.id)
    store.attempt.finished_at = data.finished_at
    store.attempt.time_left = data.time_left
    store.attempt.server_time = data.server_time
    store.attempt.time_deadline_at = data.time_deadline_at

    if (data.finished_at) {
      stopTimer()
      router.push(`/my-results/${route.params.id}`)
      return
    }
    syncTimerFromAttempt(data)
  } catch {
    updateTimeLeft()
  }
}

function onVisibilityChange() {
  if (!document.hidden) refreshTimer()
}

function startTimer(attempt) {
  syncTimerFromAttempt(attempt)
  if (!timeDeadlineMs.value) return
  timerInterval = setInterval(updateTimeLeft, 1000)
  timerSyncInterval = setInterval(refreshTimer, 30000)
  document.addEventListener('visibilitychange', onVisibilityChange)
}

function stopTimer() {
  clearInterval(timerInterval)
  clearInterval(timerSyncInterval)
  timerInterval = null
  timerSyncInterval = null
  document.removeEventListener('visibilitychange', onVisibilityChange)
}

async function loadAttempt() {
  loadError.value = ''
  try { await store.load(route.params.id) } catch {
    loadError.value = 'Не удалось загрузить тест.'
    return
  }
  startTimer(store.attempt)
  socket = io({ path: '/socket.io' })
  socket.emit('join', { room: `attempt_${route.params.id}` })
  socket.on('answer_checked', (data) => store.applyWsUpdate(data))
  socket.on('attempt_checked', () => router.push(`/my-results/${route.params.id}`))
}

onMounted(() => {
  store.attempt = null
  loadAttempt()
  window.addEventListener('beforeunload', beforeUnload)
})

onUnmounted(() => {
  stopTimer()
  saver.dispose()
  window.removeEventListener('beforeunload', beforeUnload)
  socket?.disconnect()
})
</script>

<style scoped>
.ge-question-split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 1.5rem; align-items: start; }
.ge-question-split > * { min-width: 0; }
@media (min-width: 1000px) { .ge-question-split .ge-question-condition { max-height: 70vh; overflow-y: auto; padding-right: .75rem; } }
@media (max-width: 999px) { .ge-question-split { grid-template-columns: minmax(0, 1fr); } }
</style>
