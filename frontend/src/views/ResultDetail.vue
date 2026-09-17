<template>
  <div v-if="attempt" class="ge-fade-in">
    <div v-if="loadError" class="alert alert-danger" role="alert">{{ loadError }} <button class="btn btn-outline-danger btn-sm" @click="loadResult">Повторить</button></div>
    <div class="ge-page-header">
      <h4>{{ attempt.test_title }}</h4>
      <span v-if="attempt.is_checked" class="ge-score">{{ attempt.total_points }} / {{ attempt.max_points }}</span>
      <span v-else class="badge bg-info text-dark fs-6"><span class="spinner-border spinner-border-sm me-1" /> Проверяется</span>
    </div>

    <div v-if="attempt.topic_summary?.length" class="card mb-3">
      <div class="card-header">Темы</div>
      <div class="card-body p-0">
        <table class="table mb-0">
          <thead>
            <tr>
              <th>Тема</th>
              <th class="text-end">Баллы</th>
              <th class="text-end">Верно</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in attempt.topic_summary" :key="row.topic">
              <td>{{ row.topic }}</td>
              <td class="text-end">{{ formatScore(row.points) }} / {{ formatScore(row.max_points) }}</td>
              <td class="text-end">{{ row.percent }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-for="(q, i) in attempt.questions" :key="q.id" class="card mb-3">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span>{{ numberedQuestionTitle(q.title, i) }}</span>
        <template v-if="answer(q.id)?.check_state === 'checked'">
          <span class="badge" :class="scoreStatus(answer(q.id).points, q.max_points).badge">
            {{ scoreStatus(answer(q.id).points, q.max_points).label }} · {{ answer(q.id).points }}/{{ q.max_points }}
          </span>
        </template>
        <span v-else-if="answer(q.id)?.check_state === 'checking'" class="badge bg-info text-dark">проверяется</span>
        <span v-else class="badge bg-secondary">—/{{ q.max_points }}</span>
      </div>
      <div class="card-body">
        <MarkdownBody v-if="q.body" class="mb-2" :source="q.body" compact />
        <div class="mb-2">
          <strong class="small">Ваш ответ:</strong>
          <pre v-if="q.type === 'code_input'" class="ge-code mt-1">{{ answer(q.id)?.value?.code || '—' }}</pre>
          <div v-else-if="q.type === 'true_false_table'" class="mt-1">
            <TrueFalseTableQuestion :question="q" :modelValue="answer(q.id)?.value" :readonly="true" :checkResult="null" />
          </div>
          <div v-else-if="q.type === 'choice_table'" class="mt-1">
            <ChoiceTableQuestion :question="q" :modelValue="answer(q.id)?.value" :readonly="true" :checkResult="null" />
          </div>
          <div v-else-if="q.type === 'multi_input'" class="mt-1">
            <span v-if="!answer(q.id)?.value" class="text-muted">—</span>
            <span v-for="field in (q.ui_config?.fields || [])" :key="field.name" class="me-3">
              <span class="ge-markdown-inline" v-html="markdownInline(field.label || field.name)" />
              <strong>{{ answer(q.id)?.value?.[field.name] ?? '—' }}</strong>
            </span>
          </div>
          <div v-else class="ge-answer-text mt-1">{{ answer(q.id)?.value?.text || '—' }}</div>
        </div>
        <template v-if="q.check_config && answer(q.id)?.check_state === 'checked' && answer(q.id)?.points < q.max_points">
          <div v-if="q.check_type === 'exact' && q.check_config.answer !== undefined" class="ge-check success">
            ✅ Правильный ответ: <strong>{{ q.check_config.answer }}</strong>
          </div>
          <div v-else-if="q.check_type === 'exact' && q.check_config.answers" class="ge-check success">
            ✅ <span v-for="field in (q.ui_config?.fields || [])" :key="field.name" class="me-2">
              <span class="ge-markdown-inline" v-html="markdownInline(field.label || field.name)" />:
              <strong>{{ q.check_config.answers[field.name] }}</strong>
            </span>
          </div>
        </template>
        <CheckResult :result="answer(q.id)" :max-points="q.max_points" />
      </div>
    </div>
  </div>
  <div v-else-if="loadError" class="alert alert-danger" role="alert">{{ loadError }} <button class="btn btn-outline-danger btn-sm" @click="loadResult">Повторить</button></div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { io } from 'socket.io-client'
import api from '../api'
import { numberedQuestionTitle, scoreStatus } from '../utils/answers'
import CheckResult from '../components/CheckResult.vue'
import MarkdownBody from '../components/MarkdownBody.vue'
import TrueFalseTableQuestion from '../components/questions/TrueFalseTableQuestion.vue'
import ChoiceTableQuestion from '../components/questions/ChoiceTableQuestion.vue'
import { renderMarkdown } from '../utils/markdown'

const route = useRoute()
const attempt = ref(null)
const loadError = ref('')
let socket = null

function answer(qid) { return attempt.value?.answers?.find(a => a.question_id === qid) }
function markdownInline(source) { return renderMarkdown(source, { inline: true }) }
function formatScore(value) { return Number.isInteger(value) ? value : Number(value).toFixed(2) }

async function loadResult() {
  loadError.value = ''
  let data
  try { ({ data } = await api.myAttemptResults(route.params.id)) } catch {
    loadError.value = 'Не удалось загрузить результаты.'
    return
  }
  attempt.value = data
  if (!data.is_checked) {
    socket = io({ path: '/socket.io' })
    socket.emit('join', { room: `attempt_${route.params.id}` })
    socket.on('answer_checked', (upd) => { const a = attempt.value?.answers?.find(x => x.question_id === upd.question_id); if (a) Object.assign(a, upd) })
    socket.on('attempt_checked', async () => { socket?.disconnect(); await loadResult() })
  }
}
onMounted(loadResult)
onUnmounted(() => socket?.disconnect())
</script>
