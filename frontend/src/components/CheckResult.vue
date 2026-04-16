<template>
  <div v-if="result" class="mt-2">
    <div v-if="result.check_state === 'checking'" class="text-muted small">
      <span class="spinner-border spinner-border-sm me-1" /> Проверяется...
    </div>
    <div v-else-if="result.check_state === 'checked'" :class="result.points > 0 ? 'text-success' : 'text-danger'" class="small">
      {{ result.points }} баллов — {{ result.check_comment }}
    </div>
    <div v-else-if="result.check_state === 'error'" class="text-danger small">
      Ошибка проверки: {{ result.check_comment }}
    </div>
  </div>
</template>

<script setup>
defineProps({ result: Object })
</script>
