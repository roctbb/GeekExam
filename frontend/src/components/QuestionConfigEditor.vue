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
          <textarea class="form-control mt-1" rows="4" :value="check.prompt || ''" @input="set('check', 'prompt', $event.target.value)" />
        </label>
        <label class="col-12">Эталонный ответ
          <textarea class="form-control mt-1" rows="4" :value="check.answer ?? ''" @input="set('check', 'answer', $event.target.value)" />
        </label>
      </template>
      <label v-if="checkType === 'checker'" class="col-12">Код функции проверки на Python
        <textarea class="form-control font-monospace mt-1" rows="8" :value="check.checker_code || ''" @input="set('check', 'checker_code', $event.target.value)" />
      </label>
      <div v-if="checkType === 'docker'" class="col-12">
        <div v-for="(item, i) in dockerTests" :key="i" class="row g-2 mb-3">
          <label class="col-md-5">Входные данные {{ i + 1 }}
            <textarea class="form-control font-monospace" rows="3" :value="item.input" @input="setTest(i, 'input', $event.target.value)" />
          </label>
          <label class="col-md-5">Ожидаемый вывод
            <textarea class="form-control font-monospace" rows="3" :value="item.expected" @input="setTest(i, 'expected', $event.target.value)" />
          </label>
          <div class="col-md-2 align-self-end"><button type="button" class="btn btn-sm btn-outline-danger" @click="set('check', 'tests', dockerTests.filter((_, index) => index !== i))">Удалить пример</button></div>
        </div>
        <button type="button" class="btn btn-sm btn-outline-secondary" @click="set('check', 'tests', [...dockerTests, { input: '', expected: '' }])">Добавить пример проверки</button>
      </div>
      <template v-if="checkType === 'exact'">
        <label class="col-md-6"><input type="checkbox" :checked="check.case_sensitive ?? false" @change="set('check', 'case_sensitive', $event.target.checked)" /> Учитывать регистр</label>
        <label class="col-md-6"><input type="checkbox" :checked="check.trim ?? true" @change="set('check', 'trim', $event.target.checked)" /> Убирать пробелы по краям</label>
        <label v-if="!['text_input', 'code_input'].includes(type)" class="col-12"><input type="checkbox" :checked="check.partial_scoring ?? true" @change="set('check', 'partial_scoring', $event.target.checked)" /> Начислять баллы за частично верный ответ</label>
      </template>
    </fieldset>
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
const props = defineProps({ type: String, checkType: String, checkConfig: String, uiConfig: String })
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
