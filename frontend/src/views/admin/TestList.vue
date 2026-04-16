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
              <RouterLink :to="`/admin/tests/${t.id}/results`" class="btn btn-sm btn-outline-primary">Результаты</RouterLink>
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
onMounted(async () => { const { data } = await api.getTests(); tests.value = data })
</script>
