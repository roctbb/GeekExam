import test from 'node:test'
import assert from 'node:assert/strict'
import { createAttemptTimer } from '../src/utils/attemptTimer.js'

test('55 to 70 minutes adds 15 to remaining time, preserving already elapsed time', () => {
  let monotonic = 0
  const timer = createAttemptTimer(() => monotonic)
  timer.sync({ server_time: '2026-10-22T06:40:00Z', time_deadline_at: '2026-10-22T06:55:00Z' })
  assert.equal(timer.remaining(), 15 * 60)
  monotonic += 10000
  assert.equal(timer.remaining(), 15 * 60 - 10)
  timer.sync({ server_time: '2026-10-22T06:40:10Z', time_deadline_at: '2026-10-22T07:10:00Z' })
  assert.equal(timer.remaining(), 30 * 60 - 10)
  // Date.now is deliberately irrelevant to the elapsed time calculation.
  const original = Date.now
  try {
    Date.now = () => original() - 55 * 60000
    monotonic += 1000
    assert.equal(timer.remaining(), 30 * 60 - 11)
  } finally { Date.now = original }
})

test('legacy countdown, explicit offsets, unlimited and finished attempts', () => {
  let now = 100
  const timer = createAttemptTimer(() => now)
  timer.sync({ time_left: 3 })
  now += 4000
  assert.equal(timer.remaining(), 0)
  timer.sync({ server_time: '2026-10-22T09:40:00+03:00', time_deadline_at: '2026-10-22T06:55:00' })
  assert.equal(timer.remaining(), 900)
  timer.sync({ time_left: null })
  assert.equal(timer.remaining(), null)
  timer.sync({ time_left: 300, finished_at: 'finished' })
  assert.equal(timer.remaining(), null)
})
