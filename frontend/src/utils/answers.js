export function sameAnswerValue(a, b) {
  const stable = value => {
    if (Array.isArray(value)) return value.map(stable)
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])]))
    return value
  }
  return JSON.stringify(stable(a)) === JSON.stringify(stable(b))
}

export function hasAnswerValue(value) {
  if (value == null) return false
  if (typeof value === 'string') return value.trim().length > 0
  if (typeof value === 'boolean' || typeof value === 'number') return true
  if (Array.isArray(value)) return value.length > 0 && value.every(hasAnswerValue)
  if (typeof value === 'object') return Object.values(value).some(hasAnswerValue)
  return false
}

export function isQuestionAnswered(question, value) {
  if (!value) return false
  if (question.type === 'text_input') return hasAnswerValue(value.text)
  if (question.type === 'code_input') return hasAnswerValue(value.code)
  const ui = question.ui_config || {}
  if (question.type === 'matrix_input') {
    const n = ui.size
    return Number.isInteger(n) && n > 0 && Array.isArray(value.matrix) && value.matrix.length === n
      && value.matrix.every(row => Array.isArray(row) && row.length === n && row.every(hasAnswerValue))
      && (ui.fields || []).every(field => hasAnswerValue(value.fields?.[field.name]))
  }
  if (question.type === 'multi_input') {
    return !!ui.fields?.length && ui.fields.every(field => hasAnswerValue(value[field.name]))
  }
  if (question.type === 'true_false_table' || question.type === 'choice_table') {
    const rows = question.type === 'true_false_table' ? ui.statements : ui.items
    return !!rows?.length && value.answers?.length === rows.length && value.answers.every(answer =>
      question.type === 'true_false_table' ? typeof answer === 'boolean'
        : ui.options?.some(option => option.value === answer))
  }
  return hasAnswerValue(value)
}

export function scoreStatus(points, maxPoints) {
  if (points == null) return { label: 'Не оценено', tone: 'pending', badge: 'bg-secondary', tab: 'answered', icon: '—' }
  if (maxPoints > 0 && points >= maxPoints) return { label: 'Верно', tone: 'success', badge: 'bg-success', tab: 'correct', icon: '✅' }
  if (points > 0) return { label: 'Частично', tone: 'partial', badge: 'bg-warning text-dark', tab: 'partial', icon: '◐' }
  if (maxPoints === 0) return { label: 'Без баллов', tone: 'pending', badge: 'bg-secondary', tab: 'answered', icon: '—' }
  return { label: 'Неверно', tone: 'error', badge: 'bg-danger', tab: 'wrong', icon: '❌' }
}

export function numberedQuestionTitle(title, index) {
  const text = String(title || '').trim()
  // Keep an existing title number, including one that differs from the display order.
  return /^\d+[.)]\s+/.test(text) ? text : `${index + 1}. ${text}`
}
