<template>
  <div class="row justify-content-center ge-fade-in">
    <div class="col-md-8">
      <div class="ge-page-header">
        <h4>📤 Загрузить тест</h4>
        <RouterLink to="/admin/tests" class="btn btn-outline-secondary btn-sm">← Назад</RouterLink>
      </div>
      <div class="card">
        <div class="card-body">
          <div class="mb-3">
            <label class="form-label fw-semibold">JSON-файл теста</label>
            <input type="file" class="form-control" accept=".json" @change="onFile" />
          </div>
          <div v-if="preview" class="mb-3">
            <div class="alert alert-info d-flex align-items-center gap-2">
              <span style="font-size:1.3rem">📄</span>
              <span><strong>{{ preview.title }}</strong> — {{ preview.variants?.length }} вариант(ов)</span>
            </div>
            <textarea class="form-control font-monospace small" rows="8" readonly :value="rawJson" />
          </div>
          <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary" :disabled="!preview || loading" @click="upload">
              <span v-if="loading" class="spinner-border spinner-border-sm me-1" />
              Загрузить
            </button>
          </div>
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
const preview = ref(null)
const rawJson = ref('')
const error = ref('')
const loading = ref(false)

function onFile(e) {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => {
    try {
      rawJson.value = ev.target.result
      preview.value = JSON.parse(ev.target.result)
      error.value = ''
    } catch {
      error.value = 'Невалидный JSON'
      preview.value = null
    }
  }
  reader.readAsText(file)
}

async function upload() {
  error.value = ''
  loading.value = true
  try {
    const { data } = await api.createTest(preview.value)
    router.push(`/admin/tests/${data.id}`)
  } catch (e) {
    error.value = e.response?.data?.error || 'Ошибка загрузки'
  } finally {
    loading.value = false
  }
}
</script>
