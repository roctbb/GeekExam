import { computed, onMounted, onUnmounted, ref } from 'vue'
import api from '../api'

export function useExamMonitoring(testId) {
  const data = ref(null), error = ref(''), lastUpdated = ref(null), clock = ref(Date.now())
  let timer, ticking, disposed = false, running = false
  const stale = computed(() => !lastUpdated.value || clock.value-lastUpdated.value > 20000)
  const byAttempt = computed(() => Object.fromEntries((data.value?.attempts || []).map(row => [row.attempt_id, row])))
  async function refresh() {
    if (running || disposed) return
    running = true
    try {
      const result = (await api.getPresence(testId)).data
      if (!disposed) { data.value = result; lastUpdated.value = Date.now(); error.value = '' }
    } catch { if (!disposed) error.value = 'Нет связи с GeekExam. Статусы могут быть устаревшими.' }
    finally { running = false }
  }
  onMounted(() => { refresh(); timer = setInterval(refresh, 5000); ticking = setInterval(() => { clock.value = Date.now() }, 1000) })
  onUnmounted(() => { disposed = true; clearInterval(timer); clearInterval(ticking) })
  return { data, error, lastUpdated, stale, byAttempt, refresh }
}
