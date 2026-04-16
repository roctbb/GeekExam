<template>
  <div class="ge-fade-in">
    <div class="ge-page-header">
      <h4>📊 Мои результаты</h4>
    </div>
    <div v-if="loading" class="text-center py-4"><div class="spinner-border" /></div>
    <div v-else-if="attempts.length === 0" class="text-center py-5">
      <div style="font-size:3rem;margin-bottom:.5rem">📝</div>
      <p class="text-muted">Вы ещё не проходили тестов</p>
      <RouterLink to="/join" class="btn btn-primary">Войти в тест</RouterLink>
    </div>
    <div v-else class="table-responsive">
      <table class="table table-hover align-middle">
        <thead>
          <tr><th>Тест</th><th>Вариант</th><th>Дата</th><th>Результат</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="a in attempts" :key="a.id">
            <td class="fw-semibold">{{ a.test_title }}</td>
            <td>{{ a.variant_title }}</td>
            <td class="text-muted small">{{ formatDate(a.started_at) }}</td>
            <td>
              <span v-if="!a.finished_at" class="badge bg-warning text-dark">⏳ В процессе</span>
              <span v-else-if="!a.is_checked" class="badge bg-info text-dark">🔄 Проверяется</span>
              <span v-else class="ge-score" style="font-size:.85rem;padding:.3rem .8rem">{{ a.total_points }} / {{ a.max_points }}</span>
            </td>
            <td class="text-end">
              <RouterLink v-if="a.finished_at" :to="`/my-results/${a.id}`" class="btn btn-sm btn-outline-primary">Подробнее</RouterLink>
              <RouterLink v-else :to="`/attempt/${a.id}`" class="btn btn-sm btn-outline-warning">Продолжить</RouterLink>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'

const attempts = ref([])
const loading = ref(true)

function formatDate(d) { return d ? new Date(d).toLocaleString('ru') : '' }

onMounted(async () => {
  const { data } = await api.myAttempts()
  attempts.value = data
  loading.value = false
})
</script>
