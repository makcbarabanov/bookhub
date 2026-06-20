"""Import checklist_html into book_notes and prune Morpheus junk."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from stats_util import html_to_plain

JUNK_TITLE_SQL = """
    title ILIKE '%%канон персонаж%%'
    OR title ILIKE '%%канон геро%%'
    OR title ILIKE '%%список геро%%'
    OR title ILIKE '%%герои книги%%'
    OR title ILIKE '%%Татьян%%'
    OR title ILIKE '%%Морфеус%%'
    OR title ILIKE '%%фрагмент сознания%%'
    OR title ILIKE 'Артур —%%'
    OR title ILIKE '%%полный анализ%%'
    OR title ILIKE '%%полный список%%'
"""


def delete_morpheus_junk_notes(conn, book_id: int) -> int:
    rows = conn.execute(
        f"""
        DELETE FROM book_notes
        WHERE book_id = %s AND is_section = FALSE AND ({JUNK_TITLE_SQL})
        RETURNING id
        """,
        (book_id,),
    ).fetchall()
    return len(rows)


def _next_sort_order(conn, book_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM book_notes WHERE book_id = %s",
        (book_id,),
    ).fetchone()
    return int(row["n"] if row else 0)


def _insert_note(
    conn,
    book_id: int,
    title: str,
    content: str,
    sort_order: int,
    is_section: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO book_notes (book_id, title, content, sort_order, is_section)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (book_id, title[:255], content or "", sort_order, is_section),
    )


def migrate_checklist_html_to_notes(
    conn, book_id: int, checklist_html: str, section_title: str = "Сводный Чек-лист Идей"
) -> int:
    """Parse checklist HTML into numbered notes. Returns count of new item notes."""
    html = (checklist_html or "").strip()
    if not html:
        return 0

    has_section = conn.execute(
        """
        SELECT 1 FROM book_notes
        WHERE book_id = %s AND is_section = TRUE AND title = %s
        LIMIT 1
        """,
        (book_id, section_title),
    ).fetchone()
    sort_order = _next_sort_order(conn, book_id)
    if not has_section:
        _insert_note(conn, book_id, section_title, "", sort_order, is_section=True)
        sort_order += 1

    wrap = BeautifulSoup(f"<div id='root'>{html}</div>", "html.parser")
    root = wrap.find(id="root")
    if not root:
        return 0

    created = 0
    for child in root.children:
        if not hasattr(child, "name"):
            continue
        classes = child.get("class") or []
        if "atlas-note" in classes:
            h4 = child.find("h4")
            title = (h4.get_text(strip=True) if h4 else "") or "Заметка"
            content = html_to_plain(str(child))
            if len(content) > 8000:
                content = content[:8000] + "…"
            _insert_note(conn, book_id, title, content, sort_order)
            sort_order += 1
            created += 1
        elif "max-text" in classes:
            plain = html_to_plain(str(child))
            for line in plain.split("\n"):
                line = re.sub(r"\s+", " ", line).strip()
                if not line or len(line) < 4:
                    continue
                title = line[:120] + ("…" if len(line) > 120 else "")
                _insert_note(conn, book_id, title, line, sort_order)
                sort_order += 1
                created += 1

    return created


def repair_blob_checklist_note(conn, book_id: int, section_title: str = "Сводный Чек-лист Идей") -> int:
    """Split legacy blob note «Идеи из чек-листа» into numbered lines."""
    row = conn.execute(
        """
        SELECT id, content FROM book_notes
        WHERE book_id = %s AND is_section = FALSE AND title = 'Идеи из чек-листа'
        LIMIT 1
        """,
        (book_id,),
    ).fetchone()
    if not row:
        return 0
    content = (row.get("content") or "").strip()
    conn.execute("DELETE FROM book_notes WHERE id = %s", (row["id"],))
    if not content:
        return 0
    has_section = conn.execute(
        """
        SELECT 1 FROM book_notes
        WHERE book_id = %s AND is_section = TRUE AND title = %s
        LIMIT 1
        """,
        (book_id, section_title),
    ).fetchone()
    sort_order = _next_sort_order(conn, book_id)
    if not has_section:
        _insert_note(conn, book_id, section_title, "", sort_order, is_section=True)
        sort_order += 1
    created = 0
    for line in content.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if not line or len(line) < 4:
            continue
        title = line[:120] + ("…" if len(line) > 120 else "")
        _insert_note(conn, book_id, title, line, sort_order)
        sort_order += 1
        created += 1
    return created


def ensure_checklist_section(
    conn, book_id: int, section_title: str = "Сводный Чек-лист Идей"
) -> None:
    has_section = conn.execute(
        """
        SELECT 1 FROM book_notes
        WHERE book_id = %s AND is_section = TRUE AND title = %s
        LIMIT 1
        """,
        (book_id, section_title),
    ).fetchone()
    if has_section:
        return
    has_notes = conn.execute(
        "SELECT 1 FROM book_notes WHERE book_id = %s LIMIT 1",
        (book_id,),
    ).fetchone()
    if not has_notes:
        return
    conn.execute(
        "UPDATE book_notes SET sort_order = sort_order + 1 WHERE book_id = %s",
        (book_id,),
    )
    _insert_note(conn, book_id, section_title, "", 0, is_section=True)


def normalize_notes_sort_order(conn, book_id: int) -> None:
    rows = conn.execute(
        "SELECT id FROM book_notes WHERE book_id = %s ORDER BY sort_order ASC, id ASC",
        (book_id,),
    ).fetchall()
    for idx, row in enumerate(rows):
        conn.execute(
            "UPDATE book_notes SET sort_order = %s WHERE id = %s",
            (idx, row["id"]),
        )


def format_notes_for_ai(notes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in notes:
        title = str(row.get("title") or "").strip()
        if row.get("is_section"):
            lines.append(f"## {title}")
            continue
        body = (row.get("content") or "").strip()
        if body and body != title:
            lines.append(f"- {title}: {body[:600]}")
        elif title:
            lines.append(f"- {title}")
    return "\n".join(lines)[:12000]
