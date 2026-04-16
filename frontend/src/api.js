import axios from 'axios'

const api = axios.create({ baseURL: '/api', withCredentials: true })

api.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) {
      window.location.href = '/auth/login?next=' + encodeURIComponent(window.location.pathname)
    }
    return Promise.reject(err)
  }
)

export default {
  me: () => api.get('/me'),
  // Tests (teacher)
  getTests: () => api.get('/tests'),
  createTest: (data) => api.post('/tests', data),
  getTest: (id) => api.get(`/tests/${id}`),
  updateTest: (id, data) => api.put(`/tests/${id}`, data),
  deleteTest: (id) => api.delete(`/tests/${id}`),
  activateTest: (id) => api.post(`/tests/${id}/activate`),
  deactivateTest: (id) => api.post(`/tests/${id}/deactivate`),
  setTestCode: (id, code) => api.put(`/tests/${id}/code`, { code }),
  getTestAttempts: (id) => api.get(`/tests/${id}/attempts`),
  // Attempts
  joinTest: (code) => api.post('/join', { code }),
  getAttempt: (id) => api.get(`/attempts/${id}`),
  deleteAttempt: (id) => api.delete(`/attempts/${id}`),
  finishAttempt: (id) => api.post(`/attempts/${id}/finish`),
  myAttempts: () => api.get('/my-attempts'),
  myAttemptResults: (id) => api.get(`/my-attempts/${id}/results`),
  // Answers
  saveAnswer: (id, value) => api.put(`/answers/${id}`, { value }),
  checkAnswer: (id) => api.post(`/answers/${id}/check`),
  gradeAnswer: (id, points, comment) => api.put(`/answers/${id}/grade`, { points, comment }),
}
