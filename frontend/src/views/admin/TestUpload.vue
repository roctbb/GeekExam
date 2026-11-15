<template>
  <div class="row justify-content-center ge-fade-in">
    <div class="col-md-8">
      <div class="ge-page-header">
        <h4>Загрузить тест</h4>
        <RouterLink :to="{ path: '/admin/tests', query: groupId ? { group: groupId } : {} }" class="btn btn-outline-secondary btn-sm"><AppIcon name="arrow-left" />Назад</RouterLink>
      </div>
      <div class="card">
        <div class="card-body">
          <label for="upload-group" class="form-label fw-semibold">Группа теста</label>
          <select id="upload-group" v-model="groupId" class="form-select mb-3" :disabled="groupsLoading || loading || !groupsReady">
            <option :value="null">Без группы</option>
            <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</option>
          </select>
          <div v-if="groupsError" class="alert alert-danger py-2 small" role="alert">
            {{ groupsError }} <button class="btn btn-outline-danger btn-sm" :disabled="groupsLoading" @click="loadGroups">Повторить</button>
          </div>
          <label class="form-label fw-semibold">JSON-файл теста</label>
          <input type="file" class="form-control mb-3" accept=".json" @change="onFile" />
          <div v-if="preview" class="mb-3">
            <div class="ge-check success mb-2"><AppIcon name="tests" /> <strong>{{ preview.title }}</strong> — {{ preview.variants?.length }} вариант(ов)</div>
            <textarea class="form-control font-monospace small" rows="8" readonly :value="rawJson" />
          </div>
          <div v-if="error" class="alert alert-danger py-2 small">{{ error }}</div>
          <button class="btn btn-primary" :disabled="!preview || loading || !groupsReady" @click="upload">
            <span v-if="loading" class="spinner-border spinner-border-sm me-1" /><AppIcon v-else name="upload" />Загрузить
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../api'
const router = useRouter(), route = useRoute()
const preview = ref(null), rawJson = ref(''), error = ref(''), loading = ref(false)
const groups = ref([]), groupId = ref(null), groupsLoading = ref(true), groupsReady = ref(false), groupsError = ref('')
async function loadGroups() {
  groupsLoading.value = true; groupsError.value = ''; groupsReady.value = false
  try {
    const { data } = await api.getTestGroups()
    groups.value = data.sort((a, b) => a.name.localeCompare(b.name, 'ru', { numeric: true }))
    groupId.value = data.find(group => String(group.id) === route.query.group)?.id ?? null
    groupsReady.value = true
    if (route.query.group && groupId.value === null) groupsError.value = 'Эта группа больше не существует. Выберите другую группу или «Без группы».'
  } catch { groupsError.value = 'Не удалось загрузить группы. Повторите попытку.' }
  finally { groupsLoading.value = false }
}
onMounted(loadGroups)
function onFile(e) {
  const file = e.target.files[0]; if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => { try { rawJson.value = ev.target.result; preview.value = JSON.parse(ev.target.result); error.value = '' } catch { error.value = 'Невалидный JSON'; preview.value = null } }
  reader.readAsText(file)
}
async function upload() {
  if (loading.value || !preview.value || !groupsReady.value) return
  error.value = ''; loading.value = true
  try { const { data } = await api.createTest({ ...preview.value, group_id: groupId.value }); router.push(`/admin/tests/${data.id}`) }
  catch (e) { error.value = e.response?.data?.error || 'Ошибка' }
  finally { loading.value = false }
}
</script>
