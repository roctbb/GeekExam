<template>
  <div v-if="test && currentVariant" class="ge-fade-in">
    <div class="ge-page-header">
      <h4>{{ test.title }}<span v-if="currentVariant.title">: {{ currentVariant.title }}</span></h4>
      <div class="d-flex align-items-center gap-3 flex-wrap justify-content-end">
        <select v-if="test.variants.length > 1" v-model.number="activeVariant" class="form-select form-select-sm ge-preview-variant-select">
          <option v-for="(variant, i) in test.variants" :key="variant.id" :value="i">
            {{ variant.title || `Вариант ${i + 1}` }}
          </option>
        </select>
        <span v-if="test.time_limit" class="ge-timer">⏱ {{ formatTime(test.time_limit * 60) }}</span>
        <button class="btn btn-danger btn-sm" disabled>Завершить</button>
        <RouterLink :to="`/admin/tests/${test.id}`" class="btn btn-outline-secondary btn-sm">К тесту</RouterLink>
      </div>
    </div>

    <div class="ge-progress">
      <div class="ge-progress-bar" :style="{ width: progressPct + '%' }" />
    </div>

    <div class="ge-question-tabs">
      <div
        v-for="(q, i) in currentVariant.questions"
        :key="q.id"
        class="ge-tab"
        :class="[activeTab === i ? 'active' : '', isQuestionAnswered(q, answers[q.id]) ? 'answered' : '']"
        @click="activeTab = i"
      >
        {{ i + 1 }}
      </div>
    </div>

    <div v-if="currentQuestion" class="card mb-3">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span>{{ currentQuestion.title }}</span>
        <span class="badge bg-secondary">{{ currentQuestion.max_points }} б.</span>
      </div>
      <div class="card-body">
        <div :class="{ 'ge-question-split': currentQuestion.type === 'code_input' && currentQuestion.ui_config?.layout === 'split' }">
        <MarkdownBody class="mb-3 ge-question-condition" :source="currentQuestion.body" :copy-code="currentQuestion.type === 'code_input'" />
        <component
          :is="questionComponent(currentQuestion.type)" :key="currentQuestion.id"
          :question="currentQuestion"
          :modelValue="answers[currentQuestion.id]"
          :readonly="false"
          :checkResult="null"
          @update:modelValue="onAnswerUpdate"
          @check="onPreviewCheck"
        />
        </div>
        <div class="d-flex justify-content-between mt-3">
          <button class="btn btn-outline-secondary btn-sm" :disabled="activeTab === 0" @click="activeTab--">← Назад</button>
          <button class="btn btn-outline-secondary btn-sm" :disabled="activeTab === currentVariant.questions.length - 1" @click="activeTab++">Далее →</button>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="text-center py-5"><div class="spinner-border" /></div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import api from '../../api'
import { isQuestionAnswered } from '../../utils/answers'
import MarkdownBody from '../../components/MarkdownBody.vue'
import TextInputQuestion from '../../components/questions/TextInputQuestion.vue'
import CodeInputQuestion from '../../components/questions/CodeInputQuestion.vue'
import TrueFalseTableQuestion from '../../components/questions/TrueFalseTableQuestion.vue'
import InteractiveQuestion from '../../components/questions/InteractiveQuestion.vue'
import MultiInputQuestion from '../../components/questions/MultiInputQuestion.vue'
import MatrixInputQuestion from '../../components/questions/MatrixInputQuestion.vue'
import ChoiceTableQuestion from '../../components/questions/ChoiceTableQuestion.vue'

const questionComponents = {
  text_input: TextInputQuestion,
  code_input: CodeInputQuestion,
  true_false_table: TrueFalseTableQuestion,
  interactive: InteractiveQuestion,
  multi_input: MultiInputQuestion,
  matrix_input: MatrixInputQuestion, choice_table: ChoiceTableQuestion,
}

const route = useRoute()
const test = ref(null)
const activeVariant = ref(0)
const activeTab = ref(0)
const answers = reactive({})

const currentVariant = computed(() => test.value?.variants?.[activeVariant.value] || null)
const currentQuestion = computed(() => currentVariant.value?.questions?.[activeTab.value] || null)
const progressPct = computed(() => {
  const questions = currentVariant.value?.questions || []
  if (!questions.length) return 0
  const answered = questions.filter(q => isQuestionAnswered(q, answers[q.id])).length
  return Math.round((answered / questions.length) * 100)
})

watch(activeVariant, () => { activeTab.value = 0 })

onMounted(async () => {
  const { data } = await api.getTest(route.params.id)
  test.value = data
})

function questionComponent(type) {
  return questionComponents[type] || TextInputQuestion
}

function onAnswerUpdate(value) {
  if (!currentQuestion.value) return
  answers[currentQuestion.value.id] = value
}

function onPreviewCheck() {
  alert('Это режим просмотра. Проверка ответов здесь не запускается.')
}


function formatTime(s) {
  return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`
}
</script>

<style scoped>
.ge-question-split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 1.5rem; align-items: start; }
.ge-question-split > * { min-width: 0; }
@media (min-width: 1000px) { .ge-question-split .ge-question-condition { max-height: 70vh; overflow-y: auto; padding-right: .75rem; } }
@media (max-width: 999px) { .ge-question-split { grid-template-columns: minmax(0, 1fr); } }
</style>
