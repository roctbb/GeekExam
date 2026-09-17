<template>
  <div v-if="attempt" class="ge-fade-in">
    <div class="ge-page-header">
      <h4>{{ attempt.test_title }} — {{ attempt.user_name }}</h4>
      <div class="d-flex gap-2 align-items-center flex-wrap justify-content-end">
        <button class="btn btn-sm btn-outline-secondary" :disabled="recheckingAll || !canRecheckAttempt" @click="recheckAll">
          <span v-if="recheckingAll" class="spinner-border spinner-border-sm me-1" />
          {{ recheckingAll ? 'Запускаю...' : 'Перепроверить всю работу' }}
        </button>
        <span class="ge-score">{{ attempt.total_points ?? '—' }} / {{ attempt.max_points }}</span>
        <button class="btn btn-sm btn-outline-danger" @click="del">Удалить</button>
      </div>
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
        <span class="text-muted small">{{ q.check_type }} · {{ q.max_points }} б.</span>
      </div>
      <div class="card-body">

        <!-- Question body -->
        <MarkdownBody v-if="q.body" class="mb-3 border-start border-2 ps-2" :source="q.body" compact />

        <!-- Answer display -->
        <div class="mb-3">
          <strong class="small">Ответ:</strong>
          <pre v-if="q.type === 'code_input'" class="ge-code mt-1">{{ answer(q.id)?.value?.code || '—' }}</pre>
          <div v-else-if="q.type === 'true_false_table'" class="mt-1">
            <span v-if="!answer(q.id)?.value?.answers?.length" class="text-muted">—</span>
            <span v-for="(v, idx) in (answer(q.id)?.value?.answers || [])" :key="idx" class="me-2 badge bg-light text-dark border ge-answer-badge">
              <span class="ge-markdown-inline" v-html="markdownInline(q.ui_config?.statements?.[idx] || idx + 1)" />:
              <strong>{{ v === true ? 'В' : v === false ? 'Н' : '—' }}</strong>
            </span>
          </div>
          <div v-else-if="q.type === 'multi_input'" class="mt-1">
            <span v-for="field in (q.ui_config?.fields || [])" :key="field.name" class="me-3">
              <span class="ge-markdown-inline" v-html="markdownInline(field.label || field.name)" />
              <strong>{{ answer(q.id)?.value?.[field.name] ?? '—' }}</strong>
            </span>
          </div>
          <div v-else-if="q.type === 'choice_table'" class="mt-1">
            <span v-if="!answer(q.id)?.value?.answers?.length" class="text-muted">—</span>
            <span v-for="(v, idx) in (answer(q.id)?.value?.answers || [])" :key="idx" class="me-2 badge bg-light text-dark border ge-answer-badge">
              <span class="ge-markdown-inline" v-html="markdownInline(q.ui_config?.items?.[idx]?.label || idx + 1)" />:
              <strong><span class="ge-markdown-inline" v-html="markdownInline(optionLabel(q, v))" /></strong>
            </span>
          </div>
          <div v-else class="ge-answer-text mt-1">{{ answer(q.id)?.value?.text || '—' }}</div>
        </div>

        <ExpectedAnswer :question="q" />

        <!-- Auto-check result (ai/docker/exact/checker) -->
        <div v-if="isAutoCheck(q)" class="mb-3">
          <div v-if="answer(q.id)?.check_state === 'checking'" class="text-muted small">
            <span class="spinner-border spinner-border-sm me-1" /> Проверяется...
          </div>
          <div v-else-if="answer(q.id)?.check_state === 'checked' || answer(q.id)?.check_state === 'error'" class="mb-2">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="badge" :class="answer(q.id)?.check_state === 'checked' ? scoreStatus(answer(q.id)?.points, q.max_points).badge : 'bg-warning text-dark'">
                {{ answer(q.id)?.check_state === 'checked' ? scoreStatus(answer(q.id)?.points, q.max_points).label + ' · ' + answer(q.id)?.points + ' / ' + q.max_points + ' б.' : 'Ошибка' }}
              </span>
              <button v-if="isAsyncCheck(q)" class="btn btn-sm btn-outline-secondary" @click="recheck(q.id, answer(q.id).id)">
                Перепроверить нейронкой
              </button>
            </div>
            <pre v-if="answer(q.id)?.check_comment" class="mb-0 p-2 bg-light rounded small" style="white-space: pre-wrap; word-break: break-word">{{ answer(q.id).check_comment }}</pre>
          </div>
          <div v-else class="d-flex align-items-center gap-2">
            <span class="text-muted small">Не проверено</span>
            <button v-if="isAsyncCheck(q)" class="btn btn-sm btn-outline-secondary" @click="recheck(q.id, answer(q.id).id)">
              Запустить проверку нейронкой
            </button>
          </div>
        </div>

        <!-- Grade form (manual questions, or auto-checked for teacher override) -->
        <div v-if="q.check_type === 'manual' || answer(q.id)?.check_state === 'checked'" class="row g-2 align-items-center">
          <div class="col-auto"><input :disabled="gradeFeedback[q.id]?.state === 'saving'" @input="delete gradeFeedback[q.id]" aria-label="Баллы" type="number" class="form-control form-control-sm" style="width:80px" :min="0" :max="q.max_points" v-model.number="grades[q.id].points" /></div>
          <div class="col-12 col-md"><AutoTextarea class="form-control form-control-sm" placeholder="Комментарий" aria-label="Комментарий преподавателя" v-model="grades[q.id].comment" :disabled="gradeFeedback[q.id]?.state === 'saving'" @update:model-value="delete gradeFeedback[q.id]" /></div>
          <div class="col-auto"><button class="btn btn-sm btn-primary" :disabled="gradeFeedback[q.id]?.state === 'saving'" @click="grade(q.id, answer(q.id).id)">{{ gradeFeedback[q.id]?.state === 'saving' ? 'Сохраняется…' : 'Сохранить' }}</button></div>
          <div v-if="gradeFeedback[q.id]" class="col-12 small" role="status" :class="gradeFeedback[q.id].state === 'error' ? 'text-danger' : 'text-success'">{{ gradeFeedback[q.id].message }}</div>
        </div>

      </div>
    </div>
  </div>
  <div v-else-if="loadError" class="alert alert-danger" role="alert">{{ loadError }} <button class="btn btn-outline-danger btn-sm" @click="loadAttempt">Повторить</button></div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { io } from 'socket.io-client'
import api from '../../api'
import { numberedQuestionTitle, scoreStatus } from '../../utils/answers'
import AutoTextarea from '../../components/AutoTextarea.vue'
import ExpectedAnswer from '../../components/ExpectedAnswer.vue'
import MarkdownBody from '../../components/MarkdownBody.vue'
import { renderMarkdown } from '../../utils/markdown'

const route = useRoute(), router = useRouter()
const attempt = ref(null), grades = reactive({})
const loadError = ref('')
const recheckingAll = ref(false)
const gradeFeedback = reactive({})
let socket = null

function answer(qid) { return attempt.value?.answers?.find(a => a.question_id === qid) }
function optionLabel(q, value) { return String(q.ui_config?.options?.find(o => o.value === value)?.label ?? value ?? '—') }
function markdownInline(source) { return renderMarkdown(source, { inline: true }) }
function isAutoCheck(q) { return q.check_type !== 'manual' }
function isAsyncCheck(q) { return q.check_type === 'ai' || q.check_type === 'docker' }
function formatScore(value) { return Number.isInteger(value) ? value : Number(value).toFixed(2) }

const canRecheckAttempt = computed(() => {
  if (!attempt.value?.finished_at) return false
  const autoAnswers = attempt.value.questions
    .filter(isAutoCheck)
    .map(q => answer(q.id))
    .filter(Boolean)
  return autoAnswers.length > 0 && autoAnswers.every(a => a.check_state !== 'checking')
})

async function del() {
  if (!confirm('Удалить прохождение?')) return
  await api.deleteAttempt(route.params.id)
  router.back()
}

async function grade(qid, aid) {
  if (gradeFeedback[qid]?.state === 'saving') return
  const draft = { ...grades[qid] }
  const maxPoints = attempt.value.questions.find(q => q.id === qid).max_points
  if (typeof draft.points !== 'number' || !Number.isFinite(draft.points) || draft.points < 0 || draft.points > maxPoints) {
    gradeFeedback[qid] = { state: 'error', message: `Укажите баллы от 0 до ${maxPoints}.` }
    return
  }
  gradeFeedback[qid] = { state: 'saving', message: 'Сохраняется…' }
  try {
    await api.gradeAnswer(aid, draft.points, draft.comment)
    const a = answer(qid)
    if (a) { a.points = draft.points; a.check_comment = draft.comment; a.check_state = 'checked' }
    if (attempt.value.answers.every(a => a.check_state === 'checked')) {
      attempt.value.total_points = attempt.value.answers.reduce((s, a) => s + (a.points || 0), 0)
      attempt.value.is_checked = true
    }
    gradeFeedback[qid] = { state: 'saved', message: 'Оценка и комментарий сохранены' }
  } catch (e) {
    gradeFeedback[qid] = { state: 'error', message: e?.response?.data?.error || 'Не удалось сохранить оценку. Повторите попытку.' }
  }
}

async function recheck(qid, aid) {
  const a = answer(qid)
  if (!a) return
  try {
    a.check_state = 'checking'
    await api.recheckAnswer(aid)
  } catch (e) {
    a.check_state = 'error'
    alert(e?.response?.data?.error || 'Не удалось запустить перепроверку')
  }
}

async function recheckAll() {
  if (!attempt.value || !canRecheckAttempt.value) return
  if (!confirm('Перепроверить всю работу? Баллы по автопроверяемым вопросам будут обновлены.')) return

  recheckingAll.value = true
  const autoAnswers = attempt.value.questions
    .filter(isAutoCheck)
    .map(q => answer(q.id))
    .filter(Boolean)

  try {
    for (const a of autoAnswers) {
      a.check_state = 'checking'
      a.points = null
      a.check_comment = null
    }
    attempt.value.is_checked = false
    attempt.value.total_points = null
    await api.recheckAttempt(route.params.id)
  } catch (e) {
    alert(e?.response?.data?.error || 'Не удалось запустить перепроверку работы')
    const { data } = await api.getAttempt(route.params.id)
    attempt.value = data
    syncGrades(data)
  } finally {
    recheckingAll.value = false
  }
}

function syncGrades(data) {
  for (const q of data.questions) {
    const a = answer(q.id)
    grades[q.id] = { points: a?.points ?? 0, comment: a?.check_comment ?? '' }
  }
}

async function loadAttempt() {
  loadError.value = ''
  let data
  try { ({ data } = await api.getAttempt(route.params.id)) } catch {
    loadError.value = 'Не удалось загрузить работу.'
    return
  }
  attempt.value = data
  syncGrades(data)

  // Subscribe to live check results so recheck updates without page reload.
  socket = io({ path: '/socket.io' })
  socket.emit('join', { room: `attempt_${route.params.id}` })
  socket.on('answer_checked', ({ question_id, points, check_state, check_comment }) => {
    const a = answer(question_id)
    if (!a) return
    const draft = grades[question_id]
    const dirty = draft && (draft.points !== (a.points ?? 0) || draft.comment !== (a.check_comment ?? ''))
    a.points = points
    a.check_state = check_state
    a.check_comment = check_comment
    // Sync grade form fields with new auto-check result.
    if (grades[question_id] && !dirty) {
      grades[question_id].points = points ?? grades[question_id].points
      grades[question_id].comment = check_comment ?? grades[question_id].comment
    }
    // Recompute total if all done.
    if (attempt.value.answers.every(a => a.check_state === 'checked')) {
      attempt.value.total_points = attempt.value.answers.reduce((s, a) => s + (a.points || 0), 0)
      attempt.value.is_checked = true
    }
  })
}
onMounted(loadAttempt)

onUnmounted(() => { socket?.disconnect() })
</script>
