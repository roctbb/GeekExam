import { test, expect } from '@playwright/test'
import { mockPlatform } from './fixtures.mjs'

test('teacher can opt a single test into Guard from its access settings', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  await page.goto('/admin/tests/1')
  const access = page.getByRole('region', { name: 'Доступ к тесту' })
  const requireGuard = access.getByRole('checkbox', { name: 'Требовать авторизацию устройства в Guard' })
  await expect(requireGuard).not.toBeChecked()
  expect(state.roomReads).toBe(0)

  await requireGuard.check()
  const monitoring = access.getByRole('checkbox', { name: 'Учитывать связь во время теста' })
  await expect(monitoring).toBeChecked()
  await expect(monitoring).toBeDisabled()
  const room = access.getByRole('combobox', { name: 'Кабинет Guard' })
  const save = access.getByRole('button', { name: 'Сохранить', exact: true })
  await expect(save).toBeDisabled()
  await room.selectOption('room-a')
  await save.click()
  await expect.poll(() => state.presence.config).toMatchObject({ require_guard: true, room_id: 'room-a' })
  await page.reload()
  await expect(requireGuard).toBeChecked()
  await requireGuard.uncheck()
  await save.click()
  await expect.poll(() => state.presence.config.require_guard).toBe(false)
})

test('results show a journal icon only for attempts with confirmed Guard admission', async ({ page }) => {
  const state = await mockPlatform(page, 'teacher')
  state.presence.config.require_guard = true
  const finished_at = '2026-10-10T12:30:00Z'
  await page.route('**/api/tests/1/attempts', route => route.fulfill({ json: [
    { ...state.attempt, user_name: 'Обычная попытка', finished_at },
    { ...state.attempt, id: 2, user_name: 'Строгая попытка', finished_at },
  ] }))
  await page.route('**/api/tests/1/presence', route => route.fulfill({ json: {
    ...state.presence,
    attempts: [
      { attempt_id: 1, guard_admitted: false, exam: { state: 'finished' }, review_count: 0 },
      { attempt_id: 2, guard_admitted: true, exam: { state: 'finished' }, guard: { bound: true }, review_count: 2 },
    ],
  } }))
  await page.route('**/api/attempts/2/presence/events', route => route.fulfill({ json: { items: [] } }))

  await page.goto('/admin/tests/1/results')
  const ordinary = page.getByRole('row', { name: /Обычная попытка/ })
  const strict = page.getByRole('row', { name: /Строгая попытка/ })
  const journal = strict.getByRole('button', { name: 'Журнал связи · К проверке 2' })
  await expect(journal).toBeVisible()
  await expect(journal).toHaveText('2')
  await expect(ordinary.getByRole('button', { name: /Журнал связи/ })).toHaveCount(0)
  await expect(strict.getByRole('link', { name: 'Детали' })).toHaveAttribute('href', '/admin/attempts/2')
  await expect(strict.getByRole('button', { name: 'Перепроверить', exact: true })).toHaveText('')
  await expect(strict.getByRole('button', { name: 'Удалить', exact: true })).toHaveText('')
  await journal.hover()
  await expect(page.locator('.ge-icon-tooltip')).toHaveText('Журнал связи · К проверке 2')
  await page.keyboard.press('Tab')
  await journal.focus()
  await expect(page.locator('.ge-icon-tooltip')).toHaveText('Журнал связи · К проверке 2')
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Связь: Строгая попытка' })
  await expect(dialog.getByText('Событий пока нет.')).toBeVisible()
  await dialog.getByRole('button', { name: 'Закрыть журнал' }).click()
  await expect(dialog).not.toBeVisible()

  state.presence.config.require_guard = false
  await page.reload()
  await expect(journal).toBeVisible()
  await expect(ordinary.getByRole('button', { name: /Журнал связи/ })).toHaveCount(0)
})

test('Guard-protected join stays on the entry page until network authorization is verified', async ({ page }) => {
  await mockPlatform(page)
  let authorized = false
  let localProofs = 0
  await page.route('https://lan.example.test/v1/browser-proof', async route => {
    if (route.request().method() === 'POST') {
      expect(route.request().postDataJSON()).toEqual({ token: 'local-token' })
      localProofs++
    }
    await route.fulfill({ status: 200, headers: {
      'Access-Control-Allow-Origin': 'http://127.0.0.1:4178',
      'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': 'Content-Type',
    }, json: { state: 'proved' } })
  })
  await page.route('**/api/join', async route => {
    const body = route.request().postDataJSON()
    if (!body.guard_ticket) {
      return route.fulfill({ status: 202, json: { guard_proof: {
        ticket: 'signed-ticket', items: [{ id: 'proof', token: 'local-token', url: 'https://lan.example.test/v1/browser-proof' }],
      } } })
    }
    expect(body).toEqual({ code: 'ABC', guard_ticket: 'signed-ticket', proof_ids: ['proof'] })
    if (authorized) return route.fulfill({ status: 201, json: { attempt_id: 1 } })
    return route.fulfill({ status: 403, json: { error: 'Авторизуйте это устройство в сети кабинета через Guard.' } })
  })

  await page.goto('/join')
  await page.getByPlaceholder('КОД').fill('ABC')
  await page.getByRole('button', { name: 'Начать' }).click()
  await expect(page.getByRole('alert')).toContainText('Авторизуйте это устройство')
  await expect(page).toHaveURL(/\/join$/)
  authorized = true
  await page.getByRole('button', { name: 'Начать' }).click()
  await expect(page).toHaveURL(/\/attempt\/1$/)
  expect(localProofs).toBe(2)
})
