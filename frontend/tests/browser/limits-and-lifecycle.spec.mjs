import { test, expect } from '@playwright/test'
import { mockPlatform } from './fixtures.mjs'

test('pasting a huge short answer cannot send an oversized value to autosave', async ({ page }) => {
  const state = await mockPlatform(page)
  Object.assign(state.attempt.questions[0], { type: 'multi_input',
    ui_config: { fields: [{ name: 'second', label: 'Второе число' }] } })
  await page.goto('/attempt/1')
  const input = page.getByRole('textbox', { name: 'Второе число', exact: true })
  await expect(input).toHaveAttribute('maxlength', '1000')
  await input.focus()
  await page.keyboard.insertText('x'.repeat(100000))
  await expect(input).toHaveValue('x'.repeat(1000))
  await expect.poll(() => state.saves.length).toBeGreaterThan(0)
  expect(state.saves.every(value => value.second.length <= 1000)).toBe(true)
})

test('oversized code paste is rejected while keeping the previous code editable', async ({ page }) => {
  const state = await mockPlatform(page)
  Object.assign(state.attempt.questions[0], { type: 'code_input', ui_config: { lang: 'cpp', starter_code: 'int main() {}' } })
  await page.goto('/attempt/1')
  const editor = page.locator('.cm-content')
  await expect(editor).toHaveText('int main() {}')
  await editor.focus()
  await page.keyboard.insertText('x'.repeat(50001))
  await expect(page.getByRole('alert')).toContainText('50000')
  await expect(editor).toHaveText('int main() {}')
  expect(state.saves).toEqual([])
  await page.keyboard.insertText('a')
  await expect.poll(() => state.saves.length).toBeGreaterThan(0)
  expect(state.saves.at(-1).code.length).toBeLessThan(50000)
})

test('an oversized legacy server answer is not inserted into a native text input', async ({ page }) => {
  const state = await mockPlatform(page)
  Object.assign(state.attempt.questions[0], { type: 'multi_input',
    ui_config: { fields: [{ name: 'second', label: 'Второе число' }] } })
  state.attempt.answers[0].value = { second: 'x'.repeat(100000) }
  await page.goto('/attempt/1')
  await expect(page.getByRole('alert')).toContainText('Сохранённый ответ слишком большой')
  await expect(page.getByRole('textbox', { name: 'Второе число' })).toHaveCount(0)
})

test('compilation error is visible from HTTP and after reload with a retry button', async ({ page }) => {
  const state = await mockPlatform(page)
  Object.assign(state.attempt.questions[0], { type: 'code_input', ui_config: { lang: 'cpp' } })
  Object.assign(state.attempt.answers[0], { value: { code: 'broken', lang: 'cpp' },
    check_state: 'error', check_comment: "Ошибка компиляции\nmain.cpp:4: expected ';'" })
  await page.goto('/attempt/1')
  await expect(page.getByText("main.cpp:4: expected ';'", { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Проверить', exact: true })).toBeEnabled()
  await page.reload()
  await expect(page.getByText("main.cpp:4: expected ';'", { exact: false })).toBeVisible()
})

test('teacher adds exactly 15 minutes and a stopped student is redirected without a socket event', async ({ browser }) => {
  const teacher = await browser.newPage(), student = await browser.newPage()
  try {
    const teacherState = await mockPlatform(teacher, 'teacher')
    teacherState.test.time_limit = 55
    teacherState.test.is_active = true
    const studentState = await mockPlatform(student)
    studentState.attempt = teacherState.attempt
    await teacher.goto('/admin/tests/1')
    await student.goto('/attempt/1')
    await teacher.getByRole('button', { name: '+15 минут', exact: true }).click()
    await expect(teacher.getByText('70 мин', { exact: true })).toBeVisible()
    expect(teacherState.test.time_limit).toBe(70)
    teacher.once('dialog', dialog => dialog.accept())
    await teacher.getByRole('button', { name: 'Остановить', exact: true }).click()
    await expect(teacher.getByRole('status')).toHaveText('Тест остановлен, текущие попытки завершены')
    await expect(student).toHaveURL(/\/my-results\/1$/, { timeout: 8000 })
  } finally { await teacher.close(); await student.close() }
})

test('server deadline extension changes the live countdown by fifteen minutes', async ({ page }) => {
  const state = await mockPlatform(page)
  state.attempt.time_deadline_at = new Date(Date.now() + 15 * 60000).toISOString()
  state.attempt.time_left = 900
  await page.goto('/attempt/1')
  await expect(page.locator('.ge-timer')).toContainText(/1[45]:\d\d/)
  state.attempt.time_deadline_at = new Date(Date.now() + 30 * 60000).toISOString()
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(page.locator('.ge-timer')).toContainText(/(29|30):\d\d/)
})
