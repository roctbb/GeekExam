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
