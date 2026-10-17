<template>
  <div v-if="question.allow_intermediate_check && question.check_type !== 'manual' && !readonly" class="mt-2">
    <button type="button" class="btn btn-sm btn-outline-primary"
      :disabled="busy || (result?.check_state && !['pending', 'error'].includes(result.check_state))"
      @click="$emit('check')">
      <span v-if="busy || result?.check_state === 'checking'" class="spinner-border spinner-border-sm me-1" />
      <AppIcon v-else name="circle-check" />
      {{ result?.check_state === 'intermediate' ? 'Ответ проверен' : 'Проверить' }}
    </button>
  </div>
</template>

<script setup>
defineProps({ question: Object, result: Object, readonly: Boolean, busy: Boolean })
defineEmits(['check'])
</script>
