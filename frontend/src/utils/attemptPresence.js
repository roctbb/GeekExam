// These messages prove only server contact for this attempt, not physical presence.
export function createAttemptPresence({ attemptId, register, heartbeat, storage, visible = () => true,
  onChange = () => {}, now = Date.now, schedule = setTimeout, cancel = clearTimeout }) {
  const key = `geekexam:presence:${attemptId}`
  let stopped = true, timer, credentials, sequence, pending, running = false, lastAck = null
  let state = { state: 'connecting', code: '', lastAck: null }
  function publish(value) { state = { ...state, ...value }; onChange(state) }
  function read() { try { return JSON.parse(storage?.getItem(key) || 'null') } catch { return null } }
  function save(value) { try { storage?.setItem(key, JSON.stringify(value)) } catch { /* Memory still works. */ } }
  async function tick() {
    if (stopped || running) return
    running = true
    try {
      if (!credentials) {
        const saved = read()
        let result
        try { result = await register(saved || {}) }
        catch (error) {
          if (saved && [403, 422].includes(error?.response?.status)) result = await register({})
          else throw error
        }
        if (stopped) return
        if (!result.enabled) { publish({ state: 'disabled' }); stopped = true; return }
        credentials = { client_id: result.client_id, token: result.token || saved?.token }
        sequence = result.next_sequence
        save(credentials)
        publish({ code: result.code })
      }
      // Retry precisely the same sequence when an acknowledgement was lost.
      pending ||= { ...credentials, sequence, visible: visible() }
      const result = await heartbeat(pending)
      if (stopped) return
      if (!result.enabled) { publish({ state: 'disabled' }); stopped = true; return }
      sequence = pending.sequence + 1
      pending = null
      lastAck = now()
      publish({ state: 'online', lastAck })
    } catch (error) {
      if (stopped) return
      if (error?.response?.status === 410) { publish({ state: 'finished' }); stopped = true; return }
      if (error?.response?.data?.error === 'sequence_conflict') { credentials = pending = null }
      publish({ state: 'offline', lastAck })
    } finally {
      running = false
      if (!stopped) timer = schedule(tick, 5000)
    }
  }
  return {
    start() { if (!stopped) return; stopped = false; tick() },
    ping() { if (!stopped && !running) { cancel(timer); tick() } },
    stop() { stopped = true; cancel(timer) },
  }
}
