<template>
  <component :is="to ? RouterLink : 'button'" v-bind="$attrs" :to="to" :type="to ? undefined : 'button'"
    :disabled="to ? undefined : disabled || busy" :aria-label="label" :aria-busy="busy || undefined"
    class="btn ge-icon-action" :class="`ge-icon-action--${tone}`"
    @mouseenter="showTooltip" @mouseleave="leave" @focus="focus" @blur="hideTooltip"
    @keydown.esc="dismissTooltip" @click="hideTooltip">
    <span v-if="busy" class="spinner-border spinner-border-sm" aria-hidden="true" />
    <AppIcon v-else :name="icon" />
    <span v-if="count > 0" class="ge-icon-action-count" aria-hidden="true">{{ count > 99 ? '99+' : count }}</span>
  </component>
  <Teleport v-if="tooltip" :to="tooltip.parent">
    <span class="ge-icon-tooltip" :class="tooltip.placement" :style="tooltip.style" aria-hidden="true">
      {{ label }}
    </span>
  </Teleport>
</template>

<script setup>
import { onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  icon: { type: String, required: true },
  label: { type: String, required: true },
  to: [String, Object],
  tone: { type: String, default: 'neutral' },
  disabled: Boolean,
  busy: Boolean,
  count: { type: Number, default: 0 },
})

const tooltip = ref(null)

function showTooltip({ currentTarget }) {
  if (props.disabled || props.busy) return
  const { left, right, top, bottom } = currentTarget.getBoundingClientRect()
  const above = top >= 48
  const alignRight = left + (right - left) / 2 > window.innerWidth / 2
  const style = { top: `${above ? top - 6 : bottom + 6}px` }
  if (alignRight) style.right = `${Math.max(8, window.innerWidth - right)}px`
  else style.left = `${Math.max(8, left)}px`
  tooltip.value = {
    style,
    placement: above ? 'ge-icon-tooltip--above' : '',
    parent: currentTarget.closest('dialog[open]') || 'body',
  }
  window.addEventListener('scroll', hideTooltip, true)
  window.addEventListener('resize', hideTooltip)
}

function focus(event) {
  if (event.currentTarget.matches(':focus-visible')) showTooltip(event)
}

function leave(event) {
  if (!event.currentTarget.matches(':focus-visible')) hideTooltip()
}

function hideTooltip() {
  if (!tooltip.value) return
  tooltip.value = null
  window.removeEventListener('scroll', hideTooltip, true)
  window.removeEventListener('resize', hideTooltip)
}

function dismissTooltip(event) {
  if (!tooltip.value) return
  event.preventDefault()
  event.stopPropagation()
  hideTooltip()
}

onUnmounted(hideTooltip)
</script>
