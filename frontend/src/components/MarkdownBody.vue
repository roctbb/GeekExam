<template>
  <div
    v-if="rendered"
    ref="root"
    class="ge-markdown"
    :class="{ 'ge-markdown-compact': compact }"
    v-html="rendered"
    @click="copyBlock"
  />
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import 'highlight.js/styles/github-dark.css'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps({
  source: { type: String, default: '' },
  compact: { type: Boolean, default: false },
  copyCode: { type: Boolean, default: false },
})

const rendered = computed(() => renderMarkdown(props.source))
const root = ref(null)
function addCopyButtons() {
  if (!props.copyCode) return
  root.value?.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('button')) return
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'btn btn-sm btn-outline-secondary ge-copy-code'
    button.textContent = 'Копировать'
    button.setAttribute('aria-label', 'Копировать пример')
    pre.append(button)
  })
}
async function copyBlock(event) {
  const button = event.target.closest?.('.ge-copy-code')
  if (!button) return
  try {
    await navigator.clipboard.writeText(button.closest('pre').querySelector('code').textContent)
    button.textContent = 'Скопировано'
  } catch { button.textContent = 'Выделите и скопируйте текст' }
}
watch([rendered, () => props.copyCode], addCopyButtons, { flush: 'post' })
onMounted(addCopyButtons)
</script>

<style scoped>
:deep(.ge-copy-code) { display: block; margin-top: .75rem; background: white; }
</style>
