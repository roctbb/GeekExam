<template>
  <div v-if="attempt" class="ge-fade-in">
    <div class="ge-page-header">
      <h4>{{ attempt.test_title }} — {{ attempt.user_name }}</h4>
      <div class="d-flex gap-2 align-items-center">
        <span class="ge-score">{{ attempt.total_points ?? '—' }} / {{ attempt.max_points }}</span>
        <button class="btn btn-sm btn-outline-danger" @click="deleteAttempt">Удалить</button>
      </div>
    </div>

    <div v-for="(q, i) in attempt.questions" :key="q.id" class="card mb-3">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span>{{ i + 1 }}. {{ q.title }}</span>
        <span class="text-muted small">{{ q.check_type }} · {{ q.max_points }} б.</span>
      </div>
      <div class="card-body">
        <div class="mb-3">
          <strong>Ответ:</strong>
          <pre v-if="q.type === 'code_input'" class="ge-code mt-1">{{ answer(q.id)?.value?.code || '—' }}</pre>
          <div v-else-if="q.type === 'true_false_table'" class="mt-1">
            <span v-if="!answer(q.id)?.value?.answers?.length" class="text-muted">—</span>
            <span v-for="(v, idx) in (answer(q.id)?.value?.answers || [])" :key="idx" class="me-2 badge bg-light text-dark border">
              {{ q.ui_config?.statements?.[idx] ? q.ui_config.statements[idx].slice(0, 40) + '…' : idx + 1 }}:
              <strong>{{ v === true ? 'Верно' : v === false ? 'Неверно' : '—' }}</strong>
            </span>
          </div>
          <div v-else-if="q.type === 'multi_input'" class="mt-1">
            <span v-if="!answer(q.id)?.value" class="text-muted">—</span>
            <span v-for="field in (q.ui_config?.fields || [])" :key="field.name" class="me-3">
              {{ field.label }} <strong>{{ answer(q.id)?.value?.[field.name] ?? '—' }}</strong>
            </span>
          </div>
          <span v-else class="ms-2">{{ answer(q.id)?.value?.text || '—' }}</span>
        </div>

        <div v-if="q.check_type === 'manual' || answer(q.id)?.check_state === 'checked'">
          <div class="row g-2 align-items-center">
            <div class="col-auto">
              <input type="number" class="form-control form-control-sm" style="width:80px"
                :min="0" :max="q.max_points" v-model.number="grades[q.id].points" />
            </div>
            <div class="col">
              <input type="text" class="form-control form-control-sm" placeholder="Комментарий"
                v-model="grades[q.id].comment" />
            </div>
            <div class="col-auto">
              <button class="btn btn-sm btn-primary" @click="grade(q.id, answer(q.id).id)">Сохранить</button>
            </div>
          </div>
        </div>
        <div v-else class="text-muted small">
          {{ answer(q.id)?.check_state === 'checking' ? '🔄 Проверяется...' : answer(q.id)?.check_comment || '' }}
        </div>
      </div>
    </div>
  </div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../api'

const route = useRoute()
const router = useRouter()
const attempt = ref(null)
const grades = reactive({})

async function deleteAttempt() {
  if (!confirm('Удалить прохождение? Ученик сможет пройти тест заново.')) return
  await api.deleteAttempt(route.params.id)
  router.back()
}

function answer(qid) { return attempt.value?.answers?.find(a => a.question_id === qid) }

async function grade(questionId, answerId) {
  await api.gradeAnswer(answerId, grades[questionId].points, grades[questionId].comment)
  const a = answer(questionId)
  if (a) {
    a.points = grades[questionId].points
    a.check_comment = grades[questionId].comment
    a.check_state = 'checked'
  }
  const allChecked = attempt.value.answers.every(a => a.check_state === 'checked')
  if (allChecked) {
    attempt.value.total_points = attempt.value.answers.reduce((s, a) => s + (a.points || 0), 0)
    attempt.value.is_checked = true
  }
}

onMounted(async () => {
  const { data } = await api.getAttempt(route.params.id)
  attempt.value = data
  for (const q of data.questions) {
    const a = answer(q.id)
    grades[q.id] = { points: a?.points ?? 0, comment: a?.check_comment ?? '' }
  }
})
</script>
