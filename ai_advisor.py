"""OpenRouter AI book analysis for «Советы ИИ»."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from typing import Any

from bs4 import BeautifulSoup, NavigableString

from stats_util import html_to_plain

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_CHAPTER_CHARS = 18_000
MAX_TOTAL_CHARS = 380_000

SYSTEM_PROMPT = """Ты литературный редактор русскоязычного романа. Анализируй текст книги строго по предоставленным материалам.
Не выдумывай факты. Каждая ошибка в errors должна содержать дословную цитату context из текста главы.
Ответ — только валидный JSON без markdown, по схеме:
{
  "errors": [
    {
      "type": "language|plot|character|fact",
      "severity": "high|medium|low",
      "ch_id": "ch1",
      "finding": "краткое описание проблемы",
      "context": "дословная цитата из главы (1-3 предложения)",
      "old_text": "фрагмент для замены (только для language, иначе пустая строка)",
      "new_text": "исправленный фрагмент (только для language)",
      "can_apply": true
    }
  ],
  "plot_ideas": [
    {"idea": "совет по развитию сюжета", "related_ch_ids": ["ch5"]}
  ],
  "radar": {
    "tension": 0,
    "pacing": "slow|medium|fast",
    "atmosphere": "кратко",
    "summary": "2-3 предложения о пульсе книги"
  },
  "chapter_radar": [
    {"ch_id": "ch8", "tension": 80, "pacing": "fast", "note": "кратко"}
  ],
  "strengths": ["что уже работает хорошо"]
}
Ограничения: до 12 errors, до 8 plot_ideas, до 8 chapter_radar, до 5 strengths.
can_apply=true только если type=language и old_text точно встречается в context."""


def _model() -> str:
    return os.environ.get(
        "OPENROUTER_MODEL",
        "google/gemini-2.0-flash-001",
    )


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    return key


def build_book_prompt(
    book_title: str,
    chapters: list[dict[str, Any]],
    checklist_html: str,
    heroes_text: str,
) -> str:
    parts = [
        f"# Книга: {book_title}",
        "",
        "## Чек-лист идей (канон автора)",
        html_to_plain(checklist_html)[:12_000] or "(пусто)",
        "",
        "## Главные герои",
        (heroes_text or "").strip()[:8_000] or "(пусто)",
        "",
        "## Главы",
    ]
    total = sum(len(p) for p in parts)
    for ch in chapters:
        plain = html_to_plain(ch.get("content") or "")
        if len(plain) > MAX_CHAPTER_CHARS:
            plain = plain[:MAX_CHAPTER_CHARS] + "\n[…глава обрезана для лимита контекста…]"
        block = (
            f"\n### {ch['ch_id']} | Акт {ch.get('act_number', 1)} | {ch.get('title', '')}\n"
            f"{plain}\n"
        )
        if total + len(block) > MAX_TOTAL_CHARS:
            parts.append("\n[…остальные главы опущены из-за лимита контекста…]\n")
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("AI response is not a JSON object")
    return data


def _extract_json(raw: str) -> dict[str, Any]:
    return _normalize_analysis(_parse_json_object(raw))


def _parse_fix_options(finding: str, old_text: str, new_text: str) -> list[str]:
    options: list[str] = []
    finding = finding or ""
    old_text = (old_text or "").strip()

    def add(word: str) -> None:
        word = word.strip()
        if not word or word == old_text or word in options:
            return
        options.append(word)

    if new_text:
        add(new_text)

    for pattern in (r"→[^.]*", r"должно быть[^.]*", r"должно[^.]*"):
        m = re.search(pattern, finding, re.I)
        if not m:
            continue
        for wm in re.finditer(r"«([^»]+)»", m.group(0)):
            add(wm.group(1))

    return options[:4]


def _find_chapter_for_error(
    chapters: list[dict[str, Any]], context: str, old_text: str, current_ch_id: str
) -> str | None:
    best_id: str | None = None
    best_score = 0
    context = (context or "").strip()
    old_text = (old_text or "").strip()

    for ch in chapters:
        ch_id = str(ch.get("ch_id") or "")
        plain = html_to_plain(str(ch.get("content") or ""))
        score = 0
        if context and (context in plain or _find_flexible_span(plain, context)):
            score += 10
        elif context and len(context) > 20:
            flex = _find_flexible_span(plain, context[: min(48, len(context))])
            if flex:
                score += 7
        if old_text and (old_text in plain or _find_flexible_span(plain, old_text)):
            score += 5
        if score > best_score:
            best_score = score
            best_id = ch_id

    if best_id and best_id != current_ch_id and best_score >= 5:
        return best_id
    return None


def _normalize_analysis(data: dict[str, Any]) -> dict[str, Any]:
    errors = data.get("errors") or []
    if not isinstance(errors, list):
        errors = []
    clean_errors: list[dict[str, Any]] = []
    for item in errors[:12]:
        if not isinstance(item, dict):
            continue
        etype = str(item.get("type") or "plot")
        if etype not in ("language", "plot", "character", "fact"):
            etype = "plot"
        sev = str(item.get("severity") or "medium")
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        old_t = str(item.get("old_text") or "")
        new_t = str(item.get("new_text") or "")
        finding = str(item.get("finding") or "")
        fix_options = _parse_fix_options(finding, old_t, new_t)
        can_apply = etype == "language" and (bool(old_t) or bool(fix_options))
        clean_errors.append(
            {
                "type": etype,
                "severity": sev,
                "ch_id": str(item.get("ch_id") or ""),
                "finding": finding,
                "context": str(item.get("context") or ""),
                "old_text": old_t,
                "new_text": new_t,
                "fix_options": fix_options,
                "can_apply": can_apply,
            }
        )

    plot_ideas = data.get("plot_ideas") or []
    if not isinstance(plot_ideas, list):
        plot_ideas = []
    clean_plots: list[dict[str, Any]] = []
    for item in plot_ideas[:8]:
        if isinstance(item, str):
            clean_plots.append({"idea": item, "related_ch_ids": []})
        elif isinstance(item, dict):
            clean_plots.append(
                {
                    "idea": str(item.get("idea") or ""),
                    "related_ch_ids": list(item.get("related_ch_ids") or []),
                }
            )

    radar = data.get("radar") or {}
    if not isinstance(radar, dict):
        radar = {}
    tension = radar.get("tension", 50)
    try:
        tension = max(0, min(100, int(tension)))
    except (TypeError, ValueError):
        tension = 50
    pacing = str(radar.get("pacing") or "medium")
    if pacing not in ("slow", "medium", "fast"):
        pacing = "medium"

    chapter_radar = data.get("chapter_radar") or []
    if not isinstance(chapter_radar, list):
        chapter_radar = []
    clean_radar_ch: list[dict[str, Any]] = []
    for item in chapter_radar[:8]:
        if not isinstance(item, dict):
            continue
        try:
            t = max(0, min(100, int(item.get("tension", 50))))
        except (TypeError, ValueError):
            t = 50
        clean_radar_ch.append(
            {
                "ch_id": str(item.get("ch_id") or ""),
                "tension": t,
                "pacing": str(item.get("pacing") or ""),
                "note": str(item.get("note") or ""),
            }
        )

    strengths = data.get("strengths") or []
    if not isinstance(strengths, list):
        strengths = []
    strengths = [str(s) for s in strengths[:5] if s]

    return {
        "errors": clean_errors,
        "plot_ideas": clean_plots,
        "radar": {
            "tension": tension,
            "pacing": pacing,
            "atmosphere": str(radar.get("atmosphere") or ""),
            "summary": str(radar.get("summary") or ""),
        },
        "chapter_radar": clean_radar_ch,
        "strengths": strengths,
    }


def call_openrouter_analysis(user_prompt: str) -> tuple[dict[str, Any], str, int, int]:
    return call_openrouter_json(user_prompt, SYSTEM_PROMPT)


def call_openrouter_json(
    user_prompt: str, system_prompt: str
) -> tuple[dict[str, Any], str, int, int]:
    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
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
                "X-Title": "BookHub",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
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
            if system_prompt == SYSTEM_PROMPT:
                analysis = _extract_json(content)
                return analysis, _model(), tokens_in, tokens_out
            data = _parse_json_object(content)
            return data, _model(), tokens_in, tokens_out
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


def analyze_book(
    book_title: str,
    chapters: list[dict[str, Any]],
    checklist_html: str,
    heroes_text: str,
) -> tuple[dict[str, Any], str, int, int]:
    prompt = build_book_prompt(book_title, chapters, checklist_html, heroes_text)
    return call_openrouter_analysis(prompt)


CHAPTER_ERRORS_SYSTEM = """Ты литературный редактор русскоязычного романа.
Анализируй ТОЛЬКО одну главу из запроса. Не выдумывай факты.
Фокус: орфография, пунктуация, грамматика, стиль, явные логические огрехи внутри главы.
Ответ — только валидный JSON без markdown:
{
  "errors": [
    {
      "type": "language|plot|character|fact",
      "severity": "high|medium|low",
      "ch_id": "ch1",
      "finding": "краткое описание",
      "context": "дословная цитата (1-3 предложения)",
      "old_text": "фрагмент для замены (только language)",
      "new_text": "исправление (только language)",
      "can_apply": true
    }
  ]
}
До 8 errors. ch_id каждой ошибки = ch_id из запроса.
can_apply=true только если type=language и old_text точно в context."""


CHAPTER_PLOT_SYSTEM = """Ты литературный редактор и dramaturg.
Оцени сюжет ОДНОЙ главы: конфликт, темп, крючок для читателя.
Не выдумывай события вне текста главы.
Ответ — только валидный JSON без markdown:
{
  "conflict": "главное напряжение или конфликт главы",
  "pacing": "slow|medium|fast",
  "hook": "чем глава удерживает читателя / крючок",
  "summary": "2-3 предложения о сюжетной функции главы",
  "ideas": ["совет по усилению", "ещё один совет"]
}
ideas — до 4 коротких советов."""


def _chapter_context_block(
    book_title: str,
    chapter: dict[str, Any],
    notes: str,
    heroes: str,
) -> str:
    ch_id = str(chapter.get("ch_id") or "")
    plain = html_to_plain(chapter.get("content") or "")
    if len(plain) > MAX_CHAPTER_CHARS:
        plain = plain[:MAX_CHAPTER_CHARS] + "\n[…обрезано…]"
    return "\n".join(
        [
            f"# Книга: {book_title}",
            "",
            "## Заметки автора (контекст)",
            (notes or "").strip()[:6000] or "(пусто)",
            "",
            "## Герои (кратко)",
            (heroes or "").strip()[:4000] or "(пусто)",
            "",
            f"## Глава {ch_id} | {chapter.get('title', '')}",
            plain,
            "",
            f"ch_id для ответа: {ch_id}",
        ]
    )


def _normalize_chapter_errors(data: dict[str, Any], ch_id: str) -> list[dict[str, Any]]:
    normalized = _normalize_analysis({"errors": data.get("errors") or []})
    errors = normalized.get("errors") or []
    for err in errors:
        err["ch_id"] = ch_id
    return errors


def _normalize_chapter_plot(data: dict[str, Any]) -> dict[str, Any]:
    pacing = str(data.get("pacing") or "medium")
    if pacing not in ("slow", "medium", "fast"):
        pacing = "medium"
    ideas = data.get("ideas") or []
    if not isinstance(ideas, list):
        ideas = []
    clean_ideas = [str(i).strip() for i in ideas[:4] if str(i).strip()]
    return {
        "conflict": str(data.get("conflict") or "").strip(),
        "pacing": pacing,
        "hook": str(data.get("hook") or "").strip(),
        "summary": str(data.get("summary") or "").strip(),
        "ideas": clean_ideas,
    }


def analyze_chapter_errors(
    book_title: str,
    chapter: dict[str, Any],
    notes: str,
    heroes: str,
) -> tuple[list[dict[str, Any]], str, int, int]:
    ch_id = str(chapter.get("ch_id") or "")
    prompt = _chapter_context_block(book_title, chapter, notes, heroes)
    data, model, tokens_in, tokens_out = call_openrouter_json(
        prompt, CHAPTER_ERRORS_SYSTEM
    )
    return _normalize_chapter_errors(data, ch_id), model, tokens_in, tokens_out


def analyze_chapter_plot(
    book_title: str,
    chapter: dict[str, Any],
    notes: str,
    heroes: str,
) -> tuple[dict[str, Any], str, int, int]:
    prompt = _chapter_context_block(book_title, chapter, notes, heroes)
    data, model, tokens_in, tokens_out = call_openrouter_json(
        prompt, CHAPTER_PLOT_SYSTEM
    )
    return _normalize_chapter_plot(data), model, tokens_in, tokens_out


def merge_chapter_errors(
    analysis: dict[str, Any], ch_id: str, new_errors: list[dict[str, Any]]
) -> dict[str, Any]:
    kept = [e for e in (analysis.get("errors") or []) if e.get("ch_id") != ch_id]
    kept.extend(new_errors)
    analysis["errors"] = kept
    return analysis


def merge_chapter_plot(
    analysis: dict[str, Any], ch_id: str, plot: dict[str, Any]
) -> dict[str, Any]:
    chapter_plots = analysis.get("chapter_plots")
    if not isinstance(chapter_plots, dict):
        chapter_plots = {}
    chapter_plots[ch_id] = plot
    analysis["chapter_plots"] = chapter_plots
    return analysis


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _find_flexible_span(plain: str, needle: str) -> str | None:
    needle = (needle or "").strip()
    if not needle or not plain:
        return None
    if needle in plain:
        return needle
    parts = _norm_ws(needle).split()
    if not parts:
        return None
    pattern = r"\s+".join(re.escape(part) for part in parts)
    match = re.search(pattern, plain)
    return match.group(0) if match else None


ALREADY_APPLIED = "__already_applied__"


def _context_anchors(context: str) -> list[str]:
    context = (context or "").strip()
    if not context:
        return []
    anchors = [context]
    words = context.split()
    for n in (4, 3, 2):
        if len(words) >= n:
            anchors.append(" ".join(words[:n]))
    m = re.search(r"^(.*?(?:моему|моей|моего|столе|телефон))\s", context, re.I)
    if m:
        anchors.append(m.group(1).strip())
    if len(context) > 24:
        anchors.append(context[: max(24, len(context) // 2)])
    return anchors


def _is_already_applied(plain: str, old_text: str, new_text: str, context: str) -> bool:
    new_text = (new_text or "").strip()
    if not new_text:
        return False
    if new_text not in plain and not _find_flexible_span(plain, new_text):
        return False
    if old_text in plain or _find_flexible_span(plain, old_text):
        return False
    region = _context_region(plain, context)
    if not region:
        return False
    return new_text in region or bool(_find_flexible_span(region, new_text))


def _context_region(plain: str, context: str, extra: int = 48) -> str | None:
    context = (context or "").strip()
    if not context or not plain:
        return None
    for anchor in _context_anchors(context):
        if len(anchor) < 8:
            continue
        flex = _find_flexible_span(plain, anchor)
        if flex:
            pos = plain.find(flex)
            return plain[pos : pos + len(flex) + extra]
    return None


def _age_word_pattern() -> str:
    return r"\d+и?-лет\w+"


def _resolve_old_text(
    content_html: str, old_text: str, context: str = "", new_text: str = ""
) -> str | None:
    old_text = (old_text or "").strip()
    new_text = (new_text or "").strip()
    if not old_text:
        return None

    html = content_html or ""
    plain = html_to_plain(html)

    if _is_already_applied(plain, old_text, new_text, context):
        return ALREADY_APPLIED

    for candidate in (old_text,):
        if candidate in html or candidate in plain:
            return candidate.strip()
        flex = _find_flexible_span(plain, candidate)
        if flex:
            return flex.strip()

    region = _context_region(plain, context)
    if region:
        if new_text and new_text in region:
            old_in_region = (
                old_text in region
                or _find_flexible_span(region, old_text)
                or re.search(_age_word_pattern(), region)
            )
            if not old_in_region or re.search(re.escape(new_text) + r"\w", region):
                if not old_in_region:
                    return ALREADY_APPLIED

        m = re.search(_age_word_pattern(), region)
        if m:
            word = m.group(0)
            if new_text and (_norm_ws(word) == _norm_ws(new_text) or word == new_text):
                return ALREADY_APPLIED
            return word

        norm_old = _norm_ws(old_text)
        best: str | None = None
        best_score = 0.5
        ctx_slice = context if context in plain else (_find_flexible_span(plain, context) or context)
        for start in range(len(ctx_slice)):
            for end in range(start + 3, len(ctx_slice) + 1):
                sub = ctx_slice[start:end]
                actual = sub if sub in plain else _find_flexible_span(plain, sub)
                if not actual or actual not in region:
                    continue
                score = SequenceMatcher(None, _norm_ws(actual), norm_old).ratio()
                if score > best_score:
                    best_score = score
                    best = actual
        if best:
            return best.strip()

    return None


def _replace_in_html(content_html: str, old_span: str, new_text: str) -> str | None:
    if old_span in content_html:
        return content_html.replace(old_span, new_text, 1)

    soup = BeautifulSoup(content_html or "", "html.parser")
    for node in soup.find_all(string=True):
        if not isinstance(node, NavigableString):
            continue
        parent = node.parent
        if parent and parent.name in ("script", "style"):
            continue
        text = str(node)
        if old_span in text:
            node.replace_with(text.replace(old_span, new_text, 1))
            return str(soup)
        flex = _find_flexible_span(text, old_span)
        if flex:
            node.replace_with(text.replace(flex, new_text, 1))
            return str(soup)
    return None


def prune_stale_errors(
    errors: list[dict[str, Any]], chapters: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {str(ch.get("ch_id") or ""): ch.get("content") or "" for ch in chapters}
    kept: list[dict[str, Any]] = []
    for err in errors:
        err = dict(err)
        if err.get("type") == "language" and not err.get("fix_options"):
            err["fix_options"] = _parse_fix_options(
                str(err.get("finding") or ""),
                str(err.get("old_text") or ""),
                str(err.get("new_text") or ""),
            )
        if err.get("type") == "language":
            err["can_apply"] = bool(err.get("old_text")) or bool(err.get("fix_options"))

        content = by_id.get(str(err.get("ch_id") or ""), "")
        resolved = _resolve_old_text(
            content,
            str(err.get("old_text") or ""),
            str(err.get("context") or ""),
            str(err.get("new_text") or ""),
        )
        if resolved is None:
            alt_ch = _find_chapter_for_error(
                chapters,
                str(err.get("context") or ""),
                str(err.get("old_text") or ""),
                str(err.get("ch_id") or ""),
            )
            if alt_ch:
                err["ch_id"] = alt_ch
                content = by_id.get(alt_ch, "")
                resolved = _resolve_old_text(
                    content,
                    str(err.get("old_text") or ""),
                    str(err.get("context") or ""),
                    str(err.get("new_text") or ""),
                )

        if resolved == ALREADY_APPLIED:
            continue
        if resolved:
            err["old_text"] = resolved
            err["can_apply"] = True
            kept.append(err)
            continue
        if err.get("type") == "language" and err.get("can_apply"):
            kept.append(err)
            continue
        if not err.get("can_apply"):
            kept.append(err)
            continue
        err["can_apply"] = False
        kept.append(err)
    return kept


def verify_errors_against_chapters(
    errors: list[dict[str, Any]], chapters: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return prune_stale_errors(errors, chapters)


def apply_text_fix(
    content_html: str, old_text: str, new_text: str, context: str = ""
) -> tuple[str | None, bool]:
    """Return (updated_html, changed). changed=False means already applied."""
    new_text = (new_text or "").strip()
    resolved = _resolve_old_text(content_html, old_text, context, new_text)
    if resolved == ALREADY_APPLIED:
        return content_html, False
    if not resolved or _norm_ws(resolved) == _norm_ws(new_text):
        return None, False
    updated = _replace_in_html(content_html, resolved, new_text)
    if updated is None:
        return None, False
    return updated, True
