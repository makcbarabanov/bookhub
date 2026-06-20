"""OpenRouter chat assistant «Морфеус» for BookHub v0.3."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from service_analyzer import is_cast_member

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CREATE_NOTE_RE = re.compile(r"\[CREATE_NOTE:\s*(\{.*?\})\s*\]", re.DOTALL)
OFF_TOPIC_MARKER = "[OFF_TOPIC]"

MORPHEUS_SYSTEM = """Роль: Ты — Морфеус, ИИ-секретарь, технический редактор и навигатор проекта BookHub. Твой цвет — зелёный. Ты общаешься с автором на «ты».

ТВОЯ СУТЬ И ПОВЕДЕНИЕ (СТРОГИЙ СТАНДАРТ):
1. Никакого неуправляемого творчества и мистики. Ты не «дух» и не «призрак». Ты — практичный, честный и высокопрофессиональный инструмент для работы с текстом.
2. Твой юмор — лёгкий, ироничный (в стиле Ястребиного Глаза из M*A*S*H), но всегда по делу. Ты прямой и честный.
3. Твоя главная задача — помогать автору с рутиной:
   - Искать неточности и ошибки в тексте глав.
   - Предлагать варианты развития сюжета (только если автор сам об этом просит).
   - Создавать структурированные заметки (Wiki) по ходу диалога.
4. На вопрос «Что ты умеешь?» отвечай строго структурированным списком РЕАЛЬНЫХ функций: поиск ошибок, генерация заметок, анализ структуры, ответы на вопросы по тексту книги.
5. ПРАВИЛО ВНУТРЕННЕГО КОНТЕНТА: Опирайся только на факты из блока КАНОН ПЕРСОНАЖЕЙ (book_characters). ai_summary и история чата — вторичны и могут содержать ошибки модели.
6. ИСТОРИЯ ЧАТА НЕ КАНОН: прошлые ответы assistant (Морфеуса) могли быть фантазией. НИКОГДА не используй их как источник фактов о героях, сюжете или связях. Если в истории написано про часовщика, дочку Татьяну, временную петлю — это может быть ложь; не продолжай эту линию без явного текста в каноне.
7. СПИСОК ГЕРОЕВ: если автор спрашивает «кто герои» — перечисляй ТОЛЬКО имена из блока КАНОН ПЕРСОНАЖЕЙ. Не добавляй персонажей из памяти чата. Не выдумывай внешность, рост, вес, если это не в каноне. Слова «Мне», «На», «Не», «Ну», «Почему» — не имена, даже если они встречаются в тексте.
8. Не меняй текст глав напрямую — только обсуждение, советы и заметки.

Если пользователь уходит от темы книги (погода, код, политика без связи с романом) —
добавь в конец ответа маркер [OFF_TOPIC] (на отдельной строке).

Чтобы сохранить заметку в Wiki книги, добавь в КОНЕЦ ответа (скрытый блок):
[CREATE_NOTE: {"title": "Краткий заголовок", "content": "Текст заметки"}]
Используй только валидный JSON. Не более одной заметки за сообщение.
Не дублируй CREATE_NOTE без явной просьбы пользователя."""


def _model() -> str:
    return os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    return key


def welcome_message(author_name: str) -> str:
    name = (author_name or "").strip() or "автор"
    return (
        f"Привет, {name}! Я Морфеус — ИИ-секретарь BookHub. "
        "Помогаю с ошибками в тексте, заметками Wiki и вопросами по книге. Чем займёмся?"
    )


def parse_assistant_output(raw: str) -> tuple[str, dict[str, str] | None, bool]:
    off_topic = OFF_TOPIC_MARKER in raw
    text = raw.replace(OFF_TOPIC_MARKER, "").strip()

    note: dict[str, str] | None = None
    match = CREATE_NOTE_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(1))
            title = str(data.get("title") or "").strip()
            content = str(data.get("content") or "").strip()
            if title and content:
                note = {"title": title[:255], "content": content}
        except (json.JSONDecodeError, TypeError):
            pass
        text = CREATE_NOTE_RE.sub("", text).strip()

    return text, note, off_topic


def format_characters_canon(characters: list[dict[str, Any]]) -> str:
    if not characters:
        return ""
    role_labels = {
        "protagonist": "протагонист",
        "antagonist": "антагонист",
        "secondary": "второстепенный",
    }
    lines = [
        "КАНОН ПЕРСОНАЖЕЙ (book_characters) — непреложный источник фактов о героях книги:"
    ]
    for row in characters:
        name = str(row.get("name") or "").strip()
        if not name or not is_cast_member(name):
            continue
        rel = row.get("relations_json") or {}
        if isinstance(rel, str):
            try:
                rel = json.loads(rel)
            except (json.JSONDecodeError, TypeError):
                rel = {}
        if not isinstance(rel, dict):
            rel = {}
        rel_str = ", ".join(f"{k}: {v}" for k, v in rel.items()) if rel else "—"
        role = role_labels.get(str(row.get("role_type") or ""), "персонаж")
        summary = str(row.get("summary") or "").strip()
        lines.append(f"• {row.get('name')} ({role}): {summary}")
        lines.append(f"  Связи: {rel_str}. Первое появление: {row.get('first_ch_id') or '—'}")
        bio = str(row.get("bio") or "").strip()
        if bio:
            lines.append(f"  Подробно: {bio[:600]}")
    return "\n".join(lines)


def build_chat_messages(
    author_name: str,
    book_title: str,
    ai_summary: str,
    characters: list[dict[str, Any]],
    history: list[dict[str, Any]],
    user_message: str,
) -> list[dict[str, str]]:
    context_parts = [
        f"Автор: {(author_name or '').strip() or 'автор'}",
        f"Активная книга: {book_title}",
    ]
    if ai_summary.strip():
        context_parts.append(f"Краткая память о книге (ai_summary):\n{ai_summary.strip()}")
    else:
        context_parts.append("Краткая память о книге пока пуста.")
    canon = format_characters_canon(characters)
    if canon:
        context_parts.append(canon)
    else:
        context_parts.append("Канон персонажей (book_characters) пока пуст.")

    context_parts.append(
        "При вопросе о героях книги отвечай строго по блоку КАНОН ПЕРСОНАЖЕЙ выше. "
        "Не дополняй список из ai_summary или из прошлых ответов в истории чата."
    )

    system = MORPHEUS_SYSTEM + "\n\n" + "\n\n".join(context_parts)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for row in history:
        role = "user" if row.get("sender") == "user" else "assistant"
        messages.append({"role": role, "content": str(row.get("message") or "")})
    messages.append({"role": "user", "content": user_message})
    return messages


def call_openrouter_chat(messages: list[dict[str, str]]) -> tuple[str, str, int, int]:
    payload = {
        "model": _model(),
        "messages": messages,
        "temperature": 0.5,
    }
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None

    for attempt in range(3):
        req = urllib.request.Request(
            OPENROUTER_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://book.islanddream.ru",
                "X-Title": "BookHub-Morpheus",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            usage = data.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
            return str(content), _model(), tokens_in, tokens_out
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:800]
            last_error = RuntimeError(f"OpenRouter HTTP {e.code}: {detail}")
            if e.code == 429 and attempt < 2:
                wait = 10
                try:
                    err_json = json.loads(detail)
                    wait = int(
                        err_json.get("error", {})
                        .get("metadata", {})
                        .get("retry_after_seconds", 10)
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
                time.sleep(min(max(wait, 3), 30))
                continue
            raise last_error from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"OpenRouter request failed: {e}") from e

    assert last_error is not None
    raise last_error


def summarize_book_memory(
    book_title: str,
    current_summary: str,
    recent_messages: list[dict[str, Any]],
) -> tuple[str, str, int, int]:
    dialog_lines = []
    for row in recent_messages[-12:]:
        if row.get("sender") != "user":
            continue
        dialog_lines.append(f"Автор: {row.get('message', '')}")
    dialog = "\n".join(dialog_lines) or "(нет новых сообщений автора)"

    prompt = f"""Книга: {book_title}

Текущая краткая память (ai_summary):
{current_summary or '(пусто)'}

Новые сообщения АВТОРА (не копируй ответы Морфеуса — они могли быть ошибочны):
{dialog}

Обнови краткое содержание книги для ИИ-памяти: сюжет, персонажи, открытые идеи.
Записывай только факты, которые автор явно сообщил, или которые уже в текущей памяти и не противоречат канону.
Не выдумывай часовщиков, дочек, временные петли и прочую мистику, если автор этого не писал.
Не более 500 слов. Только текст summary, без markdown и пояснений."""

    messages = [
        {"role": "system", "content": "Ты архивариус сюжета. Пиши сжато на русском."},
        {"role": "user", "content": prompt},
    ]
    return call_openrouter_chat(messages)


def chat_reply(
    author_name: str,
    book_title: str,
    ai_summary: str,
    characters: list[dict[str, Any]],
    history: list[dict[str, Any]],
    user_message: str,
) -> tuple[str, dict[str, str] | None, bool, str, int, int]:
    messages = build_chat_messages(
        author_name, book_title, ai_summary, characters, history, user_message
    )
    raw, model, tokens_in, tokens_out = call_openrouter_chat(messages)
    clean, note, off_topic = parse_assistant_output(raw)
    return clean, note, off_topic, model, tokens_in, tokens_out
