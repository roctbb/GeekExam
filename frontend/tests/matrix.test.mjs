import test from 'node:test'
import assert from 'node:assert/strict'
import { matrixValues, pasteMatrix } from '../src/utils/matrix.js'
import { isQuestionAnswered, sameAnswerValue } from '../src/utils/answers.js'

test('square matrix completion requires all cells and auxiliary fields', () => {
  const q = { type: 'matrix_input', ui_config: { size: 2, fields: [{ name: 'sum' }] } }
  assert.equal(isQuestionAnswered(q, { matrix: [[0, 1], [2, '']] }), false)
  assert.equal(isQuestionAnswered(q, { matrix: [[0, 1], [2, 3]] }), false)
  assert.equal(isQuestionAnswered(q, { matrix: [[0, 1], [2, 3]], fields: { sum: 0 } }), true)
  assert.equal(isQuestionAnswered(q, { matrix: [[0, 1, 2]], fields: { sum: 0 } }), false)
})

test('paste spreadsheet, JSON and flat matrices without modifying the old answer', () => {
  const old = matrixValues(null, 2)
  for (const text of ['0\t1\n2\t3', '[[0,1],[2,3]]', '0 1 2 3']) {
    assert.deepEqual(pasteMatrix(old, 2, 0, 0, text), [['0', '1'], ['2', '3']])
  }
  assert.deepEqual(old, [['', ''], ['', '']])
  assert.deepEqual(pasteMatrix(old, 2, 1, 0, '-2 3.5'), [['', ''], ['-2', '3.5']])
  assert.equal(pasteMatrix(old, 2, 1, 1, '1 2'), null)
  assert.equal(pasteMatrix(old, 2, 0, 0, '1 2\n3'), null)
})

test('version comparison ignores object key order but rejects edited code', () => {
  assert.equal(sameAnswerValue({ lang: 'python', code: '1' }, { code: '1', lang: 'python' }), true)
  assert.equal(sameAnswerValue({ code: '2' }, { code: '1' }), false)
  assert.equal(sameAnswerValue(undefined, { code: '1' }), false)
})
