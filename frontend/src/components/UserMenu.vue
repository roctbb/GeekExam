<template>
  <div ref="root" class="ge-user-menu" @keydown="onKeydown" @focusout="onFocusOut">
    <button ref="trigger" type="button" class="btn btn-outline-light ge-user-trigger"
      :aria-label="`Меню пользователя: ${displayName}`" aria-haspopup="menu"
      :aria-expanded="open" aria-controls="ge-account-menu" :title="displayName"
      @click="toggle" @keydown.down.prevent="show(0)" @keydown.up.prevent="show(-1)">
      <span class="ge-avatar" aria-hidden="true">
        <img v-if="avatarUrl && !avatarFailed" :src="avatarUrl" alt="" width="32" height="32"
          decoding="async" referrerpolicy="no-referrer" @error="avatarFailed = true" />
        <span v-else>{{ initials }}</span>
      </span>
      <span class="ge-user-name">{{ displayName }}</span>
      <AppIcon name="chevron-down" class="ge-user-chevron" />
    </button>
    <div v-if="open" id="ge-account-menu" ref="panel" class="ge-user-panel" role="menu" aria-label="Меню пользователя">
      <div class="ge-user-menu-heading" role="presentation">{{ displayName }}</div>
      <RouterLink v-if="isTeacher" to="/admin/tests" role="menuitem" tabindex="-1" class="ge-user-menu-item" @click="close()">
        <AppIcon name="tests" />Тесты
      </RouterLink>
      <RouterLink to="/my-results" role="menuitem" tabindex="-1" class="ge-user-menu-item" @click="close()">
        <AppIcon name="results" />Мои результаты
      </RouterLink>
      <button type="button" role="menuitem" tabindex="-1" class="ge-user-menu-item"
        :aria-label="isDark ? 'Включить светлую тему' : 'Включить тёмную тему'" @click="toggleTheme">
        <AppIcon :name="isDark ? 'sun' : 'moon'" />{{ isDark ? 'Светлая тема' : 'Тёмная тема' }}
      </button>
      <div class="ge-user-menu-divider" role="separator" />
      <button type="button" role="menuitem" tabindex="-1" class="ge-user-menu-item" :disabled="loggingOut" @click="requestLogout">
        <AppIcon name="logout" />{{ loggingOut ? 'Выход…' : 'Выйти' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme } from '../composables/useTheme'

const props = defineProps({ user: { type: Object, required: true }, loggingOut: Boolean })
const emit = defineEmits(['logout'])
const route = useRoute()
const { isDark, toggleTheme } = useTheme()
const root = ref(null), trigger = ref(null), panel = ref(null), open = ref(false)
const avatarFailed = ref(false)
const displayName = computed(() => props.user.name?.trim() || 'Пользователь')
const initials = computed(() => displayName.value.split(/\s+/).slice(0, 2).map(part => Array.from(part)[0]).join('').toLocaleUpperCase('ru-RU'))
const avatarUrl = computed(() => {
  if (typeof props.user.avatar_url !== 'string') return ''
  try {
    const url = new URL(props.user.avatar_url)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : ''
  } catch { return '' }
})
const isTeacher = computed(() => ['teacher', 'admin'].includes(props.user.role))
const items = () => [...(panel.value?.querySelectorAll('[role="menuitem"]:not(:disabled)') || [])]

async function show(index = 0) {
  open.value = true
  await nextTick()
  const available = items()
  available.at(index)?.focus()
}

function close(restoreFocus = false) {
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}

function toggle() { if (open.value) close(); else show() }
function requestLogout() { close(); emit('logout') }
function onOutside(event) { if (!root.value?.contains(event.target)) close() }
function onFocusOut(event) { if (!root.value?.contains(event.relatedTarget)) close() }

function onKeydown(event) {
  if (!open.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    close(true)
    return
  }
  if (!panel.value?.contains(event.target)) return
  const available = items(), index = available.indexOf(document.activeElement)
  let next
  if (event.key === 'ArrowDown') next = (index + 1) % available.length
  else if (event.key === 'ArrowUp') next = (index - 1 + available.length) % available.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = available.length - 1
  else return
  event.preventDefault()
  available[next]?.focus()
}

watch(() => route.fullPath, () => close())
watch(avatarUrl, () => { avatarFailed.value = false })
onMounted(() => document.addEventListener('pointerdown', onOutside))
onUnmounted(() => document.removeEventListener('pointerdown', onOutside))
</script>
