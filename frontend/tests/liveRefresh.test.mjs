import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { createLiveRefresh } from '../src/utils/liveRefresh.js'

class Socket extends EventEmitter {
  connected = false
  connect() { this.connected = true; this.emit('connect') }
  disconnect() { this.connected = false }
}
const settled = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }
function deferred() {
  let resolve
  const promise = new Promise(yes => { resolve = yes })
  return { promise, resolve }
}

test('join acknowledgement and reconnect recover missed completion events', async () => {
  const socket = new Socket(), snapshots = []
  let version = 0, joinReply
  socket.on('join', (_, reply) => { joinReply = reply })
  const live = createLiveRefresh({ socket, room: 'attempt_1', fetchSnapshot: async () => version,
    applySnapshot: value => snapshots.push(value), shouldPoll: () => false })
  try {
    await live.start()
    version = 1 // Completion occurred before joining the room: no event arrives.
    joinReply({ status: 'joined' })
    await settled()
    assert.equal(snapshots.at(-1), 1)
    socket.disconnect()
    version = 2 // Another result was missed during disconnect.
    socket.connect()
    await settled()
    assert.equal(snapshots.at(-1), 2)
  } finally { live.stop() }
})

test('an event during an HTTP request discards its stale snapshot and fetches again', async () => {
  const socket = new Socket(), old = deferred(), snapshots = []
  let requests = 0
  const live = createLiveRefresh({ socket, room: 'attempt_1', shouldPoll: () => false,
    fetchSnapshot: () => ++requests === 1 ? old.promise : Promise.resolve('checked'),
    applySnapshot: value => snapshots.push(value) })
  try {
    const loading = live.start()
    await settled()
    socket.emit('attempt_checked')
    old.resolve('checking')
    await loading
    assert.deepEqual(snapshots, ['checked'])
    assert.equal(requests, 2)
  } finally { live.stop() }
})

test('polling recovers missing socket events and stops once complete', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const socket = new Socket()
  let complete = false, requests = 0, snapshot
  const live = createLiveRefresh({ socket, room: 'attempt_1', interval: 5000,
    fetchSnapshot: async () => { requests++; return complete },
    applySnapshot: value => { snapshot = value }, shouldPoll: () => !snapshot })
  try {
    await live.start()
    complete = true
    t.mock.timers.tick(5000)
    await settled()
    assert.equal(snapshot, true)
    const done = requests
    t.mock.timers.tick(15000)
    await settled()
    assert.equal(requests, done)
  } finally { live.stop() }
})

test('intermediate payload is delivered before fetching the ungraded HTTP snapshot', async () => {
  const socket = new Socket(), updates = []
  const payload = { question_id: 1, check_state: 'intermediate', points: 5, checked_value: { text: '42' } }
  const live = createLiveRefresh({ socket, room: 'attempt_1', shouldPoll: () => false,
    fetchSnapshot: async () => 'pending', applySnapshot: state => updates.push(['snapshot', state]),
    applyAnswerUpdate: result => updates.push(['result', result]) })
  try {
    await live.start()
    updates.length = 0
    socket.emit('answer_checked', payload)
    await settled()
    assert.deepEqual(updates, [['result', payload], ['snapshot', 'pending']])
    live.stop()
    socket.emit('answer_checked', payload)
    assert.equal(updates.length, 2)
    assert.equal(socket.listenerCount('answer_checked'), 0)
  } finally { live.stop() }
})

test('unmount ignores a late response and removes socket/window listeners', async () => {
  const socket = new Socket(), response = deferred(), snapshots = []
  const network = new EventTarget(), page = new EventTarget()
  const live = createLiveRefresh({ socket, room: 'attempt_1', network, page,
    fetchSnapshot: () => response.promise, applySnapshot: value => snapshots.push(value) })
  const loading = live.start()
  await settled()
  live.stop()
  response.resolve('late')
  await loading
  socket.emit('answer_checked')
  network.dispatchEvent(new Event('online'))
  page.dispatchEvent(new Event('visibilitychange'))
  assert.deepEqual(snapshots, [])
  assert.equal(socket.listenerCount('connect'), 0)
  assert.equal(socket.listenerCount('attempt_checked'), 0)
})
