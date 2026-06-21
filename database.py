"""PostgreSQL helpers for BookHub."""

from __future__ import annotations

import glob
import os
from contextlib import contextmanager
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row

ACT_LABEL_LABELS = {
    1: "Акт I: Приговор",
    2: "Акт II: Подъём",
    3: "Акт III: Сочи",
    4: "Акт IV: 14:46",
}


def _dsn() -> str:
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ["DB_USER"]
    password = os.environ["DB_PASS"]
    dbname = os.environ.get("DB_NAME", "bookhub_prod")
    sslmode = os.environ.get("DB_SSLMODE", os.environ.get("DB_SSLMOE", "prefer"))
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}?sslmode={sslmode}"


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    conn = psycopg.connect(_dsn(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_migrations() -> None:
    sql_dir = os.path.join(os.path.dirname(__file__), "_sql")
    paths = sorted(glob.glob(os.path.join(sql_dir, "*.sql")))
    with get_conn() as conn:
        for path in paths:
            with open(path, encoding="utf-8") as f:
                conn.execute(f.read())


def fetch_user_by_login_or_phone(conn: psycopg.Connection, identifier: str) -> dict[str, Any] | None:
    from auth_util import normalize_phone

    ident = (identifier or "").strip()
    phone = normalize_phone(ident)
    row = conn.execute(
        """
        SELECT * FROM users
        WHERE is_active = TRUE
          AND (login = %s OR phone_e164 = %s OR phone_e164 = %s)
        LIMIT 1
        """,
        (ident, ident, phone),
    ).fetchone()
    return dict(row) if row else None


def fetch_user_books(conn: psycopg.Connection, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT b.id, b.title, b.slug, b.is_archived, bm.role, b.created_at, b.updated_at
        FROM book_memberships bm
        JOIN books b ON b.id = bm.book_id
        WHERE bm.user_id = %s AND b.is_archived = FALSE
        ORDER BY b.id
        """,
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def user_has_book_access(conn: psycopg.Connection, user_id: int, book_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM book_memberships
        WHERE user_id = %s AND book_id = %s
        LIMIT 1
        """,
        (user_id, book_id),
    ).fetchone()
    return row is not None


def get_active_book_id(conn: psycopg.Connection, user_id: int) -> int | None:
    pref = conn.execute(
        "SELECT active_book_id FROM user_preferences WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    if pref and pref["active_book_id"]:
        book_id = int(pref["active_book_id"])
        if user_has_book_access(conn, user_id, book_id):
            return book_id
    books = fetch_user_books(conn, user_id)
    return int(books[0]["id"]) if books else None


def set_active_book_id(conn: psycopg.Connection, user_id: int, book_id: int) -> None:
    if not user_has_book_access(conn, user_id, book_id):
        raise PermissionError("No access to book")
    conn.execute(
        """
        INSERT INTO user_preferences (user_id, active_book_id, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE
        SET active_book_id = EXCLUDED.active_book_id, updated_at = NOW()
        """,
        (user_id, book_id),
    )


def fetch_book(conn: psycopg.Connection, book_id: int | None = None) -> dict[str, Any] | None:
    if book_id:
        row = conn.execute("SELECT * FROM books WHERE id = %s", (book_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM books ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


def fetch_chapters(conn: psycopg.Connection, book_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, ch_id, title, act_number, emoji, sort_order, updated_at
        FROM chapters
        WHERE book_id = %s
        ORDER BY sort_order, id
        """,
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_chapters_full(conn: psycopg.Connection, book_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ch_id, title, act_number, emoji, content, sort_order
        FROM chapters
        WHERE book_id = %s
        ORDER BY sort_order, id
        """,
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_chapter_by_ch_id(conn: psycopg.Connection, book_id: int, ch_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM chapters WHERE book_id = %s AND ch_id = %s",
        (book_id, ch_id),
    ).fetchone()
    return dict(row) if row else None


def fetch_user_profile_row(conn: psycopg.Connection, user_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, login, phone_e164, display_name,
               first_name, last_name, patronymic, created_at
        FROM users
        WHERE id = %s AND is_active = TRUE
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def fetch_user_chapter_contents(conn: psycopg.Connection, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT b.id AS book_id, b.title, c.content, c.updated_at
        FROM book_memberships bm
        JOIN books b ON b.id = bm.book_id
        JOIN chapters c ON c.book_id = b.id
        WHERE bm.user_id = %s AND b.is_archived = FALSE
        ORDER BY b.id, c.sort_order, c.id
        """,
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_user_writing_started_at(conn: psycopg.Connection, user_id: int):
    row = conn.execute(
        """
        SELECT MIN(c.updated_at) AS writing_started_at
        FROM book_memberships bm
        JOIN books b ON b.id = bm.book_id
        JOIN chapters c ON c.book_id = b.id
        WHERE bm.user_id = %s AND b.is_archived = FALSE
        """,
        (user_id,),
    ).fetchone()
    return row["writing_started_at"] if row else None


def fetch_user_last_edited_at(conn: psycopg.Connection, user_id: int):
    row = conn.execute(
        """
        SELECT MAX(c.updated_at) AS last_edited_at
        FROM book_memberships bm
        JOIN books b ON b.id = bm.book_id
        JOIN chapters c ON c.book_id = b.id
        WHERE bm.user_id = %s AND b.is_archived = FALSE
        """,
        (user_id,),
    ).fetchone()
    return row["last_edited_at"] if row else None


def ensure_book_service(conn: psycopg.Connection, book_id: int) -> None:
    conn.execute(
        """
        INSERT INTO book_service (book_id)
        VALUES (%s)
        ON CONFLICT (book_id) DO NOTHING
        """,
        (book_id,),
    )


def fetch_book_service(conn: psycopg.Connection, book_id: int) -> dict[str, Any]:
    ensure_book_service(conn, book_id)
    row = conn.execute(
        """
        SELECT book_id, checklist_html, heroes_text, plot_json,
               checklist_updated_at, heroes_updated_at, plot_updated_at
        FROM book_service
        WHERE book_id = %s
        """,
        (book_id,),
    ).fetchone()
    return dict(row) if row else {}


def update_book_service_checklist(conn: psycopg.Connection, book_id: int, html: str) -> None:
    ensure_book_service(conn, book_id)
    conn.execute(
        """
        UPDATE book_service
        SET checklist_html = %s, checklist_updated_at = NOW()
        WHERE book_id = %s
        """,
        (html, book_id),
    )


def update_book_service_heroes(conn: psycopg.Connection, book_id: int, text: str) -> None:
    ensure_book_service(conn, book_id)
    conn.execute(
        """
        UPDATE book_service
        SET heroes_text = %s, heroes_updated_at = NOW()
        WHERE book_id = %s
        """,
        (text, book_id),
    )


def update_book_service_plot(conn: psycopg.Connection, book_id: int, plot: dict[str, Any]) -> None:
    import json

    ensure_book_service(conn, book_id)
    conn.execute(
        """
        UPDATE book_service
        SET plot_json = %s::jsonb, plot_updated_at = NOW()
        WHERE book_id = %s
        """,
        (json.dumps(plot, ensure_ascii=False), book_id),
    )


def delete_book_service(conn: psycopg.Connection, book_id: int) -> None:
    conn.execute("DELETE FROM book_service WHERE book_id = %s", (book_id,))


def fetch_book_analysis(conn: psycopg.Connection, book_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT book_id, analysis_json, model, tokens_in, tokens_out, created_at, updated_at
        FROM book_analyses
        WHERE book_id = %s
        """,
        (book_id,),
    ).fetchone()
    return dict(row) if row else None


def upsert_book_analysis(
    conn: psycopg.Connection,
    book_id: int,
    analysis: dict[str, Any],
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> dict[str, Any]:
    import json

    row = conn.execute(
        """
        INSERT INTO book_analyses (book_id, analysis_json, model, tokens_in, tokens_out, updated_at)
        VALUES (%s, %s::jsonb, %s, %s, %s, NOW())
        ON CONFLICT (book_id) DO UPDATE SET
            analysis_json = EXCLUDED.analysis_json,
            model = EXCLUDED.model,
            tokens_in = EXCLUDED.tokens_in,
            tokens_out = EXCLUDED.tokens_out,
            updated_at = NOW()
        RETURNING book_id, analysis_json, model, tokens_in, tokens_out, created_at, updated_at
        """,
        (book_id, json.dumps(analysis, ensure_ascii=False), model, tokens_in, tokens_out),
    ).fetchone()
    return dict(row)


def update_book_analysis_json(
    conn: psycopg.Connection, book_id: int, analysis: dict[str, Any]
) -> dict[str, Any] | None:
    import json

    row = conn.execute(
        """
        UPDATE book_analyses
        SET analysis_json = %s::jsonb, updated_at = NOW()
        WHERE book_id = %s
        RETURNING book_id, analysis_json, model, tokens_in, tokens_out, created_at, updated_at
        """,
        (json.dumps(analysis, ensure_ascii=False), book_id),
    ).fetchone()
    return dict(row) if row else None


def log_ai_usage(
    conn: psycopg.Connection,
    user_id: int,
    book_id: int | None,
    endpoint: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> None:
    conn.execute(
        """
        INSERT INTO ai_usage_log (user_id, book_id, endpoint, model, tokens_in, tokens_out)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (user_id, book_id, endpoint, model, tokens_in, tokens_out),
    )


def count_ai_refresh_since(conn: psycopg.Connection, user_id: int, since_hours: int = 1) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM ai_usage_log
        WHERE user_id = %s
          AND endpoint = 'ai-analysis-refresh'
          AND created_at > NOW() - make_interval(hours => %s)
        """,
        (user_id, since_hours),
    ).fetchone()
    return int(row["cnt"]) if row else 0


def count_chapter_ai_since(conn: psycopg.Connection, user_id: int, since_hours: int = 1) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM ai_usage_log
        WHERE user_id = %s
          AND endpoint IN ('ai-chapter-errors', 'ai-chapter-plot')
          AND created_at > NOW() - make_interval(hours => %s)
        """,
        (user_id, since_hours),
    ).fetchone()
    return int(row["cnt"]) if row else 0


def count_chat_send_since(conn: psycopg.Connection, user_id: int, since_hours: int = 1) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM ai_usage_log
        WHERE user_id = %s
          AND endpoint = 'chat-send'
          AND created_at > NOW() - make_interval(hours => %s)
        """,
        (user_id, since_hours),
    ).fetchone()
    return int(row["cnt"]) if row else 0


def fetch_book_ai_summary(conn: psycopg.Connection, book_id: int) -> str:
    row = conn.execute("SELECT ai_summary FROM books WHERE id = %s", (book_id,)).fetchone()
    return (row.get("ai_summary") or "") if row else ""


def update_book_ai_summary(conn: psycopg.Connection, book_id: int, summary: str) -> None:
    conn.execute(
        "UPDATE books SET ai_summary = %s, updated_at = NOW() WHERE id = %s",
        (summary or "", book_id),
    )


def fetch_chat_messages(conn: psycopg.Connection, book_id: int, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, book_id, sender, message, created_at
        FROM book_chat_messages
        WHERE book_id = %s
        ORDER BY created_at ASC
        LIMIT %s
        """,
        (book_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_chat_messages_recent(conn: psycopg.Connection, book_id: int, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT sender, message, created_at
        FROM book_chat_messages
        WHERE book_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (book_id, limit),
    ).fetchall()
    return list(reversed([dict(r) for r in rows]))


def insert_chat_message(
    conn: psycopg.Connection, book_id: int, sender: str, message: str
) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO book_chat_messages (book_id, sender, message)
        VALUES (%s, %s, %s)
        RETURNING id, book_id, sender, message, created_at
        """,
        (book_id, sender, message),
    ).fetchone()
    return dict(row)


def delete_chat_messages(conn: psycopg.Connection, book_id: int) -> int:
    rows = conn.execute(
        """
        DELETE FROM book_chat_messages
        WHERE book_id = %s
        RETURNING id
        """,
        (book_id,),
    ).fetchall()
    return len(rows)


def fetch_book_notes(conn: psycopg.Connection, book_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, book_id, title, content, sort_order, is_section,
               created_at, updated_at
        FROM book_notes
        WHERE book_id = %s
        ORDER BY sort_order ASC, id ASC
        """,
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_book_note(conn: psycopg.Connection, book_id: int, note_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, book_id, title, content, sort_order, is_section,
               created_at, updated_at
        FROM book_notes
        WHERE book_id = %s AND id = %s
        """,
        (book_id, note_id),
    ).fetchone()
    return dict(row) if row else None


def insert_book_note(
    conn: psycopg.Connection,
    book_id: int,
    title: str,
    content: str,
    sort_order: int | None = None,
    is_section: bool = False,
) -> dict[str, Any]:
    if sort_order is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM book_notes WHERE book_id = %s",
            (book_id,),
        ).fetchone()
        sort_order = int(row["n"] if row else 0)
    row = conn.execute(
        """
        INSERT INTO book_notes (book_id, title, content, sort_order, is_section)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, book_id, title, content, sort_order, is_section,
                  created_at, updated_at
        """,
        (book_id, title[:255], content, sort_order, is_section),
    ).fetchone()
    return dict(row)


def update_book_note(
    conn: psycopg.Connection,
    book_id: int,
    note_id: int,
    title: str,
    content: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        UPDATE book_notes
        SET title = %s, content = %s, updated_at = NOW()
        WHERE book_id = %s AND id = %s
        RETURNING id, book_id, title, content, sort_order, is_section,
                  created_at, updated_at
        """,
        (title[:255], content, book_id, note_id),
    ).fetchone()
    return dict(row) if row else None


def delete_book_note(conn: psycopg.Connection, book_id: int, note_id: int) -> bool:
    row = conn.execute(
        """
        DELETE FROM book_notes
        WHERE book_id = %s AND id = %s
        RETURNING id
        """,
        (book_id, note_id),
    ).fetchone()
    return row is not None


def update_user_profile(
    conn: psycopg.Connection,
    user_id: int,
    first_name: str | None,
    last_name: str | None,
    patronymic: str | None,
) -> None:
    display = " ".join(p for p in [last_name, first_name, patronymic] if p).strip() or None
    conn.execute(
        """
        UPDATE users
        SET first_name = %s, last_name = %s, patronymic = %s, display_name = COALESCE(%s, display_name)
        WHERE id = %s
        """,
        (first_name or None, last_name or None, patronymic or None, display, user_id),
    )


def fetch_book_characters(conn: psycopg.Connection, book_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, book_id, name, role_type, summary, bio, relations_json,
               first_ch_id, color, avatar_url, created_at, updated_at
        FROM book_characters
        WHERE book_id = %s
        ORDER BY
            CASE role_type
                WHEN 'protagonist' THEN 0
                WHEN 'antagonist' THEN 1
                ELSE 2
            END,
            name
        """,
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_book_character(
    conn: psycopg.Connection, book_id: int, character_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, book_id, name, role_type, summary, bio, relations_json,
               first_ch_id, color, avatar_url, created_at, updated_at
        FROM book_characters
        WHERE book_id = %s AND id = %s
        """,
        (book_id, character_id),
    ).fetchone()
    return dict(row) if row else None


def insert_book_character(
    conn: psycopg.Connection,
    book_id: int,
    name: str,
    role_type: str,
    summary: str,
    bio: str = "",
    relations: dict[str, Any] | None = None,
    first_ch_id: str | None = None,
    color: str = "#888888",
    avatar_url: str | None = None,
) -> dict[str, Any]:
    import json

    row = conn.execute(
        """
        INSERT INTO book_characters (
            book_id, name, role_type, summary, bio, relations_json,
            first_ch_id, color, avatar_url, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, NOW())
        RETURNING id, book_id, name, role_type, summary, bio, relations_json,
                  first_ch_id, color, avatar_url, created_at, updated_at
        """,
        (
            book_id,
            name[:120],
            role_type,
            summary[:300],
            bio or "",
            json.dumps(relations or {}, ensure_ascii=False),
            first_ch_id,
            color[:7] if color else "#888888",
            avatar_url,
        ),
    ).fetchone()
    return dict(row)


def update_book_character(
    conn: psycopg.Connection,
    book_id: int,
    character_id: int,
    *,
    name: str,
    role_type: str,
    summary: str,
    bio: str = "",
    relations: dict[str, Any] | None = None,
    first_ch_id: str | None = None,
    color: str = "#888888",
    avatar_url: str | None = None,
) -> dict[str, Any] | None:
    import json

    row = conn.execute(
        """
        UPDATE book_characters
        SET name = %s, role_type = %s, summary = %s, bio = %s,
            relations_json = %s::jsonb, first_ch_id = %s, color = %s,
            avatar_url = COALESCE(%s, avatar_url), updated_at = NOW()
        WHERE book_id = %s AND id = %s
        RETURNING id, book_id, name, role_type, summary, bio, relations_json,
                  first_ch_id, color, avatar_url, created_at, updated_at
        """,
        (
            name[:120],
            role_type,
            summary[:300],
            bio or "",
            json.dumps(relations or {}, ensure_ascii=False),
            first_ch_id,
            color[:7] if color else "#888888",
            avatar_url,
            book_id,
            character_id,
        ),
    ).fetchone()
    return dict(row) if row else None


def update_book_character_avatar(
    conn: psycopg.Connection, book_id: int, character_id: int, avatar_url: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        UPDATE book_characters
        SET avatar_url = %s, updated_at = NOW()
        WHERE book_id = %s AND id = %s
        RETURNING id, book_id, name, role_type, summary, bio, relations_json,
                  first_ch_id, color, avatar_url, created_at, updated_at
        """,
        (avatar_url, book_id, character_id),
    ).fetchone()
    return dict(row) if row else None


def upsert_book_character_by_name(
    conn: psycopg.Connection,
    book_id: int,
    name: str,
    role_type: str,
    summary: str,
    bio: str = "",
    relations: dict[str, Any] | None = None,
    first_ch_id: str | None = None,
    color: str = "#888888",
) -> dict[str, Any]:
    import json

    row = conn.execute(
        """
        INSERT INTO book_characters (
            book_id, name, role_type, summary, bio, relations_json,
            first_ch_id, color, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, NOW())
        ON CONFLICT (book_id, name) DO UPDATE SET
            summary = EXCLUDED.summary,
            bio = CASE WHEN book_characters.bio = '' THEN EXCLUDED.bio ELSE book_characters.bio END,
            role_type = EXCLUDED.role_type,
            first_ch_id = COALESCE(EXCLUDED.first_ch_id, book_characters.first_ch_id),
            color = EXCLUDED.color,
            updated_at = NOW()
        RETURNING id, book_id, name, role_type, summary, bio, relations_json,
                  first_ch_id, color, avatar_url, created_at, updated_at
        """,
        (
            book_id,
            name[:120],
            role_type,
            summary[:300],
            bio or "",
            json.dumps(relations or {}, ensure_ascii=False),
            first_ch_id,
            color[:7] if color else "#888888",
        ),
    ).fetchone()
    return dict(row)


def delete_book_character(conn: psycopg.Connection, book_id: int, character_id: int) -> bool:
    row = conn.execute(
        """
        DELETE FROM book_characters
        WHERE book_id = %s AND id = %s
        RETURNING id
        """,
        (book_id, character_id),
    ).fetchone()
    return row is not None
