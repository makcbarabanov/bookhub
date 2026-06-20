# BookHub — схема базы данных

**База:** `bookhub_prod`  
**Хост:** `83.217.220.97`  
**Схема:** `public`

> Этот файл — источник правды по **логической** структуре БД для разработчиков.  
> При любом изменении в `_sql/*.sql` обновляй этот документ в том же PR/сеансе.

**Последнее обновление:** 2026-06-18 (миграции `001`–`006`)

---

## Диаграмма связей

```
users ─────┬──── book_memberships ──── books ──── chapters
             │                            ├──── book_service
             │                            ├──── book_analyses
             │                            ├──── book_notes
             │                            ├──── book_chat_messages
             │                            └──── book_characters
             ├──── user_preferences
             └──── ai_usage_log
```

---

## Таблицы

### `users`

Авторы (пользователи приложения).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `phone_e164` | VARCHAR(16) UNIQUE NOT NULL | Телефон, напр. `+79886296030` |
| `login` | VARCHAR(64) UNIQUE | Логин, напр. `makc` |
| `password_hash` | TEXT NOT NULL | bcrypt |
| `display_name` | VARCHAR(120) | Собранное имя (legacy / автозаполнение) |
| `first_name` | VARCHAR(80) | Имя |
| `last_name` | VARCHAR(80) | Фамилия |
| `patronymic` | VARCHAR(80) | Отчество |
| `is_active` | BOOLEAN DEFAULT TRUE | |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | Дата регистрации |

**Миграции:** `002_multiuser.sql`, `003_profile.sql`

---

### `books`

Книги автора.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | SERIAL PK | |
| `title` | VARCHAR(255) NOT NULL | Название |
| `owner_user_id` | BIGINT FK → `users(id)` | Владелец |
| `slug` | VARCHAR(64) | URL-slug, напр. `1445` |
| `ai_summary` | TEXT DEFAULT '' | Краткая «память» Морфеуса (до ~500 слов), фоновое обновление |
| `is_archived` | BOOLEAN DEFAULT FALSE | Скрытая книга |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ DEFAULT NOW() | |

**Миграции:** `001_init.sql`, `002_multiuser.sql`, `006_book_chat_and_notes.sql` (`ai_summary`)

---

### `chapters`

Главы книги. Текст хранится как HTML (`content`).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | SERIAL PK | |
| `book_id` | INTEGER FK → `books(id)` ON DELETE CASCADE | |
| `ch_id` | VARCHAR(32) NOT NULL | Стабильный id в UI, напр. `ch1` |
| `title` | VARCHAR(512) NOT NULL | Заголовок без номера |
| `act_number` | SMALLINT DEFAULT 1 | Номер акта (1–4) |
| `emoji` | VARCHAR(8) DEFAULT 🟢 | Маркер в навигации |
| `content` | TEXT DEFAULT '' | HTML тела главы |
| `sort_order` | INTEGER DEFAULT 0 | Порядок в книге |
| `updated_at` | TIMESTAMPTZ DEFAULT NOW() | |

**Уникальность:** `(book_id, ch_id)`  
**Индекс:** `idx_chapters_book_sort (book_id, sort_order)`

**Миграции:** `001_init.sql`

---

### `book_memberships`

Доступ пользователя к книге (мультиавтор / соавторы в будущем).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `book_id` | BIGINT FK → `books(id)` CASCADE | |
| `user_id` | BIGINT FK → `users(id)` CASCADE | |
| `role` | VARCHAR(16) | `owner` \| `editor` \| `viewer` |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | |

**Уникальность:** `(book_id, user_id)`

**Миграции:** `002_multiuser.sql`

---

### `user_preferences`

Настройки пользователя.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `user_id` | BIGINT PK FK → `users(id)` CASCADE | |
| `active_book_id` | BIGINT FK → `books(id)` SET NULL | Текущая книга в UI |
| `updated_at` | TIMESTAMPTZ DEFAULT NOW() | |

**Миграции:** `002_multiuser.sql`

---

### `book_service`

Служебные вкладки **одной книги** (чек-лист, герои, сюжетный граф).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `book_id` | BIGINT PK FK → `books(id)` CASCADE | |
| `checklist_html` | TEXT DEFAULT '' | HTML чек-листа идей |
| `heroes_text` | TEXT DEFAULT '' | Текст «Главные герои» |
| `plot_json` | JSONB DEFAULT `{}` | Граф сюжетной линии (lanes, chapters, plot) |
| `checklist_updated_at` | TIMESTAMPTZ | |
| `heroes_updated_at` | TIMESTAMPTZ | |
| `plot_updated_at` | TIMESTAMPTZ | |

**Миграции:** `004_service.sql`

---

### `book_analyses`

Кэш отчёта **«Советы ИИ»** (одна актуальная запись на книгу).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `book_id` | BIGINT PK FK → `books(id)` CASCADE | |
| `analysis_json` | JSONB DEFAULT `{}` | errors, plot_ideas, radar, chapter_radar, strengths |
| `model` | VARCHAR(128) | Модель OpenRouter |
| `tokens_in` | INTEGER | Токены промпта |
| `tokens_out` | INTEGER | Токены ответа |
| `created_at` | TIMESTAMPTZ | Первый анализ |
| `updated_at` | TIMESTAMPTZ | Последнее обновление |

**Миграции:** `005_book_analyses.sql`

---

### `book_notes`

Wiki-заметки книги (создаёт Морфеус через маркер `[CREATE_NOTE]` в чате).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `book_id` | BIGINT FK → `books(id)` CASCADE | |
| `title` | VARCHAR(255) NOT NULL | Заголовок |
| `content` | TEXT NOT NULL | Текст заметки |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**Индекс:** `idx_book_notes_book (book_id)`

**Миграции:** `006_book_chat_and_notes.sql`

---

### `book_chat_messages`

История диалога с Морфеусом (активная книга пользователя).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `book_id` | BIGINT FK → `books(id)` CASCADE | |
| `sender` | VARCHAR(10) | `user` или `ai` |
| `message` | TEXT NOT NULL | Текст (маркеры CREATE_NOTE/OFF_TOPIC сняты на бэкенде) |
| `created_at` | TIMESTAMPTZ | |

**Индексы:** `idx_book_chat_book`, `idx_book_chat_book_time (book_id, created_at DESC)`

**Миграции:** `006_book_chat_and_notes.sql`

---

### `book_characters`

Канон персонажей книги (Фаза 3.2 «Кастинг»). Используется Морфеусом и анализом ИИ.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `book_id` | BIGINT FK → `books(id)` CASCADE | |
| `name` | VARCHAR(120) NOT NULL | Имя (уникально в рамках книги) |
| `role_type` | VARCHAR(20) | `protagonist`, `antagonist`, `secondary` |
| `summary` | VARCHAR(300) NOT NULL | Кратко для UI и ИИ |
| `bio` | TEXT | Подробно: мотивация, арка |
| `relations_json` | JSONB | Связи, напр. `{"партнёр": "Тимур"}` |
| `first_ch_id` | VARCHAR(10) | Первое появление |
| `color` | VARCHAR(7) | Цвет полосы на графе |
| `avatar_url` | VARCHAR(255) | URL загруженного референса |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

**Индекс:** `idx_book_characters_book (book_id)`

**Миграции:** `007_book_characters.sql`

---

### `ai_usage_log`

Учёт вызовов ИИ (лимиты, статистика).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `user_id` | BIGINT FK → `users(id)` CASCADE | |
| `book_id` | BIGINT FK → `books(id)` SET NULL | |
| `endpoint` | VARCHAR(64) | напр. `ai-analysis-refresh`, `chat-send`, `chat-summary-refresh` |
| `model` | VARCHAR(128) | |
| `tokens_in` | INTEGER | |
| `tokens_out` | INTEGER | |
| `created_at` | TIMESTAMPTZ | |

**Индекс:** `idx_ai_usage_user_time (user_id, created_at DESC)`

**Миграции:** `005_book_analyses.sql`

---

## Удалённые таблицы

| Таблица | Когда | Причина |
|---------|-------|---------|
| `revisions` | `002_multiuser.sql` | История версий глав не используется в v0.2 |

---

## Планируемые таблицы (см. Roadmap)

| Таблица | Назначение | Фаза |
|---------|------------|------|
| `book_inbox_notes` | Голосовые/быстрые заметки перед переносом в чек-лист | Фаза 5 |

После добавления — перенести из этого раздела в основной и указать миграцию.

---

## Миграции (порядок)

| Файл | Версия | Содержание |
|------|--------|------------|
| `001_init.sql` | v0.1 | `books`, `chapters`, `revisions` |
| `002_multiuser.sql` | v0.2 | `users`, memberships, preferences; DROP `revisions` |
| `003_profile.sql` | v0.3 | ФИО в `users` |
| `004_service.sql` | v0.3 | `book_service` |
| `005_book_analyses.sql` | v0.4 | `book_analyses`, `ai_usage_log` |
| `006_book_chat_and_notes.sql` | v0.3 | `books.ai_summary`, `book_notes`, `book_chat_messages` |
| `007_book_characters.sql` | v0.3.2 | `book_characters` |

Новые файлы: **`006_*.sql`**, … — только additive, без breaking changes без согласования.

---

## Чеклист при изменении схемы

1. Добавить `_sql/NNN_description.sql`
2. Обновить **`Readme/Tables.md`** (таблица, колонки, FK, индексы)
3. Обновить `database.py` / `main.py` при необходимости
4. Прогнать миграцию на `bookhub_prod` (рестарт контейнера или `run_migrations()`)
5. Проверить в DBeaver: schema `public`, database `bookhub_prod`
