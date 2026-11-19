// Local calls carry only an opaque single-use token; never login cookies or IP claims.
export async function sendLocalProof(item, { fetchLocal = fetch, signal } = {}) {
  const url = new URL(item.url)
  if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/v1/browser-proof' || url.search || url.hash) {
    throw Error('invalid_endpoint')
  }
  let confirmed = false
  try {
    const response = await fetchLocal(url.href, {
      method: 'POST', mode: 'cors', credentials: 'omit', cache: 'no-store', redirect: 'error',
      referrerPolicy: 'no-referrer', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: item.token }), signal,
    })
    confirmed = response.ok
  } catch { /* A lost response does not mean the agent failed to prove the request. */ }
  return { id: item.id, confirmed }
}

export function createAutoDeviceBinding({ start, finish, fetchLocal = fetch, onChange = () => {},
  schedule = setTimeout, cancel = clearTimeout, abortController = () => new AbortController(), now = Date.now }) {
  let stopped = false, busy = false, retry, controllers = new Set(), credentials, bound = false
  let round, roundExpires = 0, failures = 0
  async function prove(item) {
    const control = abortController(); controllers.add(control)
    const timeout = schedule(() => control.abort(),12000)
    try {
      const result = await sendLocalProof(item, { fetchLocal, signal: control.signal })
      if (stopped) throw Error('stopped')
      return result
    } finally { cancel(timeout); controllers.delete(control) }
  }
  async function run() {
    if (busy || stopped || bound || !credentials) return
    busy = true; onChange({state:'checking'})
    try {
      const result = round && now() < roundExpires ? round : await start(credentials)
      if (stopped) return
      if (result.state === 'bound') { bound = true; onChange({state:'bound'}); return }
      if (['disabled','not_configured'].includes(result.state)) { bound = true; onChange({state:'disabled'}); return }
      if (result.state !== 'ready' || !Array.isArray(result.items) || !result.items.length || result.items.length > 4) {
        onChange({state:'unavailable',reason:result.reason});return
      }
      if (round !== result) { round = result; roundExpires = now()+30000 }
      const results = await Promise.allSettled(result.items.map(prove))
      if (stopped) return
      const candidates = results.filter(row => row.status==='fulfilled').map(row => row.value).sort((a,b) => Number(b.confirmed)-Number(a.confirmed))
      let conflict = false
      for (const candidate of candidates) {
        if (stopped) return
        try {
          const result = await finish({...credentials,proof_id:candidate.id})
          if (result.state === 'bound') { bound = true; onChange({state:'bound'}); return }
        } catch (error) {
          if (error?.response?.data?.state === 'different_device') { conflict = true; break }
        }
      }
      onChange({state:conflict ? 'different_device' : 'unavailable'})
      if (conflict) bound = true // Never replace the original device silently.
    } catch { if (!stopped) onChange({state:'unavailable'}) }
    finally { busy = false; if (!stopped && !bound) retry = schedule(run,++failures <= 3 && round ? 5000 : 60000) }
  }
  return {
    begin(value, renew = false) {
      if (stopped) return
      if (renew && bound) {
        bound = false; round = null; failures = 0
      } else if (credentials) return
      credentials = {...value}
      run()
    },
    retry() { if (!stopped && !bound) { cancel(retry); run() } },
    stop() { stopped = true; cancel(retry); for (const control of controllers) control.abort() },
  }
}
