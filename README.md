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
