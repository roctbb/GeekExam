<template>
  <div>
    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>
    <div v-if="materials.length" class="mb-3"><strong class="small">Материалы задания</strong>
      <div v-for="file in materials" :key="file.id"><a :href="safeUrl(file.download_url)" target="_blank" rel="noopener">{{ file.path }}</a><span class="text-muted small" v-if="file.read_only"> · только чтение</span></div>
    </div>
    <fieldset :disabled="readonly || uploading">
      <div class="row g-2 mb-3">
        <label class="col-md-7">Способ сдачи<select class="form-select mt-1" :value="mode" @change="setMode($event.target.value)"><option v-for="key in allowedModes" :key="key" :value="key">{{ labels[key] }}</option></select></label>
        <label v-if="languages.length > 1" class="col-md-5">Язык<select class="form-select mt-1" :value="language" @change="patch({lang:$event.target.value})"><option v-for="lang in languages" :key="lang">{{ lang }}</option></select></label>
      </div>
      <template v-if="mode === 'repository'">
        <label class="d-block mb-2">Публичный репозиторий GitHub<input class="form-control mt-1" type="url" :value="value.repository_url || ''" @input="patch({repository_url:$event.target.value})" placeholder="https://github.com/username/project" /></label>
        <label class="d-block mb-3">Ветка, тег или коммит<input class="form-control mt-1" :value="value.repository_ref || ''" @input="patch({repository_ref:$event.target.value})" /></label>
        <p class="form-text">Сохранится конкретный коммит вместе с файлами решения.</p>
      </template>
      <template v-else>
        <label v-if="mode === 'text' || mode === 'files'" class="d-block mb-3">{{ mode === 'text' ? 'Ваш ответ' : 'Пояснение к работе' }}
          <textarea class="form-control mt-1" :rows="mode === 'text' ? 6 : 3" :value="value.text || ''" @input="patch({text:$event.target.value})" />
        </label>
        <CodeEditor v-if="mode === 'code'" :readonly="readonly" :model-value="value.code ?? question.ui_config?.starter_code ?? ''" :language="language" label="Код решения" @update:model-value="patch({code:$event,lang:language,mode:'code'})" />
        <div v-if="mode === 'project'">
          <div v-for="(file,index) in editorFiles" :key="index" class="mb-3">
            <div class="d-flex gap-2 mb-2"><input class="form-control" aria-label="Путь файла" :value="file.path" @input="editFile(index,{path:$event.target.value})" /><button type="button" class="btn btn-outline-danger btn-sm" @click="removeEditor(index)">Убрать</button></div>
            <CodeEditor :readonly="readonly" :model-value="file.content" :language="language" :label="file.path || 'Файл кода'" @update:model-value="editFile(index,{content:$event})" />
          </div>
          <button type="button" class="btn btn-outline-secondary btn-sm" @click="addEditor">Добавить файл кода</button>
        </div>
        <div v-if="['files','project','text'].includes(mode)" class="mt-3">
          <label v-if="!readonly" class="d-block">Добавить файлы<input class="form-control mt-1" type="file" multiple :accept="config.allowed_extensions?.map(ext=>'.'+ext).join(',')" @change="upload" /></label>
          <p v-if="!readonly" class="form-text">До {{ config.max_files || 100 }} файлов, суммарно до {{ Math.round((config.max_total_bytes || 52428800)/1048576) }} МБ. ZIP, код, Excel и изображения — в зависимости от задания.</p>
          <ul class="list-unstyled mb-0"><li v-for="file in selectedFiles" :key="file.upload_id" class="d-flex gap-2 align-items-center flex-wrap my-2">
            <span v-if="preview">{{ file.path }}</span><a v-else :href="`/api/answers/${answerId}/files/${file.upload_id}`" target="_blank" rel="noopener">{{ file.path || uploads[file.upload_id]?.path || 'Файл решения' }}</a>
            <button v-if="!readonly" class="btn btn-outline-secondary btn-sm" type="button" @click="removeUpload(file.upload_id)">Убрать</button>
          </li></ul>
        </div>
      </template>
    </fieldset>
    <div v-if="uploading" role="status" class="small text-muted mt-2">Загружаем файлы… Дождитесь завершения перед отправкой.</div>
    <p v-if="preview" class="form-text">Предпросмотр: выбранные файлы и ответы не отправляются на сервер.</p>
    <CheckResult v-if="checkResult" :result="checkResult" :max-points="question.max_points" />
  </div>
</template>
<script setup>
import {computed,onMounted,onBeforeUnmount,ref} from 'vue'
import api from '../api'
import CodeEditor from './CodeEditor.vue'
import CheckResult from './CheckResult.vue'
const props=defineProps({question:Object,modelValue:Object,answerId:Number,readonly:Boolean,checkResult:Object,preview:Boolean})
const emit=defineEmits(['update:modelValue','uploading'])
const value=computed(()=>props.modelValue || {})
const config=computed(()=>props.question.submission_config || props.question.check_config || {})
const labels={files:'Загрузить файлы',code:'Вставить код',text:'Ответ текстом',project:'Несколько файлов кода',repository:'GitHub-репозиторий'}
const allowedModes=computed(()=>config.value.submission_modes || [props.question.type === 'code_input' ? 'code' : 'text'])
const mode=computed(()=>value.value.mode || (typeof value.value.code==='string' ? 'code' : allowedModes.value[0]))
const language=computed(()=>value.value.lang || config.value.lang || props.question.ui_config?.lang || (props.question.type==='code_input'?'python':'text'))
const languages=computed(()=>config.value.allowed_languages || [language.value])
const editorFiles=computed(()=>(value.value.files || []).filter(file=>typeof file.content==='string'))
const selectedFiles=computed(()=>(value.value.files || []).filter(file=>file.upload_id))
const uploading=ref(false),error=ref(''),uploads=ref({}),materials=ref([])
let disposed=false
function safeUrl(url){try{const u=new URL(url,location.origin);return u.origin===location.origin?u.href:'#'}catch{return '#'}}
function patch(fields){emit('update:modelValue',{...value.value,mode:mode.value,lang:language.value,...fields})}
function setMode(next){const base={mode:next,lang:language.value,text:value.value.text || ''};if(next==='code')base.code=value.value.code || '';if(next==='project')base.files=value.value.files || [{path:config.value.entrypoint || 'main.py',content:value.value.code || ''}];if(['files','text'].includes(next))base.files=value.value.files || [];if(next==='repository'){base.repository_url=value.value.repository_url || '';base.repository_ref=value.value.repository_ref || ''}emit('update:modelValue',base)}
function editFile(index,fields){patch({files:[...editorFiles.value.map((file,i)=>i===index?{...file,...fields}:file),...selectedFiles.value]})}
function removeEditor(index){patch({files:[...editorFiles.value.filter((_,i)=>i!==index),...selectedFiles.value]})}
function removeUpload(id){patch({files:(value.value.files || []).filter(file=>file.upload_id!==id)})}
function addEditor(){patch({files:[...(value.value.files || []),{path:`file${editorFiles.value.length+1}.${language.value==='cpp'?'cpp':'py'}`,content:''}]})}
async function upload(event){
  const files=[...event.target.files];event.target.value='';if(!files.length || uploading.value)return
  if(props.preview){patch({files:[...(value.value.files || []),...files.map(file=>({upload_id:crypto.randomUUID(),path:file.name}))]});return}
  if(files.some(file=>file.size>(config.value.max_file_bytes || 52428800))){error.value='Файл превышает допустимый размер';return}
  uploading.value=true;emit('uploading',true);error.value=''
  const added=[]
  try{
    for(const file of files){const {data}=await api.uploadAnswerFile(props.answerId,file);added.push({upload_id:data.id,path:data.path});uploads.value[data.id]=data}
  }catch(e){error.value=e.response?.data?.error || 'Не удалось загрузить часть файлов. Уже загруженные добавлены в ответ.'}
  finally{
    uploading.value=false;emit('uploading',false)
    if(!disposed && added.length){const names=new Set(added.map(file=>file.path));patch({files:[...(value.value.files || []).filter(file=>!names.has(file.path)),...added]})}
  }
}
onMounted(async()=>{
  if(props.preview)return
  try{if(props.answerId){const {data}=await api.answerFiles(props.answerId);if(!disposed)uploads.value=Object.fromEntries(data.items.map(file=>[file.id,file]))}
    if(props.question.files_url){const {data}=await api.taskFiles(props.question.files_url);if(!disposed)materials.value=data.items}
  }catch{if(!disposed)error.value='Не удалось загрузить список материалов и файлов. Обновите страницу.'}
})
onBeforeUnmount(()=>{disposed=true;emit('uploading',false)})
</script>
