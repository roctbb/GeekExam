import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export const useAttemptStore = defineStore('attempt', () => {
  const attempt = ref(null)
  const answers = ref({}) // question_id -> answer object

  async function load(id) {
    const { data } = await api.getAttempt(id)
    attempt.value = data
    answers.value = Object.fromEntries(data.answers.map(a => [a.question_id, a]))
  }

  function updateAnswer(questionId, answerObj) {
    answers.value[questionId] = { ...answers.value[questionId], ...answerObj }
  }

  function applyWsUpdate(payload) {
    const a = answers.value[payload.question_id]
    if (a) {
      a.points = payload.points
      a.check_state = payload.check_state
      a.check_comment = payload.check_comment
    }
  }

  return { attempt, answers, load, updateAnswer, applyWsUpdate }
})
