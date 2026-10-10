import test from 'node:test'
import assert from 'node:assert/strict'
import { parseApiDate, formatDateTime } from '../src/utils/dates.js'

test('UTC, legacy naive UTC and explicit offsets denote the same instant', () => {
  const utc = parseApiDate('2026-10-10T12:00:00Z')
  assert.equal(parseApiDate('2026-10-10T12:00:00').getTime(), utc.getTime())
  assert.equal(parseApiDate('2026-10-10T15:00:00+03:00').getTime(), utc.getTime())
  assert.equal(utc.toLocaleTimeString('ru-RU', { timeZone: 'Europe/Moscow' }), '15:00:00')
  assert.equal(formatDateTime(null), '')
  assert.equal(formatDateTime('bad-date'), '')
})
