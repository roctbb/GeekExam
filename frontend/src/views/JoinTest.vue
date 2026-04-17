<template>
  <div class="ge-join-card card ge-fade-in">
    <div class="card-body p-4">
      <div class="ge-join-icon">🚀</div>
      <h4 class="fw-bold mb-1">Войти в тест</h4>
      <p class="text-muted small mb-4">Введите код от преподавателя</p>
      <input v-model="code" type="text" class="form-control form-control-lg text-uppercase mb-3"
        placeholder="КОД" maxlength="20" @keyup.enter="join" />
      <div v-if="error" class="alert alert-danger py-2 small">{{ error }}</div>
      <button class="btn btn-primary btn-lg w-100" :disabled="loading" @click="join">
        <span v-if="loading" class="spinner-border spinner-border-sm me-1" />
        Начать
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'

const router = useRouter()
const code = ref('')
const error = ref('')
const loading = ref(false)

async function join() {
  error.value = ''
  loading.value = true
  try {
    const { data } = await api.joinTest(code.value)
    router.push(`/attempt/${data.attempt_id}`)
  } catch (e) {
    const data = e.response?.data
    if (data?.attempt_id) {
      try {
        const { data: attempt } = await api.getAttempt(data.attempt_id)
        if (attempt.finished_at) router.push(`/my-results/${data.attempt_id}`)
        else router.push(`/attempt/${data.attempt_id}`)
      } catch {
        router.push(`/my-results/${data.attempt_id}`)
      }
    } else error.value = data?.error || 'Ошибка'
  } finally { loading.value = false }
}
</script>
