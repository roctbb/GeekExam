import test from 'node:test'
import assert from 'node:assert/strict'
import { createDraftStorage, createAnswerDrafts } from '../src/utils/drafts.js'

function memory() {
  const values = new Map()
  return { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
}

test('drafts survive reload and an old acknowledgement does not erase a newer edit', () => {
  const backend = memory()
  const storage = createDraftStorage('user:1:attempt:2', () => backend)
  const drafts = createAnswerDrafts(storage)
  drafts.set(7, { text: 'first' })
  drafts.set(7, { text: 'second' })
  drafts.acknowledge(7, { text: 'first' })
  const restored = createAnswerDrafts(storage)
  assert.deepEqual(restored.entries(), { 7: { value: { text: 'second' } } })
  restored.acknowledge(7, { text: 'second' })
  assert.equal(storage.read(), null)
})

test('another user/attempt cannot pick up the same draft', () => {
  const backend = memory()
  createDraftStorage('user:1:attempt:2', () => backend).write({ title: 'draft' })
  assert.equal(createDraftStorage('user:2:attempt:2', () => backend).read(), null)
  assert.equal(createDraftStorage('user:1:attempt:3', () => backend).read(), null)
})

test('unavailable or corrupt storage does not crash typing', () => {
  const unavailable = createDraftStorage('x', () => { throw Error('quota') })
  const drafts = createAnswerDrafts(unavailable)
  assert.equal(drafts.set(1, { text: 'kept in memory' }), false)
  assert.deepEqual(drafts.entries()[1].value, { text: 'kept in memory' })
  const backend = memory()
  backend.setItem('x', 'broken JSON')
  assert.deepEqual(createAnswerDrafts(createDraftStorage('x', () => backend)).entries(), {})
})
