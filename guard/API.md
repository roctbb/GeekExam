# Guard API v1

JSON, UTC ISO 8601. Базовый путь `/api/v1`. Ошибка: `{"error":"code"}` с HTTP 400/401/403/404/409. Учитель не получает чужие кабинеты даже по известному ID. Неизвестные поля тела отклоняются. Все пути ниже относятся к Guard.

## Браузер

`GET /auth/login` → CP `/insider/jwt?redirect_url=…` → `GET /auth/callback?state=…&token=…`. JWT HS256: `id` (целое CP ID), `name`, `role` (`student|teacher|admin`), `iat`; возраст до 60 секунд, допустимое опережение до 5 секунд. JWT принимается однократно, state действует 5 минут и связан с browser session. Если настроен audience, он обязателен.

Обязательны `iss:"codingprojects"`, `purpose:"service-login"` и `service_origin`, точно равный настроенному origin Guard. Токен другого сервиса отвергается, даже если подписан общим legacy-ключом SSO. Роль Coding Projects `novice` получает только права `student`.

`GET /api/me` возвращает пользователя и `csrf_token`. Все изменяющие browser-запросы передают `X-CSRF-Token` и cookie HttpOnly/Lax/Secure. `POST /auth/logout` завершает browser session; сетевой logout — отдельный отзыв сетевой сессии.

| Путь | Метод | Доступ / тело |
|---|---|---|
| `/rooms` | GET | Учитель: назначенные кабинеты. Админ: все |
| `/rooms` | POST | Админ: `name, description?, resources?` |
| `/rooms/{id}` | GET | Учитель кабинета / админ: роутеры, устройства, участники, настройки |
| `/rooms/{id}` | PATCH | Учитель/админ: `version, manual_restriction`. Только админ: также `name, description, resources` |
| `/rooms/{id}/members` | PUT | Админ: `version, teacher_ids, student_ids` (полная замена списков) |
| `/rooms/{id}/audit` | GET | Учитель кабинета / админ: последние 100 событий |
| `/users` | GET | Админ: каталог, синхронизированный из CP |
| `/routers` | POST | Админ: `name, room_id, segments:[{name, interface, purpose}]` |
| `/routers/{id}` | PATCH | Админ: `version, name?, room_id?`; перенос отзывает сетевые сессии |
| `/routers/{id}/enrollment` | POST | Админ: код однократного подключения, TTL 10 минут |
| `/devices/{id}/binding` | POST | Учитель/админ: `user_id, epoch, confirmed:true, seconds?` (60…28800) |
| `/sessions/{id}` | DELETE | Учитель/админ: отзыв привязки с учётом кабинета/пользователя |
| `/sessions/{id}/access` | PUT | Учитель/админ: `profile:full|platform_only, seconds:15…28800, reason` |
| `/sessions/{id}/access` | DELETE | Учитель/админ: убрать индивидуальное правило ученика |
| `/devices/{id}/override` | PUT | Только админ: `reason, seconds:null|15…2592000`; null — без срока |
| `/devices/{id}/override` | DELETE | Только админ: убрать исключение физического устройства |
| `/my-network` | GET | Текущий пользователь: только свои действующие привязки |

`resources` — массив `{ip:"195.133.49.12",port:443}`, публичный IPv4 и TCP-порт. `purpose` сегмента: `student|staff|equipment`. Интерфейс: `Bridge0`…`Bridge99`; локальный агент дополнительно сверяет его с разрешённой конфигурацией.

Не передавать непроверенный IP браузера как доказательство владения устройством. Ручная привязка требует свежей ассоциации, точного `epoch` подключения и явного подтверждения учителем. Учитель может привязать ученика своего кабинета или собственное устройство; чужого преподавателя/администратора — только администратор.

## Coding Projects → Guard

`POST /internal/identities`, Bearer JWT HS256 с отдельным `GUARD_CP_SERVICE_SECRET`.

```json
{"sub":"codingprojects","aud":"guard:identities","iat":1794902400,"exp":1794902430}
```

Тело: `{"users":[{"id":123,"name":"Имя","role":"student"}]}`, до 500 за запрос. CP формирует роль на своём сервере. JWT до 60 секунд, неповторяющиеся пользовательские секреты в нём не нужны. Отправлять из CP при входе/изменении роли и обновлять активных пользователей чаще 15 минут. При удалении/блокировке учётной записи немедленно отозвать её роль/сессии в будущем отдельном событии; текущее API не содержит статуса disabled, поэтому до добавления такого события верхняя граница устаревания — TTL 15 минут без дальнейшей синхронизации этого пользователя.

CP должен разрешить точный origin/path callback Guard и сохранять `state`. Общий секрет SSO, секрет синхронизации CP и секрет GeekExam — разные ключи. У браузера этих ключей нет.

## GeekExam → Guard

Bearer JWT HS256 с `GUARD_EXAM_SERVICE_SECRET`: `sub:"geekexam", aud:"guard:exams", iat, exp`, срок до 60 секунд. `actor_id` — текущий аутентифицированный преподаватель из **серверной** сессии GeekExam. Guard проверяет его свежую роль CP и доступ к кабинету. Этот доверенный серверный клиент не должен позволять браузеру подставлять `actor_id`.

- `PUT /internal/exams/rooms/{room_id}/restrictions/{external_id}`: `{actor_id,reason,seconds?}`. `external_id` — стабильный ID ограничения контрольной, до 100 символов. `seconds` 60…604800; без него ограничение действует до явного снятия. Повторный PUT обновляет то же ограничение.
- `DELETE` по тому же пути: `{actor_id}`. Снимает только ограничение GeekExam с этим ID. Не выключает ручной режим и другие контрольные.
- `POST /internal/presence/query`: `{actor_id,session_ids:["network-session-id"]}` до 200 ID. Возвращает `items` с `session_id`, `presence:online|offline|unknown`, `observed_at` и при действующей привязке — `device_id,router_id,room_id`. Просроченная/отозванная привязка возвращает `unknown`; доступа к чужому кабинету нет.

Сохранить `guard_network_session_id` на **попытке теста**, после подтверждения связи с устройством именно этой попытки. Нельзя выбирать «любую активную сессию пользователя» или сопоставлять по публичному IP за NAT. На ошибку API/таймаут/просрочку данных GeekExam показывает «нет свежих данных», а не «ученик отключился». Поле `observed_at` позволяет показать время последнего подтверждения.

В первой версии сетевое присутствие не доказывает, что вкладка теста открыта или ученик не пользуется мобильной сетью. Heartbeat вкладки следует показывать отдельным признаком.

## Агент → Guard

`POST /agent/enroll`, без machine key: `{code}`. Возвращает `{router_id,token}` ровно для одного роутера. Новый enrollment отзывает старый ключ и привязки. После этого `/agent/sync` и `/agent/report` требуют `Authorization: Bearer <opaque token>`. На сервере хранится хеш ключа, на агенте — файл 0600.

`POST /agent/sync`:

```json
{
  "boot_id":"fresh-process-uuid", "sequence":42,
  "complete":true, "mode":"observe", "source_age_seconds":0,
  "devices":[{"mac":"02:00:00:00:00:01","ip":"192.168.12.20","name":"Laptop","interface":"Bridge1","epoch":"connection-uuid"}],
  "capabilities":{"ipv4_filter":false,"ipv6_filter":false,"connections_revocation":false}
}
```

`boot_id` новый на запуск процесса, `sequence` монотонен внутри него. Идентичный повтор принят идемпотентно, изменённое/старое сообщение отвергается. Возврат к завершённому boot запрещён. Ошибка источника: `complete:false, devices:[], source_error:"code"`. Она не считается полным отсутствием клиентов. При смене IP/сегмента/epoch, перезапуске агента и подтверждённом отключении старая пользовательская привязка отзывается.

Ответ: `{server_time,policy,policy_hash}`. Policy содержит `schema_version:1,router_id,room_id,revision,manual_restriction,restrictions,resources,segments,devices,unknown_profile:"bootstrap"`. В `devices[].choices` находятся упорядоченные варианты `{profile,when,expires_at,requires_session,reason}`. `when` — `always|restricted|unrestricted`. Истёкший вариант пропускается локально без новой версии сервера; `requires_session:true` допускается только при совпадении MAC/IP/epoch со свежим локальным наблюдением. Исключение устройства привязано к MAC и имеет `requires_session:false`.

Хеш — SHA256 UTF-8 JSON с сортировкой ключей, без пробелов, `ensure_ascii:false`. Агент дополнительно проверяет схему, router_id и локально разрешённые интерфейсы. Политика не содержит паролей роутера или команд shell/CLI.

`POST /agent/report`: `{id:<uuid>,boot_id,revision,policy_hash,mode,verified,connections_revoked,error?}`. Только выданный этому роутеру снимок. `observe` не может сообщить `verified:true`. `connections_revoked:true` запрещён без соответствующей возможности. Одинаковый `id` идемпотентен. Успех старой версии не перекрывает новую желаемую настройку. `verified` текущего экспериментального агента означает проверку IPv4 ACL и привязки чтением, не наличие полной защиты от обхода.
