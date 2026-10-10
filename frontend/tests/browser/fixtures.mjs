export async function mockPlatform(page, role = 'student') {
  const question = { id: 1, order: 0, title: 'Ответ на вопрос', body: 'Введите ответ.', type: 'text_input',
    max_points: 5, check_type: 'exact', check_config: { answer: '42', custom_setting: 'keep' },
    ui_config: {}, allow_intermediate_check: true }
  const state = {
    fail: {}, saves: [], checks: 0, finishes: 0, reads: 0, testUpdates: [], onSave: null,
    test: { id: 1, title: 'Проверочный тест', description: '', code: 'ABC', is_active: false, time_limit: null,
      attempt_count: 0, variants: [{ id: 1, title: 'Вариант 1', questions: [question] }] },
    attempt: { id: 1, test_id: 1, test_title: 'Проверочный тест', user_name: 'Ученик', variant_title: 'Вариант 1',
      started_at: '2026-10-10T12:00:00Z', finished_at: null, time_left: null, time_deadline_at: null,
      is_checked: false, total_points: null, max_points: 5, questions: [question], topic_summary: [],
      answers: [{ id: 1, question_id: 1, value: null, points: null, check_state: 'pending', check_comment: null }] },
  }
  // Exercise HTTP fallback without a real Socket.IO server.
  await page.route('**/socket.io/**', route => route.abort())
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
    const failure = state.fail[`${method} ${path}`]
    if (failure) { await route.fulfill({ status: failure.status || 503, json: failure }); return }
    const body = method === 'GET' ? null : request.postDataJSON()
    if (path === '/api/me') return route.fulfill({ json: { id: 1, name: 'Пользователь', role } })
    if (path === '/api/answers/1' && method === 'PUT') {
      if (state.onSave && await state.onSave(route, body)) return
      state.saves.push(body.value)
      state.attempt.answers[0] = { ...state.attempt.answers[0], value: body.value, check_state: 'pending', points: null, check_comment: null }
      return route.fulfill({ json: { status: 'saved' } })
    }
    if (path === '/api/answers/1/check') {
      state.checks++
      Object.assign(state.attempt.answers[0], { check_state: 'intermediate', points: 5, check_comment: 'Верно' })
      return route.fulfill({ json: { status: 'checking' } })
    }
    if (path === '/api/answers/1/grade') {
      Object.assign(state.attempt.answers[0], { points: body.points, check_comment: body.comment, check_state: 'checked' })
      state.attempt.total_points = body.points
      state.attempt.is_checked = true
      state.attempt.topic_summary = [{ topic: 'Тема 1', points: body.points, max_points: 5, percent: body.points * 20 }]
      return route.fulfill({ json: { status: 'graded' } })
    }
    if (path === '/api/attempts/1/finish') {
      state.finishes++
      state.attempt.finished_at = new Date().toISOString()
      return route.fulfill({ json: { status: 'finished' } })
    }
    if (path === '/api/attempts/1' || path === '/api/my-attempts/1/results') {
      state.reads++
      return route.fulfill({ json: { ...state.attempt, server_time: new Date().toISOString() } })
    }
    if (path === '/api/my-attempts' || path === '/api/tests/1/attempts') return route.fulfill({ json: [state.attempt] })
    if (path === '/api/tests') return route.fulfill({ json: [state.test] })
    if (path === '/api/tests/1/activate' || path === '/api/tests/1/deactivate') {
      state.test.is_active = path.endsWith('/activate')
      return route.fulfill({ json: { status: 'ok' } })
    }
    if (path === '/api/tests/1/code') { state.test.code = body.code.toUpperCase(); return route.fulfill({ json: { code: state.test.code } }) }
    if (path === '/api/tests/1/params' || (path === '/api/tests/1' && method === 'PUT')) {
      state.testUpdates.push(body)
      Object.assign(state.test, body)
      return route.fulfill({ json: state.test })
    }
    if (path === '/api/tests/1') return route.fulfill({ json: state.test })
    return route.fulfill({ status: 404, json: { error: 'Unknown mock endpoint' } })
  })
  return state
}
