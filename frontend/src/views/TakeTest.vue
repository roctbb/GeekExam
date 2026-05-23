<template>
  <div v-if="store.attempt" class="ge-fade-in">
    <div class="ge-page-header">
      <h4>{{ store.attempt.test_title }}</h4>
      <div class="d-flex align-items-center gap-3">
        <span v-if="timeLeft !== null" class="ge-timer" :class="{ danger: timeLeft < 60 }">
          ⏱ {{ formatTime(timeLeft) }}
        </span>
        <button class="btn btn-danger btn-sm" @click="confirmFinish">Завершить</button>
      </div>
    </div>

    <!-- Progress -->
    <div class="ge-progress">
      <div class="ge-progress-bar" :style="{ width: progressPct + '%' }" />
    </div>

    <!-- Question tabs -->
    <div class="ge-question-tabs">
      <div v-for="(q, i) in store.attempt.questions" :key="q.id"
        class="ge-tab" :class="[activeTab === i ? 'active' : '', tabClass(q.id)]"
        @click="activeTab = i">
        {{ i + 1 }}
      </div>
    </div>

    <!-- Active question -->
    <div v-if="currentQuestion" class="card mb-3">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span>{{ currentQuestion.title }}</span>
        <span class="badge bg-secondary">{{ currentQuestion.max_points }} б.</span>
      </div>
      <div class="card-body">
        <MarkdownBody class="mb-3" :source="currentQuestion.body" />
        <component :is="questionComponent(currentQuestion.type)"
          :question="currentQuestion" :modelValue="currentAnswer.value"
          :readonly="!!store.attempt.finished_at" :checkResult="currentAnswer"
          @update:modelValue="onAnswerUpdate" @check="onIntermediateCheck" />
        <div class="d-flex justify-content-between mt-3">
          <button class="btn btn-outline-secondary btn-sm" :disabled="activeTab === 0" @click="activeTab--">← Назад</button>
          <button class="btn btn-outline-secondary btn-sm" :disabled="activeTab === store.attempt.questions.length - 1" @click="activeTab++">Далее →</button>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { io } from 'socket.io-client'
import { useAttemptStore } from '../stores/attempt'
import api from '../api'
import MarkdownBody from '../components/MarkdownBody.vue'
import TextInputQuestion from '../components/questions/TextInputQuestion.vue'
import CodeInputQuestion from '../components/questions/CodeInputQuestion.vue'
import TrueFalseTableQuestion from '../components/questions/TrueFalseTableQuestion.vue'
import InteractiveQuestion from '../components/questions/InteractiveQuestion.vue'
import MultiInputQuestion from '../components/questions/MultiInputQuestion.vue'
import ChoiceTableQuestion from '../components/questions/ChoiceTableQuestion.vue'

const questionComponents = { text_input: TextInputQuestion, code_input: CodeInputQuestion, true_false_table: TrueFalseTableQuestion, interactive: InteractiveQuestion, multi_input: MultiInputQuestion, choice_table: ChoiceTableQuestion }

const route = useRoute()
const router = useRouter()
const store = useAttemptStore()
const activeTab = ref(0)
const timeLeft = ref(null)
const finishing = ref(false)
const timeDeadlineMs = ref(null)
let serverClockOffsetMs = 0
let timerInterval = null, timerSyncInterval = null, socket = null
const saveTimeouts = new Map()
const pendingSaves = new Map()

const currentQuestion = computed(() => store.attempt?.questions[activeTab.value])
const currentAnswer = computed(() => store.answers[currentQuestion.value?.id] || {})

const progressPct = computed(() => {
  if (!store.attempt) return 0
  const answered = Object.values(store.answers).filter(a => a.value).length
  return Math.round((answered / store.attempt.questions.length) * 100)
})

function questionComponent(type) { return questionComponents[type] || TextInputQuestion }

function tabClass(questionId) {
  const a = store.answers[questionId]
  if (!a) return ''
  if (a.check_state === 'checked') return a.points > 0 ? 'correct' : 'wrong'
  // 'intermediate' is a transient UI-only state — show as answered, not scored.
  if (a.value) return 'answered'
  return ''
}

function formatTime(s) { return `${Math.floor(s/60)}:${(s%60).toString().padStart(2,'0')}` }

function onAnswerUpdate(value) {
  const questionId = currentQuestion.value.id
  const prev = currentAnswer.value

  // Only reset stale check results when the value actually changed.
  // Comparing by JSON handles table/object answers (arrays, dicts).
  const valueChanged = JSON.stringify(prev.value) !== JSON.stringify(value)
  const patch = valueChanged
    ? { value, check_state: 'pending', points: null, check_comment: null }
    : { value }

  store.updateAnswer(questionId, patch)
  scheduleAnswerSave(prev.id, value)
}

async function onIntermediateCheck() {
  const questionId = currentQuestion.value.id
  const answerId = currentAnswer.value.id
  const prev = { ...currentAnswer.value }

  // Flush any pending debounced save so the checker sees the latest value
  await flushPendingSaves()

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
  try {
    await flushPendingSaves()
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
      alert('Не удалось завершить тест. Попробуйте ещё раз.')
    }
  }
}

async function confirmFinish() {
  if (finishing.value) return
  if (!confirm('Завершить тест? Это действие нельзя отменить.')) return
  await doFinish()
}

function scheduleAnswerSave(answerId, value) {
  clearTimeout(saveTimeouts.get(answerId))
  pendingSaves.set(answerId, value)
  const timeout = setTimeout(async () => {
    saveTimeouts.delete(answerId)
    const pendingValue = pendingSaves.get(answerId)
    pendingSaves.delete(answerId)
    try {
      await api.saveAnswer(answerId, pendingValue)
    } catch (e) {
      if (e?.response?.status !== 422) {
        alert(e?.response?.data?.error || 'Не удалось сохранить ответ')
      }
    }
  }, 2000)
  saveTimeouts.set(answerId, timeout)
}

async function flushPendingSaves() {
  const entries = Array.from(pendingSaves.entries())
  if (!entries.length) return

  for (const timeout of saveTimeouts.values()) clearTimeout(timeout)
  saveTimeouts.clear()
  pendingSaves.clear()
  await Promise.all(entries.map(([answerId, value]) => api.saveAnswer(answerId, value)))
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
  if (remaining === 0) doFinish()
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

onMounted(async () => {
  await store.load(route.params.id)
  startTimer(store.attempt)
  socket = io({ path: '/socket.io' })
  socket.emit('join', { room: `attempt_${route.params.id}` })
  socket.on('answer_checked', (data) => store.applyWsUpdate(data))
  socket.on('attempt_checked', () => router.push(`/my-results/${route.params.id}`))
})

onUnmounted(() => {
  stopTimer()
  for (const timeout of saveTimeouts.values()) clearTimeout(timeout)
  saveTimeouts.clear()
  pendingSaves.clear()
  socket?.disconnect()
})
</script>
