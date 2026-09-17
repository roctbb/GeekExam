<template>
  <div v-if="result" class="mt-2">
    <div v-if="result.check_state === 'checking'" class="ge-check pending">
      <span class="spinner-border spinner-border-sm" /> Проверяется...
    </div>
    <div v-else-if="['intermediate', 'checked'].includes(result.check_state)" class="ge-check" :class="status.tone">
      <span aria-hidden="true">{{ status.icon }}</span>
      <div class="ge-check-content">
        <strong>{{ status.label }} · {{ result.points }}<template v-if="maxPoints != null"> / {{ maxPoints }}</template> б.</strong>
        <span v-if="result.check_state === 'intermediate'" class="text-muted small ms-1">(предварительно)</span>
        <div v-if="result.check_comment" class="ge-answer-text mt-1">{{ result.check_comment }}</div>
      </div>
    </div>
    <div v-else-if="result.check_state === 'error'" class="ge-check error">
      <span aria-hidden="true">⚠️</span>
      <div class="ge-check-content">Ошибка проверки:<div class="ge-answer-text">{{ result.check_comment }}</div></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { scoreStatus } from '../utils/answers'
const props = defineProps({ result: Object, maxPoints: Number })
const status = computed(() => scoreStatus(props.result?.points, props.maxPoints))
</script>
