import { test, expect } from '@playwright/test'
import { mockPlatform, openUserMenu } from './fixtures.mjs'

test.beforeEach(async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.runtimeErrors = errors
})
test.afterEach(async ({ page }) => { expect(page.runtimeErrors).toEqual([]) })

test('menu navigation flushes the last edit and keeps the SPA alive', async ({ page }) => {
  const state = await mockPlatform(page)
  await page.goto('/attempt/1')
  await page.getByRole('textbox', { name: 'Ответ на вопрос' }).fill('Последняя правка')
  await page.evaluate(() => { window.navigationMarker = 'same page' })
  await openUserMenu(page)
  await page.getByRole('menuitem', { name: 'Мои результаты', exact: true }).click()
  await expect(page).toHaveURL(/\/my-results$/)
  expect(state.saves.at(-1)).toEqual({ text: 'Последняя правка' })
  expect(await page.evaluate(() => window.navigationMarker)).toBe('same page')
})

test('failed saves block leaving and a reload can recover the local answer', async ({ page }) => {
  const state = await mockPlatform(page)
  state.fail['PUT /api/answers/1'] = { error: 'Нет связи' }
  await page.goto('/attempt/1')
  await page.getByRole('textbox', { name: 'Ответ на вопрос' }).fill('Черновик после сбоя')
  await openUserMenu(page)
  await page.getByRole('menuitem', { name: 'Мои результаты', exact: true }).click()
  await expect(page).toHaveURL(/\/attempt\/1$/)
  await expect(page.getByText('Не удалось сохранить ответы. Повторите сохранение перед выходом.')).toBeVisible()
  page.once('dialog', dialog => dialog.accept())
  await page.reload()
  await expect(page.getByRole('button', { name: 'Восстановить ответы' })).toBeVisible()
  delete state.fail['PUT /api/answers/1']
  await page.getByRole('button', { name: 'Восстановить ответы' }).click()
  await expect(page.getByRole('textbox', { name: 'Ответ на вопрос' })).toHaveValue('Черновик после сбоя')
  await expect.poll(() => state.saves.at(-1)?.text).toBe('Черновик после сбоя')
  await expect.poll(() => page.evaluate(() => localStorage.getItem('geekexam:answers:1:1'))).toBeNull()
})

test('last-seconds editing sends immediately and an expired answer remains recoverable', async ({ page }) => {
  const state = await mockPlatform(page)
  state.attempt.time_deadline_at = new Date(Date.now() + 8000).toISOString()
  state.attempt.time_left = 8
  let saveStarted = false
  state.onSave = async (route) => {
    saveStarted = true
    state.attempt.finished_at = new Date().toISOString()
    await route.fulfill({ status: 422, json: { error: 'Тест уже завершён', error_code: 'attempt_finished' } })
    return true
  }
  await page.goto('/attempt/1')
  await page.getByRole('textbox', { name: 'Ответ на вопрос' }).fill('Ответ у дедлайна')
  await expect.poll(() => saveStarted, { timeout: 600 }).toBe(true)
  await expect(page.getByRole('textbox', { name: 'Ответ на вопрос' })).not.toBeEditable()
  await expect(page.getByRole('button', { name: 'Открыть результаты' })).toBeVisible()
  expect(JSON.parse(await page.evaluate(() => localStorage.getItem('geekexam:answers:1:1')))[1].value.text).toBe('Ответ у дедлайна')
})

test('text questions expose intermediate checking and send the latest value', async ({ page }) => {
  const state = await mockPlatform(page)
  await page.goto('/attempt/1')
  await page.getByRole('textbox', { name: 'Ответ на вопрос' }).fill('42')
  await page.getByRole('button', { name: 'Проверить', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Ответ проверен' })).toBeDisabled()
  expect(state.saves.at(-1)).toEqual({ text: '42' })
  expect(state.checks).toBe(1)
})

test('checking untouched starter code saves the code actually displayed', async ({ page }) => {
  const state = await mockPlatform(page)
  Object.assign(state.attempt.questions[0], { type: 'code_input', check_type: 'checker',
    ui_config: { lang: 'python', starter_code: 'print(42)' } })
  await page.goto('/attempt/1')
  await expect(page.locator('.cm-content')).toContainText('print(42)')
  await page.getByRole('button', { name: 'Проверить', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Ответ проверен' })).toBeDisabled()
  expect(state.saves.at(-1)).toEqual({ code: 'print(42)', lang: 'python' })
})

test('result page recovers completion with no websocket event', async ({ page }) => {
  const state = await mockPlatform(page)
  state.attempt.finished_at = '2026-10-10T12:30:00Z'
  await page.goto('/my-results/1')
  await expect(page.getByText('Проверяется', { exact: true })).toBeVisible()
  state.attempt.is_checked = true
  state.attempt.total_points = 5
  state.attempt.answers[0].check_state = 'checked'
  state.attempt.answers[0].points = 5
  await expect(page.locator('.ge-score')).toHaveText('5 / 5', { timeout: 8000 })
})

test('teacher reviews answer proportions and reveals answers for every variant', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  await page.goto('/admin/tests/1')
  await page.getByRole('link', { name: 'Результаты', exact: true }).click()
  await expect(page.getByText('Пока нет оценённых ответов в проверенных работах.')).toBeVisible()
  await expect(page.getByText('В процессе', { exact: true })).toBeVisible()

  Object.assign(state.attempt, { finished_at: '2026-10-10T12:30:00Z', is_checked: true, total_points: 4 })
  state.questionReview = [
    { order: 0, title: 'Условия', variants: [
      { question_id: 1, title: 'Условия', variant_title: 'Вариант 1', correct_count: 15, incorrect_count: 5, skipped_count: 0 },
    ] },
    { order: 1, title: 'Циклы', variants: [
      { question_id: 2, title: 'Циклы', variant_title: 'Вариант 1', correct_count: 1, incorrect_count: 2, skipped_count: 1 },
      { question_id: 4, title: 'Циклы', variant_title: 'Вариант 2', correct_count: 3, incorrect_count: 2, skipped_count: 0 },
    ] },
  ]
  state.reviewQuestions = {
    0: [{ id: 1, type: 'text_input', body: 'Условие с if', check_config: { answer: 'True' } }],
    1: [
      { id: 2, type: 'text_input', body: 'Цикл в первом варианте', check_config: { answer: '3' } },
      { id: 4, type: 'text_input', body: 'Цикл во втором варианте', check_config: { answer: '6' } },
    ],
  }
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  const summary = page.getByRole('group', { name: 'Задания по доле ответов с ошибкой' })
  const firstQuestion = summary.getByRole('button').first()
  await expect(firstQuestion).toContainText('2. Циклы')
  await expect(firstQuestion).toContainText('50% / 50%')
  await expect(firstQuestion).toHaveAttribute('aria-pressed', 'true')
  await expect(summary.getByRole('button', { name: /Условия/ })).toContainText('75% / 25%')
  await expect(page.getByText('4/5', { exact: true })).toBeVisible()

  const variants = page.getByRole('region', { name: '2. Циклы' })
  await expect(variants.getByRole('article')).toHaveCount(2)
  await expect(variants.getByText('Цикл в первом варианте')).toBeVisible()
  await expect(variants.getByText('Цикл во втором варианте')).toBeVisible()
  await expect(variants.getByText('1 верно · 2 с ошибкой · Пропустили 1')).toBeVisible()
  await expect(variants.getByText('Ожидаемый ответ')).toHaveCount(0)

  const wrongAnswersUrl = '/api/tests/1/questions/2/wrong-answers'
  state.fail[`GET ${wrongAnswersUrl}`] = { status: 503 }
  state.wrongAnswers[4] = [{ preview: 'range(1, 10)', count: 2, example_attempt_id: 1 }]
  await variants.getByRole('button', { name: 'Показать ответы' }).click()
  await expect(variants.getByText('Ожидаемый ответ')).toHaveCount(2)
  await expect(variants.getByText('Не удалось загрузить ответы.')).toBeVisible()
  await expect(variants.getByText('range(1, 10)', { exact: true })).toBeVisible()

  delete state.fail[`GET ${wrongAnswersUrl}`]
  state.wrongAnswers[2] = [{ preview: 'range(1, 5)', count: 2, example_attempt_id: 1 }]
  await variants.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(variants.getByText('range(1, 5)', { exact: true })).toBeVisible()
  await expect(variants.getByRole('link', { name: 'Пример работы' }).first()).toHaveAttribute('href', '/admin/attempts/1')

  await page.setViewportSize({ width: 390, height: 844 })
  const panels = await variants.getByRole('article').evaluateAll(items => items.map(item => item.getBoundingClientRect()))
  expect(panels[1].x).toBe(panels[0].x)
  expect(panels[1].top).toBeGreaterThan(panels[0].bottom)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)

  await summary.getByRole('button', { name: /Условия/ }).click()
  const nextTask = page.getByRole('region', { name: '1. Условия' })
  await expect(nextTask.getByText('Условие с if')).toBeVisible()
  await expect(nextTask.getByRole('button', { name: 'Показать ответы' })).toHaveAttribute('aria-expanded', 'false')
})

test('editor guards changes, retains unsaved questions after saving params, and restores after reload', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  await page.goto('/admin/tests/1/edit')
  await page.getByRole('textbox', { name: 'Название', exact: true }).fill('Новое название')
  await page.getByRole('textbox', { name: 'Текст задания (Markdown)' }).fill('Несохранённое условие')
  await page.getByRole('button', { name: 'Сохранить параметры' }).click()
  await expect(page.getByText('Параметры теста сохранены')).toBeVisible()
  await expect(page.getByText('Есть несохранённые изменения')).toBeVisible()
  page.once('dialog', dialog => dialog.dismiss())
  await page.getByRole('link', { name: 'К тесту', exact: true }).click()
  await expect(page).toHaveURL(/\/edit$/)
  page.once('dialog', dialog => dialog.accept())
  await page.reload()
  await page.getByRole('button', { name: 'Восстановить черновик' }).click()
  await expect(page.getByRole('textbox', { name: 'Текст задания (Markdown)' })).toHaveValue('Несохранённое условие')
  await page.getByRole('button', { name: 'Сохранить вопросы' }).click()
  await expect(page.getByText('Все изменения сохранены')).toBeVisible()
  expect(state.testUpdates.at(-1).variants[0].questions[0].body).toBe('Несохранённое условие')
})

test('friendly config fields preserve advanced settings', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  await page.goto('/admin/tests/1/edit')
  await page.getByRole('textbox', { name: 'Правильный ответ', exact: true }).fill('43')
  await page.getByRole('button', { name: 'Сохранить вопросы' }).click()
  await expect(page.getByText('Вопросы сохранены')).toBeVisible()
  expect(state.testUpdates.at(-1).variants[0].questions[0].check_config).toEqual({ answer: '43', custom_setting: 'keep' })
})

test('failed initial editor load offers retry without exposing empty editable fields', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  state.fail['GET /api/tests/1'] = { error: 'Временная ошибка' }
  await page.goto('/admin/tests/1/edit')
  await expect(page.getByRole('button', { name: 'Повторить' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Сохранить вопросы' })).toHaveCount(0)
  delete state.fail['GET /api/tests/1']
  await page.getByRole('button', { name: 'Повторить' }).click()
  await expect(page.getByRole('textbox', { name: 'Название', exact: true })).toHaveValue('Проверочный тест')
})

test('activation errors are visible and a subsequent retry succeeds', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  state.fail['POST /api/tests/1/activate'] = { status: 422, error: 'В варианте нет вопросов' }
  await page.goto('/admin/tests/1')
  await page.getByRole('button', { name: 'Запустить', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('В варианте нет вопросов')
  delete state.fail['POST /api/tests/1/activate']
  await page.getByRole('button', { name: 'Запустить', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Остановить', exact: true })).toBeEnabled()
})

test('teacher grading refreshes the topic summary', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  Object.assign(state.attempt, { finished_at: '2026-10-10T12:30:00Z', is_checked: true, total_points: 0,
    topic_summary: [{ topic: 'Тема 1', points: 0, max_points: 5, percent: 0 }] })
  Object.assign(state.attempt.answers[0], { check_state: 'checked', points: 0 })
  await page.goto('/admin/attempts/1')
  await page.getByRole('spinbutton', { name: 'Баллы' }).fill('4')
  await page.getByRole('textbox', { name: 'Комментарий преподавателя' }).fill('Частично верно')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(page.getByRole('row', { name: /Тема 1/ })).toContainText('4 / 5')
  await expect(page.getByRole('row', { name: /Тема 1/ })).toContainText('80%')
})

test('background refresh preserves a teachers unsent grade and comment', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  state.attempt.finished_at = '2026-10-10T12:30:00Z'
  state.attempt.questions[0].check_type = 'manual'
  await page.goto('/admin/attempts/1')
  await page.getByRole('spinbutton', { name: 'Баллы' }).fill('3')
  await page.getByRole('textbox', { name: 'Комментарий преподавателя' }).fill('Ещё редактирую')
  const reads = state.reads
  Object.assign(state.attempt.answers[0], { points: 1, check_comment: 'Серверный комментарий' })
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect.poll(() => state.reads).toBeGreaterThan(reads)
  await expect(page.getByRole('spinbutton', { name: 'Баллы' })).toHaveValue('3')
  await expect(page.getByRole('textbox', { name: 'Комментарий преподавателя' })).toHaveValue('Ещё редактирую')
})

test('timestamps display local Moscow time', async ({ page }) => {
  await mockPlatform(page)
  await page.goto('/my-results')
  await expect(page.getByRole('cell', { name: '10.10.2026, 15:00:00' })).toBeVisible()
})

test('teacher actions fit a narrow mobile screen', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await mockPlatform(page, 'teacher')
  await page.goto('/admin/tests/1')
  await expect(page.getByRole('button', { name: 'Запустить', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/test-detail-mobile.png', fullPage: true, animations: 'disabled' })
})

test('auto-finish freezes input and retains a last save rejected at the deadline', async ({ page }) => {
  const state = await mockPlatform(page)
  state.attempt.time_deadline_at = new Date(Date.now() + 3000).toISOString()
  state.attempt.time_left = 3
  state.onSave = async route => {
    await new Promise(resolve => setTimeout(resolve, 3500))
    await route.fulfill({ status: 422, json: { error: 'Тест уже завершён', error_code: 'attempt_finished' } })
    return true
  }
  await page.goto('/attempt/1')
  await page.getByRole('textbox', { name: 'Ответ на вопрос' }).fill('Последние секунды')
  await expect(page.getByRole('textbox', { name: 'Ответ на вопрос' })).not.toBeEditable({ timeout: 5000 })
  await expect.poll(() => state.finishes, { timeout: 8000 }).toBe(1)
  await expect(page.getByRole('textbox', { name: 'Ответ на вопрос' })).toHaveValue('Последние секунды')
  await expect(page.getByRole('button', { name: 'Открыть результаты' })).toBeVisible()
})

test('a stalled save times out and can be retried', async ({ page }) => {
  test.setTimeout(25000)
  const state = await mockPlatform(page)
  const hang = () => new Promise(() => {})
  await page.route('**/api/answers/1', hang)
  await page.goto('/attempt/1')
  await page.getByRole('textbox', { name: 'Ответ на вопрос' }).fill('Медленный запрос')
  await expect(page.getByRole('button', { name: 'Повторить сохранение' })).toBeVisible({ timeout: 18000 })
  await page.unroute('**/api/answers/1', hang)
  await page.getByRole('button', { name: 'Повторить сохранение' }).click()
  await expect.poll(() => state.saves.at(-1)?.text).toBe('Медленный запрос')
})
