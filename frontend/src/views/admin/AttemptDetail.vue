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
    <div v-for="(q, i) in attempt.questions" :key="q.id" class="card mb-3">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span>{{ i + 1 }}. {{ q.title }}</span>
        <span class="text-muted small">{{ q.check_type }} · {{ q.max_points }} б.</span>
      </div>
      <div class="card-body">

        <!-- Question body -->
        <div v-if="q.body" class="mb-3 text-muted small border-start border-2 ps-2" style="white-space: pre-wrap">{{ q.body }}</div>

        <!-- Answer display -->
        <div class="mb-3">
          <strong class="small">Ответ:</strong>
          <pre v-if="q.type === 'code_input'" class="ge-code mt-1">{{ answer(q.id)?.value?.code || '—' }}</pre>
          <div v-else-if="q.type === 'true_false_table'" class="mt-1">
            <span v-if="!answer(q.id)?.value?.answers?.length" class="text-muted">—</span>
            <span v-for="(v, idx) in (answer(q.id)?.value?.answers || [])" :key="idx" class="me-2 badge bg-light text-dark border">
              {{ q.ui_config?.statements?.[idx]?.slice(0,40) || idx+1 }}: <strong>{{ v === true ? 'В' : v === false ? 'Н' : '—' }}</strong>
            </span>
          </div>
          <div v-else-if="q.type === 'multi_input'" class="mt-1">
            <span v-for="field in (q.ui_config?.fields || [])" :key="field.name" class="me-3">{{ field.label }} <strong>{{ answer(q.id)?.value?.[field.name] ?? '—' }}</strong></span>
          </div>
          <div v-else-if="q.type === 'choice_table'" class="mt-1">
            <span v-if="!answer(q.id)?.value?.answers?.length" class="text-muted">—</span>
            <span v-for="(v, idx) in (answer(q.id)?.value?.answers || [])" :key="idx" class="me-2 badge bg-light text-dark border">
              {{ q.ui_config?.items?.[idx]?.label || idx + 1 }}: <strong>{{ optionLabel(q, v) }}</strong>
            </span>
          </div>
          <span v-else class="ms-2">{{ answer(q.id)?.value?.text || '—' }}</span>
        </div>

        <!-- Auto-check result (ai/docker/exact/checker) -->
        <div v-if="isAutoCheck(q)" class="mb-3">
          <div v-if="answer(q.id)?.check_state === 'checking'" class="text-muted small">
            <span class="spinner-border spinner-border-sm me-1" /> Проверяется...
          </div>
          <div v-else-if="answer(q.id)?.check_state === 'checked' || answer(q.id)?.check_state === 'error'" class="mb-2">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="badge" :class="answer(q.id)?.check_state === 'checked' ? (answer(q.id)?.points > 0 ? 'bg-success' : 'bg-danger') : 'bg-warning text-dark'">
                {{ answer(q.id)?.check_state === 'checked' ? answer(q.id)?.points + ' б.' : 'Ошибка' }}
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
          <div class="col-auto"><input type="number" class="form-control form-control-sm" style="width:80px" :min="0" :max="q.max_points" v-model.number="grades[q.id].points" /></div>
          <div class="col"><input type="text" class="form-control form-control-sm" placeholder="Комментарий" v-model="grades[q.id].comment" /></div>
          <div class="col-auto"><button class="btn btn-sm btn-primary" @click="grade(q.id, answer(q.id).id)">Сохранить</button></div>
        </div>

      </div>
    </div>
  </div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { io } from 'socket.io-client'
import api from '../../api'

const route = useRoute(), router = useRouter()
const attempt = ref(null), grades = reactive({})
const recheckingAll = ref(false)
let socket = null

function answer(qid) { return attempt.value?.answers?.find(a => a.question_id === qid) }
function optionLabel(q, value) { return q.ui_config?.options?.find(o => o.value === value)?.label || value || '—' }
function isAutoCheck(q) { return q.check_type !== 'manual' }
function isAsyncCheck(q) { return q.check_type === 'ai' || q.check_type === 'docker' }

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
  await api.gradeAnswer(aid, grades[qid].points, grades[qid].comment)
  const a = answer(qid)
  if (a) { a.points = grades[qid].points; a.check_comment = grades[qid].comment; a.check_state = 'checked' }
  if (attempt.value.answers.every(a => a.check_state === 'checked')) {
    attempt.value.total_points = attempt.value.answers.reduce((s, a) => s + (a.points || 0), 0)
    attempt.value.is_checked = true
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

onMounted(async () => {
  const { data } = await api.getAttempt(route.params.id)
  attempt.value = data
  syncGrades(data)

  // Subscribe to live check results so recheck updates without page reload.
  socket = io({ path: '/socket.io' })
  socket.emit('join', { room: `attempt_${route.params.id}` })
  socket.on('answer_checked', ({ question_id, points, check_state, check_comment }) => {
    const a = answer(question_id)
    if (!a) return
    a.points = points
    a.check_state = check_state
    a.check_comment = check_comment
    // Sync grade form fields with new auto-check result.
    if (grades[question_id]) {
      grades[question_id].points = points ?? grades[question_id].points
      grades[question_id].comment = check_comment ?? grades[question_id].comment
    }
    // Recompute total if all done.
    if (attempt.value.answers.every(a => a.check_state === 'checked')) {
      attempt.value.total_points = attempt.value.answers.reduce((s, a) => s + (a.points || 0), 0)
      attempt.value.is_checked = true
    }
  })
})

onUnmounted(() => { socket?.disconnect() })
</script>
