<template>
  <div class="ge-fade-in">
    <div class="ge-page-header">
      <h4>Тесты</h4>
      <RouterLink to="/admin/tests/upload" class="btn btn-primary btn-sm"><AppIcon name="upload" />Загрузить</RouterLink>
    </div>
    <div v-if="error" class="alert alert-danger" role="alert">{{ error }} <button class="btn btn-sm btn-outline-danger" :disabled="loading" @click="loadTests">Повторить</button></div>
    <div v-if="loading" class="text-center py-4"><div class="spinner-border" /></div>
    <p v-else-if="!error && !tests.length" class="text-muted">Тестов пока нет. Загрузите первый тест.</p>
    <div v-else-if="tests.length" class="table-responsive">
      <table class="table table-hover align-middle ge-tests-table">
        <thead><tr><th>Название</th><th>Код</th><th>Статус</th><th class="text-center">Вариантов</th><th class="text-center">Попыток</th><th aria-label="Действия"></th></tr></thead>
        <tbody>
          <tr v-for="t in tests" :key="t.id">
            <td class="fw-semibold">{{ t.title }}</td>
            <td><code v-if="t.code" class="ge-access-code">{{ t.code }}</code><span v-else class="text-muted">—</span></td>
            <td><span :class="t.is_active ? 'badge bg-success' : 'badge bg-secondary'">{{ t.is_active ? 'Активен' : 'Стоп' }}</span></td>
            <td class="text-center">{{ t.variant_count ?? '—' }}</td>
            <td class="text-center">{{ t.attempt_count ?? 0 }}</td>
            <td class="text-end">
              <div class="ge-test-actions">
              <RouterLink :to="`/admin/tests/${t.id}`" class="btn btn-sm btn-outline-secondary"><AppIcon name="open" />Открыть</RouterLink>
              <RouterLink :to="`/admin/tests/${t.id}/edit`" class="btn btn-sm btn-outline-secondary"><AppIcon name="edit" />Редактировать</RouterLink>
              <RouterLink :to="`/admin/tests/${t.id}/results`" class="btn btn-sm btn-outline-primary"><AppIcon name="results" />Результаты</RouterLink>
              <button
                class="btn btn-sm btn-outline-danger"
                :disabled="deletingId === t.id"
                @click="removeTest(t)"
              >
                <span v-if="deletingId === t.id" class="spinner-border spinner-border-sm me-1" />
                <AppIcon v-else name="delete" />
                Удалить
              </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../../api'
const tests = ref([])
const deletingId = ref(null)

const loading = ref(true), error = ref('')
async function loadTests() {
  loading.value = true; error.value = ''
  try { const { data } = await api.getTests(); tests.value = data }
  catch { error.value = 'Не удалось загрузить тесты. Проверьте соединение и повторите.' }
  finally { loading.value = false }
}
onMounted(loadTests)

async function removeTest(test) {
  if (deletingId.value !== null) return
  const attemptsText = test.attempt_count
    ? ` Будут удалены все попытки: ${test.attempt_count}.`
    : ''
  const ok = confirm(`Удалить тест «${test.title}»?${attemptsText} Это действие нельзя отменить.`)
  if (!ok) return

  deletingId.value = test.id
  try {
    await api.deleteTest(test.id)
    tests.value = tests.value.filter((t) => t.id !== test.id)
  } catch (e) {
    const msg = e?.response?.data?.error || 'Не удалось удалить тест'
    error.value = msg
  } finally {
    deletingId.value = null
  }
}
</script>
