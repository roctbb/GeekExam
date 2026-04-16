<template>
  <nav class="navbar ge-navbar sticky-top mb-4">
    <div class="container">
      <a class="navbar-brand" href="/">Geek<span>Exam</span></a>
      <div class="d-flex align-items-center gap-2">
        <template v-if="auth.user">
          <span class="text-light small opacity-75">{{ auth.user.name }}</span>
          <a v-if="isTeacher" href="/admin/tests" class="btn btn-sm btn-outline-light">Тесты</a>
          <a href="/my-results" class="btn btn-sm btn-outline-light">Результаты</a>
          <button class="btn btn-sm btn-outline-secondary text-light border-secondary" @click="logout">Выйти</button>
        </template>
        <a v-else href="/auth/login" class="btn btn-sm btn-outline-light">Войти</a>
      </div>
    </div>
  </nav>
  <div class="container ge-fade-in">
    <RouterView />
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useAuthStore } from './stores/auth'

const auth = useAuthStore()
const isTeacher = computed(() => ['teacher', 'admin'].includes(auth.user?.role))

async function logout() {
  auth.user = null
  await fetch('/auth/logout', { credentials: 'include' })
  window.location.href = '/'
}

onMounted(() => auth.fetchMe())
</script>
