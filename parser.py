"""Parse BookHub HTML drafts (1445.html format)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

ACT_LABELS = {
    1: "Акт I: Приговор",
    2: "Акт II: Подъём",
    3: "Акт III: Сочи",
    4: "Акт IV: 14:46",
}


@dataclass
class ParsedChapter:
    ch_id: str
    title: str
    act_number: int
    emoji: str
    content: str
    sort_order: int


def _extract_chapters_js_meta(html: str) -> dict[str, dict]:
    """Parse `var chapters = [...]` block when present."""
    match = re.search(r"var\s+chapters\s*=\s*(\[[\s\S]*?\]);", html)
    if not match:
        return {}
    try:
        items = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    meta: dict[str, dict] = {}
    for item in items:
        ch_id = item.get("id")
        if not ch_id:
            continue
        meta[ch_id] = {
            "title": (item.get("title") or "").strip(),
            "act": int(item.get("act") or 1),
            "emoji": (item.get("emoji") or "🟢").strip(),
        }
    return meta


def _chapter_content(container) -> str:
    parts: list[str] = []
    for node in container.find_all(["div"], class_=lambda c: c and ("max-text" in c or "atlas-note" in c)):
        parts.append(str(node))
    if parts:
        return "\n".join(parts)
    h2 = container.find("h2")
    if h2:
        for sib in h2.find_next_siblings():
            parts.append(str(sib))
    return "\n".join(parts)


def _title_from_h2(container, fallback: str) -> str:
    h2 = container.find("h2")
    if not h2:
        return fallback
    text = h2.get_text(strip=True)
    return re.sub(r"^\d+\.\s*", "", text) or fallback


def parse_book_html(html: str, book_title: str | None = None) -> tuple[str, list[ParsedChapter]]:
    soup = BeautifulSoup(html, "html.parser")
    if not book_title:
        title_tag = soup.find("title")
        book_title = title_tag.get_text(strip=True) if title_tag else "BookHub"
        book_title = re.sub(r"\s*—\s*1445\s*$", "", book_title).strip() or "BookHub"

    js_meta = _extract_chapters_js_meta(html)
    containers = soup.find_all("div", class_="chapter-container", id=re.compile(r"^ch\d+$"))

    if not containers:
        containers = []
        for h2 in soup.find_all("h2"):
            parent = h2.find_parent("div", class_="chapter-container")
            if parent and parent.get("id", "").startswith("ch"):
                containers.append(parent)

    chapters: list[ParsedChapter] = []
    for idx, container in enumerate(containers, start=1):
        ch_id = container.get("id", f"ch{idx}")
        meta = js_meta.get(ch_id, {})
        title = (
            container.get("data-chapter-title")
            or meta.get("title")
            or _title_from_h2(container, f"Глава {idx}")
        )
        emoji = container.get("data-nav-emoji") or meta.get("emoji") or "🟢"
        act_number = int(meta.get("act") or 1)
        content = _chapter_content(container)
        chapters.append(
            ParsedChapter(
                ch_id=ch_id,
                title=str(title).strip(),
                act_number=act_number,
                emoji=str(emoji).strip() or "🟢",
                content=content,
                sort_order=idx,
            )
        )

    return book_title, chapters
