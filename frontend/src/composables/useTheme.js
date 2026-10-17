import { computed, readonly, ref } from 'vue'

const storageKey = 'geekexam:theme'
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)')
const theme = ref(document.documentElement.dataset.bsTheme || 'light')
let preference = null

function validTheme(value) { return ['light', 'dark'].includes(value) ? value : null }

function applyTheme() {
  theme.value = preference || (systemTheme.matches ? 'dark' : 'light')
  document.documentElement.dataset.bsTheme = theme.value
}

export function initializeTheme() {
  try { preference = validTheme(localStorage.getItem(storageKey)) } catch { /* Use the system setting. */ }
  applyTheme()
  const onSystemChange = () => { if (!preference) applyTheme() }
  const onStorage = event => {
    if (event.key !== storageKey && event.key !== null) return
    if (event.storageArea && event.storageArea !== window.localStorage) return
    preference = validTheme(event.newValue)
    applyTheme()
  }
  systemTheme.addEventListener('change', onSystemChange)
  window.addEventListener('storage', onStorage)
  return () => {
    systemTheme.removeEventListener('change', onSystemChange)
    window.removeEventListener('storage', onStorage)
  }
}

function toggleTheme() {
  preference = theme.value === 'dark' ? 'light' : 'dark'
  try { localStorage.setItem(storageKey, preference) } catch { /* The current tab can still switch themes. */ }
  applyTheme()
}

export function useTheme() {
  return { theme: readonly(theme), isDark: computed(() => theme.value === 'dark'), toggleTheme }
}
