import { test, expect } from '@playwright/test'
import { mockPlatform, switchTheme, userMenuButton } from './fixtures.mjs'

const root = page => page.locator('html')

test('system appearance is followed until the user chooses a theme, and the choice survives reload', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' })
  await mockPlatform(page)
  await page.goto('/join')
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'light')
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'dark')
  await switchTheme(page)
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'light')
  await page.reload()
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'light')
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(248, 250, 252)')
  await page.emulateMedia({ colorScheme: 'light' })
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'light')
  await switchTheme(page)
  await page.getByRole('link', { name: 'Мои результаты', exact: true }).click()
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'dark')
  await page.reload()
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'dark')
})

for (const theme of ['light', 'dark']) {
  test(`saved ${theme} theme is applied before the application loads`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme === 'light' ? 'dark' : 'light' })
    await page.addInitScript(theme => localStorage.setItem('geekexam:theme', theme), theme)
    await page.route('**/src/main.js', route => route.abort())
    await page.goto('/join')
    await expect(root(page)).toHaveAttribute('data-bs-theme', theme)
    await expect(page.locator('#app')).toBeEmpty()
  })
}

test('theme selection is synchronized between open tabs', async ({ page, context }) => {
  await mockPlatform(page)
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/join')
  const other = await context.newPage()
  await other.emulateMedia({ colorScheme: 'light' })
  await mockPlatform(other)
  await other.goto('/join')
  await switchTheme(page)
  await expect(root(other)).toHaveAttribute('data-bs-theme', 'dark')
  await other.evaluate(() => localStorage.removeItem('geekexam:theme'))
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'light')
})

test('unavailable browser storage does not prevent switching themes', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.emulateMedia({ colorScheme: 'light' })
  await page.addInitScript(() => Object.defineProperty(window, 'localStorage', {
    get() { throw new DOMException('Storage is disabled', 'SecurityError') },
  }))
  await mockPlatform(page)
  await page.goto('/join')
  await switchTheme(page)
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'dark')
  await switchTheme(page)
  await expect(root(page)).toHaveAttribute('data-bs-theme', 'light')
  expect(errors).toEqual([])
})

test('switching the code editor theme preserves the answer and undo history', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.emulateMedia({ colorScheme: 'light' })
  const state = await mockPlatform(page)
  Object.assign(state.attempt.questions[0], {
    type: 'code_input', check_type: 'checker',
    body: 'Пример:\n\n```python\nprint(42)\n```',
    ui_config: { lang: 'python', starter_code: 'print(42)' },
  })
  await page.goto('/attempt/1')
  const editor = page.locator('.cm-content')
  await editor.fill('print(43)')
  await switchTheme(page)
  await expect(editor).toHaveText('print(43)')
  await expect(page.locator('.cm-editor')).toHaveCSS('background-color', 'rgb(27, 35, 48)')
  await editor.press('ControlOrMeta+z')
  await expect(editor).toHaveText('print(42)')
  await switchTheme(page)
  await expect(page.locator('.cm-editor')).toHaveCSS('background-color', 'rgb(247, 249, 252)')
  expect(errors).toEqual([])
})

test('dark teacher and student surfaces stay readable and fit mobile widths', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  const state = await mockPlatform(page, 'teacher')
  state.test.is_active = true
  state.attempt.questions[0].body = 'Текст с `кодом`.\n\n```python\nprint(42)\n```'
  await page.goto('/admin/tests')
  await expect(page.getByRole('cell', { name: 'Активен', exact: true })).toBeVisible()
  await expect(page.locator('.table tbody td').first()).not.toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await page.screenshot({ path: 'test-results/theme-teacher-dark.png', fullPage: true, animations: 'disabled' })
  for (const width of [375, 320]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/attempt/1')
  await expect(page.locator('.card')).not.toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(page.getByRole('textbox', { name: 'Ответ на вопрос' })).not.toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await page.screenshot({ path: 'test-results/theme-student-dark.png', fullPage: true, animations: 'disabled' })
  for (const width of [375, 320]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect(userMenuButton(page)).toBeVisible()
  }
  await page.screenshot({ path: 'test-results/theme-student-dark-mobile.png', fullPage: true, animations: 'disabled' })
  await switchTheme(page)
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(248, 250, 252)')
  await page.screenshot({ path: 'test-results/theme-student-light-mobile.png', fullPage: true, animations: 'disabled' })
})
