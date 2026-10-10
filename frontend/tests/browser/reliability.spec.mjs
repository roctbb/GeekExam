import { test, expect } from '@playwright/test'
import { mockPlatform } from './fixtures.mjs'

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
  await page.getByRole('link', { name: 'Результаты', exact: true }).click()
  await expect(page).toHaveURL(/\/my-results$/)
  expect(state.saves.at(-1)).toEqual({ text: 'Последняя правка' })
  expect(await page.evaluate(() => window.navigationMarker)).toBe('same page')
})

test('failed saves block leaving and a reload can recover the local answer', async ({ page }) => {
  const state = await mockPlatform(page)
  state.fail['PUT /api/answers/1'] = { error: 'Нет связи' }
  await page.goto('/attempt/1')
  await page.getByRole('textbox', { name: 'Ответ на вопрос' }).fill('Черновик после сбоя')
  await page.getByRole('link', { name: 'Результаты', exact: true }).click()
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

test('editor guards changes, retains unsaved questions after saving params, and restores after reload', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  await page.goto('/admin/tests/1/edit')
  await page.getByRole('textbox', { name: 'Название', exact: true }).fill('Новое название')
  await page.getByRole('textbox', { name: 'Текст задания (Markdown)' }).fill('Несохранённое условие')
  await page.getByRole('button', { name: 'Сохранить параметры' }).click()
  await expect(page.getByText('Параметры теста сохранены')).toBeVisible()
  await expect(page.getByText('Есть несохранённые изменения')).toBeVisible()
  page.once('dialog', dialog => dialog.dismiss())
  await page.getByRole('link', { name: '← К тесту' }).click()
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
