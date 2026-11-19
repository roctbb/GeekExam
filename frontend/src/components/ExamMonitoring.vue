<template>
  <section class="card mb-4" aria-labelledby="presence-title">
    <div class="card-body">
      <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">
        <div>
          <h5 id="presence-title">{{ settingsOnly ? 'Доступ к тесту' : 'Связь во время теста' }}</h5>
          <template v-if="!settingsOnly">
            <p v-if="data?.config?.require_guard" class="small text-muted mb-1">Для входа требуется авторизация в кабинете Guard «{{ roomName }}».</p>
            <p class="small text-muted mb-0">Последнее обновление: {{ fmt(data?.server_time) || 'ожидается' }}</p>
          </template>
        </div>
        <IconAction v-if="!settingsOnly" icon="settings" label="Настройки связи" :aria-expanded="settings" @click="toggleSettings" />
      </div>
      <div v-if="settingsOnly && error" class="alert alert-warning mt-3 mb-0" role="alert">
        {{ error }} <button type="button" class="btn btn-sm btn-outline-secondary" @click="emit('refresh')">Повторить</button>
      </div>
      <p v-else-if="!settingsOnly && (error || stale)" class="alert alert-warning mt-3 mb-0" role="status">{{ error || 'Свежие статусы ещё не получены.' }} При отсутствии обновлений состояние становится неизвестным.</p>
      <p v-if="settings && !data?.config && !error" class="small text-muted mb-0" role="status">Загружаем настройки…</p>
      <div v-for="event in openClassroomEvents" :key="event.id" class="alert alert-warning mt-3 mb-0" role="status">
        {{ titles[event.kind] }} · с {{ fmt(event.started_at) }}.
        {{ event.kind === 'mass_disconnect' ? 'Проверьте Wi-Fi кабинета.' : 'Присутствие устройств сейчас не подтверждено.' }}
      </div>
      <form v-if="settings && data?.config" class="border-top mt-3 pt-3" @submit.prevent="saveConfig">
        <div class="form-check mb-2"><input id="monitor-enabled" v-model="enabled" type="checkbox" class="form-check-input" :disabled="saving || requireGuard" @change="dirty = true"><label class="form-check-label" for="monitor-enabled">Учитывать связь во время теста</label></div>
        <div class="form-check mb-2">
          <input id="monitor-require-guard" v-model="requireGuard" type="checkbox" class="form-check-input" :disabled="saving" @change="changeGuardRequirement">
          <label class="form-check-label" for="monitor-require-guard">Требовать авторизацию устройства в Guard</label>
        </div>
        <template v-if="requireGuard">
          <label class="form-label" for="monitor-room">Кабинет Guard</label>
          <select id="monitor-room" v-model="roomId" class="form-select mb-2" :disabled="saving" @change="dirty = true">
            <option :value="null">Выберите кабинет</option>
            <option v-if="roomId && !rooms.some(r => r.id === roomId)" :value="roomId">{{ data.config.room_name || 'Текущий кабинет' }}</option>
            <option v-for="room in rooms" :key="room.id" :value="room.id">{{ room.name }}</option>
          </select>
          <p class="small text-muted">Ученик сможет начать тест после проверки авторизации этого устройства в сети кабинета. Если Guard подтвердит отключение на 20 секунд, преподаватель, запустивший тест, получит сообщение в привязанный Telegram.</p>
          <p v-if="!data.guard_configured" class="small text-muted">Подключение к Guard ещё не настроено.</p>
        </template>
        <p v-if="dirty" class="small text-warning" role="status">Ожидает отправки: 1 изменение настроек. {{ saving ? 'Сохраняется…' : 'Нажмите «Сохранить».' }}</p>
        <p v-if="actionError" class="text-danger small" role="alert">{{ actionError }}</p>
        <button class="btn btn-sm btn-primary" :disabled="saving || !dirty || (requireGuard && !roomId)">{{ saving ? 'Сохраняется…' : 'Сохранить' }}</button>
        <button v-if="requireGuard && data.guard_configured" type="button" class="btn btn-sm btn-outline-secondary ms-2" :disabled="saving" @click="loadRooms">Обновить кабинеты</button>
      </form>
    </div>
  </section>

  <dialog v-if="!settingsOnly" ref="dialog" class="presence-dialog" aria-labelledby="presence-dialog-title" @close="selected = null" @click="backdropClose">
    <div v-if="selected" class="p-3 p-md-4">
      <div class="d-flex justify-content-between align-items-start gap-3 mb-3">
        <h5 id="presence-dialog-title" class="mb-0">Связь: {{ selected.user_name }}</h5>
        <IconAction icon="close" label="Закрыть журнал" @click="dialog.close()" />
      </div>
      <p class="small text-muted">События помогают проверить условия выполнения работы. Они сами по себе не доказывают списывание и не меняют оценку.</p>
      <div class="row g-3 mb-3">
        <div class="col-sm-6"><h6>GeekExam</h6><PresenceStatus :value="current?.exam" channel="exam" :stale="stale" :finished="!!selected.finished_at" :enabled="data?.config?.enabled !== false" /></div>
        <div v-if="current?.guard_admitted" class="col-sm-6"><h6>Сеть Guard</h6><PresenceStatus :value="current?.guard" channel="guard" :stale="stale" :finished="!!selected.finished_at" :enabled="data?.config?.enabled !== false" />
          <p v-if="current?.guard?.bound" class="small text-muted mb-0">Проверка Guard: {{ fmt(current.guard.checked_at) || 'ожидается' }}. {{ reasons[current.guard.reason] || '' }}</p>
        </div>
      </div>
      <details v-if="!selected.finished_at && data?.config?.require_guard && data.config.enabled !== false" class="border rounded p-3 mb-3" @toggle="bindingToggle">
        <summary class="fw-semibold">Подтвердить устройство ученика</summary>
        <p class="small text-muted mt-2">Сначала привяжите устройство к этому ученику в <a href="https://guard.geekclass.ru" target="_blank" rel="noopener">Guard</a>. Затем сверьте код на экране теста и выберите именно это устройство.</p>
        <button class="btn btn-sm btn-outline-secondary mb-2" :disabled="candidateLoading" @click="loadCandidates">{{ candidateLoading ? 'Загрузка…' : 'Обновить устройства' }}</button>
        <p v-if="candidateError" class="small text-danger" role="alert">{{ candidateError }}</p>
        <p v-if="!candidateLoading && !candidates.length && !candidateError" class="small text-muted">Нет свежей подтверждённой сессии этого ученика в выбранном кабинете.</p>
        <form v-if="candidates.length" @submit.prevent="bindDevice">
          <label class="form-label" for="binding-device">Устройство в сети</label>
          <select id="binding-device" v-model="sessionId" required class="form-select mb-2"><option value="" disabled>Выберите устройство</option><option v-for="c in candidates" :key="c.session_id" :value="c.session_id">{{ c.device_name || 'Без названия' }} · {{ c.ip }} · {{ c.router_name }}</option></select>
          <label class="form-label" for="binding-client">Код подключения на экране GeekExam</label>
          <select id="binding-client" v-model="clientId" required class="form-select mb-2"><option value="" disabled>Сверьте код у ученика</option><option v-for="c in current?.exam?.clients || []" :key="c.id" :value="c.id">{{ c.code }} · {{ fmt(c.last_seen_at) }}</option></select>
          <div class="form-check mb-2"><input id="binding-confirmed" v-model="confirmed" type="checkbox" required class="form-check-input"><label class="form-check-label" for="binding-confirmed">Проверено: тест с этим кодом открыт на выбранном устройстве.</label></div>
          <button class="btn btn-sm btn-primary" :disabled="binding || !confirmed || !clientId || !sessionId">{{ binding ? 'Проверка…' : 'Подтвердить привязку' }}</button>
        </form>
      </details>
      <p v-if="historyError" class="alert alert-warning" role="alert">{{ historyError }}</p>
      <h6>Журнал связи</h6>
      <p v-if="historyLoading && !events.length" class="text-muted small">Загрузка…</p>
      <p v-else-if="!events.length" class="text-muted small">Событий пока нет.</p>
      <article v-for="event in events" :key="event.id" class="border rounded p-3 mb-2" :class="{ 'border-warning': event.review_required && !event.reviewed_at }">
        <div class="d-flex gap-2 align-items-center flex-wrap"><strong>{{ event.kind === 'binding_confirmed' && event.details?.method === 'browser_lan_proof' ? 'Устройство определено локальным агентом' : titles[event.kind] || event.kind }}</strong><span v-if="event.review_required" class="badge" :class="event.reviewed_at ? 'bg-secondary' : 'bg-warning text-dark'">{{ event.reviewed_at ? 'Просмотрено' : 'Требует проверки' }}</span></div>
        <dl class="small mb-0 mt-2 event-times">
          <dt>Событие с</dt><dd>{{ fmt(event.started_at) }}</dd>
          <template v-if="event.last_confirmed_at"><dt>До обрыва подтверждено</dt><dd>{{ fmt(event.last_confirmed_at) }}</dd></template>
          <dt>Обнаружено</dt><dd>{{ fmt(event.detected_at) }}</dd>
          <template v-if="event.notification_status"><dt>Telegram преподавателя</dt><dd>{{ notificationLabels[event.notification_status] }}</dd></template>
          <template v-if="event.exam_continued_at"><dt>{{ evidenceLabels[event.details?.evidence_client_scope] || evidenceLabels.unknown }}</dt><dd>{{ fmt(event.exam_continued_at) }}</dd></template>
          <template v-if="event.ended_at"><dt>{{ event.details?.closed_by ? 'Наблюдение завершено' : 'Восстановление' }}</dt><dd>{{ fmt(event.ended_at) }}</dd></template>
        </dl>
        <p v-if="event.details?.mass_disconnect" class="small text-muted mb-0">Часть массового отключения устройств; индивидуальный сигнал списывания не создаётся.</p>
        <p v-if="event.details?.history_complete === false" class="small text-muted mb-0">История Guard неполная; автоматическое сопоставление не выполняется.</p>
        <p v-if="event.reviewed_at" class="small text-muted mb-0">Просмотрено {{ fmt(event.reviewed_at) }}. {{ event.review_note }}</p>
        <form v-else-if="event.review_required" class="mt-2" @submit.prevent="review(event)">
          <label :for="`review-${event.id}`" class="form-label small">Комментарий преподавателя</label>
          <input :id="`review-${event.id}`" v-model="notes[event.id]" maxlength="500" class="form-control form-control-sm mb-2">
          <button class="btn btn-sm btn-outline-secondary" :disabled="reviewing === event.id">Отметить просмотренным</button>
        </form>
      </article>
      <p v-if="events.length === 500" class="small text-muted">Показаны последние 500 событий.</p>
    </div>
  </dialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import api from '../api'
import PresenceStatus from './PresenceStatus.vue'
import { formatDateTime as fmt } from '../utils/dates'
const props = defineProps({ testId: [String, Number], data: Object, stale: Boolean, error: String, settingsOnly: Boolean })
const emit = defineEmits(['refresh'])
const settings = ref(props.settingsOnly), rooms = ref([]), roomId = ref(null), enabled = ref(true), requireGuard = ref(false)
const dirty = ref(false), draftVersion = ref(0), saving = ref(false), actionError = ref('')
const dialog = ref(null), selected = ref(null), events = ref([]), historyLoading = ref(false), historyError = ref(''), notes = ref({}), reviewing = ref(null)
const candidates = ref([]), candidateError = ref(''), candidateLoading = ref(false), sessionId = ref(''), clientId = ref(''), confirmed = ref(false), binding = ref(false)
const titles = { device_mismatch: 'Попытка открыта с другого устройства', exam_disconnected: 'GeekExam перестал получать ответы о связи', device_disconnected: 'Устройство отсутствует в сети Guard', binding_confirmed: 'Устройство подтверждено', binding_changed: 'Привязка устройства изменена', guard_source_lost: 'Нет связи с роутером или агентом', guard_service_unavailable: 'Нет связи с сервисом Guard', mass_disconnect: 'Массовое отключение устройств' }
const reasons = { binding_expired: 'Сетевая сессия истекла: нужна новая привязка.', binding_revoked: 'Сетевая привязка снята.', connection_changed: 'Сетевая сессия изменилась: проверьте устройство.', agent_restarted: 'Агент перезапущен: нужна новая привязка.', agent_not_reporting: 'Агент не передаёт данные.', access_denied: 'У Guard нет действующего разрешения для этого кабинета.', guard_unavailable: 'Сервис Guard не отвечает.' }
const current = computed(() => props.data?.attempts?.find(a => a.attempt_id === selected.value?.id))
const roomName = computed(() => props.data?.config?.room_name || rooms.value.find(r => r.id === props.data?.config?.room_id)?.name || 'выбран')
const openClassroomEvents = computed(() => props.data?.config?.require_guard && !props.settingsOnly
  ? (props.data.classroom_events || []).filter(e => !e.ended_at && e.kind !== 'mass_disconnect').slice(0, 3)
  : [])
const evidenceLabels = { bound: 'Привязанная вкладка вышла на связь с GeekExam', other: 'Другая вкладка попытки вышла на связь с GeekExam', unknown: 'Попытка вышла на связь с GeekExam' }
const notificationLabels = { pending: 'В очереди', sent: 'Отправлено', no_recipient: 'Нет доступного чата преподавателя', uncertain: 'Доставка не подтверждена', rejected: 'Сообщение отклонено' }
function applyConfig(config) {
  roomId.value = config.room_id
  enabled.value = config.enabled
  requireGuard.value = config.require_guard
  draftVersion.value = config.version
}
watch(() => props.data?.config, config => {
  if (!config || dirty.value) return
  const wasRequired = requireGuard.value
  applyConfig(config)
  if (settings.value && requireGuard.value && !wasRequired && props.data.guard_configured) loadRooms()
}, { immediate: true })
watch(() => props.data, () => { if (selected.value) loadHistory() })
async function loadRooms() { try { rooms.value = (await api.getPresenceRooms()).data.items; actionError.value = '' } catch { actionError.value = 'Нет связи с Guard или нет доступа к кабинетам. Изменения не отправлены.' } }
function toggleSettings() { settings.value = !settings.value; if (settings.value && requireGuard.value && props.data?.guard_configured) loadRooms() }
function changeGuardRequirement() {
  dirty.value = true
  if (requireGuard.value) enabled.value = true
  actionError.value = ''
  if (requireGuard.value && props.data?.guard_configured) loadRooms()
}
async function saveConfig() {
  saving.value = true; actionError.value = ''
  try {
    const { data } = await api.configurePresence(props.testId, {
      version: draftVersion.value, enabled: enabled.value, room_id: roomId.value, require_guard: requireGuard.value,
    })
    applyConfig(data.config)
    dirty.value = false
    emit('refresh')
  }
  catch (e) { actionError.value = e?.response?.data?.error || 'Не удалось сохранить настройки. Изменение ожидает повторной отправки.' }
  finally { saving.value = false }
}
async function open(attempt) {
  if (!props.data?.attempts?.some(row => row.attempt_id === attempt.id && row.guard_admitted)) return
  selected.value = attempt
  events.value = []
  candidates.value = []
  candidateError.value = ''
  sessionId.value = clientId.value = ''
  confirmed.value = false
  await nextTick()
  dialog.value.showModal()
  loadHistory()
}
function backdropClose(event) { if (event.target === dialog.value) { const box = dialog.value.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.value.close() } }
async function loadHistory() {
  if (historyLoading.value || !selected.value) return
  const id = selected.value.id; historyLoading.value = true
  try { const result = (await api.getPresenceEvents(id)).data; if (selected.value?.id === id) { events.value = result.items; historyError.value = '' } }
  catch { if (selected.value?.id === id) historyError.value = 'Не удалось обновить журнал. Показанные события могут быть устаревшими.' }
  finally { historyLoading.value = false }
}
function bindingToggle(event) { if (event.target.open) loadCandidates() }
async function loadCandidates() {
  if (!selected.value || candidateLoading.value) return
  const id = selected.value.id; candidateLoading.value = true; candidateError.value = ''; confirmed.value = false
  try { const result = (await api.getPresenceCandidates(id)).data; if (selected.value?.id === id) { candidates.value = result.candidates; sessionId.value = '' } }
  catch (e) { if (selected.value?.id === id) candidateError.value = e?.response?.data?.error || 'Не удалось получить устройства.' }
  finally { candidateLoading.value = false }
}
async function bindDevice() {
  binding.value = true; candidateError.value = ''
  try { await api.bindPresence(selected.value.id, { session_id: sessionId.value, client_id: clientId.value, confirmed: confirmed.value }); confirmed.value = false; emit('refresh'); await loadHistory() }
  catch (e) { candidateError.value = e?.response?.data?.error || 'Не удалось подтвердить устройство.' }
  finally { binding.value = false }
}
async function review(event) {
  reviewing.value = event.id
  try { await api.reviewPresenceEvent(event.id, notes.value[event.id] || ''); await loadHistory(); emit('refresh') }
  catch { historyError.value = 'Не удалось сохранить отметку просмотра.' }
  finally { reviewing.value = null }
}
defineExpose({ open })
</script>

<style scoped>
.presence-dialog { width: min(760px, calc(100vw - 24px)); max-height: 90dvh; padding: 0; border: 1px solid var(--bs-border-color); border-radius: 12px; color: var(--bs-body-color); background: var(--bs-body-bg); }
.presence-dialog::backdrop { background: rgb(0 0 0 / 50%); }
.event-times { display: grid; grid-template-columns: minmax(120px, 1fr) 1fr; gap: 3px 12px; }
.event-times dd { margin: 0; }
@media (max-width: 480px) { .event-times { display: block; } .event-times dd { margin-bottom: 6px; } }
</style>
