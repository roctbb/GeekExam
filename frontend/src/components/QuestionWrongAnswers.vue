<template>
  <div>
    <h6 class="mb-2">Частые ответы с ошибкой</h6>
    <p v-if="loading" class="small text-muted mb-0" role="status">Загружаем ответы…</p>
    <div v-else-if="error" class="d-flex align-items-center gap-2 flex-wrap" role="alert">
      <span>Не удалось загрузить ответы.</span>
      <button type="button" class="btn btn-sm btn-outline-secondary" @click="retry++">Повторить</button>
    </div>
    <p v-else-if="!result?.answers.length" class="small text-muted mb-0">Ответов с ошибкой пока нет.</p>
    <template v-else>
      <ul class="list-group mb-0">
        <li v-for="(answer, i) in result.answers" :key="i" class="list-group-item d-flex align-items-start gap-2">
          <div class="flex-grow-1 overflow-hidden">
            <div class="ge-answer-text">{{ answer.preview }}</div>
            <RouterLink :to="`/admin/attempts/${answer.example_attempt_id}`" class="small">Пример работы</RouterLink>
          </div>
          <span class="badge bg-secondary text-nowrap" :aria-label="`Повторений: ${answer.count}`">{{ answer.count }}×</span>
        </li>
      </ul>
      <p v-if="result.distinct_count > result.answers.length" class="small text-muted mb-0 mt-2">
        Показано {{ result.answers.length }} из {{ result.distinct_count }} разных ответов.
      </p>
    </template>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import api from '../api'

const props = defineProps({
  testId: { type: [String, Number], required: true },
  question: { type: Object, required: true },
})
const result = ref(null)
const loading = ref(false)
const error = ref(false)
const retry = ref(0)

watch([() => props.question, retry], async ([question], _, onCleanup) => {
  result.value = null
  error.value = false
  loading.value = false
  if (!question.incorrect_count) return

  const controller = new AbortController()
  onCleanup(() => controller.abort())
  loading.value = true
  try {
    const { data } = await api.getWrongAnswers(props.testId, question.question_id, controller.signal)
    if (!controller.signal.aborted) result.value = data
  } catch {
    if (!controller.signal.aborted) error.value = true
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>
