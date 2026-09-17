<template>
  <div class="ge-editor">
    <div ref="container" class="ge-editor-surface" />
    <div v-if="!readonly" class="form-text">Tab — отступ, Shift+Tab — убрать отступ. Esc, затем Tab — выйти из редактора.</div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { basicSetup } from 'codemirror'
import { Compartment, EditorState } from '@codemirror/state'
import { EditorView, keymap, placeholder as editorPlaceholder } from '@codemirror/view'
import { indentWithTab } from '@codemirror/commands'
import { indentUnit } from '@codemirror/language'
import { python } from '@codemirror/lang-python'
import { javascript } from '@codemirror/lang-javascript'
import { cpp } from '@codemirror/lang-cpp'

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: '' },
  readonly: Boolean,
  rows: { type: Number, default: 12 },
  label: { type: String, default: 'Ответ' },
  placeholder: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])
const container = ref(null)
const configuration = new Compartment()
let view
let syncing = false

function extensions() {
  const lang = props.language.toLowerCase()
  const syntax = ['python', 'python3', 'py'].includes(lang) ? python()
    : ['javascript', 'js', 'typescript', 'ts'].includes(lang) ? javascript({ typescript: ['typescript', 'ts'].includes(lang) })
    : ['c', 'cpp', 'c++'].includes(lang) ? cpp() : []
  return [
    syntax,
    ...(!lang ? [EditorView.lineWrapping] : []),
    EditorState.readOnly.of(props.readonly),
    EditorView.editable.of(!props.readonly),
    EditorView.contentAttributes.of({ 'aria-label': props.label, 'aria-readonly': String(props.readonly) }),
    editorPlaceholder(props.placeholder),
    EditorView.theme({
      '&': { border: '1px solid #cbd5e1', borderRadius: '12px', overflow: 'hidden' },
      '&.cm-focused': { outline: '2px solid var(--ge-primary)', outlineOffset: '1px' },
      '.cm-scroller': { fontFamily: "'JetBrains Mono', 'Fira Code', monospace", fontSize: '14px', lineHeight: '1.6', maxHeight: '65vh', overflow: 'auto' },
      '.cm-content': { minHeight: `${Math.max(4, Math.min(40, props.rows || 12)) * 1.6}em` },
      '.cm-gutters': { backgroundColor: '#f1f5f9', color: '#64748b', border: 'none' },
    }),
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

watch(() => [props.language, props.readonly, props.rows, props.label, props.placeholder], () => {
  view?.dispatch({ effects: configuration.reconfigure(extensions()) })
})

onBeforeUnmount(() => view?.destroy())
</script>
