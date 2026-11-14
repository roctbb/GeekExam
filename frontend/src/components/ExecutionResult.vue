<template>
  <section v-if="run || error" class="mt-3 border-top pt-3">
    <div v-if="error" class="alert alert-warning" role="status">{{ error }} <button type="button" class="btn btn-sm btn-outline-secondary" @click="load">Обновить</button></div>
    <template v-if="run">
      <div class="small mb-2" role="status" aria-live="polite">{{ phaseLabel }}<span v-if="progress?.total"> · {{ progress.completed }} из {{ progress.total }}</span></div>
      <template v-if="showSource">
        <details open class="mb-3"><summary>Отправленная версия решения</summary>
          <pre v-if="run.answer?.text" class="ge-code mt-2">{{ run.answer.text }}</pre>
          <p v-if="run.repository?.commit" class="small">Коммит {{ run.repository.commit }}</p>
          <a v-if="run.repository?.archive?.download_url" :href="safeUrl(run.repository.archive.download_url)" target="_blank" rel="noopener">Скачать репозиторий</a>
          <details v-for="file in run.files || []" :key="file.path" class="mt-2"><summary>{{ file.path }}</summary>
            <pre v-if="file.artifact.type==='inline'" class="ge-code mt-2">{{ file.artifact.text }}</pre>
            <a v-else :href="safeUrl(file.artifact.download_url)" target="_blank" rel="noopener">Скачать оригинал · {{ file.bytes }} байт</a>
          </details>
        </details>
        <pre v-if="run.comment" class="ge-code">{{ run.comment }}</pre>
      </template>
      <div v-if="run.statistics?.details?.length">
        <h6>Тесты: {{ run.statistics.tests_passed }} из {{ run.statistics.tests_total }}</h6>
        <details v-for="test in run.statistics.details" :key="test.number" class="border-top py-2">
          <summary>Тест {{ test.number }} · {{ test.ok ? 'Пройден' : verdicts[test.error_type] || 'Неверный ответ' }}<span v-if="!test.input" class="text-muted"> · скрытый</span></summary>
          <template v-for="(label,key) in fields" :key="key"><div v-if="test[key]" class="mt-2"><strong class="small">{{ label }}</strong>
            <pre v-if="test[key].type==='inline'" class="ge-code">{{ test[key].text || '(пусто)' }}</pre>
            <a v-else :href="safeUrl(test[key].download_url)" target="_blank" rel="noopener">Скачать · {{ test[key].bytes }} байт</a>
          </div></template>
        </details>
      </div>
      <details v-if="showSource" class="mt-3" @toggle="historyToggle"><summary>История проверок</summary>
        <div v-for="item in history" :key="item.execution_id" class="mt-2"><button type="button" class="btn btn-sm btn-outline-secondary" @click="inspect(item.execution_id)">{{ new Date(item.created_at).toLocaleString() }} · {{ phases[item.state] || item.state }}</button></div>
        <button v-if="selected" type="button" class="btn btn-sm btn-outline-primary mt-2" @click="selected=null; load()">К последней проверке</button>
      </details>
    </template>
  </section>
</template>
<script setup>
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import api from '../api'
import {subscribe} from '../utils/executionSocket'
const props=defineProps({answerId:Number,executionId:String,showSource:{type:Boolean,default:true},checkState:String})
const emit=defineEmits(['updated'])
const run=ref(null),progress=ref(null),error=ref(''),history=ref([]),selected=ref(null)
const phases={queued:'В очереди',preparing:'Подготовка файлов',compiling:'Компиляция',testing:'Проверка тестов',grading:'Оценка ИИ',publishing:'Сохранение результата',completed:'Проверка завершена',error:'Ошибка проверки'}
const verdicts={compilation_error:'Ошибка компиляции',runtime_error:'Ошибка выполнения',timeout:'Превышено время',time_limit_exceeded:'Превышено время',output_limit_exceeded:'Превышен вывод'}
const fields={input:'Ввод',expected:'Ожидается',got:'Получено',error:'Ошибка'}
const phaseLabel=computed(()=>phases[progress.value?.phase || run.value?.state] || 'Проверяется')
let stop=()=>{},generation=0,disposed=false
const completed=new Set()
function safeUrl(url){try{const u=new URL(url,location.origin);return u.origin===location.origin?u.href:'#'}catch{return '#'}}
async function load(){
  if(!props.answerId || selected.value)return
  const ticket=++generation
  try{const {data}=await api.execution(props.answerId);if(disposed || ticket!==generation)return
    stop();run.value=data.execution===null?null:data;error.value='';progress.value=data.progress || null
    if(!run.value)return
    const finished=()=>{if(completed.has(data.execution_id))return;completed.add(data.execution_id);emit('updated');load()}
    if(!['completed','error'].includes(data.state))stop=subscribe(data.subscription,event=>{progress.value=event;error.value=''},finished,
      ()=>{error.value='Связь с проверкой прервана. Восстанавливаем подключение…'},async()=> (await api.execution(props.answerId)).data.subscription)
  }catch{if(!disposed)error.value='Не удалось получить результат проверки.'}
}
async function historyToggle(event){if(!event.target.open)return;try{history.value=(await api.executionHistory(props.answerId)).data.items}catch{error.value='Не удалось загрузить историю'}}
async function inspect(id){const ticket=++generation;try{stop();selected.value=id;const {data}=await api.executionRun(id);if(disposed || ticket!==generation)return;run.value=data;progress.value=data.progress;error.value=''}catch{if(!disposed && ticket===generation)error.value='Не удалось открыть проверку'}}
watch(()=>[props.answerId,props.executionId,props.checkState],()=>{selected.value=null;history.value=[];load()},{immediate:true})
onBeforeUnmount(()=>{disposed=true;generation++;stop()})
</script>
<style scoped>
.ge-code { white-space:pre-wrap; overflow-wrap:anywhere; max-height:28rem; overflow:auto; }
summary { cursor:pointer; }
</style>
