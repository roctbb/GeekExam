<template>
  <div class="ge-editor">
    <div ref="container" class="ge-editor-surface" />
    <div v-if="!readonly" class="form-text">Tab — отступ, Shift+Tab — убрать отступ. Esc, затем Tab — выйти из редактора.</div>
    <div v-if="lengthError" class="text-danger small" role="alert">{{ lengthError }}</div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { basicSetup } from 'codemirror'
import { Compartment, EditorState } from '@codemirror/state'
import { EditorView, keymap, placeholder as editorPlaceholder } from '@codemirror/view'
import { indentWithTab } from '@codemirror/commands'
import { HighlightStyle, indentUnit, syntaxHighlighting } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { python } from '@codemirror/lang-python'
import { javascript } from '@codemirror/lang-javascript'
import { cpp } from '@codemirror/lang-cpp'
import { useTheme } from '../composables/useTheme'
import { CODE_LIMIT } from '../utils/answerLimits'

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: '' },
  readonly: Boolean,
  rows: { type: Number, default: 12 },
  label: { type: String, default: 'Ответ' },
  placeholder: { type: String, default: '' },
  maxLength: { type: Number, default: CODE_LIMIT },
})
const emit = defineEmits(['update:modelValue'])
const container = ref(null)
const lengthError = ref('')
const configuration = new Compartment()
const { isDark } = useTheme()
const highlighting = syntaxHighlighting(HighlightStyle.define([
  { tag: tags.comment, color: 'var(--ge-code-comment)' },
  { tag: [tags.keyword, tags.modifier, tags.operatorKeyword], color: 'var(--ge-code-keyword)' },
  { tag: [tags.string, tags.regexp], color: 'var(--ge-code-string)' },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: 'var(--ge-code-number)' },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: 'var(--ge-code-function)' },
  { tag: [tags.typeName, tags.className, tags.namespace, tags.standard(tags.variableName)], color: 'var(--ge-code-type)' },
]))
let view
let syncing = false

function extensions() {
  const lang = props.language.toLowerCase()
  const syntax = ['python', 'python3', 'py'].includes(lang) ? python()
    : ['javascript', 'js', 'typescript', 'ts'].includes(lang) ? javascript({ typescript: ['typescript', 'ts'].includes(lang) })
    : ['c', 'cpp', 'c++'].includes(lang) ? cpp() : []
  return [
    syntax,
    highlighting,
    ...(!lang ? [EditorView.lineWrapping] : []),
    EditorState.readOnly.of(props.readonly),
    EditorView.editable.of(!props.readonly),
    EditorView.contentAttributes.of({ 'aria-label': props.label, 'aria-readonly': String(props.readonly) }),
    editorPlaceholder(props.placeholder),
    EditorView.theme({
      '&': { border: '1px solid var(--ge-control-border)', borderRadius: 'var(--ge-radius-control)', overflow: 'hidden', backgroundColor: 'var(--ge-code-bg)', color: 'var(--ge-code-text)' },
      '&.cm-focused': { outline: '2px solid var(--ge-primary)', outlineOffset: '1px' },
      '.cm-scroller': { fontFamily: "'JetBrains Mono', 'Fira Code', monospace", fontSize: '14px', lineHeight: '1.6', maxHeight: '65vh', overflow: 'auto' },
      '.cm-content': { minHeight: `${Math.max(4, Math.min(40, props.rows || 12)) * 1.6}em` },
      '.cm-gutters': { backgroundColor: 'var(--ge-surface-subtle)', color: 'var(--ge-secondary-text)', border: 'none' },
      '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'var(--ge-code-active-line)' },
      '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': { backgroundColor: 'var(--ge-code-selection)' },
      '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--ge-text)' },
      '.cm-placeholder': { color: 'var(--ge-secondary-text)' },
      '.cm-panels, .cm-tooltip': { backgroundColor: 'var(--ge-surface-subtle)', color: 'var(--ge-text)', borderColor: 'var(--ge-control-border)' },
      '.cm-searchMatch': { backgroundColor: 'var(--ge-choice-primary)', outline: '1px solid var(--ge-primary)' },
      '&.cm-focused .cm-matchingBracket': { backgroundColor: 'var(--ge-code-selection)' },
    }, { dark: isDark.value }),
  ]
}

onMounted(() => {
  view = new EditorView({
    parent: container.value,
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        basicSetup,
        indentUnit.of('    '),
        EditorState.tabSize.of(4),
        keymap.of([indentWithTab]),
        configuration.of(extensions()),
        EditorState.transactionFilter.of(transaction => {
          if (!syncing && transaction.docChanged && transaction.newDoc.length > props.maxLength) {
            lengthError.value = `Не более ${props.maxLength} символов в ответе`
            return []
          }
          if (transaction.docChanged) lengthError.value = ''
          return transaction
        }),
        EditorView.updateListener.of(update => {
          if (update.docChanged && !syncing) emit('update:modelValue', update.state.doc.toString())
        }),
      ],
    }),
  })
})

watch(() => props.modelValue, value => {
  if (!view || view.state.doc.toString() === value) return
  syncing = true
  try {
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } })
  } finally {
    syncing = false
  }
})

watch(() => [props.language, props.readonly, props.rows, props.label, props.placeholder, isDark.value], () => {
  view?.dispatch({ effects: configuration.reconfigure(extensions()) })
})

onBeforeUnmount(() => view?.destroy())
</script>
