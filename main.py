"""BookHub v0.2 — FastAPI backend."""

from __future__ import annotations

import hashlib
import hmac
import html as html_module
import os
import re
import time
from collections import defaultdict
from typing import Any

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response as PlainResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth_util import verify_password
from ai_advisor import analyze_book, apply_text_fix, verify_errors_against_chapters
from ai_assistant import chat_reply, summarize_book_memory, welcome_message
from database import (
    ACT_LABEL_LABELS,
    count_ai_refresh_since,
    count_chat_send_since,
    ensure_book_service,
    fetch_book,
    fetch_book_analysis,
    fetch_book_note,
    fetch_book_notes,
    fetch_book_ai_summary,
    fetch_chat_messages,
    fetch_chat_messages_recent,
    fetch_book_service,
    fetch_chapter_by_ch_id,
    fetch_chapters,
    fetch_chapters_full,
    fetch_user_by_login_or_phone,
    fetch_user_books,
    fetch_user_chapter_contents,
    fetch_user_last_edited_at,
    fetch_user_profile_row,
    fetch_user_writing_started_at,
    get_active_book_id,
    get_conn,
    insert_book_note,
    insert_chat_message,
    log_ai_usage,
    run_migrations,
    update_book_ai_summary,
    set_active_book_id,
    update_book_service_checklist,
    update_book_service_heroes,
    update_book_service_plot,
    upsert_book_analysis,
    update_book_analysis_json,
    update_user_profile,
    user_has_book_access,
)
from service_analyzer import generate_heroes_text, generate_plot_json, plot_json_loads
from export_util import build_docx_export, build_html_export, build_pdf_export
from parser import parse_book_html
from stats_util import measure_html, sum_measures

APP_VERSION = os.environ.get("APP_VERSION", "16:30")
APP_PORT = int(os.environ.get("APP_PORT", "8001"))
SESSION_COOKIE = "bookhub_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
LOGIN_RATE_LIMIT = 3
LOGIN_RATE_WINDOW = 60
AI_REFRESH_LIMIT = int(os.environ.get("AI_REFRESH_LIMIT", "5"))
AI_REFRESH_WINDOW_HOURS = 1
CHAT_RATE_LIMIT = int(os.environ.get("CHAT_RATE_LIMIT", "45"))
CHAT_RATE_WINDOW_HOURS = 1
CHAT_MAX_MESSAGE_LEN = 4000
CHAT_HISTORY_LIMIT = 10

app = FastAPI(title="BookHub", version="0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_login_attempts: dict[str, list[float]] = defaultdict(list)


def _session_secret() -> bytes:
    secret = os.environ.get("SESSION_SECRET") or os.environ.get("AUTH_PASSWORD") or "bookhub"
    return secret.encode()


def _make_session_token(user_id: int) -> str:
    expires = int(time.time()) + SESSION_MAX_AGE
    payload = f"{user_id}:{expires}"
    signature = hmac.new(_session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def _verify_session_token(token: str | None) -> int | None:
    if not token:
        return None
    try:
        user_id_str, expires, signature = token.rsplit(":", 2)
        user_id = int(user_id_str)
        expires_at = int(expires)
    except (TypeError, ValueError):
        return None
    if expires_at < time.time():
        return None
    payload = f"{user_id}:{expires}"
    expected = hmac.new(_session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return user_id


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_login_rate_limit(ip: str) -> None:
    now = time.time()
    attempts = [t for t in _login_attempts[ip] if now - t < LOGIN_RATE_WINDOW]
    if len(attempts) >= LOGIN_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many login attempts")
    attempts.append(now)
    _login_attempts[ip] = attempts


def verify_user_id(bookhub_session: str | None = Cookie(default=None)) -> int:
    user_id = _verify_session_token(bookhub_session)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


def _user_row(conn, user_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, login, phone_e164, display_name FROM users WHERE id = %s AND is_active = TRUE",
        (user_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return dict(row)


def _require_book_access(conn, user_id: int, book_id: int) -> None:
    if not user_has_book_access(conn, user_id, book_id):
        raise HTTPException(status_code=403, detail="No access to book")


class LoginBody(BaseModel):
    login: str | None = None
    username: str | None = None
    password: str

    def identifier(self) -> str:
        return (self.login or self.username or "").strip()


class ChapterPatch(BaseModel):
    content: str | None = None
    title: str | None = None
    emoji: str | None = None


class ChapterCreate(BaseModel):
    title: str = "Новая глава"
    act_number: int | None = None
    emoji: str = "🟢"
    content: str = '<div class="max-text"></div>'


class ChapterReorderBody(BaseModel):
    chapter_ids: list[str]


ALLOWED_EMOJI = {"🟢", "🟡", "⚪", "🔴", "🔵"}


def _normalize_emoji(raw: str | None) -> str:
    emoji = (raw or "🟢").strip()
    return emoji if emoji in ALLOWED_EMOJI else "🟢"


class ActiveBookBody(BaseModel):
    book_id: int = Field(..., alias="bookId")

    model_config = {"populate_by_name": True}


class ProfilePatch(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    patronymic: str | None = None


class BookCreate(BaseModel):
    title: str = "Новая книга"


class ServiceChecklistPatch(BaseModel):
    checklist_html: str = ""


class ServiceHeroesPatch(BaseModel):
    heroes_text: str = ""


class AiApplyFixBody(BaseModel):
    ch_id: str
    old_text: str
    new_text: str
    context: str = ""
    finding: str = ""


class AiDismissErrorBody(BaseModel):
    ch_id: str = ""
    finding: str = ""
    old_text: str = ""


class AiDismissIdeaBody(BaseModel):
    idea: str


class AiIdeaToChecklistBody(BaseModel):
    idea: str
    related_ch_ids: list[str] = Field(default_factory=list)


class ChatSendBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=CHAT_MAX_MESSAGE_LEN)


def _format_dt(value) -> str | None:
    if not value:
        return None
    return value.isoformat()


def _analysis_payload(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    analysis = row.get("analysis_json")
    if isinstance(analysis, str):
        import json

        try:
            analysis = json.loads(analysis)
        except json.JSONDecodeError:
            analysis = {}
    if not isinstance(analysis, dict):
        analysis = {}
    return {
        "analysis": analysis,
        "model": row.get("model"),
        "tokens_in": row.get("tokens_in"),
        "tokens_out": row.get("tokens_out"),
        "updated_at": _format_dt(row.get("updated_at")),
        "created_at": _format_dt(row.get("created_at")),
    }


def _check_ai_refresh_limit(conn, user_id: int) -> None:
    count = count_ai_refresh_since(conn, user_id, AI_REFRESH_WINDOW_HOURS)
    if count >= AI_REFRESH_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"AI refresh limit: {AI_REFRESH_LIMIT} per hour",
        )


def _check_chat_rate_limit(conn, user_id: int) -> None:
    count = count_chat_send_since(conn, user_id, CHAT_RATE_WINDOW_HOURS)
    if count >= CHAT_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Chat limit: {CHAT_RATE_LIMIT} messages per hour",
        )


def _author_display_name(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "автор"
    name = (profile.get("display_name") or "").strip()
    return name or "автор"


def _chat_msg_payload(row: dict[str, Any], off_topic: bool = False) -> dict[str, Any]:
    payload = {
        "id": row.get("id"),
        "sender": row.get("sender"),
        "message": row.get("message"),
        "created_at": _format_dt(row.get("created_at")),
    }
    if off_topic:
        payload["off_topic"] = True
    return payload


def _note_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "book_id": row.get("book_id"),
        "title": row.get("title"),
        "content": row.get("content"),
        "created_at": _format_dt(row.get("created_at")),
        "updated_at": _format_dt(row.get("updated_at")),
    }


def _refresh_summary_background(book_id: int, user_id: int) -> None:
    try:
        with get_conn() as conn:
            book = fetch_book(conn, book_id)
            if not book:
                return
            current = fetch_book_ai_summary(conn, book_id)
            recent = fetch_chat_messages_recent(conn, book_id, CHAT_HISTORY_LIMIT)
            new_summary, model, tokens_in, tokens_out = summarize_book_memory(
                book["title"],
                current,
                recent,
            )
            text = (new_summary or "").strip()[:12000]
            update_book_ai_summary(conn, book_id, text)
            log_ai_usage(
                conn, user_id, book_id, "chat-summary-refresh", model, tokens_in, tokens_out
            )
    except Exception:
        pass


def _service_payload(row: dict[str, Any]) -> dict[str, Any]:
    plot = plot_json_loads(row.get("plot_json"))
    return {
        "checklist_html": row.get("checklist_html") or "",
        "heroes_text": row.get("heroes_text") or "",
        "plot": plot,
        "checklist_updated_at": _format_dt(row.get("checklist_updated_at")),
        "heroes_updated_at": _format_dt(row.get("heroes_updated_at")),
        "plot_updated_at": _format_dt(row.get("plot_updated_at")),
    }


def _build_profile_payload(conn, user_id: int) -> dict[str, Any]:
    user = fetch_user_profile_row(conn, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    books = fetch_user_books(conn, user_id)
    active_id = get_active_book_id(conn, user_id)
    rows = fetch_user_chapter_contents(conn, user_id)

    by_book: dict[int, dict[str, Any]] = {}
    chapter_counts: dict[int, int] = {}
    all_measures: list[dict[str, int | float]] = []

    for row in rows:
        book_id = int(row["book_id"])
        if book_id not in by_book:
            by_book[book_id] = {
                "book_id": book_id,
                "title": row["title"],
                "measures": [],
                "updated_at": None,
            }
            chapter_counts[book_id] = 0
        chapter_counts[book_id] += 1
        m = measure_html(row["content"])
        by_book[book_id]["measures"].append(m)
        all_measures.append(m)
        ts = row["updated_at"]
        prev = by_book[book_id]["updated_at"]
        if ts and (not prev or ts > prev):
            by_book[book_id]["updated_at"] = ts

    book_items: list[dict[str, Any]] = []
    for b in books:
        bid = int(b["id"])
        agg = sum_measures(by_book.get(bid, {}).get("measures", []))
        book_items.append(
            {
                "id": bid,
                "title": b["title"],
                "chapters_count": chapter_counts.get(bid, 0),
                "characters": agg["characters"],
                "words": agg["words"],
                "pages": agg["pages"],
                "is_active": bid == active_id,
                "role": b.get("role"),
                "updated_at": _format_dt(by_book.get(bid, {}).get("updated_at") or b.get("updated_at")),
            }
        )

    total = sum_measures(all_measures)
    writing_started = fetch_user_writing_started_at(conn, user_id)
    last_edited = fetch_user_last_edited_at(conn, user_id)

    return {
        "profile": {
            "login": user.get("login"),
            "phone_e164": user.get("phone_e164"),
            "first_name": user.get("first_name") or "",
            "last_name": user.get("last_name") or "",
            "patronymic": user.get("patronymic") or "",
            "registered_at": _format_dt(user.get("created_at")),
            "writing_started_at": _format_dt(writing_started),
        },
        "stats": {
            "books_count": len(books),
            "chapters_count": sum(chapter_counts.values()),
            "characters": total["characters"],
            "words": total["words"],
            "pages": total["pages"],
            "last_edited_at": _format_dt(last_edited),
        },
        "books": book_items,
    }


def _login_handler(body: LoginBody, response: Response, request: Request) -> dict[str, Any]:
    identifier = body.identifier()
    if not identifier or not body.password:
        raise HTTPException(status_code=400, detail="Login and password required")

    _check_login_rate_limit(_client_ip(request))

    with get_conn() as conn:
        user = fetch_user_by_login_or_phone(conn, identifier)
        if not user or not verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _make_session_token(int(user["id"]))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "login": user.get("login"),
            "display_name": user.get("display_name") or user.get("login"),
        },
    }


@app.on_event("startup")
def on_startup() -> None:
    run_migrations()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "BookHub", "version": "0.2", "app_version": APP_VERSION}


@app.get("/api/v1/version")
def app_version() -> dict[str, str]:
    return {"version": APP_VERSION}


@app.post("/api/v1/login")
@app.post("/api/v1/auth/login")
def login(body: LoginBody, response: Response, request: Request) -> dict[str, Any]:
    return _login_handler(body, response, request)


@app.post("/api/v1/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE, samesite="lax")
    return {"ok": True}


@app.get("/api/v1/session")
def session_status(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        user = _user_row(conn, user_id)
    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "login": user.get("login"),
            "display_name": user.get("display_name") or user.get("login"),
        },
    }


@app.get("/api/v1/me/books")
def list_my_books(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        books = fetch_user_books(conn, user_id)
        active_id = get_active_book_id(conn, user_id)
    return {
        "books": [
            {
                "id": b["id"],
                "title": b["title"],
                "slug": b.get("slug"),
                "role": b["role"],
                "is_active": b["id"] == active_id,
            }
            for b in books
        ],
        "active_book_id": active_id,
    }


@app.patch("/api/v1/me/active-book")
def patch_active_book(body: ActiveBookBody, user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        try:
            set_active_book_id(conn, user_id, body.book_id)
        except PermissionError:
            raise HTTPException(status_code=403, detail="No access to book")
    return {"ok": True, "active_book_id": body.book_id}


@app.get("/api/v1/me/profile")
def get_profile(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        payload = _build_profile_payload(conn, user_id)
    return {"ok": True, **payload}


@app.patch("/api/v1/me/profile")
def patch_profile(body: ProfilePatch, user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        update_user_profile(
            conn,
            user_id,
            (body.first_name or "").strip() or None,
            (body.last_name or "").strip() or None,
            (body.patronymic or "").strip() or None,
        )
        payload = _build_profile_payload(conn, user_id)
    return {"ok": True, **payload}


def _require_book_owner(conn, user_id: int, book_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT b.id, b.title, bm.role
        FROM books b
        JOIN book_memberships bm ON bm.book_id = b.id
        WHERE b.id = %s AND bm.user_id = %s AND b.is_archived = FALSE
        """,
        (book_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Book not found")
    if row["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only owner can modify book")
    return dict(row)


@app.post("/api/v1/books")
def create_book(
    body: BookCreate | None = None,
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    payload = body or BookCreate()
    title = (payload.title or "Новая книга").strip() or "Новая книга"
    slug = f"book-{int(time.time())}"

    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO books (title, owner_user_id, slug)
            VALUES (%s, %s, %s)
            RETURNING id, title, created_at, updated_at
            """,
            (title, user_id, slug),
        ).fetchone()
        book_id = int(row["id"])
        conn.execute(
            "INSERT INTO book_memberships (book_id, user_id, role) VALUES (%s, %s, 'owner')",
            (book_id, user_id),
        )
        conn.execute(
            """
            INSERT INTO chapters (book_id, ch_id, title, act_number, emoji, content, sort_order)
            VALUES (%s, 'ch1', 'Новая глава', 1, '🟢', '<div class="max-text"></div>', 1)
            """,
            (book_id,),
        )
        set_active_book_id(conn, user_id, book_id)
        ensure_book_service(conn, book_id)

    return {
        "ok": True,
        "book": {
            "id": book_id,
            "title": row["title"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        },
    }


@app.delete("/api/v1/books/{book_id}")
def delete_book(book_id: int, user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        books = fetch_user_books(conn, user_id)
        if len(books) <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last book")
        _require_book_owner(conn, user_id, book_id)

        active_id = get_active_book_id(conn, user_id)
        conn.execute("DELETE FROM books WHERE id = %s", (book_id,))

        if active_id == book_id:
            remaining = fetch_user_books(conn, user_id)
            if remaining:
                set_active_book_id(conn, user_id, int(remaining[0]["id"]))

    return {"ok": True, "deleted_book_id": book_id}


def _book_payload(conn, book_id: int, active_ch: str | None) -> dict[str, Any]:
    book = fetch_book(conn, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    chapters = fetch_chapters(conn, book_id)
    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters")

    target_ch_id = active_ch or chapters[0]["ch_id"]
    active = fetch_chapter_by_ch_id(conn, book_id, target_ch_id)
    if not active:
        active = conn.execute(
            "SELECT * FROM chapters WHERE book_id = %s ORDER BY sort_order LIMIT 1",
            (book_id,),
        ).fetchone()
        active = dict(active)

    acts_seen: set[int] = set()
    acts: list[dict[str, Any]] = []
    for ch in chapters:
        n = int(ch["act_number"])
        if n in acts_seen:
            continue
        acts_seen.add(n)
        acts.append({"number": n, "label": ACT_LABEL_LABELS.get(n, f"Акт {n}")})

    return {
        "book": {
            "id": book["id"],
            "title": book["title"],
            "created_at": book["created_at"].isoformat(),
        },
        "acts": acts,
        "chapters": [
            {
                "ch_id": ch["ch_id"],
                "title": ch["title"],
                "act_number": ch["act_number"],
                "emoji": ch["emoji"],
                "sort_order": ch["sort_order"],
                "updated_at": ch["updated_at"].isoformat(),
            }
            for ch in chapters
        ],
        "active_chapter": {
            "ch_id": active["ch_id"],
            "title": active["title"],
            "act_number": active["act_number"],
            "emoji": active["emoji"],
            "content": active["content"],
            "updated_at": active["updated_at"].isoformat(),
        },
    }


@app.get("/api/v1/book")
def get_book(
    active_ch: str | None = Query(None, alias="active_ch"),
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        payload = _book_payload(conn, book_id, active_ch)
        service = fetch_book_service(conn, book_id)
        payload["service"] = _service_payload(service)
        return payload


@app.get("/api/v1/book/service")
def get_book_service(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        service = fetch_book_service(conn, book_id)
    return {"ok": True, "service": _service_payload(service)}


@app.patch("/api/v1/book/service/checklist")
def patch_service_checklist(
    body: ServiceChecklistPatch,
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        update_book_service_checklist(conn, book_id, body.checklist_html or "")
        service = fetch_book_service(conn, book_id)
    return {"ok": True, "service": _service_payload(service)}


@app.patch("/api/v1/book/service/heroes")
def patch_service_heroes(
    body: ServiceHeroesPatch,
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        update_book_service_heroes(conn, book_id, body.heroes_text or "")
        service = fetch_book_service(conn, book_id)
    return {"ok": True, "service": _service_payload(service)}


@app.post("/api/v1/book/service/heroes/refresh")
def refresh_service_heroes(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        chapters = fetch_chapters_full(conn, book_id)
        heroes_text = generate_heroes_text(chapters)
        update_book_service_heroes(conn, book_id, heroes_text)
        service = fetch_book_service(conn, book_id)
    return {"ok": True, "service": _service_payload(service)}


@app.post("/api/v1/book/service/plot/refresh")
def refresh_service_plot(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        chapters = fetch_chapters_full(conn, book_id)
        plot = generate_plot_json(chapters)
        update_book_service_plot(conn, book_id, plot)
        service = fetch_book_service(conn, book_id)
    return {"ok": True, "service": _service_payload(service)}


@app.get("/api/v1/book/ai-analysis")
def get_ai_analysis(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        row = fetch_book_analysis(conn, book_id)
        if row:
            chapters = fetch_chapters_full(conn, book_id)
            analysis = _load_analysis_dict(row)
            fixed = verify_errors_against_chapters(analysis.get("errors") or [], chapters)
            if fixed != analysis.get("errors"):
                analysis["errors"] = fixed
                row = update_book_analysis_json(conn, book_id, analysis) or row
    return {"ok": True, "book_id": book_id, "ai_analysis": _analysis_payload(row)}


@app.post("/api/v1/book/ai-analysis/refresh")
def refresh_ai_analysis(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        _check_ai_refresh_limit(conn, user_id)

        book = fetch_book(conn, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        chapters = fetch_chapters_full(conn, book_id)
        if not chapters:
            raise HTTPException(status_code=400, detail="No chapters to analyze")
        service = fetch_book_service(conn, book_id)

        try:
            analysis, model, tokens_in, tokens_out = analyze_book(
                book["title"],
                chapters,
                service.get("checklist_html") or "",
                service.get("heroes_text") or "",
            )
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        analysis["errors"] = verify_errors_against_chapters(
            analysis.get("errors") or [], chapters
        )

        row = upsert_book_analysis(conn, book_id, analysis, model, tokens_in, tokens_out)
        log_ai_usage(conn, user_id, book_id, "ai-analysis-refresh", model, tokens_in, tokens_out)

    return {"ok": True, "ai_analysis": _analysis_payload(row)}


@app.post("/api/v1/book/ai-analysis/apply")
def apply_ai_fix(body: AiApplyFixBody, user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        chapter = fetch_chapter_by_ch_id(conn, book_id, body.ch_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found")

        updated_html, changed = apply_text_fix(
            chapter["content"], body.old_text, body.new_text, body.context
        )
        if updated_html is None:
            raise HTTPException(
                status_code=400,
                detail="Could not apply fix: text fragment not found in chapter",
            )

        if changed:
            conn.execute(
                """
                UPDATE chapters SET content = %s, updated_at = NOW()
                WHERE book_id = %s AND ch_id = %s
                """,
                (updated_html, book_id, body.ch_id),
            )
            conn.execute("UPDATE books SET updated_at = NOW() WHERE id = %s", (book_id,))
        updated = fetch_chapter_by_ch_id(conn, book_id, body.ch_id)
        assert updated

        analysis_row = fetch_book_analysis(conn, book_id)
        ai_payload = None
        if analysis_row:
            analysis = _load_analysis_dict(analysis_row)
            analysis["errors"] = _remove_applied_error(analysis.get("errors") or [], body)
            analysis_row = update_book_analysis_json(conn, book_id, analysis) or analysis_row
            ai_payload = _analysis_payload(analysis_row)

    return {
        "ok": True,
        "ch_id": body.ch_id,
        "content": updated["content"],
        "updated_at": updated["updated_at"].isoformat(),
        "ai_analysis": ai_payload,
    }


def _load_analysis_dict(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    analysis = row.get("analysis_json")
    if isinstance(analysis, str):
        import json

        try:
            analysis = json.loads(analysis)
        except json.JSONDecodeError:
            analysis = {}
    return analysis if isinstance(analysis, dict) else {}


def _ai_error_matches(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if (a.get("ch_id") or "") != (b.get("ch_id") or ""):
        return False
    if (b.get("finding") or "") and (a.get("finding") or "") == (b.get("finding") or ""):
        return True
    return (
        (a.get("finding") or "") == (b.get("finding") or "")
        and (a.get("old_text") or "") == (b.get("old_text") or "")
    )


def _remove_applied_error(
    errors: list[dict[str, Any]], body: AiApplyFixBody
) -> list[dict[str, Any]]:
    target = body.model_dump()
    return [e for e in errors if not _ai_error_matches(e, target)]


def _ai_idea_text(item: Any) -> str:
    if isinstance(item, dict):
        return (item.get("idea") or "").strip()
    return str(item or "").strip()


@app.post("/api/v1/book/ai-analysis/dismiss-error")
def dismiss_ai_error(body: AiDismissErrorBody, user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        row = fetch_book_analysis(conn, book_id)
        if not row:
            raise HTTPException(status_code=404, detail="No analysis cached")
        analysis = _load_analysis_dict(row)
        target = body.model_dump()
        errors = analysis.get("errors") or []
        new_errors = [e for e in errors if not _ai_error_matches(e, target)]
        if len(new_errors) == len(errors):
            raise HTTPException(status_code=404, detail="Error item not found")
        analysis["errors"] = new_errors
        row = update_book_analysis_json(conn, book_id, analysis)
    return {"ok": True, "ai_analysis": _analysis_payload(row)}


@app.post("/api/v1/book/ai-analysis/dismiss-idea")
def dismiss_ai_idea(body: AiDismissIdeaBody, user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        row = fetch_book_analysis(conn, book_id)
        if not row:
            raise HTTPException(status_code=404, detail="No analysis cached")
        analysis = _load_analysis_dict(row)
        idea_text = body.idea.strip()
        ideas = analysis.get("plot_ideas") or []
        new_ideas = [i for i in ideas if _ai_idea_text(i) != idea_text]
        if len(new_ideas) == len(ideas):
            raise HTTPException(status_code=404, detail="Plot idea not found")
        analysis["plot_ideas"] = new_ideas
        row = update_book_analysis_json(conn, book_id, analysis)
    return {"ok": True, "ai_analysis": _analysis_payload(row)}


@app.post("/api/v1/book/ai-analysis/idea-to-checklist")
def ai_idea_to_checklist(
    body: AiIdeaToChecklistBody, user_id: int = Depends(verify_user_id)
) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        row = fetch_book_analysis(conn, book_id)
        if not row:
            raise HTTPException(status_code=404, detail="No analysis cached")
        analysis = _load_analysis_dict(row)
        idea_text = body.idea.strip()
        if not idea_text:
            raise HTTPException(status_code=400, detail="Empty idea")

        ideas = analysis.get("plot_ideas") or []
        new_ideas = [i for i in ideas if _ai_idea_text(i) != idea_text]
        if len(new_ideas) == len(ideas):
            raise HTTPException(status_code=404, detail="Plot idea not found")
        analysis["plot_ideas"] = new_ideas
        row = update_book_analysis_json(conn, book_id, analysis)

        service = fetch_book_service(conn, book_id)
        checklist_html = (service.get("checklist_html") if service else "") or ""
        ch_part = ""
        if body.related_ch_ids:
            ch_part = (
                "<p><em>Главы: "
                + ", ".join(html_module.escape(c) for c in body.related_ch_ids)
                + "</em></p>"
            )
        block = (
            '<div class="atlas-note"><h4>💡 Идея ИИ</h4>'
            f"<p>⏳ {html_module.escape(idea_text)}</p>{ch_part}</div>"
        )
        update_book_service_checklist(conn, book_id, checklist_html + "\n" + block)
        service = fetch_book_service(conn, book_id)

    return {
        "ok": True,
        "ai_analysis": _analysis_payload(row),
        "service": _service_payload(service),
    }


@app.get("/api/v1/book/chat")
def get_book_chat(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        profile = fetch_user_profile_row(conn, user_id)
        author = _author_display_name(profile)
        messages = fetch_chat_messages(conn, book_id, 100)
        if not messages:
            welcome = welcome_message(author)
            row = insert_chat_message(conn, book_id, "ai", welcome)
            messages = [row]
    return {
        "ok": True,
        "messages": [_chat_msg_payload(m) for m in messages],
        "author_name": author,
    }


@app.post("/api/v1/book/chat/send")
def send_book_chat(
    body: ChatSendBody,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")

    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        _check_chat_rate_limit(conn, user_id)

        book = fetch_book(conn, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        profile = fetch_user_profile_row(conn, user_id)
        author = _author_display_name(profile)
        ai_summary = fetch_book_ai_summary(conn, book_id)
        history = fetch_chat_messages_recent(conn, book_id, CHAT_HISTORY_LIMIT)

        user_row = insert_chat_message(conn, book_id, "user", text)

        try:
            clean, note_data, off_topic, model, tokens_in, tokens_out = chat_reply(
                author,
                book["title"],
                ai_summary,
                history,
                text,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        note_created = None
        if note_data:
            note_created = insert_book_note(
                conn,
                book_id,
                note_data["title"],
                note_data["content"],
            )

        ai_row = insert_chat_message(conn, book_id, "ai", clean)
        log_ai_usage(conn, user_id, book_id, "chat-send", model, tokens_in, tokens_out)

    background_tasks.add_task(_refresh_summary_background, book_id, user_id)

    return {
        "ok": True,
        "user_message": _chat_msg_payload(user_row),
        "ai_message": _chat_msg_payload(ai_row, off_topic=off_topic),
        "note_created": _note_payload(note_created) if note_created else None,
    }


@app.get("/api/v1/book/notes")
def list_book_notes(user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        notes = fetch_book_notes(conn, book_id)
    return {"ok": True, "notes": [_note_payload(n) for n in notes]}


@app.get("/api/v1/book/notes/{note_id}")
def get_book_note(note_id: int, user_id: int = Depends(verify_user_id)) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        note = fetch_book_note(conn, book_id, note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
    return {"ok": True, "note": _note_payload(note)}


@app.patch("/api/v1/chapters/{ch_id}")
def patch_chapter(
    ch_id: str,
    body: ChapterPatch,
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        chapter = fetch_chapter_by_ch_id(conn, book_id, ch_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found")

        fields: list[str] = []
        values: list[Any] = []
        if body.content is not None:
            fields.append("content = %s")
            values.append(body.content)
        if body.title is not None:
            fields.append("title = %s")
            values.append(body.title.strip())
        if body.emoji is not None:
            fields.append("emoji = %s")
            values.append(_normalize_emoji(body.emoji))

        if not fields:
            return {"ok": True, "ch_id": ch_id, "updated_at": chapter["updated_at"].isoformat()}

        fields.append("updated_at = NOW()")
        values.extend([book_id, ch_id])
        conn.execute(
            f"UPDATE chapters SET {', '.join(fields)} WHERE book_id = %s AND ch_id = %s",
            values,
        )
        updated = fetch_chapter_by_ch_id(conn, book_id, ch_id)
        assert updated
        return {
            "ok": True,
            "ch_id": ch_id,
            "title": updated["title"],
            "emoji": updated["emoji"],
            "updated_at": updated["updated_at"].isoformat(),
        }


@app.delete("/api/v1/chapters/{ch_id}")
def delete_chapter(
    ch_id: str,
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)

        chapters = fetch_chapters(conn, book_id)
        if len(chapters) <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last chapter")

        chapter = fetch_chapter_by_ch_id(conn, book_id, ch_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found")

        conn.execute(
            "DELETE FROM chapters WHERE book_id = %s AND ch_id = %s",
            (book_id, ch_id),
        )

        remaining = conn.execute(
            """
            SELECT ch_id FROM chapters
            WHERE book_id = %s
            ORDER BY sort_order, id
            """,
            (book_id,),
        ).fetchall()
        for sort_order, row in enumerate(remaining, start=1):
            conn.execute(
                "UPDATE chapters SET sort_order = %s WHERE book_id = %s AND ch_id = %s",
                (sort_order, book_id, row["ch_id"]),
            )
        conn.execute("UPDATE books SET updated_at = NOW() WHERE id = %s", (book_id,))

    return {"ok": True, "deleted_ch_id": ch_id}


@app.post("/api/v1/chapters")
def create_chapter(
    body: ChapterCreate | None = None,
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    payload = body or ChapterCreate()
    title = (payload.title or "Новая глава").strip() or "Новая глава"
    emoji = _normalize_emoji(payload.emoji)
    content = payload.content or '<div class="max-text"></div>'

    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)

        chapters = fetch_chapters(conn, book_id)
        max_num = 0
        max_sort = 0
        last_act = 1
        for ch in chapters:
            max_sort = max(max_sort, int(ch["sort_order"]))
            last_act = int(ch["act_number"])
            m = re.match(r"^ch(\d+)$", ch["ch_id"])
            if m:
                max_num = max(max_num, int(m.group(1)))

        ch_id = f"ch{max_num + 1}"
        act_number = payload.act_number if payload.act_number is not None else last_act
        sort_order = max_sort + 1

        row = conn.execute(
            """
            INSERT INTO chapters (book_id, ch_id, title, act_number, emoji, content, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING ch_id, title, act_number, emoji, content, sort_order, updated_at
            """,
            (book_id, ch_id, title, act_number, emoji, content, sort_order),
        ).fetchone()
        conn.execute("UPDATE books SET updated_at = NOW() WHERE id = %s", (book_id,))
        created = dict(row)
        return {
            "ok": True,
            "chapter": {
                "ch_id": created["ch_id"],
                "title": created["title"],
                "act_number": created["act_number"],
                "emoji": created["emoji"],
                "content": created["content"],
                "sort_order": created["sort_order"],
                "updated_at": created["updated_at"].isoformat(),
            },
        }


@app.put("/api/v1/chapters/reorder")
def reorder_chapters(
    body: ChapterReorderBody,
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    if not body.chapter_ids:
        raise HTTPException(status_code=400, detail="chapter_ids required")

    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)

        existing = fetch_chapters(conn, book_id)
        existing_ids = {ch["ch_id"] for ch in existing}
        if len(body.chapter_ids) != len(existing_ids):
            raise HTTPException(status_code=400, detail="Invalid chapter order")
        if set(body.chapter_ids) != existing_ids:
            raise HTTPException(status_code=400, detail="Invalid chapter order")

        for sort_order, ch_id in enumerate(body.chapter_ids, start=1):
            conn.execute(
                """
                UPDATE chapters
                SET sort_order = %s, updated_at = NOW()
                WHERE book_id = %s AND ch_id = %s
                """,
                (sort_order, book_id, ch_id),
            )
        conn.execute("UPDATE books SET updated_at = NOW() WHERE id = %s", (book_id,))

    return {"ok": True, "chapter_ids": body.chapter_ids}


@app.get("/api/v1/export")
def export_book(
    format: str = Query("html", pattern="^(html|docx|pdf)$"),
    user_id: int = Depends(verify_user_id),
) -> PlainResponse:
    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if not book_id:
            raise HTTPException(status_code=404, detail="No books available")
        _require_book_access(conn, user_id, book_id)
        book = fetch_book(conn, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        chapters = fetch_chapters_full(conn, book_id)
        if not chapters:
            raise HTTPException(status_code=404, detail="No chapters")

    safe_title = re.sub(r"[^\w\s\-]+", "", book["title"]).strip().replace(" ", "_") or "book"
    filename = f"{safe_title}-export"

    if format == "html":
        body = build_html_export(book["title"], chapters)
        return PlainResponse(
            content=body,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.html"'},
        )
    if format == "docx":
        body = build_docx_export(book["title"], chapters)
        return PlainResponse(
            content=body,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}.docx"'},
        )
    body = build_pdf_export(book["title"], chapters)
    return PlainResponse(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


def _import_chapters(conn, book_id: int, chapters: list, replace: bool = False) -> dict[str, Any]:
    if replace:
        conn.execute("DELETE FROM chapters WHERE book_id = %s", (book_id,))

    imported = 0
    for ch in chapters:
        existing = fetch_chapter_by_ch_id(conn, book_id, ch.ch_id)
        if existing:
            conn.execute(
                """
                UPDATE chapters
                SET title = %s, act_number = %s, emoji = %s, content = %s,
                    sort_order = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (ch.title, ch.act_number, ch.emoji, ch.content, ch.sort_order, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO chapters (book_id, ch_id, title, act_number, emoji, content, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (book_id, ch.ch_id, ch.title, ch.act_number, ch.emoji, ch.content, ch.sort_order),
            )
        imported += 1

    conn.execute("UPDATE books SET updated_at = NOW() WHERE id = %s", (book_id,))
    return {"imported": imported}


@app.post("/api/v1/import")
async def import_draft(
    file: UploadFile = File(...),
    replace: bool = Query(False),
    user_id: int = Depends(verify_user_id),
) -> dict[str, Any]:
    raw = await file.read()
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        html = raw.decode("utf-8", errors="replace")

    book_title, chapters = parse_book_html(html)
    if not chapters:
        raise HTTPException(status_code=400, detail="No chapters found in HTML")

    with get_conn() as conn:
        book_id = get_active_book_id(conn, user_id)
        if book_id:
            _require_book_access(conn, user_id, book_id)
            book = fetch_book(conn, book_id)
            assert book
            if replace:
                conn.execute("UPDATE books SET title = %s, updated_at = NOW() WHERE id = %s", (book_title, book_id))
        else:
            row = conn.execute(
                """
                INSERT INTO books (title, owner_user_id, slug)
                VALUES (%s, %s, %s)
                RETURNING id, title
                """,
                (book_title, user_id, "import"),
            ).fetchone()
            book_id = int(row["id"])
            conn.execute(
                "INSERT INTO book_memberships (book_id, user_id, role) VALUES (%s, %s, 'owner')",
                (book_id, user_id),
            )
            set_active_book_id(conn, user_id, book_id)
            book = dict(row)

        result = _import_chapters(conn, book_id, chapters, replace=replace)
        return {
            "ok": True,
            "book_title": book_title,
            "chapters_count": len(chapters),
            **result,
        }


static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return JSONResponse(
        {"message": f"BookHub v0.2 запущен на порту {APP_PORT}", "docs": "/docs"},
        status_code=200,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=APP_PORT, reload=False)
