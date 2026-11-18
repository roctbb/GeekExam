import test from 'node:test'
import assert from 'node:assert/strict'
import { createAttemptPresence } from '../src/utils/attemptPresence.js'
const settled = async () => { for (let i = 0; i < 16; i++) await Promise.resolve() }
function harness(overrides = {}) {
  const calls = [], states = [], values = new Map()
  let tick
  const controller = createAttemptPresence({ attemptId: 1,
    register: async () => ({ enabled: true, client_id: 'c', token: 't', code: 'C', next_sequence: 1 }),
    heartbeat: async data => { calls.push(data); return { enabled: true } },
    storage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) },
    schedule: callback => { tick = callback; return 1 }, cancel: () => {}, onChange: state => states.push(state), ...overrides })
  return { controller, calls, states, values, tick: async () => { tick(); await settled() } }
}
test('lost heartbeat acknowledgement retries the same sequence and visibility hint', async () => {
  const sent = []; let fail = true, visible = true
  const h = harness({ visible: () => visible, heartbeat: async data => { sent.push(data); if (fail) { fail = false; throw Error('lost ack') } return { enabled: true } } })
  h.controller.start(); await settled()
  assert.equal(h.states.at(-1).state, 'offline')
  visible = false; await h.tick()
  assert.deepEqual(sent[0], sent[1]); assert.equal(sent[1].sequence, 1)
  await h.tick(); assert.equal(sent[2].sequence, 2); assert.equal(sent[2].visible, false)
  h.controller.stop()
})
test('reload resumes saved client with next server sequence', async () => {
  let registration
  const h = harness({ register: async saved => { registration = saved; return { enabled: true, client_id: 'c', code: 'C', next_sequence: 8 } } })
  h.values.set('geekexam:presence:1', JSON.stringify({ client_id: 'c', token: 'saved' }))
  h.controller.start(); await settled()
  assert.equal(registration.token, 'saved'); assert.equal(h.calls[0].sequence, 8); assert.equal(h.calls[0].token, 'saved')
  h.controller.stop()
})
test('unmount ignores late acknowledgement and schedules no new heartbeat', async () => {
  let resolve, scheduled = 0
  const h = harness({ heartbeat: () => new Promise(yes => { resolve = yes }), schedule: () => { scheduled++ } })
  h.controller.start(); await settled(); h.controller.stop(); const count = h.states.length
  resolve({ enabled: true }); await settled()
  assert.equal(h.states.length, count); assert.equal(scheduled, 0)
})
test('finished or disabled monitoring stops retries', async () => {
  const h = harness({ heartbeat: async () => { throw { response: { status: 410 } } } })
  h.controller.start(); await settled(); assert.equal(h.states.at(-1).state, 'finished')
  h.controller.ping(); await settled(); assert.equal(h.states.at(-1).state, 'finished')
  const disabled = harness({ register: async () => ({ enabled: false }) })
  disabled.controller.start(); await settled(); assert.equal(disabled.calls.length, 0); assert.equal(disabled.states.at(-1).state, 'disabled')
})
