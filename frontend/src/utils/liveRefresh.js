// Socket events invalidate the HTTP snapshot. Polling and reconnect/visibility
// refreshes also recover events missed while the browser was disconnected.
export function createLiveRefresh({ socket, room, fetchSnapshot, applySnapshot,
  onError = () => {}, shouldPoll = () => true, interval = 5000,
  page = globalThis.document, network = globalThis.window }) {
  let stopped = true, running = null, queued = false, timer = null
  const events = ['answer_checked', 'attempt_checked', 'attempt_finished']

  function refresh() {
    if (stopped) return Promise.resolve()
    queued = true
    clearTimeout(timer)
    if (running) return running
    // Defer execution so even synchronously throwing fetchers share one promise.
    running = Promise.resolve().then(async () => {
      let failed = false
      do {
        queued = false
        try {
          const data = await fetchSnapshot()
          if (!stopped && !queued) { applySnapshot(data); onError(null) }
          failed = false
        } catch (error) {
          failed = true
          if (!stopped && !queued) onError(error)
        }
      } while (!stopped && queued)
      if (!stopped && (failed || shouldPoll())) timer = setTimeout(refresh, interval)
    }).finally(() => { running = null })
    return running
  }

  function connect() {
    socket.emit('join', { room }, reply => {
      if (stopped) return
      if (reply?.error) onError(new Error('Не удалось подписаться на обновления'))
      refresh()
    })
    // Also work with a lost acknowledgement; the reply triggers another fetch.
    refresh()
  }
  function visible() { if (!page?.hidden) refresh() }

  return {
    refresh,
    start() {
      if (!stopped) return
      stopped = false
      socket.on('connect', connect)
      for (const event of events) socket.on(event, refresh)
      page?.addEventListener('visibilitychange', visible)
      network?.addEventListener('online', refresh)
      if (socket.connected) connect()
      else socket.connect()
      return refresh()
    },
    stop() {
      stopped = true
      queued = false
      clearTimeout(timer)
      socket.off('connect', connect)
      for (const event of events) socket.off(event, refresh)
      socket.disconnect()
      page?.removeEventListener('visibilitychange', visible)
      network?.removeEventListener('online', refresh)
    },
  }
}
