<template>
  <div class="row justify-content-center ge-fade-in">
    <div class="col-xl-11">
      <div class="ge-page-header">
        <h4>Редактирование теста</h4>
        <RouterLink :to="`/admin/tests/${route.params.id}`" class="btn btn-outline-secondary btn-sm"><AppIcon name="arrow-left" />К тесту</RouterLink>
      </div>

      <div v-if="error" class="alert alert-danger py-2 small" role="alert">{{ error }} <button v-if="!ready" class="btn btn-sm btn-outline-danger" :disabled="loading" @click="loadTest">Повторить</button></div>
      <div v-if="success" class="alert alert-success py-2 small" role="status">{{ success }}</div>
      <div v-if="!ready && loading" class="text-center py-4"><div class="spinner-border" /></div>
      <div v-if="recovery" class="alert alert-warning" role="alert">
        Найден несохранённый черновик. Его восстановление заменит загруженные поля редактора; для отправки изменений нажмите «Сохранить».
        <div class="d-flex gap-2 flex-wrap mt-2">
          <button class="btn btn-primary btn-sm" @click="restoreDraft">Восстановить черновик</button>
          <button class="btn btn-outline-secondary btn-sm" @click="discardDraft">Оставить версию с сервера</button>
        </div>
      </div>
      <p v-if="ready && !recovery" class="small" role="status">{{ dirty ? 'Есть несохранённые изменения' : 'Все изменения сохранены' }}</p>
      <div v-if="draftWarning" class="alert alert-warning" role="alert">{{ draftWarning }}</div>
      <fieldset v-if="ready" :disabled="loading || !!recovery">
      <div v-if="hasAttempts" class="alert alert-warning py-2 small">
        У теста уже есть прохождения. Можно редактировать существующие вопросы и варианты, но нельзя добавлять или удалять их.
      </div>

      <div class="card mb-4">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span class="fw-semibold">Параметры теста</span>
          <button class="btn btn-primary btn-sm" :disabled="loading" @click="saveParams">
            <span v-if="loading && savingSection === 'params'" class="spinner-border spinner-border-sm me-1" />
            <AppIcon v-else name="save" />
            Сохранить параметры
          </button>
        </div>
        <div class="card-body">
          <div class="mb-3">
            <label class="form-label" for="test-title">Название</label>
            <input id="test-title" v-model.trim="draft.title" type="text" class="form-control" placeholder="Название теста" />
          </div>

          <div class="mb-3">
            <label class="form-label" for="test-description">Описание</label>
            <textarea id="test-description" v-model="draft.description" class="form-control" rows="4" placeholder="Описание (Markdown)"></textarea>
          </div>

          <div class="mb-0">
            <label class="form-label" for="test-time-limit">Лимит времени (мин), пусто = без лимита</label>
            <input
              id="test-time-limit" v-model="timeLimitInput"
              type="number"
              min="1"
              class="form-control"
              placeholder="Например, 45"
            />
            <div class="form-text">Общее время с начала каждой попытки. Например, изменение 55 → 70 добавляет 15 минут.</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span class="fw-semibold">Вопросы и варианты</span>
          <div class="d-flex gap-2 flex-wrap">
            <input ref="jsonInput" class="d-none" type="file" accept=".json,application/json" @change="onJsonFile" />
            <button class="btn btn-outline-primary btn-sm" :disabled="loading" @click="chooseJsonFile"><AppIcon name="upload" />Загрузить JSON</button>
            <button class="btn btn-outline-secondary btn-sm" :disabled="hasAttempts" @click="addVariant"><AppIcon name="plus" />Вариант</button>
            <button class="btn btn-primary btn-sm" :disabled="loading" @click="saveQuestions">
              <span v-if="loading && savingSection === 'questions'" class="spinner-border spinner-border-sm me-1" />
              <AppIcon v-else name="save" />
              Сохранить вопросы
            </button>
          </div>
        </div>

        <div class="card-body">
          <div v-if="!draft.variants.length" class="text-muted">Вариантов нет. Добавьте вариант.</div>

          <div v-for="(variant, variantIndex) in draft.variants" :key="variant.localId" class="border rounded p-3 mb-3">
            <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
              <div class="w-100 me-3">
                <label class="form-label mb-1">Название варианта</label>
                <input
                  v-model="variant.title"
                  type="text"
                  class="form-control form-control-sm"
                  :placeholder="`Вариант ${variantIndex + 1}`"
                />
              </div>
              <button class="btn btn-outline-danger btn-sm mt-4" :disabled="hasAttempts" @click="removeVariant(variantIndex)"><AppIcon name="delete" />Удалить вариант</button>
            </div>

            <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
              <h6 class="mb-0">Вопросы</h6>
              <button class="btn btn-outline-secondary btn-sm" :disabled="hasAttempts" @click="addQuestion(variantIndex)"><AppIcon name="plus" />Вопрос</button>
            </div>

            <div v-if="!variant.questions.length" class="text-muted small">В этом варианте пока нет вопросов.</div>

            <div
              v-for="(question, questionIndex) in variant.questions"
              :key="question.localId"
              class="card mb-3"
            >
              <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2 py-2">
                <strong>Вопрос {{ questionIndex + 1 }}</strong>
                <button class="btn btn-outline-danger btn-sm" :disabled="hasAttempts" @click="removeQuestion(variantIndex, questionIndex)"><AppIcon name="delete" />Удалить</button>
              </div>

              <div class="card-body">
                <div class="row g-3">
                  <div class="col-md-4">
                    <label class="form-label" :for="`question-type-${question.localId}`">Тип вопроса</label>
                    <select :id="`question-type-${question.localId}`" v-model="question.type" class="form-select">
                      <option v-for="type in questionTypeOptions" :key="type" :value="type">{{ questionTypeLabels[type] }}</option>
                    </select>
                  </div>

                  <div class="col-md-4">
                    <label class="form-label" :for="`question-check_type-${question.localId}`">Тип проверки</label>
                    <select :id="`question-check_type-${question.localId}`" v-model="question.check_type" class="form-select">
                      <option v-for="type in checkTypeOptions" :key="type" :value="type">{{ checkTypeLabels[type] }}</option>
                    </select>
                  </div>

                  <div class="col-md-2">
                    <label class="form-label" :for="`question-max_points-${question.localId}`">Макс. баллы</label>
                    <input :id="`question-max_points-${question.localId}`" v-model="question.max_points" type="number" min="0" class="form-control" />
                  </div>

                  <div class="col-md-2 d-flex align-items-end">
                    <div class="form-check mb-2">
                      <input v-model="question.allow_intermediate_check" class="form-check-input" type="checkbox" :id="`intermediate-${question.localId}`" />
                      <label class="form-check-label" :for="`intermediate-${question.localId}`">Пром. проверка</label>
                    </div>
                  </div>

                  <div class="col-12">
                    <label class="form-label" :for="`question-title-${question.localId}`">Заголовок вопроса</label>
                    <input :id="`question-title-${question.localId}`" v-model="question.title" type="text" class="form-control" placeholder="Например, Задача 1" />
                  </div>

                  <div class="col-12">
                    <label class="form-label" :for="`question-body-${question.localId}`">Текст задания (Markdown)</label>
                    <textarea :id="`question-body-${question.localId}`" v-model="question.body" class="form-control" rows="4"></textarea>
                  </div>

                  <div class="col-12">
                    <QuestionConfigEditor :type="question.type" :check-type="question.check_type"
                      v-model:check-config="question.check_config_text" v-model:ui-config="question.ui_config_text" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      </fieldset>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import api from '../../api'
import QuestionConfigEditor from '../../components/QuestionConfigEditor.vue'
import { useAuthStore } from '../../stores/auth'
import { createDraftStorage } from '../../utils/drafts'

const route = useRoute()

const loading = ref(true)
const ready = ref(false)
const recovery = ref(null)
const draftWarning = ref('')
const baseline = reactive({ params: '', questions: '' })
const draftStorage = createDraftStorage(`geekexam:test-editor:${useAuthStore().user.id}:${route.params.id}`)
let disposed = false
const savingSection = ref('')
const error = ref('')
const success = ref('')
const timeLimitInput = ref('')
let savedTimeLimit = null
const hasAttempts = ref(false)
const jsonInput = ref(null)
const uid = ref(1)

const questionTypeOptions = ['text_input', 'code_input', 'true_false_table', 'interactive', 'multi_input', 'choice_table', 'matrix_input']
const checkTypeOptions = ['exact', 'checker', 'docker', 'ai', 'manual']
const questionTypeLabels = { text_input: 'Текстовый ответ', code_input: 'Программный код', true_false_table: 'Верно / неверно', interactive: 'Интерактивное задание', multi_input: 'Несколько полей', choice_table: 'Таблица с выбором', matrix_input: 'Матрица' }
const checkTypeLabels = { exact: 'Сравнение с эталоном', checker: 'Функция проверки', docker: 'Запуск тестов', ai: 'Оценка нейросетью', manual: 'Ручная оценка' }

const draft = reactive({
  title: '',
  description: '',
  variants: [],
})

function captureDraft() {
  return {
    title: draft.title, description: draft.description, timeLimitInput: timeLimitInput.value,
    variants: draft.variants.map(({ localId, questions, ...variant }) => ({
      ...variant, questions: questions.map(({ localId, ...question }) => ({ ...question })),
    })),
  }
}
function paramsSnapshot(value) {
  return JSON.stringify({ title: value.title, description: value.description, timeLimitInput: value.timeLimitInput })
}
const currentParams = computed(() => paramsSnapshot(captureDraft()))
const currentQuestions = computed(() => JSON.stringify(captureDraft().variants))
const dirty = computed(() => ready.value && (currentParams.value !== baseline.params || currentQuestions.value !== baseline.questions))
function rememberDraft() {
  if (!ready.value || recovery.value) return
  const ok = dirty.value ? draftStorage.write(captureDraft()) : draftStorage.clear()
  draftWarning.value = ok ? '' : 'Резервный черновик недоступен. Сохраните изменения перед закрытием страницы.'
}
watch([currentParams, currentQuestions, () => baseline.params, () => baseline.questions], rememberDraft, { flush: 'sync' })
function markSaved(snapshot, section = 'questions') {
  baseline.params = paramsSnapshot(snapshot)
  if (section === 'questions') baseline.questions = JSON.stringify(snapshot.variants)
  rememberDraft()
}
function restoreDraft() {
  const saved = recovery.value
  draft.title = saved.title
  draft.description = saved.description
  timeLimitInput.value = saved.timeLimitInput
  draft.variants = saved.variants.map(variant => ({ ...variant, localId: nextId(),
    questions: variant.questions.map(question => ({ ...question, localId: nextId() })),
  }))
  recovery.value = null
  rememberDraft()
}
function discardDraft() {
  if (!confirm('Удалить несохранённый черновик?')) return
  recovery.value = null
  draftStorage.clear()
}
function beforeLeave() {
  if (loading.value && ready.value) { error.value = 'Дождитесь завершения сохранения.'; return false }
  return !dirty.value || confirm('Изменения не отправлены на сервер. Покинуть редактор?')
}
function beforeUnload(event) {
  if (!dirty.value && !(loading.value && ready.value)) return
  event.preventDefault(); event.returnValue = ''
}
onBeforeRouteLeave(beforeLeave)
onBeforeRouteUpdate(beforeLeave)

function nextId() {
  const id = uid.value
  uid.value += 1
  return id
}

function toPrettyJson(value, fallback = '{}') {
  if (value === null || value === undefined || value === '') return fallback
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return fallback
  }
}

function makeQuestion(question = {}) {
  return {
    localId: nextId(),
    type: question.type || 'text_input',
    title: question.title || '',
    body: question.body || '',
    max_points: question.max_points ?? 1,
    check_type: question.check_type || 'exact',
    check_config_text: toPrettyJson(question.check_config, '{}'),
    ui_config_text: toPrettyJson(question.ui_config, '{}'),
    allow_intermediate_check: Boolean(question.allow_intermediate_check),
  }
}

function makeVariant(variant = {}, index = 0) {
  return {
    localId: nextId(),
    title: variant.title || `Вариант ${index + 1}`,
    questions: (variant.questions || []).map((q) => makeQuestion(q)),
  }
}

function setDraftFromPayload(payload) {
  draft.title = payload.title || ''
  draft.description = payload.description || ''
  timeLimitInput.value = payload.time_limit === null || payload.time_limit === undefined ? '' : String(payload.time_limit)
  savedTimeLimit = payload.time_limit ?? null

  draft.variants.splice(0, draft.variants.length)
  ;(payload.variants || []).forEach((variant, index) => {
    draft.variants.push(makeVariant(variant, index))
  })
}

function parseConfig(text, fieldName, variantIndex, questionIndex) {
  const trimmed = String(text || '').trim()
  if (!trimmed) return {}
  try {
    return JSON.parse(trimmed)
  } catch {
    throw new Error(`Невалидный JSON в ${fieldName} (вариант ${variantIndex + 1}, вопрос ${questionIndex + 1})`)
  }
}

function toPayload() {
  const title = String(draft.title || '').trim()
  if (!title) throw new Error('Название теста не может быть пустым')

  let time_limit = null
  if (String(timeLimitInput.value).trim() !== '') {
    const value = Number(timeLimitInput.value)
    if (!Number.isInteger(value) || value <= 0) {
      throw new Error('Лимит времени должен быть положительным целым числом')
    }
    time_limit = value
  }

  const variants = draft.variants.map((variant, variantIndex) => {
    const questions = variant.questions.map((question, questionIndex) => {
      const maxPoints = Number(question.max_points)
      if (!Number.isInteger(maxPoints) || maxPoints < 0) {
        throw new Error(`Некорректные баллы (вариант ${variantIndex + 1}, вопрос ${questionIndex + 1})`)
      }

      const type = String(question.type || '').trim()
      const title = String(question.title || '').trim()
      const checkType = String(question.check_type || '').trim()
      if (!type || !title || !checkType) {
        throw new Error(`Заполните тип, заголовок и тип проверки (вариант ${variantIndex + 1}, вопрос ${questionIndex + 1})`)
      }

      return {
        type,
        title,
        body: String(question.body || ''),
        max_points: maxPoints,
        check_type: checkType,
        check_config: parseConfig(question.check_config_text, 'check_config', variantIndex, questionIndex),
        ui_config: parseConfig(question.ui_config_text, 'ui_config', variantIndex, questionIndex),
        allow_intermediate_check: checkType !== 'manual' && Boolean(question.allow_intermediate_check),
      }
    })

    return {
      title: String(variant.title || '').trim() || `Вариант ${variantIndex + 1}`,
      questions,
    }
  })

  return {
    title,
    description: String(draft.description || ''),
    time_limit,
    variants,
  }
}

function toParamsPayload() {
  const title = String(draft.title || '').trim()
  if (!title) throw new Error('Название теста не может быть пустым')

  let time_limit = null
  if (String(timeLimitInput.value).trim() !== '') {
    const value = Number(timeLimitInput.value)
    if (!Number.isInteger(value) || value <= 0) {
      throw new Error('Лимит времени должен быть положительным целым числом')
    }
    time_limit = value
  }

  return {
    title,
    description: String(draft.description || ''),
    time_limit,
  }
}

async function save(section) {
  if (loading.value || !ready.value || recovery.value) return
  const sentSnapshot = captureDraft()
  error.value = ''
  success.value = ''
  loading.value = true
  savingSection.value = section
  try {
    if (section === 'params') {
      const paramsPayload = toParamsPayload()
      paramsPayload.expected_time_limit = savedTimeLimit
      await api.updateTestParams(route.params.id, paramsPayload)
      savedTimeLimit = paramsPayload.time_limit
    } else {
      const payload = toPayload()
      payload.expected_time_limit = savedTimeLimit
      await api.updateTest(route.params.id, payload)
      savedTimeLimit = payload.time_limit
    }
    markSaved(sentSnapshot, section)
    success.value = section === 'params' ? 'Параметры теста сохранены' : 'Вопросы сохранены'
  } catch (e) {
    error.value = e.response?.data?.error || e.message || 'Ошибка сохранения'
  } finally {
    loading.value = false
    savingSection.value = ''
  }
}

function saveParams() {
  return save('params')
}

function saveQuestions() {
  return save('questions')
}

function chooseJsonFile() {
  jsonInput.value?.click()
}

async function onJsonFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || loading.value || !ready.value) return
  if (dirty.value && !confirm('Загрузка JSON заменит текущие несохранённые изменения. Продолжить?')) return

  error.value = ''
  success.value = ''
  loading.value = true
  savingSection.value = 'questions'
  try {
    const payload = JSON.parse(await file.text())
    validateImportedPayload(payload)
    await api.updateTest(route.params.id, payload)
    setDraftFromPayload(payload)
    markSaved(captureDraft())
    success.value = 'JSON загружен и тест сохранён'
  } catch (e) {
    error.value = e.response?.data?.error || e.message || 'Не удалось загрузить JSON'
  } finally {
    loading.value = false
    savingSection.value = ''
  }
}

function validateImportedPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('JSON должен содержать объект теста')
  }
  if (!Array.isArray(payload.variants)) {
    throw new Error('В JSON должен быть массив variants')
  }

  if (!hasAttempts.value) return

  if (payload.variants.length !== draft.variants.length) {
    throw new Error('У теста уже есть прохождения: количество вариантов менять нельзя')
  }
  payload.variants.forEach((variant, index) => {
    const importedQuestions = Array.isArray(variant.questions) ? variant.questions.length : 0
    const currentQuestions = draft.variants[index]?.questions.length || 0
    if (importedQuestions !== currentQuestions) {
      throw new Error(`У теста уже есть прохождения: количество вопросов в варианте ${index + 1} менять нельзя`)
    }
  })
}

function addVariant() {
  if (hasAttempts.value) return
  draft.variants.push(makeVariant({}, draft.variants.length))
}

function removeVariant(index) {
  if (hasAttempts.value) return
  draft.variants.splice(index, 1)
}

function addQuestion(variantIndex) {
  if (hasAttempts.value) return
  draft.variants[variantIndex].questions.push(makeQuestion())
}

function removeQuestion(variantIndex, questionIndex) {
  if (hasAttempts.value) return
  draft.variants[variantIndex].questions.splice(questionIndex, 1)
}

function buildFallbackPayload(test) {
  return {
    title: test.title,
    description: test.description,
    time_limit: test.time_limit,
    variants: (test.variants || []).map((variant, index) => ({
      title: variant.title || `Вариант ${index + 1}`,
      questions: (variant.questions || []).map((question) => ({
        type: question.type,
        title: question.title,
        body: question.body,
        max_points: question.max_points,
        check_type: question.check_type,
        check_config: question.check_config,
        ui_config: question.ui_config,
        allow_intermediate_check: Boolean(question.allow_intermediate_check),
      })),
    })),
  }
}

async function loadTest() {
  if (ready.value) return
  loading.value = true
  error.value = ''; success.value = ''
  try {
    const { data } = await api.getTest(route.params.id)
    if (disposed) return
    hasAttempts.value = Number(data.attempt_count || 0) > 0
    setDraftFromPayload(data.source_json || buildFallbackPayload(data))
    baseline.params = paramsSnapshot(captureDraft())
    baseline.questions = JSON.stringify(captureDraft().variants)
    const saved = draftStorage.read()
    if (saved && typeof saved.title === 'string' && Array.isArray(saved.variants)
        && saved.variants.every(v => Array.isArray(v.questions) && v.questions.every(q => q && typeof q === 'object'))
        && (paramsSnapshot(saved) !== baseline.params || JSON.stringify(saved.variants) !== baseline.questions)) recovery.value = saved
    ready.value = true
  } catch (e) { error.value = e?.response?.data?.error || 'Не удалось загрузить тест. Проверьте соединение и повторите.' }
  finally { loading.value = false }
}
onMounted(() => { loadTest(); window.addEventListener('beforeunload', beforeUnload) })
onUnmounted(() => { disposed = true; window.removeEventListener('beforeunload', beforeUnload) })

</script>
