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
      a.check_comment = payload.check_comment
      if (payload.check_state === 'intermediate') {
        // Intermediate result: show score in UI but keep answer in 'pending'
        // state so it is re-evaluated on final submission.
        a.points = payload.points
        a.check_state = 'intermediate'
      } else {
        a.points = payload.points
        a.check_state = payload.check_state
      }
    }
  }

  return { attempt, answers, load, updateAnswer, applyWsUpdate }
})
