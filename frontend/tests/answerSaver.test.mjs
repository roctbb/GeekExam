import test from 'node:test'
import assert from 'node:assert/strict'
import { createAnswerSaver } from '../src/utils/answerSaver.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('failed saves remain pending and can be retried without typing again', async () => {
  let fail = true
  const saved = [], states = []
  const saver = createAnswerSaver(async (id, value) => {
    if (fail) throw Error('offline')
    saved.push([id, value])
  }, state => states.push(state))
  try {
    saver.schedule(1, { text: 'Ответ' })
    await assert.rejects(saver.flush(), /offline/)
    assert.equal(saver.hasPending(), true)
    assert.equal(states.at(-1), 'error')
    fail = false
    await saver.flush()
    assert.deepEqual(saved, [[1, { text: 'Ответ' }]])
    assert.equal(states.at(-1), 'saved')
    assert.equal(saver.hasPending(), false)
  } finally { saver.dispose() }
})

test('flush waits for in-flight writes and serializes newer edits', async () => {
  const requests = []
  const saver = createAnswerSaver((id, value) => {
    const request = deferred()
    requests.push({ id, value, ...request })
    return request.promise
  })
  try {
    saver.schedule(1, { text: 'Старый' })
    const firstFlush = saver.flush()
    saver.schedule(1, { text: 'Новый' })
    let completed = false
    const finishFlush = saver.flush().then(() => { completed = true })
    assert.equal(requests.length, 1)
    requests[0].resolve()
    await Promise.resolve()
    assert.equal(requests.length, 2)
    assert.equal(requests[1].value.text, 'Новый')
    assert.equal(completed, false)
    requests[1].resolve()
    await Promise.all([firstFlush, finishFlush])
    assert.equal(completed, true)
    assert.equal(saver.hasPending(), false)
  } finally { saver.dispose() }
})

test('different questions save independently and empty answers are persisted', async () => {
  const saved = []
  const saver = createAnswerSaver(async (id, value) => saved.push([id, value]))
  try {
    const value = { text: 'Исходный' }
    saver.schedule(1, value)
    value.text = 'Изменение вне очереди'
    saver.schedule(2, { text: '' })
    await saver.flush()
    assert.deepEqual(saved, [[1, { text: 'Исходный' }], [2, { text: '' }]])
  } finally { saver.dispose() }
})

test('continuous typing is saved within maxWait without waiting for a pause', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const saved = []
  const saver = createAnswerSaver(async (_, value) => saved.push(value), () => {}, 750, 2000)
  try {
    for (let i = 0; i < 4; i++) {
      saver.schedule(1, { text: String(i) })
      t.mock.timers.tick(500)
    }
    assert.deepEqual(saved, [{ text: '3' }])
    await saver.flush()
    assert.equal(saver.hasPending(), false)
    saver.schedule(1, { text: 'next' })
    assert.equal(saver.hasPending(1), true)
    assert.equal(saver.hasPending(2), false)
  } finally { saver.dispose() }
})

test('disposing cancels both debounce and maximum-wait timers', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let calls = 0
  const saver = createAnswerSaver(async () => { calls++ })
  saver.schedule(1, { text: 'draft' })
  saver.dispose()
  t.mock.timers.tick(10000)
  assert.equal(calls, 0)
})
