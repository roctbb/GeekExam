<template>
  <div v-if="test" class="ge-fade-in">
    <div class="ge-page-header">
      <h4>{{ test.title }}</h4>
      <div class="d-flex gap-2">
        <button v-if="!test.is_active" class="btn btn-success btn-sm" :disabled="!test.code" @click="activate">Запустить</button>
        <button v-else class="btn btn-warning btn-sm" @click="deactivate">Остановить</button>
        <RouterLink :to="`/admin/tests/${test.id}/edit`" class="btn btn-outline-secondary btn-sm">Редактировать</RouterLink>
        <RouterLink :to="`/admin/tests/${test.id}/results`" class="btn btn-outline-primary btn-sm">Результаты</RouterLink>
      </div>
    </div>
    <div class="card mb-4">
      <div class="card-header">Код доступа</div>
      <div class="card-body d-flex align-items-center gap-3">
        <code v-if="test.code" class="fs-4 fw-bold">{{ test.code }}</code>
        <span v-else class="text-muted">не задан</span>
        <div class="d-flex gap-2 ms-auto">
          <input v-model="newCode" type="text" class="form-control form-control-sm text-uppercase" style="width:140px" placeholder="Новый код" />
          <button class="btn btn-sm btn-primary" @click="saveCode">Сохранить</button>
        </div>
      </div>
    </div>
    <div v-for="v in test.variants" :key="v.id" class="mb-4">
      <h6 class="fw-bold mb-2">{{ v.title }}</h6>
      <div class="table-responsive">
        <table class="table table-sm table-bordered align-middle">
          <thead><tr><th style="width:50px">#</th><th>Вопрос</th><th>Тип</th><th>Проверка</th><th style="width:70px">Баллы</th></tr></thead>
          <tbody>
            <tr v-for="q in v.questions" :key="q.id">
              <td class="text-center">{{ q.order + 1 }}</td><td>{{ q.title }}</td>
              <td><code>{{ q.type }}</code></td><td><code>{{ q.check_type }}</code></td>
              <td class="text-center fw-bold">{{ q.max_points }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '../../api'
const route = useRoute()
const test = ref(null), newCode = ref('')
onMounted(async () => { const { data } = await api.getTest(route.params.id); test.value = data; newCode.value = data.code || '' })
async function activate() { await api.activateTest(test.value.id); test.value.is_active = true }
async function deactivate() { await api.deactivateTest(test.value.id); test.value.is_active = false }
async function saveCode() { const { data } = await api.setTestCode(test.value.id, newCode.value); test.value.code = data.code }
</script>
