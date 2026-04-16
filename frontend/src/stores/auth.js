import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)

  async function fetchMe() {
    try {
      const { data } = await api.me()
      user.value = data
    } catch {
      user.value = null
    }
  }

  return { user, fetchMe }
})
