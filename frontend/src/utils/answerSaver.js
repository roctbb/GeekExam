// Serialize writes to each answer so an older request cannot overwrite a newer edit.
export function createAnswerSaver(save, onChange = () => {}, delay = 2000) {
  const entries = new Map()
  let disposed = false
  const notify = () => {
    if (disposed) return
    const values = [...entries.values()]
    onChange(values.some(e => e.error) ? 'error'
      : values.some(e => e.version > e.savedVersion || e.inFlight) ? 'saving'
        : values.length ? 'saved' : 'idle')
  }

  function drain(id) {
    const entry = entries.get(id)
    if (!entry || disposed) return Promise.resolve()
    clearTimeout(entry.timer)
    if (entry.inFlight) return entry.inFlight
    entry.error = false
    entry.inFlight = (async () => {
      while (entry.savedVersion < entry.version) {
        const version = entry.version
        const value = entry.value
        await save(id, value)
        entry.savedVersion = version
      }
    })().catch(error => {
      entry.error = true
      throw error
    }).finally(() => {
      entry.inFlight = null
      notify()
    })
    notify()
    return entry.inFlight
  }

  return {
    schedule(id, value) {
      let entry = entries.get(id)
      if (!entry) {
        entry = { version: 0, savedVersion: 0 }
        entries.set(id, entry)
      }
      clearTimeout(entry.timer)
      entry.value = JSON.parse(JSON.stringify(value))
      entry.version++
      entry.error = false
      entry.timer = setTimeout(() => { drain(id).catch(() => {}) }, delay)
      notify()
    },
    async flush() {
      // Include in-flight writes and retain failed values for retry.
      await Promise.all([...entries.keys()].map(drain))
    },
    hasPending() { return [...entries.values()].some(e => e.savedVersion < e.version) },
    dispose() {
      disposed = true
      for (const entry of entries.values()) clearTimeout(entry.timer)
    },
  }
}
