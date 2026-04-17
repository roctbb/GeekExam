<template>
  <div class="ge-fade-in">
    <div class="ge-page-header">
      <h4>Результаты</h4>
      <RouterLink :to="`/admin/tests/${$route.params.id}`" class="btn btn-outline-secondary btn-sm">← Назад</RouterLink>
    </div>
    <div v-if="loading" class="text-center py-4"><div class="spinner-border" /></div>
    <div v-else-if="attempts.length === 0" class="text-center py-5 text-muted">Пока никто не проходил этот тест</div>
    <div v-else>
      <div class="d-flex justify-content-end mb-2 gap-2">
        <select v-model="sortBy" class="form-select form-select-sm" style="width:auto">
          <option value="started_at">Сортировка: по времени</option>
          <option value="user_name">Сортировка: по имени</option>
        </select>
        <button class="btn btn-sm btn-outline-secondary" @click="toggleSortDir">
          {{ sortDir === 'asc' ? '↑ По возрастанию' : '↓ По убыванию' }}
        </button>
      </div>
      <div class="table-responsive">
      <table class="table table-hover align-middle">
        <thead><tr><th>Ученик</th><th>Вариант</th><th>Начало</th><th>Конец</th><th>Результат</th><th></th></tr></thead>
        <tbody>
          <tr v-for="a in sortedAttempts" :key="a.id">
            <td class="fw-semibold">{{ a.user_name }}</td>
            <td>{{ a.variant_title }}</td>
            <td class="text-muted small">{{ fmt(a.started_at) }}</td>
            <td class="text-muted small">{{ fmt(a.finished_at) || '—' }}</td>
            <td>
              <span v-if="!a.finished_at" class="badge bg-warning text-dark">В процессе</span>
              <span v-else-if="!a.is_checked" class="badge bg-info text-dark">Проверяется</span>
              <span v-else class="ge-score" style="font-size:.8rem;padding:.25rem .7rem">{{ a.total_points }}/{{ a.max_points }}</span>
            </td>
            <td class="text-end">
              <RouterLink :to="`/admin/attempts/${a.id}`" class="btn btn-sm btn-outline-primary me-1">Детали</RouterLink>
              <button class="btn btn-sm btn-outline-danger" @click="del(a.id)">Удалить</button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '../../api'
const route = useRoute()
const attempts = ref([]), loading = ref(true)
const sortBy = ref('started_at')
const sortDir = ref('desc')
const fmt = (d) => d ? new Date(d).toLocaleString('ru') : ''
async function del(id) { if (!confirm('Удалить прохождение?')) return; await api.deleteAttempt(id); attempts.value = attempts.value.filter(a => a.id !== id) }

function toggleSortDir() {
  sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
}

const sortedAttempts = computed(() => {
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...attempts.value].sort((a, b) => {
    if (sortBy.value === 'user_name') {
      return dir * (a.user_name || '').localeCompare(b.user_name || '', 'ru')
    }
    const aTs = a.started_at ? new Date(a.started_at).getTime() : 0
    const bTs = b.started_at ? new Date(b.started_at).getTime() : 0
    return dir * (aTs - bTs)
  })
})

onMounted(async () => { const { data } = await api.getTestAttempts(route.params.id); attempts.value = data; loading.value = false })
</script>
