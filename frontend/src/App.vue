<template>
  <nav ref="navbar" class="navbar ge-navbar sticky-top mb-4">
    <div class="container">
      <RouterLink class="navbar-brand" to="/">Geek<span>Exam</span></RouterLink>
      <UserMenu v-if="auth.user" :user="auth.user" :logging-out="loggingOut" @logout="logout" />
      <div v-else class="d-flex align-items-center gap-2 flex-wrap justify-content-end">
        <a href="/auth/login" class="btn btn-sm btn-outline-light"><AppIcon name="login" />Войти</a>
        <button class="btn btn-sm btn-outline-light ge-theme-toggle"
          :aria-label="isDark ? 'Включить светлую тему' : 'Включить тёмную тему'" @click="toggleTheme">
          <AppIcon :name="isDark ? 'sun' : 'moon'" />{{ isDark ? 'Светлая тема' : 'Тёмная тема' }}
        </button>
      </div>
    </div>
  </nav>
  <div class="container ge-fade-in">
    <div v-if="logoutError" class="alert alert-danger" role="alert">{{ logoutError }}</div>
    <RouterView :key="$route.path" />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter, isNavigationFailure } from 'vue-router'
import { useAuthStore } from './stores/auth'
import api from './api'
import { initializeTheme, useTheme } from './composables/useTheme'
import UserMenu from './components/UserMenu.vue'

const auth = useAuthStore()
const router = useRouter()
const { isDark, toggleTheme } = useTheme()
const stopTheme = initializeTheme()
const navbar = ref(null)
const loggingOut = ref(false), logoutError = ref('')
let navbarObserver

async function logout() {
  if (loggingOut.value) return
  loggingOut.value = true
  logoutError.value = ''
  try {
    // Run the current page's save/unsaved-change guard before ending the session.
    const failure = await router.push('/join')
    if (isNavigationFailure(failure) && router.currentRoute.value.path !== '/join') return
    await api.logout()
    auth.user = null
  } catch {
    logoutError.value = 'Не удалось выйти. Проверьте соединение и повторите.'
  } finally { loggingOut.value = false }
}

onMounted(() => {
  auth.fetchMe()
  navbarObserver = new ResizeObserver(() => {
    document.documentElement.style.setProperty('--ge-navbar-height', `${navbar.value.offsetHeight}px`)
  })
  navbarObserver.observe(navbar.value)
})
onUnmounted(() => { navbarObserver?.disconnect(); stopTheme() })
</script>
