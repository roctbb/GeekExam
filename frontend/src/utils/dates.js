export function parseApiDate(value) {
  if (!value) return null
  // Older API responses used naive UTC; retain compatibility during rollout.
  const source = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`
  const date = new Date(source)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDateTime(value) {
  return parseApiDate(value)?.toLocaleString('ru-RU') || ''
}
