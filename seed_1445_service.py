#!/usr/bin/env python3
"""Seed curated service-tab content for book «14:45» from static/index.html."""

from __future__ import annotations

import json
import os
import re

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from database import (
    fetch_book,
    get_conn,
    run_migrations,
    update_book_service_checklist,
    update_book_service_heroes,
    update_book_service_plot,
)
from service_analyzer import PLOT_ACTS

ROOT = os.path.dirname(__file__)
INDEX_PATH = os.path.join(ROOT, "static", "index.html")


def extract_checklist_html(soup: BeautifulSoup) -> str:
    panel = soup.find(id="checklist")
    if not panel:
        return ""
    parts: list[str] = []
    for child in panel.children:
        if getattr(child, "get", None) and child.get("class") and "checklist-header" in child.get("class", []):
            continue
        if getattr(child, "name", None):
            parts.append(str(child))
    return "\n".join(parts).strip()


def extract_heroes_text(soup: BeautifulSoup) -> str:
    body = soup.find(id="heroes-body")
    if body:
        return body.get_text("\n", strip=False).strip()
    heroes = soup.find(id="heroes")
    if not heroes:
        return ""
    max_text = heroes.find(class_="max-text")
    return max_text.get_text("\n", strip=False).strip() if max_text else ""


def extract_plot_json(html: str) -> dict:
    match = re.search(r"var chapters = (\[\s*\{.*?\n            \]);", html, re.DOTALL)
    if not match:
        return {}
    raw = match.group(1)
    raw = re.sub(r"\bid:\s*", '"id":', raw)
    raw = re.sub(r"\btitle:\s*", '"title":', raw)
    raw = re.sub(r"\bact:\s*", '"act":', raw)
    raw = re.sub(r"\bemoji:\s*", '"emoji":', raw)
    raw = re.sub(r"\bplot:\s*", '"plot":', raw)
    raw = re.sub(r"\blane:\s*", '"lane":', raw)
    raw = re.sub(r"\bx:\s*", '"x":', raw)
    raw = re.sub(r"\blabel:\s*", '"label":', raw)
    raw = re.sub(r"\btype:\s*", '"type":', raw)
    raw = re.sub(r"'([^']*)'", r'"\1"', raw)
    chapters = json.loads(raw)

    lanes = [
        {"id": "artur", "label": "Артур", "color": "#d9772b"},
        {"id": "timur", "label": "Тимур", "color": "#5c9fd4"},
        {"id": "luchik", "label": "Лучик", "color": "#e879a6"},
        {"id": "zavod", "label": "Завод", "color": "#6abf69"},
    ]
    parallels = [
        {"x": 68, "label": "Сочи · ресторан"},
        {"x": 84, "label": "Сочи ‖ офис · 14:45"},
    ]
    return {
        "lanes": lanes,
        "acts": PLOT_ACTS,
        "parallels": parallels,
        "chapters": [
            {
                "id": ch["id"],
                "title": ch["title"],
                "act": ch["act"],
                "emoji": ch.get("emoji", "🟢"),
                "plot": ch.get("plot", []),
            }
            for ch in chapters
        ],
    }


def main() -> None:
    load_dotenv()
    run_migrations()

    with open(INDEX_PATH, encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")

    checklist_html = extract_checklist_html(soup)
    heroes_text = extract_heroes_text(soup)
    plot = extract_plot_json(html)

    with get_conn() as conn:
        book = conn.execute(
            "SELECT id, title FROM books WHERE title = %s OR slug = %s ORDER BY id LIMIT 1",
            ("14:45", "1445"),
        ).fetchone()
        if not book:
            book = fetch_book(conn)
        if not book:
            raise SystemExit("Book not found — run import_1445.py first")

        book_id = int(book["id"])
        if checklist_html:
            update_book_service_checklist(conn, book_id, checklist_html)
        if heroes_text:
            update_book_service_heroes(conn, book_id, heroes_text)
        if plot.get("chapters"):
            update_book_service_plot(conn, book_id, plot)

        row = conn.execute(
            "SELECT checklist_updated_at, heroes_updated_at, plot_updated_at FROM book_service WHERE book_id = %s",
            (book_id,),
        ).fetchone()

    print(f"Seeded service content for book id={book_id} title={book['title']!r}")
    print(f"  checklist: {len(checklist_html)} chars")
    print(f"  heroes: {len(heroes_text)} chars")
    print(f"  plot chapters: {len(plot.get('chapters', []))}")
    if row:
        print(f"  updated: checklist={row['checklist_updated_at']} heroes={row['heroes_updated_at']} plot={row['plot_updated_at']}")


if __name__ == "__main__":
    main()
