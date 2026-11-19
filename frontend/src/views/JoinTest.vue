<template>
  <div class="ge-join-card card ge-fade-in">
    <div class="card-body p-4">
      <div class="ge-join-icon"><AppIcon name="key" /></div>
      <h4 class="fw-bold mb-1">Войти в тест</h4>
      <p class="text-muted small mb-4">Введите код от преподавателя</p>
      <input v-model="code" type="text" class="form-control form-control-lg text-uppercase mb-3"
        placeholder="КОД" maxlength="20" :disabled="loading" @keyup.enter="join" />
      <div v-if="error" class="alert alert-danger py-2 small" role="alert">{{ error }}</div>
      <button class="btn btn-primary btn-lg w-100" :disabled="loading" @click="join">
        <span v-if="loading" class="spinner-border spinner-border-sm me-1" />
        <AppIcon v-else name="play" />
        {{ checkingGuard ? 'Проверяем устройство…' : 'Начать' }}
      </button>
      <RouterLink to="/my-results" class="ge-join-results"><AppIcon name="results" />Мои результаты</RouterLink>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { sendLocalProof } from '../utils/autoDeviceBinding'

const router = useRouter()
const code = ref('')
const error = ref('')
const loading = ref(false)
const checkingGuard = ref(false)

async function confirmGuard(enteredCode, { ticket, items }) {
  checkingGuard.value = true
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 12000)
  try {
    const results = await Promise.allSettled(items.map(item => sendLocalProof(item, { signal: controller.signal })))
    const candidates = results.filter(result => result.status === 'fulfilled').map(result => result.value)
    candidates.sort((a, b) => Number(b.confirmed) - Number(a.confirmed))
    if (!candidates.length) throw new Error('Не удалось проверить устройство в сети кабинета.')
    return await api.joinTest(enteredCode, { guard_ticket: ticket, proof_ids: candidates.map(candidate => candidate.id) })
  } finally {
    clearTimeout(timeout)
  }
}

async function join() {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    const enteredCode = code.value
    let { data } = await api.joinTest(enteredCode)
    if (data.guard_proof) ({ data } = await confirmGuard(enteredCode, data.guard_proof))
    router.push(`/attempt/${data.attempt_id}`)
  } catch (e) {
    const data = e.response?.data
    if (data?.attempt_id) {
      try {
        const { data: attempt } = await api.getAttempt(data.attempt_id)
        if (attempt.finished_at) router.push(`/my-results/${data.attempt_id}`)
        else router.push(`/attempt/${data.attempt_id}`)
      } catch (failure) {
        if (failure.response?.data?.error_code === 'guard_authorization_required') error.value = failure.response.data.error
        else router.push(`/my-results/${data.attempt_id}`)
      }
    } else error.value = data?.error || (checkingGuard.value ? 'Не удалось проверить устройство в сети кабинета.' : 'Не удалось войти в тест.')
  } finally {
    loading.value = false
    checkingGuard.value = false
  }
}
</script>
