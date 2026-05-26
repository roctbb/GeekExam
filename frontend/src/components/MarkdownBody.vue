<template>
  <div
    v-if="rendered"
    class="ge-markdown"
    :class="{ 'ge-markdown-compact': compact }"
    v-html="rendered"
  />
</template>

<script setup>
import { computed } from 'vue'
import 'highlight.js/styles/github-dark.css'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps({
  source: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})

const rendered = computed(() => renderMarkdown(props.source))
</script>
