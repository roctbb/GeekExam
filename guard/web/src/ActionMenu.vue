<script setup>
import { nextTick, onUnmounted, ref, useId } from "vue";
import Icon from "./Icon.vue";

defineProps({
  items: { type: Array, required: true },
  label: { type: String, required: true },
  disabled: Boolean,
});
const emit = defineEmits(["select"]);
const id = useId(),
  expanded = ref(false),
  trigger = ref(null),
  menu = ref(null),
  position = ref({});
let anchorRect;

function close(restoreFocus = false) {
  expanded.value = false;
  document.removeEventListener("pointerdown", outside);
  document.removeEventListener("focusin", outside);
  document.removeEventListener("scroll", scroll, true);
  window.removeEventListener("resize", resize);
  if (restoreFocus) trigger.value?.focus();
}
function outside(event) {
  if (
    !trigger.value?.contains(event.target) &&
    !menu.value?.contains(event.target)
  )
    close();
}
function scroll(event) {
  if (menu.value?.contains(event.target)) return;
  const current = trigger.value?.getBoundingClientRect();
  // The browser may deliver the click's scroll-into-view notification after
  // opening. Close only if the anchor has actually moved since positioning.
  if (
    !current ||
    current.top !== anchorRect?.top ||
    current.left !== anchorRect?.left
  )
    close();
}
function resize() {
  close();
}
async function show(last = false) {
  if (expanded.value) {
    close(true);
    return;
  }
  expanded.value = true;
  await nextTick();
  const anchor = trigger.value.getBoundingClientRect();
  anchorRect = anchor;
  const width = Math.min(272, window.innerWidth - 24);
  position.value = {
    width: `${width}px`,
    maxHeight: `${window.innerHeight - 24}px`,
    visibility: "hidden",
  };
  await nextTick();
  const height = menu.value.getBoundingClientRect().height;
  const below = window.innerHeight - anchor.bottom - 8,
    above = anchor.top - 8;
  const top =
    below >= height || below >= above
      ? anchor.bottom + 6
      : anchor.top - height - 6;
  position.value = {
    width: `${width}px`,
    maxHeight: `${window.innerHeight - 24}px`,
    left: `${Math.max(12, Math.min(anchor.right - width, window.innerWidth - width - 12))}px`,
    top: `${Math.max(12, Math.min(top, window.innerHeight - height - 12))}px`,
  };
  await nextTick();
  const buttons = menu.value.querySelectorAll("button");
  buttons[last ? buttons.length - 1 : 0]?.focus({ preventScroll: true });
  document.addEventListener("pointerdown", outside);
  document.addEventListener("focusin", outside);
  document.addEventListener("scroll", scroll, true);
  window.addEventListener("resize", resize);
}
function keydown(event) {
  if (event.key === "Escape") {
    event.preventDefault();
    close(true);
  }
  if (event.key === "Tab") close(true);
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const buttons = [...menu.value.querySelectorAll("button")];
  let index = buttons.indexOf(document.activeElement);
  if (event.key === "Home") index = 0;
  else if (event.key === "End") index = buttons.length - 1;
  else
    index =
      (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) %
      buttons.length;
  buttons[index]?.focus();
}
function select(key) {
  close(true);
  emit("select", key);
}
onUnmounted(() => close());
</script>

<template>
  <button
    ref="trigger"
    type="button"
    class="action-trigger"
    :aria-label="label"
    aria-haspopup="menu"
    :aria-expanded="expanded"
    :aria-controls="expanded ? id : undefined"
    :disabled="disabled || !items.length"
    @click="show()"
    @keydown.down.prevent="show()"
    @keydown.up.prevent="show(true)"
  >
    <Icon name="more" />
  </button>
  <Teleport to="body">
    <div
      v-if="expanded"
      :id="id"
      ref="menu"
      class="action-menu"
      :style="position"
      role="menu"
      :aria-label="label"
      @keydown="keydown"
    >
      <button
        v-for="item in items"
        :key="item.key"
        type="button"
        role="menuitem"
        tabindex="-1"
        @click="select(item.key)"
      >
        {{ item.label }}
      </button>
    </div>
  </Teleport>
</template>
