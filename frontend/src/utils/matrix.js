export function matrixValues(value, size) {
  return Array.from({ length: size }, (_, r) =>
    Array.from({ length: size }, (_, c) => String(value?.[r]?.[c] ?? '')))
}

// Paste a rectangle (e.g. from a spreadsheet), JSON matrix, or a flat sequence.
// Reject overflow instead of silently discarding values.
export function pasteMatrix(current, size, row, col, text) {
  let rows
  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed) && parsed.every(Array.isArray)) rows = parsed
  } catch { /* Plain text is the common clipboard format. */ }
  rows ??= text.trim().split(/\r?\n/).map(line => line.trim().split(/[\s;]+/))
  if (!rows.length || rows.some(line => !line.length || line.some(x =>
    !['string', 'number'].includes(typeof x) || !String(x).trim()))) return null
  const result = matrixValues(current, size)
  if (rows.length === 1) {
    const start = row * size + col
    if (start + rows[0].length > size * size) return null
    rows[0].forEach((x, i) => { result[Math.floor((start + i) / size)][(start + i) % size] = String(x) })
  } else {
    if (row + rows.length > size || rows.some(line => col + line.length > size || line.length !== rows[0].length)) return null
    rows.forEach((line, r) => line.forEach((x, c) => { result[row + r][col + c] = String(x) }))
  }
  return result
}
