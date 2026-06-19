"""Text volume stats for author profile."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

CHARS_PER_PAGE = 1800


def html_to_plain(content_html: str) -> str:
    soup = BeautifulSoup(content_html or "", "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.append("\n")
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def measure_text(text: str) -> dict[str, int | float]:
    plain = (text or "").strip()
    characters = len(plain)
    words = len(re.findall(r"\S+", plain)) if plain else 0
    pages = round(characters / CHARS_PER_PAGE, 1) if characters else 0.0
    return {
        "characters": characters,
        "words": words,
        "pages": pages,
    }


def measure_html(content_html: str) -> dict[str, int | float]:
    return measure_text(html_to_plain(content_html))


def sum_measures(items: list[dict[str, int | float]]) -> dict[str, int | float]:
    chars = sum(int(i.get("characters", 0)) for i in items)
    words = sum(int(i.get("words", 0)) for i in items)
    pages = round(chars / CHARS_PER_PAGE, 1) if chars else 0.0
    return {"characters": chars, "words": words, "pages": pages}
