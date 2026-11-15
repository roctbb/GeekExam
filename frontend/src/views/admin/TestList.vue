<template>
  <div class="ge-fade-in">
    <div class="ge-page-header">
      <h4>Тесты</h4>
      <RouterLink :to="uploadLink" class="btn btn-primary btn-sm"><AppIcon name="upload" />Загрузить</RouterLink>
    </div>
    <div v-if="loadError" class="alert alert-danger" role="alert">
      {{ loadError }} <button class="btn btn-sm btn-outline-danger" :disabled="loading" @click="loadTests">Повторить</button>
    </div>
    <div v-if="loading" class="text-center py-4"><div class="spinner-border" /></div>
    <template v-else-if="!loadError">
      <section class="card mb-4" aria-labelledby="test-groups-heading">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
            <h5 id="test-groups-heading" class="mb-0">Группы тестов</h5>
            <button class="btn btn-outline-primary btn-sm" :disabled="busy" @click="editGroup()"><AppIcon name="plus" />Создать группу</button>
          </div>
          <p class="text-muted small mb-3">Объединяйте тесты по классам или темам. Группу теста можно выбрать под его названием.</p>
          <nav class="d-flex flex-wrap gap-2" aria-label="Группы тестов">
            <button class="ge-group-button" :class="{ active: selectedGroup === 'all' }" :aria-pressed="selectedGroup === 'all'" @click="selectGroup('all')">
              Все тесты <span class="ge-group-count">{{ tests.length }}</span>
            </button>
            <button class="ge-group-button" :class="{ active: selectedGroup === 'none' }" :aria-pressed="selectedGroup === 'none'" @click="selectGroup('none')">
              Без группы <span class="ge-group-count">{{ ungroupedCount }}</span>
            </button>
            <button v-for="group in groups" :key="group.id" class="ge-group-button" :class="{ active: selectedGroup === group.id }"
              :aria-pressed="selectedGroup === group.id" @click="selectGroup(group.id)">
              <AppIcon name="open" /> {{ group.name }} <span class="ge-group-count">{{ groupCounts.get(group.id) || 0 }}</span>
            </button>
          </nav>
          <form v-if="groupEditor" class="mt-3" @submit.prevent="saveGroup">
            <fieldset :disabled="busy">
              <label for="group-name" class="form-label">{{ groupEditor.id ? 'Новое название группы' : 'Название группы' }}</label>
              <div class="d-flex flex-wrap gap-2">
                <input id="group-name" ref="groupNameInput" v-model="groupEditor.name" class="form-control ge-group-name" maxlength="120" required placeholder="Например, 7 класс" />
                <button class="btn btn-primary btn-sm" :disabled="!groupEditor.name.trim()">
                  <span v-if="groupSaving" class="spinner-border spinner-border-sm me-1" />{{ groupEditor.id ? 'Сохранить' : 'Создать' }}
                </button>
                <button type="button" class="btn btn-outline-secondary btn-sm" @click="groupEditor = null">Отмена</button>
              </div>
            </fieldset>
          </form>
        </div>
      </section>
      <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>
      <div v-if="success" class="alert alert-success py-2" role="status">{{ success }}</div>
      <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
        <h5 class="mb-0 ge-group-heading">{{ selectedTitle }} <span class="text-muted small">({{ visibleTests.length }})</span></h5>
        <div v-if="activeGroup" class="d-flex flex-wrap gap-2">
          <button class="btn btn-outline-secondary btn-sm" :disabled="busy" @click="editGroup(activeGroup)"><AppIcon name="edit" />Переименовать группу</button>
          <button class="btn btn-outline-danger btn-sm" :disabled="busy" @click="removeGroup"><AppIcon name="delete" />Удалить группу</button>
        </div>
      </div>
      <div v-if="!visibleTests.length" class="card">
        <div class="card-body text-center py-4">
          <p class="text-muted mb-2">{{ tests.length ? 'В этой группе пока нет тестов.' : 'Тестов пока нет. Загрузите первый тест.' }}</p>
          <p v-if="activeGroup" class="text-muted small">Загрузите тест в эту группу или выберите группу у существующего теста.</p>
          <div class="d-flex justify-content-center flex-wrap gap-2">
            <RouterLink :to="uploadLink" class="btn btn-primary btn-sm"><AppIcon name="upload" />Загрузить тест</RouterLink>
            <button v-if="selectedGroup !== 'all' && tests.length" class="btn btn-outline-secondary btn-sm" @click="selectGroup('all')">Выбрать из всех тестов</button>
          </div>
        </div>
      </div>
      <div v-else class="table-responsive">
        <table class="table table-hover align-middle ge-tests-table">
          <thead><tr><th>Название / группа</th><th>Код</th><th>Статус</th><th class="text-center">Вариантов</th><th class="text-center">Попыток</th><th aria-label="Действия"></th></tr></thead>
          <tbody>
            <tr v-for="t in visibleTests" :key="t.id">
              <td>
                <div class="fw-semibold ge-test-title">{{ t.title }}</div>
                <label :for="`test-group-${t.id}`" class="visually-hidden">Группа теста «{{ t.title }}»</label>
                <select :id="`test-group-${t.id}`" class="form-select form-select-sm ge-test-group-select mt-2" :value="t.group_id ?? ''" :disabled="busy" @change="moveTest(t, $event)">
                  <option value="">Без группы</option>
                  <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</option>
                </select>
              </td>
              <td><code v-if="t.code" class="ge-access-code">{{ t.code }}</code><span v-else class="text-muted">—</span></td>
              <td><span :class="t.is_active ? 'badge bg-success' : 'badge bg-secondary'">{{ t.is_active ? 'Активен' : 'Стоп' }}</span></td>
              <td class="text-center">{{ t.variant_count ?? '—' }}</td>
              <td class="text-center">{{ t.attempt_count ?? 0 }}</td>
              <td class="text-end">
                <div class="ge-test-actions">
                  <RouterLink :to="`/admin/tests/${t.id}`" class="btn btn-sm btn-outline-secondary"><AppIcon name="open" />Открыть</RouterLink>
                  <RouterLink :to="`/admin/tests/${t.id}/edit`" class="btn btn-sm btn-outline-secondary"><AppIcon name="edit" />Редактировать</RouterLink>
                  <RouterLink :to="`/admin/tests/${t.id}/results`" class="btn btn-sm btn-outline-primary"><AppIcon name="results" />Результаты</RouterLink>
                  <button class="btn btn-sm btn-outline-danger" :disabled="busy" @click="removeTest(t)">
                    <span v-if="deletingId === t.id" class="spinner-border spinner-border-sm me-1" /><AppIcon v-else name="delete" />Удалить
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../api'

const route = useRoute(), router = useRouter()
const tests = ref([]), groups = ref([])
const deletingId = ref(null), movingId = ref(null), groupSaving = ref(false)
const groupEditor = ref(null), groupNameInput = ref(null)
const loading = ref(true), loadError = ref(''), error = ref(''), success = ref('')
const busy = computed(() => groupSaving.value || movingId.value !== null || deletingId.value !== null)
const activeGroup = computed(() => groups.value.find(group => String(group.id) === route.query.group))
const selectedGroup = computed(() => route.query.group === 'none' ? 'none' : activeGroup.value?.id ?? 'all')
const selectedTitle = computed(() => activeGroup.value?.name || (selectedGroup.value === 'none' ? 'Без группы' : 'Все тесты'))
const visibleTests = computed(() => tests.value.filter(test => selectedGroup.value === 'all'
  || (selectedGroup.value === 'none' ? test.group_id == null : test.group_id === selectedGroup.value)))
const ungroupedCount = computed(() => tests.value.filter(test => test.group_id == null).length)
const groupCounts = computed(() => {
  const counts = new Map()
  for (const test of tests.value) counts.set(test.group_id, (counts.get(test.group_id) || 0) + 1)
  return counts
})
const uploadLink = computed(() => ({ path: '/admin/tests/upload', query: activeGroup.value ? { group: activeGroup.value.id } : {} }))

function selectGroup(value) {
  const query = { ...route.query }
  if (value === 'all') delete query.group
  else query.group = String(value)
  return router.replace({ query })
}

async function loadTests() {
  loading.value = true; loadError.value = ''
  try {
    const [testResponse, groupResponse] = await Promise.all([api.getTests(), api.getTestGroups()])
    tests.value = testResponse.data
    groups.value = sortGroups(groupResponse.data)
  } catch { loadError.value = 'Не удалось загрузить тесты и группы. Проверьте соединение и повторите.' }
  finally { loading.value = false }
}
onMounted(loadTests)

function sortGroups(items) {
  return items.sort((a, b) => a.name.localeCompare(b.name, 'ru', { numeric: true }))
}

async function editGroup(group = null) {
  error.value = ''; success.value = ''
  groupEditor.value = { id: group?.id ?? null, name: group?.name ?? '' }
  await nextTick()
  groupNameInput.value?.focus()
}

async function saveGroup() {
  if (busy.value || !groupEditor.value?.name.trim()) return
  const { id, name } = groupEditor.value
  groupSaving.value = true; error.value = ''; success.value = ''
  try {
    const { data } = await (id ? api.renameTestGroup(id, name.trim()) : api.createTestGroup(name.trim()))
    groups.value = sortGroups([...groups.value.filter(group => group.id !== data.id), data])
    groupEditor.value = null
    await selectGroup(data.id)
    success.value = id ? 'Название группы сохранено.' : `Группа «${data.name}» создана.`
  } catch (e) { error.value = e.response?.data?.error || 'Не удалось сохранить группу. Повторите попытку.' }
  finally { groupSaving.value = false }
}

async function removeGroup() {
  const group = activeGroup.value
  if (busy.value || !group || !confirm(`Удалить группу «${group.name}»? Все её тесты сохранятся в разделе «Без группы».`)) return
  groupSaving.value = true; error.value = ''; success.value = ''
  try {
    await api.deleteTestGroup(group.id)
    tests.value.forEach(test => { if (test.group_id === group.id) test.group_id = null })
    groups.value = groups.value.filter(item => item.id !== group.id)
    groupEditor.value = null
    await selectGroup('none')
    success.value = 'Группа удалена. Все тесты сохранены.'
  } catch (e) { error.value = e.response?.data?.error || 'Не удалось удалить группу. Повторите попытку.' }
  finally { groupSaving.value = false }
}

async function moveTest(test, event) {
  const groupId = event.target.value === '' ? null : Number(event.target.value)
  if (busy.value) { event.target.value = test.group_id ?? ''; return }
  movingId.value = test.id; error.value = ''; success.value = ''
  try {
    const { data } = await api.moveTestToGroup(test.id, groupId)
    test.group_id = data.group_id
    const destination = groupId === null ? 'раздел «Без группы»' : `группу «${groups.value.find(group => group.id === groupId)?.name}»`
    success.value = `Тест «${test.title}» перемещён в ${destination}.`
  } catch (e) { error.value = e.response?.data?.error || 'Не удалось переместить тест. Повторите попытку.' }
  finally { event.target.value = test.group_id ?? ''; movingId.value = null }
}

async function removeTest(test) {
  if (busy.value) return
  const attemptsText = test.attempt_count ? ` Будут удалены все попытки: ${test.attempt_count}.` : ''
  if (!confirm(`Удалить тест «${test.title}»?${attemptsText} Это действие нельзя отменить.`)) return
  deletingId.value = test.id; error.value = ''; success.value = ''
  try {
    await api.deleteTest(test.id)
    tests.value = tests.value.filter(t => t.id !== test.id)
  } catch (e) { error.value = e.response?.data?.error || 'Не удалось удалить тест' }
  finally { deletingId.value = null }
}
</script>

<style scoped>
.ge-group-button { display: inline-flex; align-items: center; gap: .5rem; max-width: 100%; min-height: var(--ge-field-height); padding: .5rem .75rem; border: 1px solid var(--ge-control-border); border-radius: var(--ge-radius-control); background: var(--ge-surface); color: var(--ge-text); font-size: var(--ge-font-ui); text-align: left; overflow-wrap: anywhere; }
.ge-group-button:hover { border-color: var(--ge-primary); }
.ge-group-button.active { border-color: var(--ge-primary); background: var(--ge-primary-soft); color: var(--ge-primary); }
.ge-group-button:focus-visible { outline: 2px solid var(--ge-primary); outline-offset: 2px; }
.ge-group-count { font-size: var(--ge-font-meta); opacity: .8; flex-shrink: 0; }
.ge-group-name { flex: 1 1 15rem; max-width: 30rem; }
.ge-group-heading { overflow-wrap: anywhere; min-width: 0; max-width: 100%; }
.ge-test-title { overflow-wrap: anywhere; }
.ge-test-group-select { max-width: 16rem; font-weight: 400; }
</style>
