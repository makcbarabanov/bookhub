#!/usr/bin/env python3
"""Import 1445.html into BookHub PostgreSQL database."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from auth_util import hash_password, normalize_phone
from database import fetch_book, get_conn, run_migrations
from parser import parse_book_html

DEFAULT_PHONE = os.environ.get("AUTH_PHONE", "+79886296030")
DEFAULT_LOGIN = os.environ.get("AUTH_USER", "makc")
DEFAULT_PASSWORD = os.environ.get("AUTH_PASSWORD", "6030")
DEFAULT_TITLE = "14:45"


def ensure_user(conn, phone: str, login: str, password: str) -> int:
    phone_e164 = normalize_phone(phone)
    row = conn.execute(
        "SELECT id FROM users WHERE phone_e164 = %s OR login = %s LIMIT 1",
        (phone_e164, login),
    ).fetchone()
    if row:
        user_id = int(row["id"])
        conn.execute(
            """
            UPDATE users
            SET phone_e164 = %s, login = %s, password_hash = %s,
                display_name = %s, is_active = TRUE
            WHERE id = %s
            """,
            (phone_e164, login, hash_password(password), login, user_id),
        )
        return user_id

    row = conn.execute(
        """
        INSERT INTO users (phone_e164, login, password_hash, display_name)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (phone_e164, login, hash_password(password), login),
    ).fetchone()
    return int(row["id"])


def ensure_book(conn, user_id: int, title: str) -> int:
    row = conn.execute(
        "SELECT id FROM books WHERE owner_user_id = %s ORDER BY id LIMIT 1",
        (user_id,),
    ).fetchone()
    if row:
        book_id = int(row["id"])
        conn.execute(
            "UPDATE books SET title = %s, slug = %s, updated_at = NOW() WHERE id = %s",
            (title, "1445", book_id),
        )
        return book_id

    book = fetch_book(conn)
    if book:
        book_id = int(book["id"])
        conn.execute(
            """
            UPDATE books
            SET title = %s, owner_user_id = %s, slug = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (title, user_id, "1445", book_id),
        )
        return book_id

    row = conn.execute(
        """
        INSERT INTO books (title, owner_user_id, slug)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (title, user_id, "1445"),
    ).fetchone()
    return int(row["id"])


def ensure_membership(conn, book_id: int, user_id: int) -> None:
    conn.execute(
        """
        INSERT INTO book_memberships (book_id, user_id, role)
        VALUES (%s, %s, 'owner')
        ON CONFLICT (book_id, user_id) DO NOTHING
        """,
        (book_id, user_id),
    )
    conn.execute(
        """
        INSERT INTO user_preferences (user_id, active_book_id, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE
        SET active_book_id = EXCLUDED.active_book_id, updated_at = NOW()
        """,
        (user_id, book_id),
    )


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Import 1445.html into bookhub_prod")
    parser.add_argument(
        "html_path",
        nargs="?",
        default=os.path.join(os.path.dirname(__file__), "1445.html"),
        help="Path to source HTML (default: ./1445.html)",
    )
    parser.add_argument("--title", default=DEFAULT_TITLE, help="Book title")
    parser.add_argument("--phone", default=DEFAULT_PHONE, help="Owner phone E.164")
    parser.add_argument("--login", default=DEFAULT_LOGIN, help="Owner login")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Owner password")
    parser.add_argument("--replace", action="store_true", help="Replace existing chapters")
    args = parser.parse_args()

    if not os.path.isfile(args.html_path):
        print(f"File not found: {args.html_path}", file=sys.stderr)
        return 1

    with open(args.html_path, encoding="utf-8") as f:
        html = f.read()

    book_title, chapters = parse_book_html(html, book_title=args.title)
    if not chapters:
        print("No chapters parsed from HTML", file=sys.stderr)
        return 1

    print(f"Parsed book «{book_title}» — {len(chapters)} chapters")
    run_migrations()

    with get_conn() as conn:
        user_id = ensure_user(conn, args.phone, args.login, args.password)
        book_id = ensure_book(conn, user_id, book_title)
        ensure_membership(conn, book_id, user_id)

        existing = conn.execute(
            "SELECT COUNT(*) AS n FROM chapters WHERE book_id = %s",
            (book_id,),
        ).fetchone()
        if int(existing["n"]) > 0 and not args.replace:
            print(f"Book already has chapters (id={book_id}). Use --replace to overwrite.")
            return 0

        if args.replace:
            conn.execute("DELETE FROM chapters WHERE book_id = %s", (book_id,))

        for ch in chapters:
            conn.execute(
                """
                INSERT INTO chapters (book_id, ch_id, title, act_number, emoji, content, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (book_id, ch.ch_id, ch.title, ch.act_number, ch.emoji, ch.content, ch.sort_order),
            )
            print(f"  ✓ {ch.ch_id}: {ch.title} ({ch.emoji})")

    print("Import complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
