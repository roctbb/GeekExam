<template>
  <figure class="ge-matrix-display">
    <figcaption class="fw-semibold mb-2">{{ label }}</figcaption>
    <table class="ge-matrix-table" :aria-label="label">
      <tbody><tr v-for="(row, r) in values" :key="r">
        <td v-for="(value, c) in row" :key="c" :style="cellStyle(value)">{{ value }}</td>
      </tr></tbody>
    </table>
    <div v-if="divisor" class="small mt-2">Все элементы ядра делятся на {{ divisor }}</div>
  </figure>
</template>
<script setup>
const props = defineProps({ values: Array, label: String, grayscale: Boolean, divisor: Number })
function cellStyle(value) {
  if (!props.grayscale) return {}
  const n = Math.max(0, Math.min(255, Number(value)))
  return { background: `rgb(${n}, ${n}, ${n})`, color: n < 140 ? '#fff' : '#111' }
}
</script>
<style scoped>
.ge-matrix-display { margin: 0; overflow-x: auto; }
.ge-matrix-table { border-collapse: collapse; font-variant-numeric: tabular-nums; }
td { border: 1px solid #929ca8; min-width: 3.6rem; height: 3.1rem; text-align: center; padding: .4rem; }
</style>
