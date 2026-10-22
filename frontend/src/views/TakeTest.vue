<template>
  <div v-if="store.attempt" class="ge-fade-in">
    <div class="ge-attempt-toolbar">
    <div class="ge-page-header">
      <h4>{{ store.attempt.test_title }}</h4>
      <div class="d-flex align-items-center gap-3 flex-wrap">
        <span v-if="timeLeft !== null" class="ge-timer" :class="{ danger: timeLeft < 60 }">
          <AppIcon name="clock" />{{ formatTime(timeLeft) }}
        </span>
        <button class="btn btn-danger btn-sm" :disabled="finishing || saveClosed || hasRecovery || !!store.attempt.finished_at" @click="confirmFinish"><AppIcon name="finish" />{{ finishing ? 'Завершаю…' : 'Завершить' }}</button>
      </div>
    </div>

    <div v-if="saveClosed" class="alert alert-warning" role="alert">
      Тест завершён. Показанный черновик может отличаться от отправленных ответов. Скопируйте нужный текст перед выходом.
      <button class="btn btn-sm btn-outline-secondary ms-2" @click="openClosedResults">Открыть результаты</button>
    </div>
    <div v-else-if="actionError" class="alert alert-danger" role="alert">{{ actionError }}</div>
    <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
      <span class="small">Отвечено {{ answeredCount }} из {{ store.attempt.questions.length }}</span>
      <span v-if="saveState !== 'idle'" class="small" role="status" :class="saveState === 'error' ? 'text-danger' : 'text-muted'">
        <AppIcon v-if="saveState !== 'saving'" :name="saveState === 'saved' ? 'check' : 'warning'" class="me-1" />
        {{ saveState === 'saving' ? 'Сохраняется…' : saveState === 'saved' ? 'Все изменения сохранены' : 'Не удалось сохранить ответ' }}
        <button v-if="saveState === 'error' && !saveClosed" class="btn btn-sm btn-outline-danger ms-2" @click="retrySaves">Повторить сохранение</button>
      </span>
    </div>
    <!-- Progress -->
    <div class="ge-progress">
      <div class="ge-progress-bar" :style="{ width: progressPct + '%' }" />
    </div>
    </div>
    <div v-if="hasRecovery" class="alert alert-warning" role="alert">
      Найдены несохранённые ответы с прошлого посещения. Восстановление заменит соответствующие ответы на экране.
      <div class="d-flex gap-2 flex-wrap mt-2">
        <button class="btn btn-sm btn-primary" @click="restoreDrafts">{{ saveClosed ? 'Показать черновик' : 'Восстановить ответы' }}</button>
        <button class="btn btn-sm btn-outline-secondary" @click="discardDrafts">Оставить ответы с сервера</button>
      </div>
    </div>
    <div v-if="draftWarning" class="alert alert-warning" role="alert">{{ draftWarning }}</div>

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
        <div v-if="currentAnswerSizeError" class="alert alert-danger" role="alert">
          {{ currentAnswerSizeError }}. Сохранённый ответ слишком большой для открытия. Обратитесь к преподавателю.
        </div>
        <component v-else :is="questionComponent(currentQuestion.type)" :key="currentQuestion.id"
          :question="currentQuestion" :modelValue="currentAnswer.value"
          :readonly="answerReadonly" :checkResult="currentAnswer"
          @update:modelValue="onAnswerUpdate" />
        </div>
        <IntermediateCheckButton :question="currentQuestion" :result="currentAnswer" :readonly="answerReadonly || !!currentAnswerSizeError"
          :busy="checkingIds.has(currentQuestion.id)" @check="onIntermediateCheck" />
        <div class="d-flex justify-content-between mt-3">
          <button class="btn btn-outline-secondary btn-sm" :disabled="activeTab === 0" @click="activeTab--"><AppIcon name="arrow-left" />Назад</button>
          <button class="btn btn-outline-secondary btn-sm" :disabled="activeTab === store.attempt.questions.length - 1" @click="activeTab++">Далее<AppIcon name="arrow-right" class="ge-icon-trailing" /></button>
        </div>
      </div>
    </div>
  </div>
  <div v-else-if="loadError" class="alert alert-danger" role="alert">{{ loadError }} <button class="btn btn-outline-danger btn-sm" @click="loadAttempt">Повторить</button></div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { io } from 'socket.io-client'
import { useAttemptStore } from '../stores/attempt'
import { useAuthStore } from '../stores/auth'
import api from '../api'
import { isQuestionAnswered, scoreStatus, sameAnswerValue } from '../utils/answers'
import { createAnswerSaver } from '../utils/answerSaver'
import { createDraftStorage, createAnswerDrafts } from '../utils/drafts'
import { createLiveRefresh } from '../utils/liveRefresh'
import { validateAnswerSize } from '../utils/answerLimits'
import { createAttemptTimer } from '../utils/attemptTimer'
import IntermediateCheckButton from '../components/IntermediateCheckButton.vue'
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
const attemptTimer = createAttemptTimer()
let timerInterval = null, live = null, disposed = false
const saveState = ref('idle')
const actionError = ref('')
const loadError = ref('')
const saveClosed = ref(false)
const recoveredDrafts = ref({})
const hasRecovery = computed(() => Object.keys(recoveredDrafts.value).length > 0)
const draftWarning = ref('')
const checkingIds = ref(new Set())
const answerReadonly = computed(() => !!store.attempt?.finished_at || finishing.value || saveClosed.value || timeLeft.value === 0 || hasRecovery.value)
const drafts = createAnswerDrafts(createDraftStorage(`geekexam:answers:${useAuthStore().user.id}:${route.params.id}`))
let leaveUnsaved = false
function draftStored(ok) {
  draftWarning.value = ok ? '' : 'Не удалось сохранить резервный черновик в браузере. Не закрывайте страницу, пока ответы не отправлены на сервер.'
}
const saver = createAnswerSaver(async (id, value) => {
  try {
    await api.saveAnswer(id, value)
    draftStored(drafts.acknowledge(id, value))
  } catch (e) {
    if (e?.response?.data?.error_code === 'attempt_finished') { saveClosed.value = true; stopTimer() }
    throw e
  }
}, state => { saveState.value = state })
let autoFinishAttempted = false
let nextFinishRetryAt = 0

const currentQuestion = computed(() => store.attempt?.questions[activeTab.value])
const currentAnswer = computed(() => store.answers[currentQuestion.value?.id] || {})
const currentAnswerSizeError = computed(() => {
  if (!currentQuestion.value) return ''
  try { validateAnswerSize(currentAnswer.value.value, currentQuestion.value); return '' }
  catch (error) { return error.message }
})

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
  if (answerReadonly.value) return
  try { validateAnswerSize(value, currentQuestion.value) }
  catch (error) { actionError.value = error.message; return }
  const questionId = currentQuestion.value.id
  const prev = currentAnswer.value

  // Only reset stale check results when the value actually changed.
  // Comparing by JSON handles table/object answers (arrays, dicts).
  const valueChanged = JSON.stringify(prev.value) !== JSON.stringify(value)
  const patch = valueChanged
    ? { value, check_state: 'pending', points: null, check_comment: null }
    : { value }

  store.updateAnswer(questionId, patch)
  if (valueChanged) {
    draftStored(drafts.set(prev.id, value))
    saver.schedule(prev.id, value)
    if (timeLeft.value !== null && timeLeft.value <= 10) saver.flush().catch(() => {})
  }
}

async function onIntermediateCheck() {
  const question = currentQuestion.value
  const questionId = question.id
  if (answerReadonly.value || checkingIds.value.has(questionId)) return
  checkingIds.value.add(questionId)
  actionError.value = ''
  let previous
  try {
    if (question.type === 'code_input' && currentAnswer.value.value == null && question.ui_config?.starter_code) {
      onAnswerUpdate({ code: question.ui_config.starter_code, lang: question.ui_config.lang || 'python' })
    }
    await saver.flush()
    if (answerReadonly.value) return
    previous = { ...store.answers[questionId] }
    store.updateAnswer(questionId, { check_state: 'checking', points: null, check_comment: null })
    await api.checkAnswer(previous.id)
    await live?.refresh()
  } catch (e) {
    const current = store.answers[questionId]
    if (previous && sameAnswerValue(current.value, previous.value) && current.check_state === 'checking') {
      store.updateAnswer(questionId, { check_state: previous.check_state, check_comment: previous.check_comment, points: previous.points })
    }
    actionError.value = e?.response?.data?.error || 'Не удалось сохранить или проверить ответ. Проверьте соединение и повторите.'
  } finally { checkingIds.value.delete(questionId) }
}

function showFinished(data) {
  store.attempt.finished_at = data.finished_at || store.attempt.finished_at || new Date().toISOString()
  stopTimer()
  live?.stop()
  if (saver.hasPending() || hasRecovery.value || saveClosed.value) {
    saveClosed.value = true
    finishing.value = false
  } else {
    router.replace(`/my-results/${route.params.id}`)
  }
}

async function doFinish() {
  if (finishing.value || hasRecovery.value) return
  finishing.value = true
  actionError.value = ''
  try { await saver.flush() } catch {
    if (timeLeft.value !== 0 && !saveClosed.value) {
      finishing.value = false
      actionError.value = 'Ответы не сохранены. Повторите сохранение перед завершением теста.'
      return
    }
    // A failed last save must not keep an expired attempt editable. Preserve
    // its draft, but still request finalization of the server's saved answers.
    saveClosed.value = true
  }
  try {
    await api.finishAttempt(route.params.id)
    showFinished({})
  } catch (e) {
    if (e?.response?.status === 422) showFinished({})
    else {
      finishing.value = false
      autoFinishAttempted = false
      nextFinishRetryAt = Date.now() + 5000
      actionError.value = 'Не удалось завершить тест. Проверьте соединение и повторите.'
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
  if (leaveUnsaved || (!saver.hasPending() && !hasRecovery.value)) return
  event.preventDefault()
  event.returnValue = ''
}

async function beforeLeave() {
  if (leaveUnsaved) return true
  if (hasRecovery.value) return confirm('Покинуть страницу? Несохранённые ответы останутся в черновике этого браузера.')
  if (!saver.hasPending()) return true
  try { await saver.flush(); return true } catch {
    actionError.value = 'Не удалось сохранить ответы. Повторите сохранение перед выходом.'
    return false
  }
}
onBeforeRouteLeave(beforeLeave)
onBeforeRouteUpdate(beforeLeave)

function restoreDrafts() {
  const entries = recoveredDrafts.value
  recoveredDrafts.value = {}
  for (const [id, entry] of Object.entries(entries)) {
    const answer = Object.values(store.answers).find(a => String(a.id) === id)
    if (!answer) continue
    const question = store.attempt.questions.find(q => q.id === answer.question_id)
    try { validateAnswerSize(entry.value, question) }
    catch (error) { actionError.value = error.message; continue }
    store.updateAnswer(answer.question_id, { value: entry.value, check_state: 'pending', points: null, check_comment: null })
    if (!saveClosed.value && !store.attempt.finished_at && timeLeft.value !== 0) saver.schedule(answer.id, entry.value)
  }
  if (!saveClosed.value && !store.attempt.finished_at && timeLeft.value !== 0) retrySaves()
  else {
    saveClosed.value = true
    if (!store.attempt.finished_at) doFinish()
  }
}

function discardDrafts() {
  if (!confirm('Удалить найденный черновик и оставить ответы с сервера?')) return
  recoveredDrafts.value = {}
  draftStored(drafts.clear())
  if (store.attempt.finished_at) { saveClosed.value = false; showFinished(store.attempt) }
  else if (timeLeft.value === 0) doFinish()
}

function openClosedResults() {
  if (!confirm('Последние изменения не сохранены. Открыть результаты и покинуть эту страницу?')) return
  leaveUnsaved = true
  router.push(`/my-results/${route.params.id}`)
}

function syncTimerFromAttempt(attempt) {
  attemptTimer.sync(attempt)
  updateTimeLeft()
}

function updateTimeLeft() {
  if (finishing.value) return
  const remaining = attemptTimer.remaining()
  timeLeft.value = remaining
  if (remaining === 0 && !autoFinishAttempted && Date.now() >= nextFinishRetryAt) { autoFinishAttempted = true; doFinish() }
}

function mergeSnapshot(data) {
  // Do not replace typed values with an HTTP response that started before a
  // local edit/save. Only adopt check results for the exact displayed answer.
  Object.assign(store.attempt, data)
  for (const answer of data.answers) {
    const local = store.answers[answer.question_id]
    if (local && !saver.hasPending(answer.id) && sameAnswerValue(local.value, answer.value)) {
      // The backend keeps an active attempt ungraded (pending). Its HTTP
      // snapshot must not erase a matching intermediate result from Socket.IO.
      const preserveResult = !data.finished_at && answer.check_state === 'pending'
        && ['intermediate', 'error'].includes(local.check_state)
      if (!preserveResult) store.updateAnswer(answer.question_id, answer)
    }
  }
  if (data.finished_at) showFinished(data)
  else syncTimerFromAttempt(data)
}

function onOnline() {
  if (!saveClosed.value && timeLeft.value !== 0 && saver.hasPending()) retrySaves()
  if (timeLeft.value === 0 && !store.attempt?.finished_at) doFinish()
}
function onVisibilityChange() {
  if (document.hidden && !saveClosed.value && saver.hasPending()) saver.flush().catch(() => {})
}

function startTimer(attempt) {
  syncTimerFromAttempt(attempt)
  stopTimer()
  timerInterval = setInterval(updateTimeLeft, 1000)
}

function stopTimer() {
  clearInterval(timerInterval)
  timerInterval = null
}

async function loadAttempt() {
  loadError.value = ''
  try { await store.load(route.params.id) } catch {
    loadError.value = 'Не удалось загрузить тест.'
    return
  }
  if (disposed) return
  const savedDrafts = drafts.entries()
  for (const answer of Object.values(store.answers)) {
    const draft = savedDrafts[answer.id]
    if (!draft || !Object.hasOwn(draft, 'value')) continue
    if (sameAnswerValue(answer.value, draft.value)) draftStored(drafts.acknowledge(answer.id, draft.value))
    else recoveredDrafts.value[answer.id] = draft
  }
  startTimer(store.attempt)
  if (store.attempt.finished_at) { showFinished(store.attempt); return }
  live = createLiveRefresh({
    socket: io({ path: '/socket.io', autoConnect: false }),
    room: `attempt_${route.params.id}`,
    fetchSnapshot: async () => (await api.getAttempt(route.params.id)).data,
    applySnapshot: mergeSnapshot,
    applyAnswerUpdate: payload => {
      const answer = store.answers[payload?.question_id]
      if (answer && !saver.hasPending(answer.id) && Object.hasOwn(payload, 'checked_value')) {
        store.applyWsUpdate(payload)
      }
    },
    shouldPoll: () => !store.attempt.finished_at,
  })
  live.start()
}

onMounted(() => {
  store.attempt = null
  loadAttempt()
  window.addEventListener('beforeunload', beforeUnload)
  window.addEventListener('online', onOnline)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  disposed = true
  stopTimer()
  saver.dispose()
  window.removeEventListener('beforeunload', beforeUnload)
  window.removeEventListener('online', onOnline)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  live?.stop()
})
</script>

<style scoped>
.ge-question-split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 1.5rem; align-items: start; }
.ge-question-split > * { min-width: 0; }
@media (min-width: 1000px) { .ge-question-split .ge-question-condition { max-height: 70vh; overflow-y: auto; padding-right: .75rem; } }
@media (max-width: 999px) { .ge-question-split { grid-template-columns: minmax(0, 1fr); } }
</style>
