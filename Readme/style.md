# BookHub — стандарты UI

Источник правды по визуальному языку приложения.  
Реализация: встроенные стили в `static/index.html` (отдельного CSS-файла пока нет).

**Последнее обновление:** 2026-06-19

При добавлении новых экранов, панелей и компонентов **сначала сверяйся с этим документом**, затем дополняй его, если вводишь новый переиспользуемый паттерн.

---

## 1. Дизайн-токены (CSS-переменные)

Тема переключается атрибутом `data-theme` на `<html>` (`dark` | `light`).

| Токен | Тёмная тема | Светлая тема | Назначение |
|-------|-------------|--------------|------------|
| `--bg-dark` | `#0f0f11` | `#ececef` | Фон приложения |
| `--bg-panel` | `#1a1a1d` | `#ffffff` | Панели, сайдбар, модалки |
| `--text-main` | `#e0e0e0` | `#1a1a1d` | Основной текст |
| `--text-muted` | `#888888` | `#666666` | Подписи, вторичный текст |
| `--text-content` | `#ffffff` | `#1a1a1d` | Тело глав в редакторе |
| `--accent-amber` | `#d9772b` | `#c56a1f` | Акцент, заголовки, активные пункты |
| `--accent-green` | `#4caf50` | `#2e7d32` | Успех, сохранение |
| `--border` | `#333333` | `#d8d8dc` | Рамки, разделители |
| `--sidebar-width` | `350px` | `350px` | Ширина боковой панели |

**Правило:** новые цвета — через переменные или согласованные hex из таблицы ниже. Не вводить случайные оттенки без причины.

### Семантические цвета (фиксированные)

| Роль | Цвет | Пример |
|------|------|--------|
| Опасность / удаление | `#ef5350`, `#c62828` | `.modal-box--danger`, `.btn-danger` |
| Успех / применить | `#81c784`, `#8fd694` | diff «новый текст», `.btn-ai-apply` |
| Предупреждение | `#ffb74d` | severity medium |
| Ошибка в diff | `#e57373` | `.old` в ai-fix-modal |
| ИИ-кнопка | `#5b8def` | `.btn-ai` hover |

---

## 2. Типографика

Подключение: Google Fonts — **Playfair Display** (600) + **Inter** (300, 400, 600).

| Элемент | Шрифт | Размер | Цвет |
|---------|-------|--------|------|
| Заголовок книги (sidebar) | Playfair Display | 22px | `--accent-amber` |
| `h2` в контенте | Playfair Display | 32px | `--text-main` |
| Заголовок модалки `h3` | Playfair Display | inherit | `--accent-amber` (danger: `#ef5350`) |
| Основной UI | Inter | 14px | `--text-main` |
| Подписи, мета | Inter | 11–12px | `--text-muted` |
| Тело главы | Inter | 16px | `--text-content` |
| Навигация | Inter | 14px | `--text-main` / active: amber |

**Правило:** `font-family: inherit` на кнопках и полях ввода.

---

## 3. Макет

```
┌─────────────────┬──────────────────────────────┐
│ sidebar 350px   │  content (scroll)            │
│ nav + service   │  chapter editor              │
└─────────────────┴──────────────────────────────┘
```

- `body`: `display: flex`, `height: 100vh`, `overflow: hidden`
- Сайдбар: `--bg-panel`, `border-right: 1px solid var(--border)`
- Контент: flex-grow, вертикальный скролл
- Сайдбар сворачивается классом на `body` (кнопки `.btn-sidebar-toggle` / `.btn-sidebar-expand`)

---

## 4. Модальные окна (обязательный стандарт)

**Все модалки** в проекте используют единую разметку и классы. Не создавать отдельные overlay/box с другими стилями.

### Разметка

```html
<div class="modal-overlay" id="my-modal" role="dialog" aria-modal="true" aria-labelledby="my-modal-title">
    <div class="modal-box">
        <h3 id="my-modal-title">Заголовок</h3>
        <p>Поясняющий текст (опционально).</p>
        <!-- контент -->
        <div class="modal-actions">
            <button type="button" id="my-modal-cancel">Отмена</button>
            <button type="button" id="my-modal-confirm" class="btn-primary">Подтвердить</button>
        </div>
    </div>
</div>
```

### Классы

| Класс | Назначение |
|-------|------------|
| `.modal-overlay` | Полноэкранный затемнённый фон, `z-index: 550`, flex center |
| `.modal-box` | Карточка: `max-width: 440px`, `border-radius: 12px`, padding 24px |
| `.modal-box--danger` | Удаление: красный заголовок |
| `.modal-box--success` | Успех: зелёный заголовок (`#81c784`) |
| `.modal-box--profile` | Широкая модалка профиля: `max-width: 480px`, scroll |
| `.modal-message` | Текст уведомления в `#app-notice-modal` |
| `.modal-actions` | Кнопки справа внизу, `gap: 10px` |
| `.modal-chapter-name` | Выделенный блок с именем сущности |
| `.btn-primary` | Основное действие (amber) |
| `.btn-danger` | Деструктивное действие (красный) |

### Показ / скрытие

- По умолчанию: `display: none` на `.modal-overlay`
- Открытие: `style.display = 'flex'` (или класс-утилита, если появится)
- Закрытие: клик «Отмена», успешное действие, клик по overlay (если реализовано в JS)

### Существующие модалки (эталон)

| ID | Модификатор | Назначение |
|----|-------------|------------|
| `#import-modal` | — | Импорт |
| `#delete-modal` | `--danger` | Удаление главы |
| `#delete-book-modal` | `--danger` | Удаление книги |
| `#ai-fix-modal` | — | Подтверждение исправления ИИ |
| `#app-notice-modal` | `--success` / `--danger` / — | **Уведомления** (успех, ошибка, инфо) — вместо `alert()` |
| `#profile-modal` | `--profile` | Личный кабинет |

### Уведомления вместо `alert()`

**Запрещено** использовать `window.alert`, `window.confirm`, `window.prompt` для пользовательских сообщений.

Используй **`showAppNotice({ title?, message, variant? })`** в `bookhub.js`:

```javascript
showAppNotice({ variant: 'success', message: 'Исправление применено.' });
showAppNotice({ variant: 'danger', message: 'Не удалось сохранить.' });
showAppNotice({ variant: 'info', title: 'Подсказка', message: '…' });
```

| variant | Модификатор box | Заголовок по умолчанию |
|---------|-----------------|------------------------|
| `success` | `.modal-box--success` (зелёный h3) | «Готово» |
| `danger` | `.modal-box--danger` | «Ошибка» |
| `info` | — (amber h3) | «Сообщение» |

Текст — в `<p class="modal-message">`, одна кнопка **OK** (`.btn-primary`).

### Исключение: логин

`#login-overlay` — полноэкранный блок входа (`z-index: 600`), визуально согласован с `.modal-box` (те же радиусы, amber-кнопка), но не использует `.modal-overlay` из-за отдельного жизненного цикла.

---

## 5. Кнопки

### Общие правила

- `border-radius: 6px` (крупные блоки — `8px`)
- Hover: `border-color: var(--accent-amber)` или фон с прозрачностью amber/green
- `cursor: pointer`, `font-family: inherit`

### Типы

| Класс | Контекст |
|-------|----------|
| `.btn-primary` / `button[type="submit"]` в `.modal-actions` | Главное действие — amber фон, тёмный текст |
| `.btn-danger` | Удаление |
| `.btn-export` | Полноширинная в сайдбаре |
| `.btn-export-disk`, `.btn-save-disk` | Иконки в тулбаре |
| `.btn-theme`, `.btn-lock` | 36×28, тулбар |
| `.btn-profile` | Аватар 👤 |
| `.btn-ai` | 🤖, синий hover |
| `.btn-service-refresh` | «Обновить» в служебных вкладках |
| `.btn-add-chapter`, `.btn-add-idea` | Пунктирная рамка, hover amber |
| `.btn-ai-apply`, `.btn-ai-open-ch` | Действия в карточках ИИ |
| `.btn-ai-leave` | «Оставить» — убрать замечание без правки |
| `.btn-icon` | Иконка-кнопка 32×32 с `title` (подсказка при наведении) |
| `.ai-idea-item` + `.ai-idea-actions` | Строка идеи сюжета с кнопками справа |

---

## 6. Навигация

- `.nav-group` — секция: uppercase, 11px, `--text-muted`, letter-spacing
- `.nav-item` — пункт: padding 10px 20px, `border-left: 3px solid transparent`
- `.nav-item.active` — amber border + цвет
- `.nav-item:hover` — фон `#2a2a2e` (в light — светлее через тему)
- `.service-nav-item` — служебные вкладки (чек-лист, герои, сюжет, ИИ)

---

## 7. Формы

### Поля ввода (профиль, логин)

```css
padding: 8–10px;
border-radius: 6px;
border: 1px solid var(--border);
background: #1a1a1e; /* dark; в light — светлее */
color: var(--text-main);
```

### Лейблы профиля

- Grid 2 колонки, отчество на всю ширину
- Label: uppercase 11px, `--text-muted`, letter-spacing

---

## 8. Служебные панели и ИИ

### Служебные вкладки (`book_service`)

- Заголовок `h2` + `.service-updated` (метка времени)
- `.btn-service-refresh` справа
- Редакторы: contenteditable / textarea в стиле панели

### «Советы ИИ»

| Класс | Назначение |
|-------|------------|
| `.ai-tabs` / `.ai-tab` | Вкладки как у service, active = amber border |
| `.ai-empty`, `.ai-loading` | Пустое состояние / загрузка |
| `.ai-meta` | Модель, токены, дата |
| `.ai-card` | Карточка замечания, `border-left` по severity |
| `.ai-card.sev-high/medium/low` | Красный / оранжевый / зелёный |
| `.ai-radar-grid`, `.ai-radar-stat` | Кардиограмма |
| `.ai-idea-item` | Пунктирная рамка для идей |

---

## 9. Редактор глав

- `.max-text`, `.atlas-note` — основной контент
- `.atlas-note` — callout: amber left border, полупрозрачный amber фон
- `.poem` — курсив, левый border
- Contenteditable: без видимой рамки в режиме чтения; outline amber при редактировании заголовков в nav

---

## 10. Z-index

| Слой | z-index |
|------|---------|
| Модалки | 550 |
| Логин | 600 |
| (будущие тосты) | 650+ |

---

## 11. Тема light/dark

- Переключатель: `.btn-theme` в тулбаре
- Сохранение: `localStorage` + `data-theme` на `<html>`
- При добавлении стилей проверять оба режима или использовать только CSS-переменные

---

## 12. Чеклист для нового UI

1. Цвета — из токенов §1
2. Шрифты — Inter / Playfair по §2
3. **Модалка** — только паттерн §4
4. Кнопки — существующие классы §5
5. Отступы: кратно 4px (8, 12, 16, 20, 24)
6. Обновить **этот файл**, если добавлен новый переиспользуемый компонент

---

## Связанные документы

- `Readme/Readme.md` — обзор приложения
- `Readme/Roadmap.md` — планы фич
- `.cursor/rules/frontend-style.mdc` — правило для Cursor при правках фронтенда
