<template>
  <div class="small" :class="tone">
    <strong>{{ label }}</strong>
    <div v-if="last" class="text-muted">{{ channel === 'exam' ? 'Ответ' : 'Подтверждение' }}: {{ fmt(last) }}</div>
    <div v-if="!stale && value?.since" class="text-muted">С {{ fmt(value.since) }}</div>
    <div v-if="channel === 'exam' && value?.active_clients > 1" class="text-warning">Подключений: {{ value.active_clients }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatDateTime as fmt } from '../utils/dates'
const props = defineProps({ value: Object, channel: String, stale: Boolean, finished: Boolean, enabled: Boolean })
const state = computed(() => !props.enabled ? 'disabled' : props.stale ? 'unknown' : props.value?.state || 'unknown')
const label = computed(() => {
  if (props.finished && props.channel === 'guard') return props.value?.bound ? 'Снимок сохранён' : 'Не привязано'
  return { online: 'Онлайн', offline: props.channel === 'exam' ? 'Нет ответа' : 'Устройство вне сети',
    unknown: 'Нет свежих данных', unbound: 'Не привязано', not_seen: 'Ещё не подключался', finished: 'Завершено', disabled: 'Учёт выключен' }[state.value]
})
const tone = computed(() => props.finished ? 'text-muted' : state.value === 'online' ? 'text-success' : state.value === 'offline' ? 'text-danger' : 'text-muted')
const last = computed(() => props.value?.last_seen_at || props.value?.last_confirmed_at)
</script>
