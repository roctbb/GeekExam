<template>
  <div v-if="result" class="mt-2">
    <div v-if="result.check_state === 'checking'" class="ge-check pending">
      <span class="spinner-border spinner-border-sm" /> Проверяется...
    </div>
    <div v-else-if="result.check_state === 'checked'" class="ge-check" :class="result.points > 0 ? 'success' : 'error'">
      {{ result.points > 0 ? '✅' : '❌' }} {{ result.points }} б. — {{ result.check_comment }}
    </div>
    <div v-else-if="result.check_state === 'error'" class="ge-check error">
      ⚠️ Ошибка проверки: {{ result.check_comment }}
    </div>
  </div>
</template>

<script setup>
defineProps({ result: Object })
</script>
