<template>
  <div v-if="test" class="ge-fade-in">
    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>
    <div v-if="success" class="alert alert-success" role="status">{{ success }}</div>
    <div class="ge-page-header">
      <h4>{{ test.title }}</h4>
      <div class="d-flex gap-2 flex-wrap">
        <button v-if="!test.is_active" class="btn btn-success btn-sm" :disabled="!!pending || !test.code" @click="activate"><AppIcon name="play" />Запустить</button>
        <button v-else class="btn btn-warning btn-sm" :disabled="!!pending" @click="deactivate"><AppIcon name="stop" />Остановить</button>
        <RouterLink :to="`/admin/tests/${test.id}/preview`" class="btn btn-outline-primary btn-sm"><AppIcon name="preview" />Просмотр как ученик</RouterLink>
        <RouterLink :to="`/admin/tests/${test.id}/edit`" class="btn btn-outline-secondary btn-sm"><AppIcon name="edit" />Редактировать</RouterLink>
        <RouterLink :to="`/admin/tests/${test.id}/results`" class="btn btn-outline-primary btn-sm"><AppIcon name="results" />Результаты</RouterLink>
        <button class="btn btn-outline-danger btn-sm" :disabled="!!pending" @click="removeTest"><AppIcon name="delete" />Удалить</button>
      </div>
    </div>
    <div class="card mb-4">
      <div class="card-header">Код доступа</div>
      <div class="card-body d-flex align-items-center gap-3 flex-wrap">
        <code v-if="test.code" class="ge-access-code ge-access-code-lg">{{ test.code }}</code>
        <span v-else class="text-muted">не задан</span>
        <div class="d-flex gap-2 flex-wrap">
          <input v-model="newCode" :disabled="!!pending" aria-label="Новый код доступа" type="text" class="form-control form-control-sm text-uppercase" style="width:140px" placeholder="Новый код" />
          <button class="btn btn-sm btn-primary" :disabled="!!pending || !newCode.trim()" @click="saveCode"><AppIcon name="save" />Сохранить</button>
        </div>
      </div>
    </div>
    <div class="card mb-4">
      <div class="card-body d-flex align-items-center gap-3 flex-wrap">
        <span>Лимит на одну попытку: <strong>{{ test.time_limit == null ? 'без ограничения' : `${test.time_limit} мин` }}</strong></span>
        <button v-if="test.time_limit != null" class="btn btn-outline-primary btn-sm" :disabled="!!pending" @click="extendTime">+15 минут</button>
      </div>
    </div>
    <div v-for="v in test.variants" :key="v.id" class="mb-4">
      <h6 class="fw-bold mb-2">{{ v.title }}</h6>
      <div class="table-responsive">
        <table class="table table-sm table-bordered align-middle">
          <thead><tr><th style="width:50px">#</th><th>Вопрос</th><th>Тип</th><th>Проверка</th><th style="width:70px">Баллы</th></tr></thead>
          <tbody>
            <tr v-for="q in v.questions" :key="q.id">
              <td class="text-center">{{ q.order + 1 }}</td>
              <td>
                <div class="fw-semibold">{{ q.title }}</div>
                <MarkdownBody v-if="q.body" class="mt-1" :source="q.body" compact />
                <span v-else class="small text-muted">—</span>
              </td>
              <td><code>{{ q.type }}</code></td><td><code>{{ q.check_type }}</code></td>
              <td class="text-center fw-bold">{{ q.max_points }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <div v-else-if="error" class="alert alert-danger" role="alert">{{ error }} <button class="btn btn-sm btn-outline-danger" @click="loadTest">Повторить</button></div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../api'
import MarkdownBody from '../../components/MarkdownBody.vue'
const route = useRoute()
const router = useRouter()
const test = ref(null), newCode = ref('')
const pending = ref(''), error = ref(''), success = ref('')
async function loadTest() {
  error.value = ''
  try {
    const { data } = await api.getTest(route.params.id)
    test.value = data
    newCode.value = data.code || ''
  } catch { error.value = 'Не удалось загрузить тест. Проверьте соединение и повторите.' }
}
onMounted(loadTest)
async function runAction(name, action, message) {
  if (pending.value) return
  pending.value = name
  error.value = ''; success.value = ''
  try { await action(); success.value = message }
  catch (e) { error.value = e?.response?.data?.error || 'Не удалось выполнить действие. Проверьте соединение и повторите.' }
  finally { pending.value = '' }
}
function activate() {
  return runAction('activate', async () => { await api.activateTest(test.value.id); test.value.is_active = true }, 'Тест запущен')
}
function deactivate() {
  if (!confirm('Остановить тест и завершить все текущие попытки? Сохранённые ответы будут отправлены на проверку.')) return
  return runAction('deactivate', async () => { await api.deactivateTest(test.value.id); test.value.is_active = false }, 'Тест остановлен, текущие попытки завершены')
}
function extendTime() {
  return runAction('extend-time', async () => {
    const { data } = await api.extendTestTime(test.value.id, test.value.time_limit)
    test.value.time_limit = data.time_limit
  }, 'Добавлено 15 минут к лимиту каждой незавершённой попытки')
}
function saveCode() {
  return runAction('code', async () => {
    const { data } = await api.setTestCode(test.value.id, newCode.value)
    test.value.code = newCode.value = data.code
  }, 'Код доступа сохранён')
}
function removeTest() {
  if (pending.value) return
  const attemptsText = test.value.attempt_count ? ` Будут удалены все попытки: ${test.value.attempt_count}.` : ''
  if (!confirm(`Удалить тест «${test.value.title}»?${attemptsText} Это действие нельзя отменить.`)) return
  return runAction('delete', async () => { await api.deleteTest(test.value.id); await router.push('/admin/tests') }, '')
}
</script>
