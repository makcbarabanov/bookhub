# BookHub — личный кабинет писателя

Веб-редактор романа с главами, служебными вкладками (сюжет, чек-лист, герои), мульти-книгами и профилем автора.

**Прод:** https://book.islanddream.ru/  
**Версия приложения:** см. `/api/v1/version` и бейдж под списком глав в сайдбаре.

---

## Инфраструктура (SRE)

| Параметр | Значение |
|----------|----------|
| Хост приложения | `188.225.44.48` (Timeweb) |
| Директория проекта | `/home/makc/Projects/bookhub` |
| Домен | `book.islanddream.ru` — Nginx на хосте: 443 → `127.0.0.1:8001` |
| Контейнер | `docker compose` → сервис `bookhub`, порт **8001** |
| PostgreSQL | `83.217.220.97:5432`, БД **`bookhub_prod`**, пользователь из `.env` |
| SSL к БД | `sslmode=require` |

PostgreSQL **не** в Docker — только FastAPI-приложение. Миграции применяются при старте (`run_migrations()` в `main.py`).

---

## Стек

- **Backend:** Python 3.12, FastAPI, psycopg
- **Frontend:** `static/index.html` + `static/bookhub.js` (без сборщика)
- **БД:** PostgreSQL, миграции additive в `_sql/`
- **Деплой:** `docker compose up -d --build` (на прод-хосте)

---

## Структура репозитория

```
bookhub/
├── Readme/           # документация (этот файл, Tables.md, Roadmap.md)
├── _sql/             # миграции БД (001_, 002_, …)
├── main.py           # FastAPI, API, статика
├── database.py       # PostgreSQL helpers
├── static/           # index.html, bookhub.js
├── import_1445.py    # импорт книги «14:45»
├── seed_1445_service.py
├── service_analyzer.py  # rule-based герои / сюжет
├── .env              # секреты (не в git)
└── docker-compose.yml
```

Подробная схема БД: [Tables.md](./Tables.md)  
Планы развития: [Roadmap.md](./Roadmap.md)

---

## Правила разработки (SOP)

1. **Git:** разработка на сервере (direct-to-prod); коммиты в `main` после рабочего сеанса.
2. **БД:** только additive-миграции в `_sql/`. После каждой миграции — обновить **`Readme/Tables.md`** (см. правило Cursor `.cursor/rules/db-schema.mdc`).
3. **Авторизация:** сессионная cookie (`bookhub_session`), логин = телефон или `makc`, пароль в `.env`.
4. **Деплой:** `docker compose up -d --build` в корне проекта.
5. **Секреты:** API-ключи (OpenRouter и др.) только в `.env`, не в коде и не в git.

---

## Основные возможности (v0.2)

- Вход, несколько книг на автора, переключение активной книги
- Главы: CRUD, drag-reorder, emoji-маркеры, autosave
- Служебные вкладки **per book** (`book_service`): чек-лист, герои, сюжетная линия
- Профиль: ФИО, статистика (страницы / слова / знаки)
- Экспорт: HTML, DOCX, PDF
- Импорт черновика из HTML

---

## API (кратко)

| Метод | Путь | Назначение |
|-------|------|------------|
| POST | `/api/v1/login` | Вход |
| GET | `/api/v1/book` | Книга + главы + `service` |
| PATCH | `/api/v1/chapters/{ch_id}` | Сохранение главы |
| GET | `/api/v1/me/profile` | Профиль и список книг |
| GET | `/api/v1/book/ai-analysis` | Кэш «Советы ИИ» |
| POST | `/api/v1/book/ai-analysis/refresh` | Новый анализ (OpenRouter) |
| POST | `/api/v1/book/ai-analysis/apply` | Применить языковое исправление |
| POST | `/api/v1/book/ai-analysis/dismiss-error` | Убрать замечание («Оставить») |
| POST | `/api/v1/book/ai-analysis/dismiss-idea` | Удалить идею сюжета |
| POST | `/api/v1/book/ai-analysis/idea-to-checklist` | Идея → чек-лист |

Полный список: `/docs` на инстансе.

---

## Локальная проверка БД

```bash
cd /home/makc/Projects/bookhub
source .venv/bin/activate
python3 -c "from dotenv import load_dotenv; load_dotenv(); from database import get_conn; ..."
```

Список таблиц в DBeaver: host `83.217.220.97`, database **`bookhub_prod`**, schema **`public`**, SSL require.

---

## Cursor / AI-агент на проде

**Workspace Cursor = прод-сервер.** Репозиторий открыт там же, где крутится BookHub:

| | |
|---|---|
| Хост | `island` (Timeweb, `188.225.44.48`) |
| Путь | `/home/makc/Projects/bookhub` |
| Контейнер | `docker compose` → `bookhub` на `:8001` |
| Домен | https://book.islanddream.ru |

Агент в этой сессии **редактирует файлы на месте** и **может сам** пересобирать приложение:

```bash
cd /home/makc/Projects/bookhub && docker compose up -d --build
```

Git — бэкап после рабочего сеанса; **`git pull` на прод не используется** (разработка direct-to-prod).

Подробная матрица «что агент делает сам / что только вручную» — в разделе ниже (заполняется совместно).

### Возможности и ограничения прода на сервере

> *Черновик — дополним после согласования с автором.*

---

## Документация

- [Tables.md](./Tables.md) — схема PostgreSQL
- [Roadmap.md](./Roadmap.md) — ИИ, виджет, голосовой ассистент
