import { ref, onMounted, onUnmounted } from 'vue'

export function useResultList(fetchList) {
  const attempts = ref([])
  const loading = ref(true)
  const refreshing = ref(false)
  const error = ref('')
  let timer, stopped = false

  async function refresh() {
    if (refreshing.value || stopped) return
    clearTimeout(timer)
    refreshing.value = true
    try {
      const { data } = await fetchList()
      if (!stopped) {
        attempts.value = data
        error.value = ''
      }
    } catch {
      if (!stopped) error.value = 'Не удалось обновить результаты. Проверьте соединение и повторите.'
    } finally {
      loading.value = false
      refreshing.value = false
      if (!stopped) timer = setTimeout(refresh, 5000)
    }
  }

  function onVisibilityChange() { if (!document.hidden) refresh() }
  onMounted(() => {
    refresh()
    document.addEventListener('visibilitychange', onVisibilityChange)
  })
  onUnmounted(() => {
    stopped = true
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })
  return { attempts, loading, refreshing, error, refresh }
}
