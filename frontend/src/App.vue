<template>
  <nav ref="navbar" class="navbar ge-navbar sticky-top mb-4">
    <div class="container">
      <RouterLink class="navbar-brand" to="/">Geek<span>Exam</span></RouterLink>
      <div class="d-flex align-items-center gap-2 flex-wrap">
        <template v-if="auth.user">
          <span class="text-light small opacity-75">{{ auth.user.name }}</span>
          <RouterLink v-if="isTeacher" to="/admin/tests" class="btn btn-sm btn-outline-light">Тесты</RouterLink>
          <RouterLink to="/my-results" class="btn btn-sm btn-outline-light">Результаты</RouterLink>
          <button class="btn btn-sm btn-outline-secondary text-light border-secondary" :disabled="loggingOut" @click="logout">Выйти</button>
        </template>
        <a v-else href="/auth/login" class="btn btn-sm btn-outline-light">Войти</a>
      </div>
    </div>
  </nav>
  <div class="container ge-fade-in">
    <div v-if="logoutError" class="alert alert-danger" role="alert">{{ logoutError }}</div>
    <RouterView :key="$route.path" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter, isNavigationFailure } from 'vue-router'
import { useAuthStore } from './stores/auth'
import api from './api'

const auth = useAuthStore()
const router = useRouter()
const navbar = ref(null)
const loggingOut = ref(false), logoutError = ref('')
let navbarObserver
const isTeacher = computed(() => ['teacher', 'admin'].includes(auth.user?.role))

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
onUnmounted(() => navbarObserver?.disconnect())
</script>
