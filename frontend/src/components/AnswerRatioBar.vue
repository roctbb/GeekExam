<template>
  <span class="ge-answer-ratio-bar" aria-hidden="true">
    <template v-if="total">
      <span class="ge-answer-ratio-correct" :style="{ width: `${100 * correct / total}%` }" />
      <span class="ge-answer-ratio-incorrect" />
    </template>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  correct: { type: Number, required: true },
  incorrect: { type: Number, required: true },
})
const total = computed(() => props.correct + props.incorrect)
</script>

<style scoped>
.ge-answer-ratio-bar {
  display: flex;
  height: var(--answer-ratio-height, .875rem);
  background: var(--ge-surface-subtle);
  border-radius: .25rem;
  overflow: hidden;
}
.ge-answer-ratio-correct { background: var(--answer-ratio-correct); }
.ge-answer-ratio-incorrect { background: var(--answer-ratio-incorrect); flex: 1; }
</style>
