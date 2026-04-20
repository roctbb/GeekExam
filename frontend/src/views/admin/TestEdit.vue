<template>
  <div class="row justify-content-center ge-fade-in">
    <div class="col-xl-11">
      <div class="ge-page-header">
        <h4>Редактирование теста</h4>
        <RouterLink :to="`/admin/tests/${route.params.id}`" class="btn btn-outline-secondary btn-sm">← К тесту</RouterLink>
      </div>

      <div v-if="error" class="alert alert-danger py-2 small">{{ error }}</div>
      <div v-if="success" class="alert alert-success py-2 small">{{ success }}</div>

      <div class="card mb-4">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span class="fw-semibold">Параметры теста</span>
          <button class="btn btn-primary btn-sm" :disabled="loading" @click="saveParams">
            <span v-if="loading && savingSection === 'params'" class="spinner-border spinner-border-sm me-1" />
            Сохранить параметры
          </button>
        </div>
        <div class="card-body">
          <div class="mb-3">
            <label class="form-label">Название</label>
            <input v-model.trim="draft.title" type="text" class="form-control" placeholder="Название теста" />
          </div>

          <div class="mb-3">
            <label class="form-label">Описание</label>
            <textarea v-model="draft.description" class="form-control" rows="4" placeholder="Описание (Markdown)"></textarea>
          </div>

          <div class="mb-0">
            <label class="form-label">Лимит времени (мин), пусто = без лимита</label>
            <input
              v-model="timeLimitInput"
              type="number"
              min="1"
              class="form-control"
              placeholder="Например, 45"
            />
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span class="fw-semibold">Вопросы и варианты</span>
          <div class="d-flex gap-2">
            <button class="btn btn-outline-secondary btn-sm" @click="addVariant">+ Вариант</button>
            <button class="btn btn-primary btn-sm" :disabled="loading" @click="saveQuestions">
              <span v-if="loading && savingSection === 'questions'" class="spinner-border spinner-border-sm me-1" />
              Сохранить вопросы
            </button>
          </div>
        </div>

        <div class="card-body">
          <div v-if="!draft.variants.length" class="text-muted">Вариантов нет. Добавьте вариант.</div>

          <div v-for="(variant, variantIndex) in draft.variants" :key="variant.localId" class="border rounded p-3 mb-3">
            <div class="d-flex justify-content-between align-items-center mb-3">
              <div class="w-100 me-3">
                <label class="form-label mb-1">Название варианта</label>
                <input
                  v-model="variant.title"
                  type="text"
                  class="form-control form-control-sm"
                  :placeholder="`Вариант ${variantIndex + 1}`"
                />
              </div>
              <button class="btn btn-outline-danger btn-sm mt-4" @click="removeVariant(variantIndex)">Удалить вариант</button>
            </div>

            <div class="d-flex justify-content-between align-items-center mb-2">
              <h6 class="mb-0">Вопросы</h6>
              <button class="btn btn-outline-secondary btn-sm" @click="addQuestion(variantIndex)">+ Вопрос</button>
            </div>

            <div v-if="!variant.questions.length" class="text-muted small">В этом варианте пока нет вопросов.</div>

            <div
              v-for="(question, questionIndex) in variant.questions"
              :key="question.localId"
              class="card mb-3"
            >
              <div class="card-header d-flex justify-content-between align-items-center py-2">
                <strong>Вопрос {{ questionIndex + 1 }}</strong>
                <button class="btn btn-outline-danger btn-sm" @click="removeQuestion(variantIndex, questionIndex)">Удалить</button>
              </div>

              <div class="card-body">
                <div class="row g-3">
                  <div class="col-md-4">
                    <label class="form-label">Тип вопроса</label>
                    <select v-model="question.type" class="form-select">
                      <option v-for="type in questionTypeOptions" :key="type" :value="type">{{ type }}</option>
                    </select>
                  </div>

                  <div class="col-md-4">
                    <label class="form-label">Тип проверки</label>
                    <select v-model="question.check_type" class="form-select">
                      <option v-for="type in checkTypeOptions" :key="type" :value="type">{{ type }}</option>
                    </select>
                  </div>

                  <div class="col-md-2">
                    <label class="form-label">Макс. баллы</label>
                    <input v-model="question.max_points" type="number" min="0" class="form-control" />
                  </div>

                  <div class="col-md-2 d-flex align-items-end">
                    <div class="form-check mb-2">
                      <input v-model="question.allow_intermediate_check" class="form-check-input" type="checkbox" :id="`intermediate-${question.localId}`" />
                      <label class="form-check-label" :for="`intermediate-${question.localId}`">Пром. проверка</label>
                    </div>
                  </div>

                  <div class="col-12">
                    <label class="form-label">Заголовок вопроса</label>
                    <input v-model="question.title" type="text" class="form-control" placeholder="Например, Задача 1" />
                  </div>

                  <div class="col-12">
                    <label class="form-label">Текст задания (Markdown)</label>
                    <textarea v-model="question.body" class="form-control" rows="4"></textarea>
                  </div>

                  <div class="col-md-6">
                    <label class="form-label">check_config (JSON)</label>
                    <textarea v-model="question.check_config_text" class="form-control font-monospace small" rows="8" spellcheck="false"></textarea>
                  </div>

                  <div class="col-md-6">
                    <label class="form-label">ui_config (JSON)</label>
                    <textarea v-model="question.ui_config_text" class="form-control font-monospace small" rows="8" spellcheck="false"></textarea>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import api from '../../api'

const route = useRoute()

const loading = ref(false)
const savingSection = ref('')
const error = ref('')
const success = ref('')
const timeLimitInput = ref('')
const uid = ref(1)

const questionTypeOptions = ['text_input', 'code_input', 'true_false_table', 'interactive', 'multi_input']
const checkTypeOptions = ['exact', 'checker', 'docker', 'ai', 'manual']

const draft = reactive({
  title: '',
  description: '',
  variants: [],
})

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
  error.value = ''
  success.value = ''
  loading.value = true
  savingSection.value = section
  try {
    if (section === 'params') {
      const paramsPayload = toParamsPayload()
      await api.updateTestParams(route.params.id, paramsPayload)
    } else {
      const payload = toPayload()
      await api.updateTest(route.params.id, payload)
    }
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

function addVariant() {
  draft.variants.push(makeVariant({}, draft.variants.length))
}

function removeVariant(index) {
  draft.variants.splice(index, 1)
}

function addQuestion(variantIndex) {
  draft.variants[variantIndex].questions.push(makeQuestion())
}

function removeQuestion(variantIndex, questionIndex) {
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

onMounted(async () => {
  error.value = ''
  success.value = ''
  const { data } = await api.getTest(route.params.id)
  const payload = data.source_json || buildFallbackPayload(data)
  setDraftFromPayload(payload)
})
</script>
