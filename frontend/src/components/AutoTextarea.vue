<template>
  <textarea ref="input" :value="modelValue" rows="3" @input="emit('update:modelValue', $event.target.value)" />
</template>

<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
const props = defineProps({ modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])
const input = ref(null)
function resize() {
  if (!input.value) return
  input.value.style.height = 'auto'
  input.value.style.height = `${input.value.scrollHeight + 4}px`
}
onMounted(resize)
watch(() => props.modelValue, () => nextTick(resize))
</script>

<style scoped>
textarea { max-height: 50vh; overflow-y: auto; }
</style>
