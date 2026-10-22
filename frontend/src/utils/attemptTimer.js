import { parseApiDate } from './dates.js'

// Anchor server time to a monotonic clock: changing the computer's clock must
// not add/subtract time between snapshots.
export function createAttemptTimer(now = () => performance.now()) {
  let remainingMs = null, syncedAt = 0
  return {
    sync(attempt) {
      const deadline = parseApiDate(attempt.time_deadline_at)?.getTime()
      const serverTime = parseApiDate(attempt.server_time)?.getTime()
      remainingMs = attempt.finished_at ? null
        : deadline != null && serverTime != null ? Math.max(0, deadline - serverTime)
          : attempt.time_left != null ? Math.max(0, attempt.time_left) * 1000 : null
      syncedAt = now()
    },
    remaining() {
      return remainingMs === null ? null : Math.max(0, Math.ceil((remainingMs - (now() - syncedAt)) / 1000))
    },
  }
}
