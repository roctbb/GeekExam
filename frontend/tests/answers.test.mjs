import test from 'node:test'
import assert from 'node:assert/strict'
import { isQuestionAnswered, scoreStatus, numberedQuestionTitle } from '../src/utils/answers.js'

test('empty text/code do not count as answers, including language-only metadata', () => {
  assert.equal(isQuestionAnswered({ type: 'text_input' }, { text: ' \n ' }), false)
  assert.equal(isQuestionAnswered({ type: 'code_input' }, { code: '', lang: 'python' }), false)
  assert.equal(isQuestionAnswered({ type: 'code_input' }, { code: 'print(0)', lang: 'python' }), true)
})

test('tables count only complete answers and accept false and zero', () => {
  const binary = { type: 'true_false_table', ui_config: { statements: ['a', 'b'] } }
  assert.equal(isQuestionAnswered(binary, { answers: [false, null] }), false)
  assert.equal(isQuestionAnswered(binary, { answers: [false, false] }), true)
  const choice = { type: 'choice_table', ui_config: { items: [{}], options: [{ value: 0 }] } }
  assert.equal(isQuestionAnswered(choice, { answers: [0] }), true)
  assert.equal(isQuestionAnswered(choice, { answers: [null] }), false)
})

test('multiple inputs require every field, preserving numeric zero', () => {
  const q = { type: 'multi_input', ui_config: { fields: [{ name: 'a' }, { name: 'b' }] } }
  assert.equal(isQuestionAnswered(q, { a: '1', b: '' }), false)
  assert.equal(isQuestionAnswered(q, { a: '1', b: 0 }), true)
})

test('partial credit is distinct from full credit and ungraded results', () => {
  assert.equal(scoreStatus(1, 3).tone, 'partial')
  assert.equal(scoreStatus(3, 3).tone, 'success')
  assert.equal(scoreStatus(0, 3).tone, 'error')
  assert.equal(scoreStatus(null, 3).tone, 'pending')
  assert.equal(scoreStatus(0, 0).tone, 'pending')
})

test('titles keep an existing number and otherwise receive the display number', () => {
  assert.equal(numberedQuestionTitle('12. Повторяющееся сообщение', 11), '12. Повторяющееся сообщение')
  assert.equal(numberedQuestionTitle('4) Задача', 1), '4) Задача')
  assert.equal(numberedQuestionTitle('Повторяющееся сообщение', 11), '12. Повторяющееся сообщение')
  assert.equal(numberedQuestionTitle('3.14 — число', 1), '2. 3.14 — число')
})
