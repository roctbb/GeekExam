// Scope keys to a signed-in user and a test/attempt. Storage may be unavailable
// (private browsing or a full quota); callers can still save to the server.
export function createDraftStorage(key, storage = () => window.localStorage) {
  return {
    read() {
      try { return JSON.parse(storage().getItem(key) || 'null') } catch { return null }
    },
    write(value) {
      try { storage().setItem(key, JSON.stringify(value)); return true } catch { return false }
    },
    clear() {
      try { storage().removeItem(key); return true } catch { return false }
    },
  }
}

export function createAnswerDrafts(storage) {
  let entries = storage.read()
  if (!entries || typeof entries !== 'object' || Array.isArray(entries)) entries = {}
  function persist() { return Object.keys(entries).length ? storage.write(entries) : storage.clear() }
  return {
    entries: () => JSON.parse(JSON.stringify(entries)),
    set(id, value) {
      entries[id] = { value: JSON.parse(JSON.stringify(value)) }
      return persist()
    },
    acknowledge(id, value) {
      // An older successful request must not erase a more recent local edit.
      if (JSON.stringify(entries[id]?.value) === JSON.stringify(value)) delete entries[id]
      return persist()
    },
    clear() { entries = {}; return storage.clear() },
  }
}
