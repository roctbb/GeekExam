import test from 'node:test'
import assert from 'node:assert/strict'
import { validateAnswerSize, SHORT_FIELD_LIMIT, CODE_LIMIT } from '../src/utils/answerLimits.js'

test('small fields and code have separate caps, checked before draft serialization', () => {
  assert.doesNotThrow(() => validateAnswerSize({ second: 'x'.repeat(SHORT_FIELD_LIMIT) }, { type: 'multi_input' }))
  assert.throws(() => validateAnswerSize({ second: 'x'.repeat(SHORT_FIELD_LIMIT + 1) }, { type: 'multi_input' }), /1000/)
  assert.doesNotThrow(() => validateAnswerSize({ code: 'x'.repeat(CODE_LIMIT) }, { type: 'code_input' }))
  assert.throws(() => validateAnswerSize({ code: 'x'.repeat(CODE_LIMIT + 1) }, { type: 'code_input' }), /50000/)
  assert.throws(() => validateAnswerSize({ second: '😀'.repeat(501) }, { type: 'multi_input' }), /1000/)
})

test('aggregate and nesting limits also protect interactive drafts and unknown fields', () => {
  assert.throws(() => validateAnswerSize(['x'.repeat(50000), 'y'.repeat(50000), 'z'], { type: 'interactive' }), /100000/)
  assert.throws(() => validateAnswerSize({ text: 'ok', extra: 'x'.repeat(10001) }, { type: 'text_input' }), /10000/)
  let value = 'ok'
  for (let i = 0; i < 22; i++) value = [value]
  assert.throws(() => validateAnswerSize(value, { type: 'interactive' }), /вложенных/)
})
