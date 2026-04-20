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
        <div class="mb-3" v-html="renderedBody" />
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
import { marked } from 'marked'
import { useAttemptStore } from '../stores/attempt'
import api from '../api'
import TextInputQuestion from '../components/questions/TextInputQuestion.vue'
import CodeInputQuestion from '../components/questions/CodeInputQuestion.vue'
import TrueFalseTableQuestion from '../components/questions/TrueFalseTableQuestion.vue'
import InteractiveQuestion from '../components/questions/InteractiveQuestion.vue'
import MultiInputQuestion from '../components/questions/MultiInputQuestion.vue'

const questionComponents = { text_input: TextInputQuestion, code_input: CodeInputQuestion, true_false_table: TrueFalseTableQuestion, interactive: InteractiveQuestion, multi_input: MultiInputQuestion }

const route = useRoute()
const router = useRouter()
const store = useAttemptStore()
const activeTab = ref(0)
const timeLeft = ref(null)
let timerInterval = null, saveTimeout = null, socket = null

const currentQuestion = computed(() => store.attempt?.questions[activeTab.value])
const currentAnswer = computed(() => store.answers[currentQuestion.value?.id] || {})
const renderedBody = computed(() => currentQuestion.value?.body ? marked(currentQuestion.value.body) : '')

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
  if (a.value) return 'answered'
  return ''
}

function formatTime(s) { return `${Math.floor(s/60)}:${(s%60).toString().padStart(2,'0')}` }

function onAnswerUpdate(value) {
  store.updateAnswer(currentQuestion.value.id, { value })
  clearTimeout(saveTimeout)
  const answerId = currentAnswer.value.id
  saveTimeout = setTimeout(() => api.saveAnswer(answerId, value), 2000)
}

async function onIntermediateCheck() {
  const questionId = currentQuestion.value.id
  const prev = { ...currentAnswer.value }
  store.updateAnswer(questionId, { check_state: 'checking' })
  try {
    await api.checkAnswer(currentAnswer.value.id)
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

async function confirmFinish() {
  if (!confirm('Завершить тест? Это действие нельзя отменить.')) return
  await api.finishAttempt(route.params.id)
  router.push(`/my-results/${route.params.id}`)
}

onMounted(async () => {
  await store.load(route.params.id)
  if (store.attempt.time_left !== null) {
    timeLeft.value = store.attempt.time_left
    timerInterval = setInterval(() => {
      if (timeLeft.value > 0) timeLeft.value--
      else { clearInterval(timerInterval); api.finishAttempt(route.params.id).then(() => router.push(`/my-results/${route.params.id}`)) }
    }, 1000)
  }
  socket = io({ path: '/socket.io' })
  socket.emit('join', { room: `attempt_${route.params.id}` })
  socket.on('answer_checked', (data) => store.applyWsUpdate(data))
  socket.on('attempt_checked', () => router.push(`/my-results/${route.params.id}`))
})

onUnmounted(() => { clearInterval(timerInterval); clearTimeout(saveTimeout); socket?.disconnect() })
</script>
