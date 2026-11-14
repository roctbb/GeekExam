<template>
  <details class="mt-3" @toggle="opened"><summary>Материалы и файлы задания</summary>
    <p class="form-text">Файлы сохраняются сразу. Закрытые вложения доступны только преподавателю и проверке.</p>
    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>
    <ul class="list-unstyled"><li v-for="file in files" :key="file.id" class="d-flex gap-2 align-items-center flex-wrap my-2">
      <a :href="`/api/questions/${questionId}/files/${file.id}`" target="_blank" rel="noopener">{{ file.path }}</a>
      <span class="small text-muted">{{ file.is_public ? 'Доступен ученику':'Закрытый' }} · {{ kinds[file.kind] }}{{ file.read_only?' · только чтение':'' }}</span>
      <button type="button" class="btn btn-sm btn-outline-danger" :disabled="busy" @click="remove(file)">Удалить</button>
    </li></ul>
    <fieldset :disabled="busy" class="row g-2">
      <label class="col-md-6">Назначение<select class="form-select mt-1" v-model="kind"><option v-for="(label,key) in kinds" :key="key" :value="key">{{ label }}</option></select></label>
      <label class="col-md-6">Путь (необязательно)<input class="form-control mt-1" v-model="path" placeholder="data/input.csv" /></label>
      <label class="col-12"><input type="checkbox" v-model="isPublic" :disabled="kind!=='attachment'" /> Доступен ученику</label>
      <label class="col-12"><input type="checkbox" v-model="readOnly" /> Только чтение</label>
      <label class="col-12"><input type="checkbox" v-model="includeInCheck" /> Передавать в проверку</label>
      <label class="col-12">Загрузить файл<input class="form-control mt-1" type="file" @change="upload" /></label>
    </fieldset>
  </details>
</template>
<script setup>
import {ref} from 'vue'
import api from '../api'
const props=defineProps({questionId:Number})
const files=ref([]),error=ref(''),busy=ref(false),kind=ref('attachment'),path=ref(''),isPublic=ref(true),readOnly=ref(false),includeInCheck=ref(false)
const kinds={attachment:'Вложение',starter:'Начальные файлы',resource:'Ресурс проверки'}
let loaded=false
async function load(){try{files.value=(await api.questionFiles(props.questionId)).data.items;loaded=true}catch{error.value='Не удалось загрузить материалы'}}
function opened(event){if(event.target.open && !loaded)load()}
async function upload(event){const file=event.target.files[0];event.target.value='';if(!file)return;busy.value=true;error.value='';try{const data=new FormData();data.append('file',file);data.append('kind',kind.value);data.append('path',path.value || file.name);data.append('is_public',kind.value==='attachment'?String(isPublic.value):'true');data.append('read_only',String(readOnly.value));data.append('include_in_check',String(includeInCheck.value));files.value=(await api.uploadQuestionFile(props.questionId,data)).data.items;path.value=''}catch(e){error.value=e.response?.status===409?'Такой путь уже занят. Измените путь или удалите прежний файл.':'Не удалось загрузить файл'}finally{busy.value=false}}
async function remove(file){if(!confirm(`Удалить ${file.path}? Старые отправленные версии сохранят этот файл.`))return;busy.value=true;try{await api.deleteQuestionFile(props.questionId,file.id);await load()}catch{error.value='Не удалось удалить файл'}finally{busy.value=false}}
</script>
