# GeekExam

Платформа для проведения тестов по информатике в школе. Интегрируется с [CodingProjects](https://codingprojects.ru) через JWT и использует [GeekPasteV2](../GeekPasteV2) для проверки кода.

## Быстрый старт

```bash
cp .env.example .env
# Заполните .env (JWT_SECRET должен совпадать с GeekPasteV2)

docker compose up -d

# Применить миграции
docker compose exec backend flask db upgrade
```

Фронтенд: http://localhost:8080  
Backend API: http://localhost:8085

## Структура

```
backend/    — Flask API + Celery
frontend/   — Vue 3 + Bootstrap 5
```

## Формат JSON теста

Смотри [SPEC.md](SPEC.md#7-формат-json-описания-теста) и пример в `backend/example_test.json`.

## Типы вопросов

| Тип | Описание |
|-----|----------|
| `text_input` | Текстовый ответ |
| `code_input` | Ввод кода с редактором |
| `true_false_table` | Таблица утверждений верно/неверно |
| `interactive` | Кастомный Vue-компонент |

Для `code_input` используется CodeMirror с номерами строк, отступами и подсветкой
Python, JavaScript, TypeScript и C/C++. Язык задаётся в `ui_config.lang`
(по умолчанию Python), начальный код — в `ui_config.starter_code`.

Текстовые задания с `ui_config.multiline: true` также используют редактор.
Без `ui_config.lang` текст отображается без подсветки; для кода можно указать язык.
`ui_config.rows` задаёт высоту в строках (по умолчанию 4 для текста и 12 для кода).
Формат сохранённых ответов остаётся прежним: `{ "text": "..." }` для текста
и `{ "code": "...", "lang": "python" }` для кода.

## Типы проверки

| Тип | Описание |
|-----|----------|
| `exact` | Сравнение с эталоном |
| `checker` | Python-функция на сервере |
| `docker` | Запуск кода через GeekPasteV2 |
| `ai` | GPT-проверка через GeekPasteV2 |
| `manual` | Ручная оценка учителем |

## Добавление нового типа вопроса

1. Создать Vue-компонент в `frontend/src/components/questions/`
2. Зарегистрировать в `frontend/src/views/TakeTest.vue` → `questionComponents`
3. Добавить тип в `backend/checkers/registry.py` → `VALID_QUESTION_TYPES`

## Добавление интерактивного компонента

Зарегистрировать в `frontend/src/components/interactiveRegistry.js`:

```js
import MyComponent from './questions/MyComponent.vue'
export const interactiveComponents = { 'my-component': MyComponent }
```

В JSON теста указать `"type": "interactive", "ui_config": { "component": "my-component" }`.

## Проверки фронтенда

Ответы ограничены по длине: 1 000 символов для каждого короткого поля и ячейки
матрицы, 10 000 для текста, 50 000 для кода и 100 000 суммарно на ответ.
Ограничения действуют в браузере и API; слишком большой запрос отклоняется,
сохранённый ответ остаётся прежним. Ввод кода сверх лимита не заменяет текст
в редакторе. Ошибки компиляции видны ученику и после обновления страницы.

На странице теста кнопка «+15 минут» увеличивает текущий общий лимит ровно на
15 минут, сохраняя время начала и ответы. Повторный запрос со старым лимитом
отклоняется. В редакторе задаётся полная длительность: изменение 55 → 70
добавляет 15 минут. «Остановить» завершает все начатые попытки и запрещает
новые входы; ученики получают завершение через Socket.IO или опрос API.

В каталоге `frontend`:

```bash
npm ci
npm test
npx playwright install chromium
npm run test:browser
npm run build
```

Браузерные тесты сами запускают Vite на `127.0.0.1:4178` и подменяют API.
Они проверяют сохранение и восстановление ответов, истечение таймера, сетевые
ошибки, обновление результатов, редактор преподавателя и мобильную страницу.
Интеграция с настоящим сервером и GeekPaste проверяется отдельно.
