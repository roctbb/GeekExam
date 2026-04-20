<template>
  <div class="ge-fade-in">
    <div class="ge-page-header">
      <h4>Тесты</h4>
      <RouterLink to="/admin/tests/upload" class="btn btn-primary btn-sm">+ Загрузить</RouterLink>
    </div>
    <div class="table-responsive">
      <table class="table table-hover align-middle">
        <thead><tr><th>Название</th><th>Код</th><th>Статус</th><th>Вариантов</th><th></th></tr></thead>
        <tbody>
          <tr v-for="t in tests" :key="t.id">
            <td class="fw-semibold">{{ t.title }}</td>
            <td><code v-if="t.code" class="fs-6">{{ t.code }}</code><span v-else class="text-muted">—</span></td>
            <td><span :class="t.is_active ? 'badge bg-success' : 'badge bg-secondary'">{{ t.is_active ? 'Активен' : 'Стоп' }}</span></td>
            <td>{{ t.variant_count ?? '—' }}</td>
            <td class="text-end">
              <RouterLink :to="`/admin/tests/${t.id}`" class="btn btn-sm btn-outline-secondary me-1">Открыть</RouterLink>
              <RouterLink :to="`/admin/tests/${t.id}/edit`" class="btn btn-sm btn-outline-secondary me-1">Редактировать</RouterLink>
              <RouterLink :to="`/admin/tests/${t.id}/results`" class="btn btn-sm btn-outline-primary me-1">Результаты</RouterLink>
              <button
                class="btn btn-sm btn-outline-danger"
                :disabled="deletingId === t.id"
                @click="removeTest(t)"
              >
                <span v-if="deletingId === t.id" class="spinner-border spinner-border-sm me-1" />
                Удалить
              </button>
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

onMounted(async () => { const { data } = await api.getTests(); tests.value = data })

async function removeTest(test) {
  const ok = confirm(`Удалить тест «${test.title}»? Это действие нельзя отменить.`)
  if (!ok) return

  deletingId.value = test.id
  try {
    await api.deleteTest(test.id)
    tests.value = tests.value.filter((t) => t.id !== test.id)
  } catch (e) {
    const msg = e?.response?.data?.error || 'Не удалось удалить тест'
    alert(msg)
  } finally {
    deletingId.value = null
  }
}
</script>
