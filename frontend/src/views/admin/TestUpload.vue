<template>
  <div class="row justify-content-center ge-fade-in">
    <div class="col-md-8">
      <div class="ge-page-header">
        <h4>Загрузить тест</h4>
        <RouterLink to="/admin/tests" class="btn btn-outline-secondary btn-sm">← Назад</RouterLink>
      </div>
      <div class="card">
        <div class="card-body">
          <label class="form-label fw-semibold">JSON-файл теста</label>
          <input type="file" class="form-control mb-3" accept=".json" @change="onFile" />
          <div v-if="preview" class="mb-3">
            <div class="ge-check success mb-2">📄 <strong>{{ preview.title }}</strong> — {{ preview.variants?.length }} вариант(ов)</div>
            <textarea class="form-control font-monospace small" rows="8" readonly :value="rawJson" />
          </div>
          <div v-if="error" class="alert alert-danger py-2 small">{{ error }}</div>
          <button class="btn btn-primary" :disabled="!preview || loading" @click="upload">
            <span v-if="loading" class="spinner-border spinner-border-sm me-1" />Загрузить
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../../api'
const router = useRouter()
const preview = ref(null), rawJson = ref(''), error = ref(''), loading = ref(false)
function onFile(e) {
  const file = e.target.files[0]; if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => { try { rawJson.value = ev.target.result; preview.value = JSON.parse(ev.target.result); error.value = '' } catch { error.value = 'Невалидный JSON'; preview.value = null } }
  reader.readAsText(file)
}
async function upload() {
  error.value = ''; loading.value = true
  try { const { data } = await api.createTest(preview.value); router.push(`/admin/tests/${data.id}`) }
  catch (e) { error.value = e.response?.data?.error || 'Ошибка' }
  finally { loading.value = false }
}
</script>
