"""Auto-generate heroes and plotline from chapter text."""

from __future__ import annotations

import json
import re
from typing import Any

from stats_util import html_to_plain

NAME_RE = re.compile(
    r"(?<![а-яёА-ЯЁ])([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?(?:\s*\([^)]+\))?)"
)

STOP_NAMES = {
    "А",
    "Бог",
    "В",
    "Все",
    "Вы",
    "Где",
    "Германия",
    "Глава",
    "Да",
    "Его",
    "Её",
    "Если",
    "И",
    "Их",
    "Как",
    "Когда",
    "Кто",
    "Москва",
    "Мы",
    "Нет",
    "Новая",
    "Но",
    "Он",
    "Она",
    "Они",
    "Россия",
    "Слава",
    "Сочи",
    "Так",
    "Татьяна",
    "Ты",
    "Что",
    "Это",
    "Я",
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


def slug_lane(name: str) -> str:
    base = name.split("(")[0].strip().split()[0].lower().translate(CYRILLIC_SLUG)
    slug = re.sub(r"[^a-z0-9]+", "", base)
    return slug or "hero"


def normalize_name(raw: str) -> str:
    name = raw.strip()
    if "(" in name:
        name = name.split("(")[0].strip()
    return name


def extract_names(text: str) -> list[str]:
    found: list[str] = []
    for match in NAME_RE.finditer(text or ""):
        name = normalize_name(match.group(1))
        if len(name) < 2 or name in STOP_NAMES:
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

        for name in extract_names(title):
            title_counts[name] = title_counts.get(name, 0) + 2

        for part in re.split(r"[:—–-]", title, maxsplit=1):
            for name in extract_names(part):
                title_counts[name] = title_counts.get(name, 0) + 3

    counts: dict[str, int] = {}
    for name in set(body_counts) | set(title_counts):
        body = body_counts.get(name, 0)
        title = title_counts.get(name, 0)
        if body == 0 and title < 3:
            continue
        counts[name] = body + title
    return counts


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


def generate_heroes_text(chapters: list[dict[str, Any]], limit: int = 12) -> str:
    counts = count_mentions(chapters)
    if not counts:
        return "Пока не найдено имён в тексте. Напишите больше глав и нажмите «Обновить»."

    min_count = 2 if len(chapters) <= 3 else 3
    ranked = sorted(
        ((name, cnt) for name, cnt in counts.items() if cnt >= min_count),
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
