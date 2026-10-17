import { test, expect } from '@playwright/test'
import { mockPlatform, openUserMenu, userMenuButton } from './fixtures.mjs'

const avatarPng = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=', 'base64')

test('profile avatar loads from the API URL without exposing the page referrer', async ({ page }) => {
  const state = await mockPlatform(page)
  state.user.avatar_url = 'https://avatars.example.test/me.png?v=123'
  let avatarRequest
  await page.route('https://avatars.example.test/**', route => {
    avatarRequest = route.request()
    return route.fulfill({ contentType: 'image/png', body: avatarPng })
  })
  await page.goto('/join')
  const avatar = page.locator('.ge-avatar img')
  await expect(avatar).toBeVisible()
  await expect.poll(() => avatar.evaluate(image => image.naturalWidth)).toBeGreaterThan(0)
  expect(avatarRequest.url()).toBe(state.user.avatar_url)
  expect(avatarRequest.headers().referer).toBeUndefined()
})

test('unavailable avatar falls back to initials and a new URL can load on the next visit', async ({ page }) => {
  const state = await mockPlatform(page)
  state.user.name = 'Бородин Ростислав'
  state.user.avatar_url = 'https://avatars.example.test/missing.png'
  await page.route('https://avatars.example.test/**', route => route.request().url().includes('missing')
    ? route.fulfill({ status: 404 }) : route.fulfill({ contentType: 'image/png', body: avatarPng }))
  await page.goto('/join')
  await expect(page.locator('.ge-avatar')).toHaveText('БР')
  await expect(page.locator('.ge-avatar img')).toHaveCount(0)
  state.user.avatar_url = 'https://avatars.example.test/me.png?v=124'
  await page.reload()
  await expect.poll(() => page.locator('.ge-avatar img').evaluate(image => image.naturalWidth)).toBeGreaterThan(0)
})

for (const role of ['student', 'teacher']) {
  test(`${role} account menu exposes the right pages and the home shortcut opens personal results`, async ({ page }) => {
    const state = await mockPlatform(page, role)
    state.user.name = 'Бородин Ростислав Алексеевич'
    await page.goto('/join')
    await expect(userMenuButton(page)).toBeVisible()
    await expect(page.locator('.ge-avatar')).toHaveText('БР')
    await expect(page.getByRole('menu')).toHaveCount(0)
    const menu = await openUserMenu(page)
    await expect(menu.getByRole('menuitem', { name: 'Тесты', exact: true })).toHaveCount(role === 'teacher' ? 1 : 0)
    await expect(menu.getByRole('menuitem', { name: 'Мои результаты' })).toBeVisible()
    if (role === 'teacher') {
      await menu.getByRole('menuitem', { name: 'Тесты', exact: true }).click()
      await expect(page).toHaveURL(/\/admin\/tests$/)
      await expect(page.getByRole('menu')).toHaveCount(0)
      await page.getByRole('link', { name: 'GeekExam' }).click()
    } else await userMenuButton(page).press('Escape')
    await page.getByRole('link', { name: 'Мои результаты', exact: true }).click()
    await expect(page).toHaveURL(/\/my-results$/)
    await expect(page.getByRole('heading', { name: 'Мои результаты' })).toBeVisible()
  })
}

test('account menu supports keyboard navigation, escape, tab and outside clicks', async ({ page }) => {
  await mockPlatform(page, 'teacher')
  await page.goto('/join')
  const trigger = userMenuButton(page)
  await trigger.press('ArrowDown')
  await expect(page.getByRole('menuitem', { name: 'Тесты', exact: true })).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(page.getByRole('menuitem', { name: 'Мои результаты' })).toBeFocused()
  await page.keyboard.press('End')
  await expect(page.getByRole('menuitem', { name: 'Выйти' })).toBeFocused()
  await page.keyboard.press('Home')
  await expect(page.getByRole('menuitem', { name: 'Тесты', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('menu')).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await trigger.press('ArrowUp')
  await expect(page.getByRole('menuitem', { name: 'Выйти' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('menu')).toHaveCount(0)
  await expect(page.getByPlaceholder('КОД')).toBeFocused()
  await trigger.click()
  await page.getByRole('heading', { name: 'Войти в тест' }).click()
  await expect(page.getByRole('menu')).toHaveCount(0)
})

test('long names and open account menus fit narrow screens', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  state.user.name = 'Оченьдлиннаяфамилия Оченьдлинноеимя Оченьдлинноеотчество'
  await page.goto('/join')
  for (const width of [375, 320]) {
    await page.setViewportSize({ width, height: 700 })
    const menu = await openUserMenu(page)
    const bounds = await menu.boundingBox()
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await userMenuButton(page).press('Escape')
  }
})

test('logout preserves unsaved answers when saving fails, then flushes before ending the session', async ({ page }) => {
  const state = await mockPlatform(page)
  state.fail['PUT /api/answers/1'] = { error: 'Нет связи' }
  let logouts = 0
  await page.route('**/auth/logout', route => { logouts++; return route.fulfill({ json: { status: 'ok' } }) })
  await page.goto('/attempt/1')
  await page.getByRole('textbox', { name: 'Ответ на вопрос' }).fill('Сохранить перед выходом')
  await openUserMenu(page)
  await page.getByRole('menuitem', { name: 'Выйти' }).click()
  await expect(page.getByText('Не удалось сохранить ответы. Повторите сохранение перед выходом.')).toBeVisible()
  expect(logouts).toBe(0)
  await expect(page.getByRole('textbox', { name: 'Ответ на вопрос' })).toHaveValue('Сохранить перед выходом')
  delete state.fail['PUT /api/answers/1']
  await openUserMenu(page)
  await page.getByRole('menuitem', { name: 'Выйти' }).click()
  await expect(page).toHaveURL(/\/join$/)
  await expect(page.getByRole('link', { name: 'Войти', exact: true })).toBeVisible()
  expect(state.saves.at(-1)).toEqual({ text: 'Сохранить перед выходом' })
  expect(logouts).toBe(1)
})
