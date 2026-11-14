<template>
  <div>
    <p v-if="!valid" class="text-danger small" role="alert">Исправьте JSON в дополнительных настройках, чтобы пользоваться формой.</p>
    <fieldset :disabled="!valid" class="row g-3">
      <label v-if="type === 'text_input'" class="col-12 form-check ms-2">
        <input type="checkbox" class="form-check-input" :checked="ui.multiline" @change="set('ui', 'multiline', $event.target.checked)" />
        Многострочный ответ
      </label>
      <label v-if="type === 'text_input'" class="col-md-6">Подсказка в поле ответа
        <input class="form-control mt-1" :value="ui.placeholder || ''" @input="set('ui', 'placeholder', $event.target.value)" />
      </label>
      <template v-if="type === 'code_input'">
        <label class="col-md-6">Язык программирования
          <input class="form-control mt-1" :value="ui.lang || check.lang || 'python'" placeholder="python" @input="setLanguage($event.target.value)" />
        </label>
        <label class="col-md-6">Расположение задания и редактора
          <select class="form-select mt-1" :value="ui.layout || ''" @change="set('ui', 'layout', $event.target.value)">
            <option value="">Друг под другом</option><option value="split">Рядом</option>
          </select>
        </label>
        <label class="col-12">Начальный код
          <textarea class="form-control font-monospace mt-1" rows="5" :value="ui.starter_code || ''" @input="set('ui', 'starter_code', $event.target.value)" />
        </label>
      </template>
      <label v-if="checkType === 'exact' && type === 'text_input'" class="col-12">Правильный ответ
        <textarea class="form-control mt-1" rows="3" :value="check.answer ?? ''" @input="set('check', 'answer', $event.target.value)" />
      </label>
      <template v-if="checkType === 'ai'">
        <label class="col-12">Критерии оценки
          <textarea class="form-control mt-1" rows="4" :value="check.prompt ?? check.private_instructions ?? ''" @input="set('check', 'prompt', $event.target.value)" />
        </label>
        <label class="col-12">Эталонный ответ
          <textarea class="form-control mt-1" rows="4" :value="check.reference_answer ?? check.answer ?? ''" @input="set('check', 'reference_answer', $event.target.value)" />
        </label>
        <label class="col-12">Модель ИИ (необязательно)<input class="form-control mt-1" :value="check.gpt_model || ''" @input="set('check','gpt_model',$event.target.value || null)" /></label>
      </template>
      <template v-if="['ai','docker','manual'].includes(checkType)">
        <div class="col-12"><strong>Форматы сдачи</strong><p class="form-text">Ученик выбирает один из разрешённых способов. Файлы можно приложить к тексту или проекту.</p>
          <label v-for="(label,key) in availableModes" :key="key" class="form-check form-check-inline"><input class="form-check-input" type="checkbox" :checked="submissionModes.includes(key)" @change="toggleMode(key,$event.target.checked)" />{{ label }}</label>
        </div>
        <label class="col-md-6">Языки через запятую<input class="form-control mt-1" :value="(check.allowed_languages || [check.lang || ui.lang || (checkType === 'docker' ? 'python':'text')]).join(', ')" @change="set('check','allowed_languages',$event.target.value.split(',').map(s=>s.trim()).filter(Boolean))" /></label>
        <label class="col-md-6">Точка входа<input class="form-control mt-1" :value="check.entrypoint || ''" placeholder="main.py" @input="set('check','entrypoint',$event.target.value)" /></label>
        <label class="col-md-6">Расширения файлов через запятую<input class="form-control mt-1" :value="(check.allowed_extensions || []).join(', ')" placeholder="py, cpp, zip, xlsx, png" @change="set('check','allowed_extensions',$event.target.value.split(',').map(s=>s.trim().replace(/^\./,'')).filter(Boolean))" /></label>
        <label class="col-md-3">Максимум файлов<input class="form-control mt-1" type="number" min="1" max="100" :value="check.max_files || 100" @change="set('check','max_files',Number($event.target.value))" /></label>
        <label class="col-md-3">Общий размер, МБ<input class="form-control mt-1" type="number" min="1" max="50" :value="(check.max_total_bytes || 52428800)/1048576" @change="set('check','max_total_bytes',Math.round(Number($event.target.value)*1048576))" /></label>
      </template>
      <label v-if="checkType === 'checker'" class="col-12">Код функции проверки на Python
        <textarea class="form-control font-monospace mt-1" rows="8" :value="check.checker_code || ''" @input="set('check', 'checker_code', $event.target.value)" />
      </label>
      <div v-if="checkType === 'docker'" class="col-12">
        <label class="d-block mb-3">Время на тест, секунд<input class="form-control mt-1" type="number" min="0.1" max="30" step="0.1" :value="check.time_limit || 2" @change="set('check','time_limit',Number($event.target.value))" /></label>
        <div v-for="(item, i) in dockerTests" :key="i" class="row g-2 mb-3">
          <label class="col-md-5">Входные данные {{ i + 1 }}
            <textarea class="form-control font-monospace" rows="3" :value="item.input" @input="setTest(i, 'input', $event.target.value)" />
          </label>
          <label class="col-md-5">Ожидаемый вывод
            <textarea class="form-control font-monospace" rows="3" :value="item.expected" @input="setTest(i, 'expected', $event.target.value)" />
          </label>
          <div class="col-md-2 align-self-end"><button type="button" class="btn btn-sm btn-outline-danger" @click="set('check', 'tests', dockerTests.filter((_, index) => index !== i))">Удалить пример</button></div>
          <label class="col-12 form-check ms-2"><input class="form-check-input" type="checkbox" :checked="!item.hidden" @change="setTest(i,'hidden',!$event.target.checked)" />Показать ученику ввод и ожидаемый вывод</label>
        </div>
        <button type="button" class="btn btn-sm btn-outline-secondary" @click="set('check', 'tests', [...dockerTests, { input: '', expected: '' }])">Добавить пример проверки</button>
      </div>
      <template v-if="checkType === 'exact'">
        <label class="col-md-6"><input type="checkbox" :checked="check.case_sensitive ?? false" @change="set('check', 'case_sensitive', $event.target.checked)" /> Учитывать регистр</label>
        <label class="col-md-6"><input type="checkbox" :checked="check.trim ?? true" @change="set('check', 'trim', $event.target.checked)" /> Убирать пробелы по краям</label>
        <label v-if="!['text_input', 'code_input'].includes(type)" class="col-12"><input type="checkbox" :checked="check.partial_scoring ?? true" @change="set('check', 'partial_scoring', $event.target.checked)" /> Начислять баллы за частично верный ответ</label>
      </template>
    </fieldset>
    <QuestionFiles v-if="['ai','docker','manual'].includes(checkType) && questionId" :key="questionId" :question-id="questionId" />
    <p v-else-if="['ai','docker','manual'].includes(checkType)" class="form-text">Загрузить материалы можно после первого сохранения вопроса.</p>
    <details class="mt-3" :open="!valid || !['text_input', 'code_input'].includes(type)">
      <summary class="fw-semibold">Дополнительные настройки (JSON)</summary>
      <div class="row g-3 mt-1">
        <label class="col-md-6">Настройки проверки
          <textarea :value="checkConfig" class="form-control font-monospace small mt-1" rows="8" spellcheck="false" @input="$emit('update:checkConfig', $event.target.value)" />
        </label>
        <label class="col-md-6">Настройки отображения
          <textarea :value="uiConfig" class="form-control font-monospace small mt-1" rows="8" spellcheck="false" @input="$emit('update:uiConfig', $event.target.value)" />
        </label>
      </div>
    </details>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import QuestionFiles from './QuestionFiles.vue'
const props = defineProps({ questionId:Number, type: String, checkType: String, checkConfig: String, uiConfig: String })
const emit = defineEmits(['update:checkConfig', 'update:uiConfig'])
function parse(value) {
  try {
    const parsed = JSON.parse(value || '{}')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
  } catch { return null }
}
const valid = computed(() => !!parse(props.checkConfig) && !!parse(props.uiConfig))
const check = computed(() => parse(props.checkConfig) || {})
const ui = computed(() => parse(props.uiConfig) || {})
const dockerTests = computed(() => Array.isArray(check.value.tests) ? check.value.tests : [])
const modes={files:'Файлы',code:'Вставить код',text:'Текст',project:'Несколько файлов кода',repository:'GitHub'}
const availableModes=computed(()=>Object.fromEntries(Object.entries(modes).filter(([key])=>key!=='text' || props.checkType!=='docker')))
const submissionModes=computed(()=>check.value.submission_modes || (props.type==='code_input'?['code']:['text']))
function toggleMode(mode,enabled){set('check','submission_modes',enabled?[...submissionModes.value,mode]:submissionModes.value.filter(m=>m!==mode))}
function set(target, key, value) {
  if (!valid.value) return
  const source = target === 'check' ? check.value : ui.value
  // Retain configuration keys this form does not know about.
  emit(`update:${target}Config`, JSON.stringify({ ...source, [key]: value }, null, 2))
}
function setLanguage(value) { set('ui', 'lang', value); set('check', 'lang', value) }
function setTest(index, key, value) {
  set('check', 'tests', dockerTests.value.map((item, i) => i === index ? { ...item, [key]: value } : item))
}
</script>
