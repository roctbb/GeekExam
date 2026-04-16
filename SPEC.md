# GeekExam — Техническое задание

## 1. Обзор проекта

GeekExam — платформа для проведения тестов по информатике в школе. Интегрируется с CodingProjects (codingprojects.ru) через JWT-авторизацию. Использует GeekPasteV2 как сервис проверки кода (через API с callback).

### Стек технологий

- **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-SocketIO, Celery
- **Frontend:** Vue 3 + Bootstrap 5
- **БД:** PostgreSQL
- **Очереди:** Redis + Celery
- **Контейнеризация:** Docker Compose (Flask + Vue + PostgreSQL + Redis)
- **Проверка кода:** Делегируется в GeekPasteV2 через API

---

## 2. Роли пользователей

| Роль | Источник | Возможности |
|------|----------|-------------|
| `student` | JWT из CodingProjects | Ввод кода теста, прохождение теста, просмотр результатов |
| `teacher` | JWT из CodingProjects | Управление тестами (CRUD, загрузка JSON), запуск/остановка, просмотр результатов учеников |
| `admin` | JWT из CodingProjects | Всё что teacher + управление системой |

---

## 3. Авторизация

Механизм идентичен GeekPasteV2:

1. Пользователь перенаправляется на `{GEEKCLASS_HOST}/insider/jwt?redirect_url={url}`
2. CodingProjects возвращает JWT-токен в query-параметре `token`
3. Backend декодирует JWT с помощью `JWT_SECRET` (алгоритм HS256)
4. Из токена извлекаются: `id`, `role` (student/teacher/admin), `name`
5. Данные сохраняются в Flask session
6. Имя пользователя сохраняется/обновляется в таблице `users` при каждой авторизации
7. Проверка `iat` — токен валиден не более 5 секунд

```python
# Структура JWT payload
{
    "id": 123,
    "role": "student",  # | "teacher" | "admin"
    "name": "Иван Иванов",
    "iat": 1713272000
}
```

---

## 4. Модель данных (PostgreSQL)

### 4.1. User (пользователь)

```
users
├── id              (PK, Integer — id из CodingProjects, НЕ autoincrement)
├── name            (String — имя из JWT, обновляется при каждой авторизации)
├── role            (String — последняя известная роль)
└── last_login      (DateTime)
```

### 4.2. Test (тест)

```
tests
├── id              (PK, Integer, autoincrement)
├── title           (String, название теста)
├── description     (Text, описание, Markdown)
├── code            (String, unique, nullable — код доступа к тесту, например "ABC123")
├── time_limit      (Integer, nullable — ограничение по времени в минутах, null = без лимита)
├── is_active       (Boolean, default=false — запущен ли тест)
├── created_by      (Integer, FK → users.id — учитель)
├── created_at      (DateTime)
├── updated_at      (DateTime)
└── source_json     (Text — оригинальный JSON теста для экспорта)
```

### 4.3. Variant (вариант теста)

```
variants
├── id              (PK, Integer)
├── test_id         (FK → tests.id)
├── title           (String, например "Вариант 1")
└── order           (Integer — порядок)
```

Тест содержит один или несколько вариантов. Сумма максимальных баллов по вопросам одинакова во всех вариантах.

### 4.4. Question (вопрос)

```
questions
├── id              (PK, Integer)
├── variant_id      (FK → variants.id)
├── order           (Integer — порядок вопроса в варианте)
├── type            (String — тип вопроса: "text_input", "code_input", "true_false_table", "interactive")
├── title           (String — краткое название)
├── body            (Text — текст задания в Markdown, картинки по внешним URL)
├── max_points      (Integer — максимальный балл)
├── check_type      (String — тип проверки: "exact", "checker", "ai", "docker", "manual")
├── check_config    (JSON — конфигурация проверки, зависит от check_type)
├── ui_config       (JSON — конфигурация отображения, зависит от type)
└── allow_intermediate_check (Boolean, default=false — доступна ли промежуточная проверка)
```

### 4.5. Attempt (попытка прохождения теста)

```
attempts
├── id              (PK, Integer)
├── test_id         (FK → tests.id)
├── variant_id      (FK → variants.id)
├── user_id         (FK → users.id — ученик)
├── started_at      (DateTime)
├── finished_at     (DateTime, nullable — null = тест ещё идёт)
├── is_checked      (Boolean, default=false — все ответы проверены)
├── total_points    (Integer, nullable — итоговый балл)
└── max_points      (Integer — максимально возможный балл)
```

Ограничение: один ученик может пройти один вариант только один раз (`UniqueConstraint(user_id, variant_id)`). Вариант выбирается случайно из тех, которые ученик ещё не проходил.

### 4.6. Answer (ответ на вопрос)

```
answers
├── id              (PK, Integer)
├── attempt_id      (FK → attempts.id)
├── question_id     (FK → questions.id)
├── value           (JSON — ответ ученика, формат зависит от типа вопроса)
├── points          (Integer, nullable — начисленные баллы, null = не проверено)
├── check_state     (String — "pending", "checking", "checked", "error")
├── check_comment   (Text, nullable — комментарий проверки)
└── updated_at      (DateTime)
```

---

## 5. Типы вопросов (расширяемая система)

Система типов вопросов построена как плагинная архитектура. Каждый тип — отдельный Vue-компонент на фронте + обработчик проверки на бэке.

### 5.1. Регистрация типа вопроса

На бэкенде — словарь `QUESTION_TYPES`, где ключ — строковый идентификатор типа, значение — класс-обработчик с методами `validate_answer(answer, config)` и `check(answer, config)`.

На фронте — маппинг `type → Vue-компонент` для рендеринга.

### 5.2. Базовые типы (первая итерация)

#### `text_input` — Ввод текстового ответа

- **UI:** Текстовое поле (однострочное или многострочное, задаётся в `ui_config`)
- **answer value:** `{"text": "ответ ученика"}`
- **check_config для exact:** `{"answer": "правильный ответ", "case_sensitive": false, "trim": true}`
- **check_config для ai:** `{"prompt": "...", "answer": "эталон"}`

#### `code_input` — Ввод кода

- **UI:** Код-редактор (CodeMirror/Monaco), язык задаётся в `ui_config.lang`
- **answer value:** `{"code": "print('hello')", "lang": "python"}`
- **check_type:** `docker` или `checker`
- **check_config для docker:** `{"lang": "python", "tests": [...]}` — делегирует проверку в GeekPasteV2, передавая текст задания и тесты
- **Поддерживает промежуточную проверку** (`allow_intermediate_check: true`)

#### `true_false_table` — Таблица утверждений (верно/неверно)

- **UI:** Таблица с утверждениями, для каждого — переключатель "Верно" / "Неверно"
- **ui_config:** `{"statements": ["Утверждение 1", "Утверждение 2", ...]}`
- **answer value:** `{"answers": [true, false, true, ...]}`
- **check_config:** `{"correct": [true, false, true, ...], "partial_scoring": true}`
- При `partial_scoring: true` — баллы пропорционально количеству правильных ответов

#### `interactive` — Интерактивный вопрос (например, Brainfuck-отладчик)

- **UI:** Кастомный Vue-компонент, указанный в `ui_config.component`
- **answer value:** Произвольный JSON, определяемый компонентом
- **check_type:** Любой поддерживаемый

### 5.3. Добавление нового типа

1. Создать Vue-компонент в `frontend/src/components/questions/`
2. Зарегистрировать в маппинге `questionComponents`
3. Создать класс-обработчик в `backend/checkers/question_types/`
4. Зарегистрировать в `QUESTION_TYPES`

---

## 6. Типы проверки (расширяемая система)

Аналогично типам вопросов — плагинная архитектура. Каждый тип проверки — класс с методом `check(answer_value, check_config) → (points, comment)`.

### 6.1. `exact` — Сравнение с эталоном

- Для `text_input`: сравнивает `answer_value.text` с `check_config.answer`. Поддержка: `case_sensitive`, `trim`, `normalize_whitespace`
- Для `true_false_table`: сравнивает `answer_value.answers` с `check_config.correct`. При `partial_scoring` — баллы пропорционально
- Возвращает от `0` до `max_points`

### 6.2. `checker` — Проверяющая программа

- Python-функция в `check_config.checker_code` или файл `check_config.checker_path`
- Функция принимает ответ ученика, возвращает `(points, comment)`
- Выполняется на сервере GeekExam

### 6.3. `ai` — Нейросетевая проверка (через GeekPasteV2)

- Делегируется в GeekPasteV2 через тот же `POST /api/external/check`
- Работает как для кода (`code_input`), так и для текстовых ответов (`text_input`)
- `check_config`: `{"prompt": "Оцени ответ...", "answer": "эталонный ответ"}` — текст задания и эталон передаются в GeekPasteV2
- Результат приходит через callback
- GeekExam не хранит GPT-ключи — вся AI-логика в GeekPasteV2

### 6.4. `docker` — Запуск кода в Docker (через GeekPasteV2 API)

- GeekExam отправляет код ученика в GeekPasteV2 через новый API-эндпоинт
- GeekPasteV2 запускает код в Docker-контейнере, прогоняет тесты
- По завершении GeekPasteV2 отправляет callback на GeekExam с результатом
- Асинхронная проверка

#### Новый API в GeekPasteV2:

```
POST /api/external/check
Content-Type: application/json
Authorization: Bearer {JWT подписанный общим JWT_SECRET}

{
    "callback_url": "https://auditor.geekclass.ru/api/callback/check",
    "callback_id": "answer_123",
    "code": "print('hello')",
    "lang": "python",
    "task_text": "Напишите функцию add(a, b), которая возвращает сумму двух чисел.",
    "check_type": "tests",
    "check_config": { ... }
}

Response: {"status": "queued", "job_id": "..."}
```

```
POST {callback_url}  (от GeekPasteV2 → GeekExam)
{
    "callback_id": "answer_123",
    "job_id": "...",
    "status": "success" | "error",
    "points": 8,
    "max_points": 10,
    "comment": "8 из 10 тестов пройдено",
    "details": [...]
}
```

### 6.5. `manual` — Ручная проверка учителем

- Ответ сохраняется, `check_state = "pending"`
- Учитель видит ответ в панели и выставляет баллы вручную

### 6.6. Добавление нового типа проверки

1. Создать класс в `backend/checkers/check_types/`
2. Реализовать метод `check(answer_value, check_config) → (points, comment)`
3. Зарегистрировать в `CHECK_TYPES`

---

## 7. Формат JSON описания теста

```json
{
  "title": "Контрольная по Python",
  "description": "Итоговая контрольная за 1 полугодие",
  "time_limit": 45,
  "variants": [
    {
      "title": "Вариант 1",
      "questions": [
        {
          "type": "text_input",
          "title": "Что выведет программа?",
          "body": "```python\nprint(2 + 2)\n```\n\nВведите результат выполнения программы.",
          "max_points": 2,
          "check_type": "exact",
          "check_config": {
            "answer": "4",
            "trim": true
          },
          "ui_config": {
            "multiline": false
          }
        },
        {
          "type": "true_false_table",
          "title": "Утверждения о Python",
          "body": "Определите, верны ли следующие утверждения:",
          "max_points": 4,
          "check_type": "exact",
          "check_config": {
            "correct": [true, false, true, false],
            "partial_scoring": true
          },
          "ui_config": {
            "statements": [
              "Python — интерпретируемый язык",
              "В Python индексация начинается с 1",
              "Списки в Python мутабельны",
              "Python не поддерживает ООП"
            ]
          }
        },
        {
          "type": "code_input",
          "title": "Напишите функцию сложения",
          "body": "Напишите функцию `add(a, b)`, которая возвращает сумму двух чисел.",
          "max_points": 5,
          "check_type": "docker",
          "check_config": {
            "lang": "python",
            "tests": [
              {"input": "print(add(2, 3))", "expected": "5"},
              {"input": "print(add(-1, 1))", "expected": "0"}
            ]
          },
          "ui_config": {
            "lang": "python",
            "starter_code": "def add(a, b):\n    pass"
          },
          "allow_intermediate_check": true
        }
      ]
    },
    {
      "title": "Вариант 2",
      "questions": [
        "..."
      ]
    }
  ]
}
```

### Валидация JSON

При загрузке JSON бэкенд проверяет:
- Наличие обязательных полей
- Все `type` и `check_type` зарегистрированы в системе
- Сумма `max_points` одинакова во всех вариантах
- `check_config` и `ui_config` валидны для указанных типов

---

## 8. API эндпоинты (Backend, Flask)

### 8.1. Авторизация

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/auth/login` | Редирект на CodingProjects JWT |
| GET | `/auth/callback?token=...` | Обработка JWT, сохранение в session |
| GET | `/auth/logout` | Очистка session |
| GET | `/api/me` | Текущий пользователь (id, role) |

### 8.2. Тесты (teacher/admin)

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/tests` | Список всех тестов |
| POST | `/api/tests` | Создать тест (загрузка JSON) |
| GET | `/api/tests/:id` | Детали теста |
| PUT | `/api/tests/:id` | Обновить тест (перезагрузка JSON) |
| DELETE | `/api/tests/:id` | Удалить тест |
| POST | `/api/tests/:id/activate` | Запустить тест (is_active=true) |
| POST | `/api/tests/:id/deactivate` | Остановить тест |
| PUT | `/api/tests/:id/code` | Установить/изменить код доступа |

### 8.3. Результаты (teacher/admin)

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/tests/:id/attempts` | Список попыток по тесту (ученики + баллы) |
| GET | `/api/attempts/:id` | Детали попытки (ответы, баллы, комментарии) |
| PUT | `/api/answers/:id/grade` | Ручная оценка ответа (для manual check_type) |

### 8.4. Прохождение теста (student)

| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/join` | Присоединиться к тесту по коду `{"code": "ABC123"}` |
| GET | `/api/attempts/:id` | Получить текущую попытку (вопросы, оставшееся время) |
| PUT | `/api/answers/:id` | Сохранить/обновить ответ на вопрос |
| POST | `/api/answers/:id/check` | Промежуточная проверка (если allow_intermediate_check) |
| POST | `/api/attempts/:id/finish` | Завершить тест |
| GET | `/api/my-attempts` | Список моих попыток (история) |
| GET | `/api/my-attempts/:id/results` | Результаты попытки (после проверки) |

### 8.5. Callback (внутренний, от GeekPasteV2)

| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/callback/check` | Callback от GeekPasteV2 с результатом проверки кода |

---

## 9. Frontend (Vue 3 + Bootstrap 5)

### 9.1. Страницы

#### Ученик:
- **Ввод кода теста** (`/join`) — поле для ввода кода, кнопка "Войти"
- **Прохождение теста** (`/attempt/:id`) — табы с вопросами, таймер (если есть time_limit), кнопка "Завершить тест"
- **Мои результаты** (`/my-results`) — список пройденных тестов
- **Детали результата** (`/my-results/:id`) — баллы по каждому вопросу, комментарии проверки. Если проверка не завершена — сообщение "Идёт проверка..."

#### Учитель/Админ:
- **Список тестов** (`/admin/tests`) — таблица тестов, статус (активен/неактивен), код доступа
- **Детали теста** (`/admin/tests/:id`) — просмотр вариантов и вопросов, кнопки управления
- **Загрузка теста** (`/admin/tests/upload`) — загрузка JSON-файла, валидация, предпросмотр
- **Результаты теста** (`/admin/tests/:id/results`) — таблица учеников, баллы, статус проверки
- **Детали попытки** (`/admin/attempts/:id`) — ответы ученика, баллы, возможность ручной оценки

### 9.2. Компоненты вопросов

Каждый тип вопроса — отдельный Vue-компонент:

```
src/components/questions/
├── TextInputQuestion.vue        # text_input
├── CodeInputQuestion.vue        # code_input (CodeMirror)
├── TrueFalseTableQuestion.vue   # true_false_table
└── InteractiveQuestion.vue      # interactive (загрузка кастомного компонента)
```

Props: `question`, `answer`, `readonly`, `checkResult`
Emit: `update:answer`

### 9.3. Навигация по вопросам

- Горизонтальные табы: "Вопрос 1", "Вопрос 2", ...
- Цветовая индикация: серый (не отвечен), синий (отвечен), зелёный (проверен, ОК), красный (проверен, ошибка)
- Таймер в правом верхнем углу (обратный отсчёт)
- При истечении времени — автоматическое завершение теста
- WebSocket (Flask-SocketIO) для real-time обновлений: статус проверки, результаты промежуточных проверок

---

## 10. Бизнес-логика

### 10.1. Присоединение к тесту

1. Ученик вводит код теста
2. Система проверяет: тест существует, `is_active = true`, код совпадает
3. Выбирается случайный вариант из тех, которые ученик ещё не проходил
4. Если все варианты пройдены — ошибка "Вы уже прошли все варианты"
5. Создаётся `Attempt`, создаются пустые `Answer` для каждого вопроса
6. Фиксируется `started_at`

### 10.2. Прохождение теста

- Ученик переключается между вопросами (табы)
- Ответы сохраняются на сервер при каждом изменении (автосохранение, debounce 2 сек)
- Если `allow_intermediate_check` — кнопка "Проверить" отправляет ответ на проверку
- Нельзя отправить новую промежуточную проверку, пока предыдущая не завершена (`check_state != "checking"`)
- Таймер на фронте + проверка на бэке: `finished_at` автоматически = `started_at + time_limit`
- Celery-beat задача периодически (раз в минуту) проверяет просроченные попытки и завершает их серверно — не зависит от браузера ученика

### 10.3. Завершение теста

1. Ученик нажимает "Завершить" ИЛИ истекает таймер
2. `finished_at` фиксируется
3. Все ответы со статусом `pending` отправляются на проверку через Celery
4. Ученик видит "Идёт проверка..."
5. По мере проверки каждого ответа обновляется `check_state`
6. Когда все ответы проверены — `attempt.is_checked = true`, считается `total_points`
7. Ученик видит детализированный результат

### 10.4. Проверка ответов (Celery tasks)

```
celery_tasks/
├── check_exact.py      # Синхронная проверка сравнением
├── check_checker.py    # Синхронная проверка программой
└── check_docker.py     # Асинхронный запрос к GeekPasteV2 (docker + ai)
```

Каждая задача:
1. Устанавливает `answer.check_state = "checking"`
2. Выполняет проверку
3. Записывает `answer.points`, `answer.check_comment`, `answer.check_state = "checked"`
4. Отправляет WebSocket-событие ученику с обновлённым статусом
5. Проверяет, все ли ответы в попытке проверены → если да, финализирует `attempt`

---

## 11. Конфигурация

### 11.1. Переменные окружения (.env)

```env
# Flask
SECRET_KEY=...
DEBUG=false
PORT=8085

# Database
CONNECTION_STRING=postgresql+psycopg2://user:pass@db:5432/geekexam

# Redis / Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER=redis://redis:6379/0

# CodingProjects Auth
GEEKCLASS_HOST=https://codingprojects.ru
JWT_SECRET=...

# GeekPasteV2 Integration
GEEKPASTE_API_URL=https://paste.geekclass.ru/api/external/check
CALLBACK_BASE_URL=https://auditor.geekclass.ru
```

---

## 12. Docker Compose

```yaml
services:
  backend:
    build: ./backend
    ports: ["8085:8085"]
    depends_on: [db, redis]
    env_file: .env

  celery_worker:
    build: ./backend
    command: celery -A celery_app worker --loglevel=info
    depends_on: [db, redis]
    env_file: .env

  celery_beat:
    build: ./backend
    command: celery -A celery_app beat --loglevel=info
    depends_on: [db, redis]
    env_file: .env

  frontend:
    build: ./frontend
    ports: ["8080:80"]

  db:
    image: postgres:16
    volumes: ["pgdata:/var/lib/postgresql/data"]
    environment:
      POSTGRES_DB: geekexam
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass

  redis:
    image: redis:7-alpine

volumes:
  pgdata:
```

---

## 13. Структура проекта

```
GeekExam/
├── backend/
│   ├── app.py                  # Flask app factory
│   ├── config.py               # Конфигурация из .env
│   ├── models.py               # SQLAlchemy модели
│   ├── manage.py               # Flask-Migrate setup
│   ├── celery_app.py           # Celery setup
│   ├── auth.py                 # JWT авторизация, декораторы
│   ├── routes/
│   │   ├── auth.py             # /auth/*
│   │   ├── tests.py            # /api/tests/*
│   │   ├── attempts.py         # /api/attempts/*, /api/join, /api/my-*
│   │   ├── answers.py          # /api/answers/*
│   │   └── callbacks.py        # /api/callback/*
│   ├── checkers/
│   │   ├── registry.py         # Реестры QUESTION_TYPES, CHECK_TYPES
│   │   ├── question_types/
│   │   │   ├── text_input.py
│   │   │   ├── code_input.py
│   │   │   ├── true_false_table.py
│   │   │   └── interactive.py
│   │   └── check_types/
│   │       ├── exact.py
│   │       ├── checker.py
│   │       └── docker.py         # Handles both docker and ai (via GeekPasteV2)
│   ├── celery_tasks/
│   │   └── check_answer.py     # Celery task для проверки
│   ├── migrations/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.vue
│   │   ├── main.js
│   │   ├── router.js
│   │   ├── api.js              # Axios wrapper
│   │   ├── views/
│   │   │   ├── JoinTest.vue
│   │   │   ├── TakeTest.vue
│   │   │   ├── MyResults.vue
│   │   │   ├── ResultDetail.vue
│   │   │   ├── admin/
│   │   │   │   ├── TestList.vue
│   │   │   │   ├── TestDetail.vue
│   │   │   │   ├── TestUpload.vue
│   │   │   │   ├── TestResults.vue
│   │   │   │   └── AttemptDetail.vue
│   │   ├── components/
│   │   │   ├── QuestionTabs.vue
│   │   │   ├── Timer.vue
│   │   │   └── questions/
│   │   │       ├── TextInputQuestion.vue
│   │   │       ├── CodeInputQuestion.vue
│   │   │       ├── TrueFalseTableQuestion.vue
│   │   │       └── InteractiveQuestion.vue
│   │   └── stores/             # Pinia
│   │       ├── auth.js
│   │       └── attempt.js
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
├── SPEC.md
├── TASK.md
└── README.md
```

---

## 14. Изменения в GeekPasteV2

Для интеграции необходимо добавить в GeekPasteV2:

### 14.1. Новый API-эндпоинт `POST /api/external/check`

- Авторизация: `Authorization: Bearer {JWT подписанный общим JWT_SECRET}`
- Принимает: `code`, `lang`, `task_text`, `check_type`, `check_config`, `callback_url`, `callback_id`
- Создаёт Celery-задачу на проверку
- Возвращает `{"status": "queued", "job_id": "..."}`

### 14.2. Callback после проверки

- По завершении проверки Celery-задача отправляет POST на `callback_url`
- Payload: `callback_id`, `status`, `points`, `max_points`, `comment`, `details`
- Retry при ошибке (3 попытки с экспоненциальным backoff)

### 14.3. Новая переменная окружения

```env
# Используется общий JWT_SECRET для авторизации между сервисами
```
