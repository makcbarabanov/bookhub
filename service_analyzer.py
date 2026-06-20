"""Auto-generate heroes and plotline from chapter text."""

from __future__ import annotations

import json
import re
from typing import Any

from stats_util import html_to_plain

NAME_RE = re.compile(
    r"(?<![а-яёА-ЯЁ])([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?(?:\s*\([^)]+\))?)"
)

PATRONYMIC_RE = re.compile(
    r"(?<![а-яёА-ЯЁ])([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+(?:ович|евич|ич|овна|евна|ьевич))"
)

STOP_NAMES = {
    "А",
    "Бог",
    "Боже",
    "В",
    "Все",
    "Вы",
    "Бег",
    "Братан",
    "Вдруг",
    "Вжих",
    "Вот",
    "Всего",
    "Всё",
    "Где",
    "Германия",
    "Глава",
    "Год",
    "Да",
    "Дай",
    "Даже",
    "Дружище",
    "Для",
    "Его",
    "Её",
    "Если",
    "Ещё",
    "Жена",
    "Завтра",
    "И",
    "Их",
    "Как",
    "Когда",
    "Конечно",
    "Контекст",
    "Кто",
    "Мне",
    "Может",
    "Москва",
    "Мы",
    "Машина",
    "На",
    "Не",
    "Нет",
    "Никто",
    "Новая",
    "Но",
    "Ну",
    "Общем",
    "Обычно",
    "Он",
    "Она",
    "Они",
    "По",
    "Потом",
    "Потому",
    "Почему",
    "Прячет",
    "Разговор",
    "Рад",
    "Рядом",
    "Россия",
    "Сейчас",
    "Сегодня",
    "Сколько",
    "Слава",
    "Сочи",
    "Ссора",
    "Сюрприз",
    "Так",
    "Там",
    "Татьяна",
    "Точка",
    "Тут",
    "Ты",
    "Успешный",
    "Финал",
    "Цветы",
    "Хотя",
    "Чего",
    "Что",
    "Это",
    "Я",
    "Каждый",
    "Просто",
    "Увольнение",
    "Конверт",
    "Мимика",
    "Вспомнил",
    "Атриплан",
    "Без",
    "Дверь",
    "Ему",
    "Живой",
    "Интересно",
    "Кажется",
    "Опять",
    "Перед",
    "Пока",
    "Самое",
    "Сердце",
    "Тим",
}

# Склонения и уменьшительные → каноническое имя для подсчёта
NAME_VARIANTS: dict[str, str] = {
    "артур": "Артур",
    "артура": "Артур",
    "артуру": "Артур",
    "артуром": "Артур",
    "артуре": "Артур",
    "тимур": "Тимур",
    "тимура": "Тимур",
    "тимуру": "Тимур",
    "тимуром": "Тимур",
    "юлия": "Юлия",
    "юль": "Юлия",
    "юли": "Юлия",
    "юле": "Юлия",
    "юлей": "Юлия",
    "юлю": "Юлия",
    "кирюха": "Кирюха",
    "кирюхи": "Кирюха",
    "кирюху": "Кирюха",
    "кирюхой": "Кирюха",
    "кирюхе": "Кирюха",
    "толяныч": "Толяныч",
    "толяну": "Толяныч",
    "толяныча": "Толяныч",
    "толянычу": "Толяныч",
    "андрей": "Андрей",
    "андрея": "Андрей",
    "андрею": "Андрей",
    "андреем": "Андрей",
    "аня": "Аня",
    "ани": "Аня",
    "ане": "Аня",
    "аню": "Аня",
    "аней": "Аня",
    "вадим": "Вадим",
    "вадима": "Вадим",
    "вадиму": "Вадим",
    "вадимом": "Вадим",
    "дударь": "Дударь",
    "дударя": "Дударь",
    "лучик": "Лучик",
    "лучика": "Лучик",
    "левирский": "Левирский",
    "левирского": "Левирский",
    "игорь": "Игорь",
    "игоря": "Игорь",
    "игорю": "Игорь",
    "игорем": "Игорь",
    "марк давидович": "Марк Давидович",
    "вадимыч": "Вадимыч",
    "вадимыча": "Вадимыч",
    "лучику": "Лучик",
    "надежда": "Надежда Сергеевна",
    "сергеевна": "Надежда Сергеевна",
    "петр": "Петр Сергеевич",
    "резанов": "Резанов",
    "резанова": "Резанов",
    "татьяна": "Татьяна",
    "татьяну": "Татьяна",
    "татьяны": "Татьяна",
}

CANONICAL_CAST = frozenset(NAME_VARIANTS.values())

# Слова в заголовках глав, которые не являются именами
TITLE_NOISE = {
    "встреча",
    "разговор",
    "история",
    "задача",
    "договор",
    "конверт",
    "контекст",
    "великое",
    "поселение",
    "кабинет",
    "глава",
    "часть",
    "сцена",
    "эпизод",
    "бунт",
    "собрание",
    "плоды",
    "дорога",
    "реанимация",
    "авария",
    "очередь",
    "маска",
    "идей",
    "чек",
    "лист",
    "сводный",
    "именованые",
    "необычная",
    "право",
    "поселение",
    "великое",
    "задача",
    "договор",
    "ресторан",
    "партнером",
    "партнёром",
}

LANE_COLORS = ["#d9772b", "#5c9fd4", "#e879a6", "#6abf69", "#a78bfa", "#fbbf24"]

CYRILLIC_SLUG = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)

FLASHBACK_RE = re.compile(
    r"вспомнил|вспомнила|вспоминал|флешбек|год\s+назад|много\s+лет|в\s+прошлом|"
    r"бессонниц|флешбэк",
    re.IGNORECASE,
)

PLOT_ACTS = [
    {"label": "Акт I", "x0": 0, "x1": 25},
    {"label": "Акт II", "x0": 25, "x1": 50},
    {"label": "Акт III", "x0": 50, "x1": 75},
    {"label": "Акт IV", "x0": 75, "x1": 100},
]

CHARACTER_CARD_LIMIT = 30


def slug_lane(name: str) -> str:
    base = name.split("(")[0].strip().split()[0].lower().translate(CYRILLIC_SLUG)
    slug = re.sub(r"[^a-z0-9]+", "", base)
    return slug or "hero"


def normalize_name(raw: str) -> str:
    name = raw.strip()
    if "(" in name:
        name = name.split("(")[0].strip()
    return name


def canonical_person_name(name: str) -> str:
    """Сводит склонения и уменьшительные к одному имени."""
    clean = normalize_name(name)
    if not clean:
        return ""
    full_key = clean.lower()
    if full_key in NAME_VARIANTS:
        return NAME_VARIANTS[full_key]
    first = clean.split()[0]
    key = first.lower()
    if key in NAME_VARIANTS:
        return NAME_VARIANTS[key]
    if len(clean.split()) >= 2:
        second = clean.split()[1].lower()
        if second.endswith(("ович", "евич", "ич", "овна", "евна", "ьевич")):
            return clean
    return clean


def is_probable_person_name(name: str) -> bool:
    clean = normalize_name(name)
    if not clean or clean in STOP_NAMES:
        return False
    parts = clean.split()
    first = parts[0]
    if first in STOP_NAMES:
        return False
    low = first.lower()
    if low in TITLE_NOISE:
        return False
    if len(parts) >= 2:
        second = parts[1].lower()
        if second.endswith(("ович", "евич", "ич", "овна", "евна", "ьевич")):
            return True
        if low not in NAME_VARIANTS:
            return False
    if low in NAME_VARIANTS:
        return True
    if low.endswith(("ович", "евич", "ич")) and len(parts) == 1:
        return False
    if low.endswith(("ыч", "ич", "ка", "ша", "ня")) and len(low) >= 5:
        return True
    if len(first) <= 2:
        return False
    return True


def is_sentence_start_only(name: str, text: str) -> bool:
    """Отсекает «Мне», «На», «Не» — слова только в начале предложения."""
    if not text or not name:
        return False
    first = name.split()[0]
    if first in NAME_VARIANTS or first.lower().endswith(("ыч", "ич")):
        return False
    escaped = re.escape(first)
    all_re = re.compile(rf"(?<![а-яёА-ЯЁ]){escaped}(?![а-яёА-ЯЁ])")
    start_re = re.compile(
        rf"(?:^|[.!?…][\s\n]+|\n\s*){escaped}(?![а-яёА-ЯЁ])",
        re.MULTILINE,
    )
    total = len(all_re.findall(text))
    if total < 3:
        return False
    at_start = len(start_re.findall(text))
    return at_start / total >= 0.75


def extract_names_from_title(title: str) -> list[str]:
    """Имена из заголовка: «Тимур: …», «Встреча с Кирюхой»."""
    found: list[str] = []
    title = re.sub(r"^\d+\.\s*", "", (title or "").strip())
    if not title:
        return found

    head = re.match(r"^([А-ЯЁ][а-яё]+)\s*:", title)
    if head:
        name = canonical_person_name(head.group(1))
        if is_probable_person_name(name):
            found.append(name)

    for match in re.finditer(
        r"(?:\bс\s+|\bи\s+|\bо\s+|\bу\s+)([А-ЯЁ][а-яё]+)",
        title,
        re.IGNORECASE,
    ):
        name = canonical_person_name(match.group(1))
        if is_probable_person_name(name):
            found.append(name)

    for match in NAME_RE.finditer(title):
        name = canonical_person_name(normalize_name(match.group(1)))
        if is_probable_person_name(name):
            found.append(name)

    return found


def is_cast_member(name: str) -> bool:
    """Имя похоже на персонажа книги (не случайное слово из текста)."""
    canon = canonical_person_name(name)
    if not canon:
        return False
    first = canon.split()[0]
    low = first.lower()
    if canon in STOP_NAMES or first in STOP_NAMES or low in TITLE_NOISE:
        return False
    if canon in CANONICAL_CAST or low in NAME_VARIANTS:
        return True
    parts = canon.split()
    if len(parts) >= 2 and parts[1].lower().endswith(
        ("ович", "евич", "ич", "овна", "евна", "ьевич")
    ):
        return True
    if low.endswith(("ыч", "ич")) and len(low) >= 5:
        return True
    return False


def is_garbage_character_name(name: str) -> bool:
    return not is_cast_member(name)


def extract_names(text: str) -> list[str]:
    found: list[str] = []
    plain = text or ""
    for match in PATRONYMIC_RE.finditer(plain):
        full = f"{match.group(1)} {match.group(2)}"
        name = canonical_person_name(full)
        if is_probable_person_name(name):
            found.append(name)
    for match in NAME_RE.finditer(plain):
        name = canonical_person_name(normalize_name(match.group(1)))
        if not is_probable_person_name(name):
            continue
        if is_sentence_start_only(name, plain):
            continue
        found.append(name)
    return found


def count_mentions(chapters: list[dict[str, Any]]) -> dict[str, int]:
    body_counts: dict[str, int] = {}
    title_counts: dict[str, int] = {}

    for ch in chapters:
        title = ch.get("title") or ""
        plain = html_to_plain(ch.get("content") or "")

        for name in extract_names(plain):
            body_counts[name] = body_counts.get(name, 0) + 1

        for name in extract_names_from_title(title):
            title_counts[name] = title_counts.get(name, 0) + 5

    counts: dict[str, int] = {}
    for name in set(body_counts) | set(title_counts):
        body = body_counts.get(name, 0)
        title = title_counts.get(name, 0)
        if body == 0 and title < 5:
            continue
        score = body + title
        stem = name.split()[0].lower()
        if stem in NAME_VARIANTS or stem.endswith(("ыч", "ич")):
            score += 3
        counts[name] = score
    return counts


def mention_count_for_character(chapters: list[dict[str, Any]], character_name: str) -> int:
    """Сколько раз имя героя встречается в главах (0 = ещё не введён в текст)."""
    name = (character_name or "").strip()
    if not name:
        return 0
    counts = count_mentions(chapters)
    canon = canonical_person_name(name)
    if canon in counts:
        return counts[canon]
    if name in counts:
        return counts[name]
    first = canon.split()[0]
    for key, value in counts.items():
        if key == first or key.split()[0] == first:
            return value
        if canonical_person_name(key) == canon:
            return value
    return 0


def first_sentence_with_name(text: str, name: str, limit: int = 280) -> str:
    plain = html_to_plain(text or "")
    if not plain:
        return "упоминается в тексте книги."
    parts = re.split(r"(?<=[.!?…])\s+", plain)
    needle = name.split()[0]
    for sentence in parts:
        if needle in sentence:
            s = re.sub(r"\s+", " ", sentence).strip()
            if len(s) > limit:
                s = s[: limit - 1].rstrip() + "…"
            return s
    snippet = plain[:limit].strip()
    if len(plain) > limit:
        snippet += "…"
    return snippet or "упоминается в тексте книги."


def generate_heroes_text(
    chapters: list[dict[str, Any]], limit: int = CHARACTER_CARD_LIMIT
) -> str:
    counts = count_mentions(chapters)
    if not counts:
        return "Пока не найдено имён в тексте. Напишите больше глав и нажмите «Обновить»."

    min_count = 2 if len(chapters) <= 3 else 3
    ranked = sorted(
        (
            (name, cnt)
            for name, cnt in counts.items()
            if cnt >= min_count and is_cast_member(name)
        ),
        key=lambda item: (-item[1], item[0]),
    )[:limit]
    if not ranked:
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[: min(5, len(counts))]

    full_text = "\n\n".join(
        html_to_plain(ch.get("content") or "") for ch in chapters
    )
    lines: list[str] = []
    for name, _ in ranked:
        desc = first_sentence_with_name(full_text, name)
        lines.append(f"{name} — {desc}")
    return "\n\n".join(lines)


def find_first_chapter_with_name(chapters: list[dict[str, Any]], name: str) -> str | None:
    canon = canonical_person_name(name)
    needles = {canon.split()[0].lower()}
    key = canon.split()[0].lower()
    for variant, target in NAME_VARIANTS.items():
        if target == canon or target.split()[0].lower() == key:
            needles.add(variant)
    for ch in chapters:
        plain = html_to_plain(ch.get("content") or "").lower()
        title = (ch.get("title") or "").lower()
        if any(n in plain or n in title for n in needles):
            return ch.get("ch_id")
    return None


def generate_characters_from_chapters(
    chapters: list[dict[str, Any]], limit: int = CHARACTER_CARD_LIMIT
) -> list[dict[str, Any]]:
    counts = count_mentions(chapters)
    if not counts:
        return []

    min_count = 2 if len(chapters) <= 3 else 3
    ranked = sorted(
        (
            (name, cnt)
            for name, cnt in counts.items()
            if cnt >= min_count and is_cast_member(name)
        ),
        key=lambda item: (-item[1], item[0]),
    )[:limit]
    if not ranked:
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[: min(5, len(counts))]

    full_text = "\n\n".join(
        html_to_plain(ch.get("content") or "") for ch in chapters
    )
    characters: list[dict[str, Any]] = []
    for idx, (name, _) in enumerate(ranked):
        display_name = canonical_person_name(name)
        summary = first_sentence_with_name(full_text, display_name, limit=280)
        if len(summary) > 300:
            summary = summary[:297] + "…"
        role_type = "protagonist" if idx == 0 else "secondary"
        characters.append(
            {
                "name": display_name,
                "role_type": role_type,
                "summary": summary,
                "bio": "",
                "relations_json": {},
                "first_ch_id": find_first_chapter_with_name(chapters, display_name),
                "color": LANE_COLORS[idx % len(LANE_COLORS)],
            }
        )
    return characters


def act_x_position(act_number: int, index_in_act: int, total_in_act: int) -> float:
    idx = min(max(act_number, 1), len(PLOT_ACTS)) - 1
    band = PLOT_ACTS[idx]
    span = band["x1"] - band["x0"]
    if total_in_act <= 1:
        return band["x0"] + span * 0.5
    step = span / (total_in_act + 1)
    return band["x0"] + step * (index_in_act + 1)


def short_plot_label(title: str) -> str:
    title = (title or "").strip()
    if ":" in title:
        title = title.split(":", 1)[1].strip()
    title = re.sub(r"^\d+\.\s*", "", title)
    words = title.split()
    if not words:
        return "Сцена"
    label = words[0]
    if len(words) > 1 and len(label) < 8:
        label = " ".join(words[:2])
    return label[:18]


def chapter_lane_counts(
    ch: dict[str, Any], hero_names: list[str]
) -> dict[str, int]:
    title = ch.get("title") or ""
    plain = html_to_plain(ch.get("content") or "")
    blob = f"{title}\n{plain}".lower()
    counts: dict[str, int] = {}
    for name in hero_names:
        needle = name.split()[0].lower()
        if needle in blob:
            counts[name] = blob.count(needle)
    return counts


def is_flashback(ch: dict[str, Any]) -> bool:
    title = ch.get("title") or ""
    plain = html_to_plain(ch.get("content") or "")
    return bool(FLASHBACK_RE.search(f"{title}\n{plain}"))


def generate_plot_json(chapters: list[dict[str, Any]]) -> dict[str, Any]:
    counts = count_mentions(chapters)
    min_count = 2 if len(chapters) <= 3 else 3
    hero_names = [
        name
        for name, cnt in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if cnt >= min_count
    ][:6]
    if not hero_names and counts:
        hero_names = [
            name
            for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
        ]

    lanes = []
    lane_ids: dict[str, str] = {}
    for idx, name in enumerate(hero_names):
        lane_id = slug_lane(name)
        if lane_id in lane_ids.values():
            lane_id = f"{lane_id}{idx}"
        lane_ids[name] = lane_id
        lanes.append(
            {
                "id": lane_id,
                "label": name.split()[0],
                "color": LANE_COLORS[idx % len(LANE_COLORS)],
            }
        )

    acts: dict[int, list[dict[str, Any]]] = {}
    for ch in chapters:
        act = int(ch.get("act_number") or 1)
        acts.setdefault(act, []).append(ch)

    plot_chapters: list[dict[str, Any]] = []
    for ch in chapters:
        act = int(ch.get("act_number") or 1)
        act_list = acts.get(act, [ch])
        index_in_act = act_list.index(ch)
        x = round(act_x_position(act, index_in_act, len(act_list)), 1)
        lane_counts = chapter_lane_counts(ch, hero_names)
        if not lane_counts:
            continue

        sorted_lanes = sorted(lane_counts.items(), key=lambda item: -item[1])
        primary_name, primary_count = sorted_lanes[0]
        event_type = "flashback" if is_flashback(ch) else "normal"
        label = short_plot_label(ch.get("title") or "")
        plot_events = [
            {
                "lane": lane_ids[primary_name],
                "x": x,
                "label": label,
                "type": event_type,
            }
        ]
        for name, cnt in sorted_lanes[1:3]:
            if primary_count and cnt >= max(2, primary_count * 0.35):
                plot_events.append(
                    {
                        "lane": lane_ids[name],
                        "x": x,
                        "label": label,
                        "type": event_type,
                    }
                )

        plot_chapters.append(
            {
                "id": ch.get("ch_id"),
                "title": ch.get("title") or "",
                "act": act,
                "emoji": ch.get("emoji") or "🟢",
                "plot": plot_events,
            }
        )

    return {
        "lanes": lanes,
        "acts": PLOT_ACTS,
        "parallels": [],
        "chapters": plot_chapters,
    }


def plot_json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def plot_json_loads(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
