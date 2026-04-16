<template>
  <div v-if="attempt" class="ge-fade-in">
    <div class="ge-page-header">
      <h4>{{ attempt.test_title }}</h4>
      <span v-if="attempt.is_checked" class="ge-score">
        {{ attempt.total_points }} / {{ attempt.max_points }}
      </span>
      <span v-else class="badge bg-info text-dark fs-6">
        <span class="spinner-border spinner-border-sm me-1" /> Идёт проверка...
      </span>
    </div>

    <div v-for="(q, i) in attempt.questions" :key="q.id" class="card mb-3">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span>{{ i + 1 }}. {{ q.title }}</span>
        <span>
          <template v-if="answer(q.id)?.check_state === 'checked'">
            <span class="badge" :class="answer(q.id).points >= q.max_points ? 'bg-success' : answer(q.id).points > 0 ? 'bg-warning text-dark' : 'bg-danger'">
              {{ answer(q.id).points }} / {{ q.max_points }} б.
            </span>
          </template>
          <span v-else-if="answer(q.id)?.check_state === 'checking'" class="badge bg-info text-dark">проверяется...</span>
          <span v-else class="badge bg-secondary">— / {{ q.max_points }} б.</span>
        </span>
      </div>
      <div class="card-body">
        <div v-if="q.body" class="mb-2 text-muted small" v-html="renderBody(q.body)" />
        <div class="mb-2">
          <strong>Ваш ответ:</strong>
          <pre v-if="q.type === 'code_input'" class="ge-code mt-1">{{ answer(q.id)?.value?.code || '—' }}</pre>
          <div v-else-if="q.type === 'true_false_table'" class="mt-1">
            <TrueFalseTableQuestion :question="q" :modelValue="answer(q.id)?.value" :readonly="true" :checkResult="null" />
          </div>
          <div v-else-if="q.type === 'multi_input'" class="mt-1">
            <span v-if="!answer(q.id)?.value" class="text-muted">—</span>
            <span v-for="field in (q.ui_config?.fields || [])" :key="field.name" class="me-3">
              {{ field.label }} <strong>{{ answer(q.id)?.value?.[field.name] ?? '—' }}</strong>
            </span>
          </div>
          <span v-else>{{ answer(q.id)?.value?.text || '—' }}</span>
        </div>

        <template v-if="q.check_config && answer(q.id)?.check_state === 'checked' && answer(q.id)?.points < q.max_points">
          <div v-if="q.check_type === 'exact' && q.check_config.answer !== undefined" class="mb-2 text-success small">
            ✅ Правильный ответ: <strong>{{ q.check_config.answer }}</strong>
          </div>
          <div v-else-if="q.check_type === 'exact' && q.check_config.answers" class="mb-2 text-success small">
            ✅ Правильный ответ:
            <span v-for="field in (q.ui_config?.fields || [])" :key="field.name" class="me-3">
              {{ field.label }} <strong>{{ q.check_config.answers[field.name] }}</strong>
            </span>
          </div>
        </template>

        <div v-if="answer(q.id)?.check_comment" class="text-muted small mt-1">
          💬 {{ answer(q.id).check_comment }}
        </div>
      </div>
    </div>
  </div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { io } from 'socket.io-client'
import { marked } from 'marked'
import api from '../api'
import TrueFalseTableQuestion from '../components/questions/TrueFalseTableQuestion.vue'

const route = useRoute()
const attempt = ref(null)
let socket = null

function answer(qid) { return attempt.value?.answers?.find(a => a.question_id === qid) }
function renderBody(body) { return body ? marked(body) : '' }

onMounted(async () => {
  const { data } = await api.myAttemptResults(route.params.id)
  attempt.value = data

  if (!data.is_checked) {
    socket = io({ path: '/socket.io' })
    socket.emit('join', { room: `attempt_${route.params.id}` })
    socket.on('answer_checked', (upd) => {
      const a = attempt.value?.answers?.find(x => x.question_id === upd.question_id)
      if (a) Object.assign(a, upd)
    })
    socket.on('attempt_checked', async () => {
      const { data: fresh } = await api.myAttemptResults(route.params.id)
      attempt.value = fresh
      socket?.disconnect()
    })
  }
})

onUnmounted(() => socket?.disconnect())
</script>
