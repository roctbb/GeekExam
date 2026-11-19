<template>
  <span class="ge-answer-ratio-bar" aria-hidden="true">
    <span v-for="(count, status) in segments" :key="status" :class="`ge-answer-ratio-${status}`"
      :style="{ flexGrow: count }" />
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  correct: { type: Number, required: true },
  incorrect: { type: Number, required: true },
  skipped: { type: Number, required: true },
  ungraded: { type: Number, required: true },
})
const segments = computed(() => ({
  correct: props.correct,
  incorrect: props.incorrect,
  skipped: props.skipped,
  ungraded: props.ungraded,
}))
</script>

<style scoped>
.ge-answer-ratio-bar {
  display: flex;
  height: var(--answer-ratio-height, .875rem);
  background: var(--ge-surface-subtle);
  border-radius: .25rem;
  overflow: hidden;
}
.ge-answer-ratio-bar > span { flex: 0 0 0; }
.ge-answer-ratio-correct { background: var(--answer-ratio-correct); }
.ge-answer-ratio-incorrect { background: var(--answer-ratio-incorrect); }
.ge-answer-ratio-skipped { background: var(--answer-ratio-skipped); }
.ge-answer-ratio-ungraded { background: var(--answer-ratio-ungraded); }
</style>
