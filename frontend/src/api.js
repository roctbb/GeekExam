import axios from 'axios'

const api = axios.create({ baseURL: '/api', withCredentials: true, timeout: 15000 })

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
  logout: () => api.get('/auth/logout', { baseURL: '' }),
  // Tests (teacher)
  getTests: () => api.get('/tests'),
  getTestGroups: () => api.get('/test-groups'),
  createTestGroup: (name) => api.post('/test-groups', { name }),
  renameTestGroup: (id, name) => api.put(`/test-groups/${id}`, { name }),
  deleteTestGroup: (id) => api.delete(`/test-groups/${id}`),
  moveTestToGroup: (id, groupId) => api.put(`/tests/${id}/group`, { group_id: groupId }),
  createTest: (data) => api.post('/tests', data),
  getTest: (id) => api.get(`/tests/${id}`),
  updateTest: (id, data) => api.put(`/tests/${id}`, data),
  updateTestParams: (id, data) => api.put(`/tests/${id}/params`, data),
  deleteTest: (id) => api.delete(`/tests/${id}`),
  activateTest: (id) => api.post(`/tests/${id}/activate`),
  deactivateTest: (id) => api.post(`/tests/${id}/deactivate`),
  extendTestTime: (id, timeLimit, minutes = 15) => api.post(`/tests/${id}/extend-time`, { minutes, expected_time_limit: timeLimit }),
  setTestCode: (id, code) => api.put(`/tests/${id}/code`, { code }),
  getTestResults: (id) => api.get(`/tests/${id}/results`),
  getPresence: id => api.get(`/tests/${id}/presence`),
  configurePresence: (id, data) => api.put(`/tests/${id}/presence`, data),
  getPresenceRooms: () => api.get('/presence/rooms'),
  getPresenceCandidates: id => api.get(`/attempts/${id}/presence/candidates`),
  bindPresence: (id, data) => api.post(`/attempts/${id}/presence/binding`, data),
  getPresenceEvents: id => api.get(`/attempts/${id}/presence/events`),
  reviewPresenceEvent: (id, note) => api.post(`/presence/events/${id}/review`, { note }),
  registerPresence: (id, data) => api.post(`/attempts/${id}/presence/clients`, data, { timeout: 8000 }),
  heartbeat: (id, data) => api.post(`/attempts/${id}/presence/heartbeat`, data, { timeout: 8000 }),
  startDeviceProof: (id,data) => api.post(`/attempts/${id}/presence/auto/start`,data,{timeout:10000}),
  finishDeviceProof: (id,data) => api.post(`/attempts/${id}/presence/auto/finish`,data,{timeout:10000}),
  getWrongAnswers: (testId, questionId, signal) => api.get(`/tests/${testId}/questions/${questionId}/wrong-answers`, { signal }),
  // Attempts
  joinTest: (code) => api.post('/join', { code }),
  getAttempt: (id) => api.get(`/attempts/${id}`),
  deleteAttempt: (id) => api.delete(`/attempts/${id}`),
  finishAttempt: (id) => api.post(`/attempts/${id}/finish`),
  recheckAttempt: (id) => api.post(`/attempts/${id}/recheck`),
  myAttempts: () => api.get('/my-attempts'),
  myAttemptResults: (id) => api.get(`/my-attempts/${id}/results`),
  // Answers
  saveAnswer: (id, value) => api.put(`/answers/${id}`, { value }),
  checkAnswer: (id) => api.post(`/answers/${id}/check`),
  recheckAnswer: (id) => api.post(`/answers/${id}/recheck`),
  gradeAnswer: (id, points, comment) => api.put(`/answers/${id}/grade`, { points, comment }),
  execution: id => api.get(`/answers/${id}/execution`),
  executionRun: id => api.get(`/executions/${id}`),
  executionHistory: id => api.get(`/answers/${id}/executions`),
  answerFiles: id => api.get(`/answers/${id}/files`),
  uploadAnswerFile: (id, file) => {const data=new FormData();data.append('file',file);return api.post(`/answers/${id}/files`,data,{timeout:120000})},
  taskFiles: url => api.get(url, {baseURL:''}),
  questionFiles: id => api.get(`/questions/${id}/files`),
  uploadQuestionFile: (id,data) => api.post(`/questions/${id}/files`,data,{timeout:120000}),
  deleteQuestionFile: (id,file) => api.delete(`/questions/${id}/files/${file}`),
}
