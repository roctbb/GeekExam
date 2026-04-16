<template>
  <div class="ge-fade-in">
    <div class="ge-page-header">
      <h4>📊 Результаты теста</h4>
      <RouterLink :to="`/admin/tests/${$route.params.id}`" class="btn btn-outline-secondary btn-sm">← Назад</RouterLink>
    </div>
    <div v-if="loading" class="text-center py-4"><div class="spinner-border" /></div>
    <div v-else-if="attempts.length === 0" class="text-center py-5">
      <div style="font-size:3rem;margin-bottom:.5rem">📭</div>
      <p class="text-muted">Пока никто не проходил этот тест</p>
    </div>
    <div v-else class="table-responsive">
      <table class="table table-hover align-middle">
        <thead>
          <tr><th>Ученик</th><th>Вариант</th><th>Начало</th><th>Завершение</th><th>Результат</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="a in attempts" :key="a.id">
            <td class="fw-semibold">{{ a.user_name }}</td>
            <td>{{ a.variant_title }}</td>
            <td class="text-muted small">{{ fmt(a.started_at) }}</td>
            <td class="text-muted small">{{ fmt(a.finished_at) || '—' }}</td>
            <td>
              <span v-if="!a.finished_at" class="badge bg-warning text-dark">⏳ В процессе</span>
              <span v-else-if="!a.is_checked" class="badge bg-info text-dark">🔄 Проверяется</span>
              <span v-else class="ge-score" style="font-size:.85rem;padding:.3rem .8rem">{{ a.total_points }} / {{ a.max_points }}</span>
            </td>
            <td class="text-end">
              <RouterLink :to="`/admin/attempts/${a.id}`" class="btn btn-sm btn-outline-primary me-1">Детали</RouterLink>
              <button class="btn btn-sm btn-outline-danger" @click="deleteAttempt(a.id)">Удалить</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '../../api'

const route = useRoute()
const attempts = ref([])
const loading = ref(true)
const fmt = (d) => d ? new Date(d).toLocaleString('ru') : ''

async function deleteAttempt(id) {
  if (!confirm('Удалить прохождение? Ученик сможет пройти тест заново.')) return
  await api.deleteAttempt(id)
  attempts.value = attempts.value.filter(a => a.id !== id)
}

onMounted(async () => {
  const { data } = await api.getTestAttempts(route.params.id)
  attempts.value = data
  loading.value = false
})
</script>
