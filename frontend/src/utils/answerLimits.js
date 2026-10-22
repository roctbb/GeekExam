export const SHORT_FIELD_LIMIT = 1000
export const TEXT_LIMIT = 10000
export const CODE_LIMIT = 50000
export const TOTAL_LIMIT = 100000

export function validateAnswerSize(value, question) {
  const limit = ['code_input', 'interactive'].includes(question.type) ? CODE_LIMIT
    : question.type === 'text_input' ? TEXT_LIMIT : SHORT_FIELD_LIMIT
  let total = 0, nodes = 0
  const stack = [[value, 0]]
  while (stack.length) {
    const [item, depth] = stack.pop()
    if (++nodes > 10000 || depth > 20) throw new Error('Ответ содержит слишком много вложенных данных')
    if (typeof item === 'string') {
      if (item.length > limit) throw new Error(`Не более ${limit} символов в одном поле ответа`)
      total += item.length
    } else if (item && typeof item === 'object') {
      const entries = Array.isArray(item) ? item : Object.entries(item).flat()
      if (entries.length > 20000) throw new Error('Ответ содержит слишком много элементов')
      for (const part of entries) stack.push([part, depth + 1])
    }
    if (total > TOTAL_LIMIT) throw new Error(`Не более ${TOTAL_LIMIT} символов во всём ответе`)
  }
}
