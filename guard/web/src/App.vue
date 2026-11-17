<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import Icon from "./Icon.vue";
import { initializeTheme, useTheme } from "./useTheme";

const { isDark, toggleTheme } = useTheme();
const stopTheme = initializeTheme();

const me = ref(null),
  ready = ref(false),
  rooms = ref([]),
  currentData = ref(null),
  selectedId = ref("");
const lastLoadedAt = ref(0),
  clock = ref(Date.now());
const freshData = computed(() => clock.value - lastLoadedAt.value <= 20000);
const current = computed(() => {
  const data = currentData.value;
  if (!data || freshData.value) return data;
  return {
    ...data,
    status: "unknown",
    applied_count: 0,
    devices: data.devices.map((device) => ({ ...device, presence: "unknown" })),
    routers: data.routers.map((router) => ({ ...router, status: "unknown" })),
  };
});
const tab = ref("devices"),
  search = ref(""),
  filter = ref("all"),
  error = ref(""),
  notice = ref(""),
  busy = ref(false);
const dialog = ref(null),
  form = ref({}),
  users = ref([]),
  enrollment = ref(null),
  events = ref([]);
const ownDevices = ref([]);
let interval,
  reading = false,
  reloadQueued = false,
  accountGeneration = 0;
const admin = computed(() => me.value?.role === "admin");
const online = computed(
  () =>
    (current.value?.devices || []).filter((d) => d.presence === "online")
      .length,
);
const visible = computed(() =>
  (current.value?.devices || []).filter((d) => {
    const query = search.value.toLocaleLowerCase("ru");
    return (
      (!query ||
        [d.name, d.ip, d.mac, d.user?.name, d.router_name].some((x) =>
          x?.toLocaleLowerCase("ru").includes(query),
        )) &&
      (filter.value === "all" || filter.value === "unbound"
        ? filter.value === "all" || !d.user
        : d.presence === filter.value)
    );
  }),
);
const stateNames = {
  applied: "Правила подтверждены",
  partial: "Применено частично",
  pending: "Ожидает применения",
  not_enrolled: "Агент не подключён",
  unknown: "Нет свежих данных",
  error: "Ошибка применения",
  observe: "Только наблюдение",
  empty: "Нет роутеров",
};
const profileNames = {
  full: "Полный интернет",
  platform_only: "Учебные сервисы",
  bootstrap: "Только вход",
};
const presenceNames = {
  online: "В сети",
  offline: "Отключено",
  unknown: "Данные устарели",
};
const errorNames = {
  forbidden: "Недостаточно прав для этого действия.",
  admin_required: "Это действие доступно администратору.",
  version_conflict:
    "Настройки уже изменились. Данные обновлены — повторите действие.",
  conflict_refresh_required:
    "Данные изменились одновременно с запросом. Повторите действие.",
  fresh_device_confirmation_required:
    "Устройство переподключилось или данные устарели. Обновите список.",
  identity_refresh_required:
    "Нужно обновить вход пользователя через Coding Projects.",
  active_student_session_required: "Действующая сессия ученика не найдена.",
  member_role_mismatch: "Роль выбранного пользователя не соответствует списку.",
  public_resource_ip_required: "Для сервиса нужен публичный IPv4-адрес.",
  sso_not_configured: "Вход через Coding Projects ещё не настроен.",
};
function date(value) {
  return value
    ? new Date(value).toLocaleString("ru", {
        hour: "2-digit",
        minute: "2-digit",
        day: "2-digit",
        month: "short",
      })
    : "Нет данных";
}
function clearAccount() {
  accountGeneration++;
  me.value = null;
  currentData.value = null;
  rooms.value = [];
  selectedId.value = "";
  ownDevices.value = [];
  users.value = [];
  events.value = [];
  dialog.value = null;
  enrollment.value = null;
  error.value = "";
  notice.value = "";
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(me.value?.csrf_token ? { "X-CSRF-Token": me.value.csrf_token } : {}),
      ...options.headers,
    },
  });
  const result = await response.json().catch(() => ({ error: "server_error" }));
  if (!response.ok) {
    if (response.status === 401) clearAccount();
    throw new Error(
      errorNames[result.error] ||
        (response.status === 401
          ? "Войдите через Coding Projects."
          : `Запрос не выполнен: ${result.error || response.status}`),
    );
  }
  return result;
}
async function load() {
  if (!me.value) return;
  if (reading) {
    reloadQueued = true;
    return;
  }
  reading = true;
  const generation = accountGeneration;
  try {
    const identity = await api("/api/me");
    if (generation !== accountGeneration) return;
    if (identity.role !== me.value.role) {
      clearAccount();
      me.value = identity;
      reloadQueued = true;
      return;
    }
    me.value = identity;
    if (me.value.role === "student") {
      const own = await api("/api/v1/my-network");
      if (generation === accountGeneration) {
        ownDevices.value = own.items;
        lastLoadedAt.value = clock.value = Date.now();
      }
      return;
    }
    const list = await api("/api/v1/rooms");
    if (generation !== accountGeneration) return;
    rooms.value = list.items;
    if (
      !selectedId.value ||
      !rooms.value.some((r) => r.id === selectedId.value)
    )
      selectedId.value = rooms.value[0]?.id || "";
    const roomId = selectedId.value;
    if (roomId) {
      const details = await api(`/api/v1/rooms/${roomId}`);
      if (generation !== accountGeneration || roomId !== selectedId.value)
        return;
      currentData.value = details;
      lastLoadedAt.value = clock.value = Date.now();
    } else currentData.value = null;
    if (tab.value === "audit" && current.value) {
      const journal = await api(`/api/v1/rooms/${roomId}/audit`);
      if (generation === accountGeneration && roomId === selectedId.value)
        events.value = journal.items;
    }
  } catch (e) {
    if (generation === accountGeneration) error.value = e.message;
  } finally {
    reading = false;
    if (reloadQueued) {
      reloadQueued = false;
      void load();
    }
  }
}
async function changeRoom(id) {
  selectedId.value = id;
  currentData.value = null;
  search.value = "";
  filter.value = "all";
  await load();
}
async function act(fn, message) {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await fn();
    notice.value = message;
    dialog.value = null;
    await load();
  } catch (e) {
    error.value = e.message;
    await load();
  } finally {
    busy.value = false;
  }
}
async function toggleRestriction() {
  const room = current.value;
  await act(
    () =>
      api(`/api/v1/rooms/${room.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          version: room.version,
          manual_restriction: !room.manual_restriction,
        }),
      }),
    "Настройки сохранены. Результат применения показан по каждому роутеру.",
  );
}
async function open(kind, item) {
  error.value = "";
  enrollment.value = null;
  if (kind === "members" || kind === "binding") {
    if (admin.value) {
      try {
        users.value = (await api("/api/v1/users")).items;
      } catch (e) {
        error.value = e.message;
        return;
      }
    } else
      users.value = [
        ...(current.value.students || []).map((u) => ({
          ...u,
          role: "student",
        })),
        me.value,
      ];
  }
  form.value =
    kind === "room"
      ? { name: "", description: "" }
      : kind === "router"
        ? { name: "", interface: "Bridge1", segment_name: "Учебная сеть" }
        : kind === "members"
          ? {
              teacher_ids: [...current.value.teacher_ids],
              student_ids: current.value.students.map((s) => s.id),
            }
          : kind === "resources"
            ? {
                endpoints: current.value.resources
                  .map((r) => `${r.ip}:${r.port}`)
                  .join("\n"),
              }
            : kind === "binding"
              ? { device: item, user_id: "", confirmed: false }
              : kind === "access"
                ? { device: item, profile: "full", minutes: 10, reason: "" }
                : kind === "override"
                  ? {
                      device: item,
                      reason: item.override?.reason || "",
                      minutes: 0,
                    }
                  : kind === "move"
                    ? { router: item, room_id: item.room_id }
                    : {};
  dialog.value = kind;
}
async function save() {
  const f = form.value,
    room = current.value,
    kind = dialog.value;
  await act(async () => {
    if (kind === "room") {
      const created = await api("/api/v1/rooms", {
        method: "POST",
        body: JSON.stringify({ name: f.name, description: f.description }),
      });
      selectedId.value = created.id;
    } else if (kind === "router") {
      await api("/api/v1/routers", {
        method: "POST",
        body: JSON.stringify({
          name: f.name,
          room_id: room.id,
          segments: [
            {
              name: f.segment_name,
              interface: f.interface,
              purpose: "student",
            },
          ],
        }),
      });
    } else if (kind === "members") {
      await api(`/api/v1/rooms/${room.id}/members`, {
        method: "PUT",
        body: JSON.stringify({
          version: room.version,
          teacher_ids: f.teacher_ids,
          student_ids: f.student_ids,
        }),
      });
    } else if (kind === "resources") {
      const resources = f.endpoints
        .split("\n")
        .filter((x) => x.trim())
        .map((line) => {
          const [ip, port] = line.trim().split(":");
          return { ip, port: Number(port) };
        });
      await api(`/api/v1/rooms/${room.id}`, {
        method: "PATCH",
        body: JSON.stringify({ version: room.version, resources }),
      });
    } else if (kind === "binding") {
      await api(`/api/v1/devices/${f.device.id}/binding`, {
        method: "POST",
        body: JSON.stringify({
          user_id: Number(f.user_id),
          epoch: f.device.epoch,
          confirmed: f.confirmed,
        }),
      });
    } else if (kind === "access") {
      await api(`/api/v1/sessions/${f.device.session_id}/access`, {
        method: "PUT",
        body: JSON.stringify({
          profile: f.profile,
          seconds: Number(f.minutes) * 60,
          reason: f.reason,
        }),
      });
    } else if (kind === "override") {
      await api(`/api/v1/devices/${f.device.id}/override`, {
        method: "PUT",
        body: JSON.stringify({
          reason: f.reason,
          seconds: Number(f.minutes) ? Number(f.minutes) * 60 : null,
        }),
      });
    } else if (kind === "move") {
      await api(`/api/v1/routers/${f.router.id}`, {
        method: "PATCH",
        body: JSON.stringify({ version: f.router.version, room_id: f.room_id }),
      });
    }
  }, "Изменение сохранено. Ожидается подтверждение агента.");
}
async function enroll(router) {
  busy.value = true;
  error.value = "";
  try {
    enrollment.value = await api(`/api/v1/routers/${router.id}/enrollment`, {
      method: "POST",
    });
    dialog.value = "enroll";
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function removeAccess(device) {
  await act(
    () =>
      api(`/api/v1/sessions/${device.session_id}/access`, { method: "DELETE" }),
    "Индивидуальное правило отозвано.",
  );
}
async function removeOverride(device) {
  await act(
    () => api(`/api/v1/devices/${device.id}/override`, { method: "DELETE" }),
    "Исключение устройства отозвано.",
  );
}
async function revoke(device) {
  await act(
    () => api(`/api/v1/sessions/${device.session_id}`, { method: "DELETE" }),
    "Привязка пользователя отозвана.",
  );
}
async function logout() {
  try {
    await api("/auth/logout", { method: "POST" });
    clearAccount();
  } catch (e) {
    error.value = e.message;
  }
}
async function setTab(value) {
  tab.value = value;
  if (value === "audit") await load();
}
onMounted(async () => {
  try {
    me.value = await api("/api/me");
    await load();
  } catch (e) {
    if (!e.message.includes("Войдите")) error.value = e.message;
  }
  ready.value = true;
  interval = setInterval(() => {
    clock.value = Date.now();
    void load();
  }, 5000);
});
onUnmounted(() => {
  clearInterval(interval);
  stopTheme();
});
</script>

<template>
  <div class="app-shell">
    <header class="global-nav">
      <div class="nav-inner">
        <a class="brand" href="/">Geek<span>Guard</span></a
        ><span class="brand-description">Управление доступом</span>
        <div class="nav-account">
          <button
            class="nav-button theme-toggle"
            :aria-label="
              isDark ? 'Включить светлую тему' : 'Включить тёмную тему'
            "
            @click="toggleTheme"
          >
            <Icon :name="isDark ? 'sun' : 'moon'" /><span>{{
              isDark ? "Светлая тема" : "Тёмная тема"
            }}</span>
          </button>
          <div v-if="me" class="account">
            <span class="avatar">{{ me.name[0] }}</span
            ><span class="account-name"
              >{{ me.name
              }}<small>{{
                admin
                  ? "Администратор"
                  : me.role === "teacher"
                    ? "Преподаватель"
                    : "Ученик"
              }}</small></span
            ><button class="nav-button" aria-label="Выйти" @click="logout">
              <Icon name="logout" />
            </button>
          </div>
        </div>
      </div>
    </header>
    <div :class="['workspace', { 'no-sidebar': !me || me.role === 'student' }]">
      <aside v-if="me && me.role !== 'student'" class="sidebar">
        <div class="sidebar-label">
          Кабинеты <span class="nav-count">{{ rooms.length }}</span>
        </div>
        <div class="room-nav">
          <button
            v-for="room in rooms"
            :key="room.id"
            :class="['room-link', { active: selectedId === room.id }]"
            @click="changeRoom(room.id)"
          >
            <Icon name="room" /><span>Кабинет {{ room.name }}</span
            ><span class="room-router-count">{{ room.router_count }}</span>
          </button>
        </div>
        <button v-if="admin" class="sidebar-add" @click="open('room')">
          <Icon name="plus" /> Добавить кабинет
        </button>
        <div class="sidebar-bottom">Роутеры и устройства<br />по кабинетам</div>
      </aside>

      <main class="main">
        <div v-if="me?.demo" class="demo-banner">
          Демонстрационные данные · Реальные роутеры не управляются
        </div>
        <section v-if="!ready" class="empty-state">
          <h1>Загрузка Guard…</h1>
        </section>
        <section v-else-if="!me" class="login-screen">
          <div class="login-symbol"><Icon name="router" /></div>
          <h1>Доступ к учебной сети</h1>
          <p>Кабинеты, подключения учеников и правила доступа к интернету.</p>
          <a class="button primary" href="/auth/login"
            ><Icon name="login" />Войти через Coding Projects</a
          >
          <p class="muted">Используется ваша учётная запись Coding Projects.</p>
        </section>
        <section v-else-if="me.role === 'student'" class="empty-state panel">
          <h1>Мой доступ</h1>
          <p>Ваши устройства с действующей сетевой авторизацией.</p>
          <div class="student-networks">
            <article v-for="device in ownDevices" :key="device.id">
              <strong>{{ device.name || device.ip }}</strong>
              <p>
                {{ presenceNames[freshData ? device.presence : "unknown"] }} ·
                {{ profileNames[device.profile] }}
              </p>
              <small>{{ device.reason }}</small>
            </article>
          </div>
          <p v-if="!ownDevices.length">
            Привязанных устройств пока нет. Обратитесь к преподавателю.
          </p>
        </section>
        <section v-else class="content">
          <div class="page-heading">
            <div>
              <h1>
                {{ current ? `Кабинет ${current.name}` : "Ваши кабинеты" }}
              </h1>
              <p>
                {{
                  current?.description ||
                  "Подключения, разрешения и состояние учебной сети."
                }}
              </p>
            </div>
            <button class="button" :disabled="busy" @click="load">
              <Icon name="refresh" /> Обновить
            </button>
          </div>
          <div v-if="error" class="alert error" role="alert">
            {{ error }}<button @click="error = ''">×</button>
          </div>
          <div v-if="notice" class="alert success" role="status">
            {{ notice }}<button @click="notice = ''">×</button>
          </div>
          <div v-if="!current" class="empty-state panel">
            <div class="empty-icon"><Icon name="room" /></div>
            <h2>Кабинеты ещё не добавлены</h2>
            <p>
              {{
                admin
                  ? "Создайте кабинет, затем добавьте его роутеры и назначьте преподавателей."
                  : "Администратор назначит вам доступ к кабинетам."
              }}
            </p>
            <button v-if="admin" class="button primary" @click="open('room')">
              Добавить кабинет
            </button>
          </div>
          <template v-else>
            <div class="stats-grid">
              <div class="stat-card">
                <span class="stat-label">Устройства в сети</span>
                <div class="stat-number">
                  {{ online }}<span>/ {{ current.devices.length }}</span>
                </div>
                <span class="stat-foot">По свежим данным роутеров</span>
              </div>
              <div class="stat-card">
                <span class="stat-label">Роутеры кабинета</span>
                <div class="stat-number">{{ current.router_count }}</div>
                <span class="stat-foot">Применяют правила отдельно</span>
              </div>
              <div class="stat-card">
                <span class="stat-label">Правила применены</span>
                <div class="stat-number">
                  {{ current.applied_count
                  }}<span>/ {{ current.router_count }}</span>
                </div>
                <span
                  :class="[
                    'stat-foot',
                    { warning: current.status !== 'applied' },
                  ]"
                  >{{ stateNames[current.status] }}</span
                >
              </div>
            </div>
            <section
              :class="['policy-card', { restricted: current.restricted }]"
            >
              <div class="policy-symbol">
                <Icon :name="current.restricted ? 'lock' : 'unlock'" />
              </div>
              <div class="policy-copy">
                <h2>
                  {{
                    current.restricted
                      ? "Учебный режим включён"
                      : "Обычный режим доступа"
                  }}
                </h2>
                <p>
                  {{
                    current.restricted
                      ? "Авторизованным ученикам доступны только учебные сервисы."
                      : "Авторизованным ученикам доступен полный интернет."
                  }}
                </p>
                <small
                  >Преподаватели и устройства с действующими исключениями
                  сохраняют полный доступ.</small
                >
                <div
                  v-if="current.restrictions.length"
                  class="restriction-tags"
                >
                  <span v-for="lock in current.restrictions" :key="lock.id"
                    >Контрольная: {{ lock.reason }}</span
                  >
                </div>
              </div>
              <div class="policy-control">
                <button
                  :class="['switch', { on: current.manual_restriction }]"
                  role="switch"
                  :aria-checked="current.manual_restriction"
                  aria-label="Ручное ограничение интернета"
                  :disabled="busy"
                  @click="toggleRestriction"
                >
                  <span></span></button
                ><small>Ручное ограничение</small>
              </div>
            </section>
            <div class="section-toolbar">
              <div class="tabs">
                <button
                  :class="{ active: tab === 'devices' }"
                  @click="setTab('devices')"
                >
                  Устройства <span>{{ current.devices.length }}</span></button
                ><button
                  :class="{ active: tab === 'routers' }"
                  @click="setTab('routers')"
                >
                  Роутеры <span>{{ current.router_count }}</span></button
                ><button
                  :class="{ active: tab === 'audit' }"
                  @click="setTab('audit')"
                >
                  Журнал
                </button>
              </div>
              <div v-if="admin" class="toolbar-actions">
                <button class="text-button" @click="open('members')">
                  Участники</button
                ><button class="text-button" @click="open('resources')">
                  Учебные сервисы
                </button>
              </div>
            </div>
            <section v-if="tab === 'devices'" class="panel devices-panel">
              <div class="list-toolbar">
                <label class="search"
                  ><Icon name="search" /><input
                    v-model="search"
                    aria-label="Поиск устройств"
                    placeholder="Пользователь, устройство или IP" /></label
                ><select v-model="filter" aria-label="Фильтр устройств">
                  <option value="all">Все устройства</option>
                  <option value="online">В сети</option>
                  <option value="offline">Отключены</option>
                  <option value="unknown">Данные устарели</option>
                  <option value="unbound">Без пользователя</option></select
                ><span class="live-note"
                  ><span class="small-dot green"></span> Обновление каждые 5
                  сек.</span
                >
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Устройство / пользователь</th>
                      <th>Подключение</th>
                      <th>Состояние</th>
                      <th>Назначенный доступ</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="device in visible" :key="device.id">
                      <td>
                        <div class="device-cell">
                          <span class="device-icon"
                            ><Icon
                              :name="
                                device.name?.includes('Принтер')
                                  ? 'printer'
                                  : 'laptop'
                              "
                          /></span>
                          <div>
                            <strong>{{
                              device.user?.name ||
                              device.name ||
                              "Устройство без имени"
                            }}</strong
                            ><small>{{
                              device.user
                                ? device.name
                                : "Пользователь не привязан"
                            }}</small>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span class="mono">{{
                          device.ip || "IP ещё не определён"
                        }}</span
                        ><small>{{ device.router_name }}</small>
                      </td>
                      <td>
                        <span :class="['presence', device.presence]"
                          ><span class="small-dot"></span
                          >{{ presenceNames[device.presence] }}</span
                        ><small>{{ date(device.observed_at) }}</small>
                      </td>
                      <td>
                        <span :class="['access-badge', device.profile]">{{
                          profileNames[device.profile]
                        }}</span
                        ><small class="reason">{{ device.reason }}</small>
                      </td>
                      <td>
                        <details class="actions">
                          <summary aria-label="Действия с устройством">
                            <Icon name="more" />
                          </summary>
                          <div class="action-menu">
                            <button
                              v-if="device.presence === 'online'"
                              @click="open('binding', device)"
                            >
                              {{
                                device.session_id
                                  ? "Сменить пользователя"
                                  : "Привязать пользователя"
                              }}</button
                            ><button
                              v-if="device.user?.role === 'student'"
                              @click="open('access', device)"
                            >
                              Доступ ученика</button
                            ><button
                              v-if="device.student_rule"
                              @click="removeAccess(device)"
                            >
                              Снять правило ученика</button
                            ><button
                              v-if="device.session_id"
                              @click="revoke(device)"
                            >
                              Отозвать привязку</button
                            ><button
                              v-if="admin"
                              @click="open('override', device)"
                            >
                              Исключение устройства</button
                            ><button
                              v-if="admin && device.override"
                              @click="removeOverride(device)"
                            >
                              Удалить исключение
                            </button>
                          </div>
                        </details>
                      </td>
                    </tr>
                    <tr v-if="!visible.length">
                      <td colspan="5" class="table-empty">
                        {{
                          search || filter !== "all"
                            ? "По этому запросу устройств нет."
                            : "Устройства появятся после подключения агента."
                        }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="table-footer">
                Назначенный доступ применяется после подтверждения роутера.<span
                  >Всего: {{ visible.length }}</span
                >
              </div>
            </section>
            <section v-if="tab === 'routers'" class="router-grid">
              <article
                v-for="router in current.routers"
                :key="router.id"
                class="panel router-card"
              >
                <div class="router-card-top">
                  <span class="device-icon"><Icon name="router" /></span
                  ><span :class="['status-badge', router.status]">{{
                    stateNames[router.status]
                  }}</span>
                </div>
                <h2>{{ router.name }}</h2>
                <p>
                  {{ router.model || "Ожидает подключения агента" }}
                  {{ router.firmware }}
                </p>
                <dl>
                  <div>
                    <dt>Последняя связь</dt>
                    <dd>{{ date(router.last_seen) }}</dd>
                  </div>
                  <div>
                    <dt>Версия правил</dt>
                    <dd>
                      {{ router.applied_revision ?? "—" }} /
                      {{ router.desired_revision }}
                    </dd>
                  </div>
                  <div>
                    <dt>Сети</dt>
                    <dd>{{ router.segments.map((s) => s.name).join(", ") }}</dd>
                  </div>
                </dl>
                <p v-if="router.error" class="warning">{{ router.error }}</p>
                <p
                  v-if="
                    router.capabilities.ipv4_filter &&
                    !router.capabilities.connections_revocation
                  "
                  class="capability-note"
                >
                  Поддерживается фильтрация новых IPv4-соединений. Отзыв старых
                  соединений не подтверждён.
                </p>
                <div v-if="admin" class="router-actions">
                  <button class="button" @click="enroll(router)">
                    Подключить агента</button
                  ><button class="text-button" @click="open('move', router)">
                    Перенести
                  </button>
                </div>
              </article>
              <button
                v-if="admin"
                class="panel add-router"
                @click="open('router')"
              >
                <Icon name="plus" />Добавить роутер в кабинет
              </button>
            </section>
            <section v-if="tab === 'audit'" class="panel audit-list">
              <article v-for="event in events" :key="event.id">
                <span class="event-dot"></span>
                <div>
                  <strong>{{ event.actor }}</strong>
                  <p>{{ event.event }}</p>
                  <small>{{ date(event.created_at) }}</small>
                </div>
                <span class="event-target mono">{{
                  event.details.revision
                    ? `Версия ${event.details.revision}`
                    : event.details.profile
                      ? profileNames[event.details.profile]
                      : ""
                }}</span>
              </article>
              <p v-if="!events.length" class="table-empty">Событий пока нет.</p>
            </section>
            <div class="page-footnote">
              Guard показывает подтверждённое состояние каждого роутера. При
              потере связи данные отмечаются как устаревшие.
            </div>
          </template>
        </section>
      </main>
    </div>

    <div v-if="dialog" class="modal-backdrop" @click.self="dialog = null">
      <section
        class="modal"
        role="dialog"
        aria-modal="true"
        :aria-label="
          {
            room: 'Новый кабинет',
            router: 'Новый роутер',
            members: 'Участники кабинета',
            resources: 'Учебные сервисы',
            binding: 'Привязка пользователя',
            access: 'Доступ ученика',
            override: 'Исключение устройства',
            enroll: 'Подключение агента',
            move: 'Перенос роутера',
          }[dialog]
        "
      >
        <button class="modal-close" aria-label="Закрыть" @click="dialog = null">
          <Icon name="close" />
        </button>
        <div class="eyebrow">GEEKCLASS GUARD</div>
        <h2>
          {{
            {
              room: "Новый кабинет",
              router: "Новый роутер",
              members: "Участники кабинета",
              resources: "Учебные сервисы",
              binding: "Привязка пользователя",
              access: "Доступ ученика",
              override: "Исключение устройства",
              enroll: "Подключение агента",
              move: "Перенос роутера",
            }[dialog]
          }}
        </h2>
        <div v-if="error" class="alert error">{{ error }}</div>
        <form v-if="dialog !== 'enroll'" @submit.prevent="save">
          <template v-if="dialog === 'room'"
            ><label
              >Название кабинета<input
                v-model="form.name"
                required
                maxlength="100"
                placeholder="Например, 409" /></label
            ><label
              >Описание<input
                v-model="form.description"
                maxlength="500"
                placeholder="Учебная сеть информатики" /></label
          ></template>
          <template v-if="dialog === 'router'"
            ><label
              >Название роутера<input
                v-model="form.name"
                required
                maxlength="100"
                placeholder="Основной роутер" /></label
            ><label
              >Название учебной сети<input
                v-model="form.segment_name"
                required
                maxlength="100" /></label
            ><label
              >Интерфейс учебного сегмента<input
                v-model="form.interface"
                required
                pattern="Bridge[0-9]{1,2}"
            /></label>
            <p class="muted">
              Укажите отдельно подготовленный учебный сегмент. Добавление
              роутера само по себе не меняет его настройки.
            </p></template
          >
          <template v-if="dialog === 'members'"
            ><label
              >Преподаватели<select
                v-model="form.teacher_ids"
                multiple
                size="4"
              >
                <option
                  v-for="u in users.filter((u) => u.role === 'teacher')"
                  :key="u.id"
                  :value="u.id"
                >
                  {{ u.name }}
                </option>
              </select></label
            ><label
              >Ученики<select v-model="form.student_ids" multiple size="6">
                <option
                  v-for="u in users.filter((u) => u.role === 'student')"
                  :key="u.id"
                  :value="u.id"
                >
                  {{ u.name }}
                </option>
              </select></label
            >
            <p class="muted">
              Список пользователей приходит из Coding Projects. Роли здесь не
              редактируются.
            </p></template
          >
          <template v-if="dialog === 'resources'"
            ><label
              >Разрешённые серверы<textarea
                v-model="form.endpoints"
                rows="5"
                required
                placeholder="195.133.49.12:443"
              ></textarea>
            </label>
            <p class="muted">
              Один IPv4 и TCP-порт на строку. Все HTTPS-приложения на
              разрешённом IP будут доступны.
            </p></template
          >
          <template v-if="dialog === 'binding'"
            ><p>{{ form.device.name }} · {{ form.device.ip }}</p>
            <label
              >Пользователь<select v-model="form.user_id" required>
                <option value="" disabled>Выберите пользователя</option>
                <option v-for="u in users" :key="u.id" :value="u.id">
                  {{ u.name }}{{ u.role === "student" ? "" : " · сотрудник" }}
                </option>
              </select></label
            ><label class="checkbox-label"
              ><input type="checkbox" v-model="form.confirmed" required />Я
              проверил, что это устройство выбранного пользователя.</label
            >
            <p class="muted">
              Ручная привязка действует для текущего подключения. Автоматический
              вход через Wi-Fi-портал появится отдельным этапом.
            </p></template
          >
          <template v-if="dialog === 'access'"
            ><p>{{ form.device.user?.name }} · {{ form.device.ip }}</p>
            <label
              >Доступ<select v-model="form.profile">
                <option value="full">Полный интернет</option>
                <option value="platform_only">Только учебные сервисы</option>
              </select></label
            ><label
              >Длительность, минут<input
                type="number"
                v-model="form.minutes"
                required
                min="1"
                max="480" /></label
            ><label
              >Причина<input
                v-model="form.reason"
                required
                maxlength="300"
                placeholder="Например, работа с документацией" /></label
          ></template>
          <template v-if="dialog === 'override'"
            ><p>{{ form.device.name }} · {{ form.device.ip }}</p>
            <label
              >Причина полного доступа<input
                v-model="form.reason"
                required
                maxlength="300"
                placeholder="Например, принтер кабинета" /></label
            ><label
              >Длительность, минут<input
                type="number"
                v-model="form.minutes"
                required
                min="0"
                max="43200"
            /></label>
            <p class="muted">
              0 — до явного отзыва. Исключение действует независимо от
              ученических ограничений и авторизации пользователя.
            </p></template
          >
          <template v-if="dialog === 'move'"
            ><p>{{ form.router.name }}</p>
            <label
              >Кабинет<select v-model="form.room_id">
                <option v-for="room in rooms" :key="room.id" :value="room.id">
                  Кабинет {{ room.name }}
                </option>
              </select></label
            >
            <p class="muted">
              При переносе текущие привязки пользователей этого роутера будут
              отозваны.
            </p></template
          >
          <footer class="modal-actions">
            <button type="button" class="button" @click="dialog = null">
              Отмена</button
            ><button class="button primary" :disabled="busy">
              {{ busy ? "Сохранение…" : "Сохранить" }}
            </button>
          </footer>
        </form>
        <template v-else
          ><p>
            Одноразовый код связывает агента с выбранным роутером. Действителен
            до {{ date(enrollment.expires_at) }}.
          </p>
          <textarea
            class="enrollment-code"
            readonly
            rows="3"
            :value="enrollment.code"
            aria-label="Одноразовый код агента"
          ></textarea>
          <p class="muted">
            При подключении нового агента прежний машинный ключ будет отозван.
            Код показывается один раз.
          </p>
          <footer class="modal-actions">
            <button class="button primary" @click="dialog = null">
              Готово
            </button>
          </footer></template
        >
      </section>
    </div>
  </div>
</template>
