"""Parent dashboard logic: today's stats + Gemma-4-generated English summary.

One Gemma 4 call per dashboard load via direct OpenRouter POST.
TODO (Phase 5.5 / Phase 8): once query_gemma is extended to support tools and
a shared retry-with-backoff wrapper is in place, route this call through it.
For now the no-retry one-shot pattern is acceptable because the parent
triggers this manually, not in a tight loop.
"""
import json
import os
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from app.curriculum import TELUGU_CURRICULUM
from app.prompts import SESSION_SUMMARY_PROMPT_V1, SessionSummary
from app.session import DEFAULT_DB_PATH, _connect

load_dotenv()
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_MODEL_CLOUD = os.getenv("MODEL_CLOUD", "google/gemma-4-31b-it:free")
_TIMEOUT_S = 60.0
_IST = timezone(timedelta(hours=5, minutes=30))

_SUMMARY_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "return_session_summary",
        "description": "Return the daily progress summary for the parent.",
        "parameters": {
            "type": "object",
            "properties": {
                "letters_practiced": {"type": "array", "items": {"type": "string"},
                                      "description": "Distinct character glyphs seen today."},
                "strong_letters": {"type": "array", "items": {"type": "string"},
                                   "description": "Letters handled well today."},
                "needs_practice": {"type": "array", "items": {"type": "string"},
                                   "description": "Letters that need reinforcement."},
                "suggested_next": {"type": "array", "items": {"type": "string"},
                                   "description": "Letters or skills for tomorrow."},
                "parent_summary_english": {"type": "string",
                                           "description": "2-4 sentences warm plain-English summary."},
            },
            "required": ["letters_practiced", "strong_letters", "needs_practice",
                         "suggested_next", "parent_summary_english"],
            "additionalProperties": False,
        },
    },
}


def _ist_day_bounds_utc_iso(today_ist: date) -> tuple[str, str]:
    start_ist = datetime.combine(today_ist, time.min, tzinfo=_IST)
    end_ist = start_ist + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start_ist.astimezone(timezone.utc).strftime(fmt), end_ist.astimezone(timezone.utc).strftime(fmt)


def _translit_for(character: str) -> str:
    entry = next((e for e in TELUGU_CURRICULUM if e.character == character), None)
    return entry.letter.transliteration if entry else ""


def get_today_summary(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Aggregate today-in-IST sessions and attempts into a structured dict."""
    now_ist = datetime.now(timezone.utc).astimezone(_IST)
    today_ist_date = now_ist.date()
    start_utc, end_utc = _ist_day_bounds_utc_iso(today_ist_date)
    date_label = today_ist_date.strftime("%A, %B %-d, %Y")

    sessions: list[str] = []
    attempts_rows: list[sqlite3.Row] = []
    with _connect(db_path) as conn:
        try:
            sessions = [
                r["id"] for r in conn.execute(
                    "SELECT id FROM sessions WHERE started_at >= ? AND started_at < ?",
                    (start_utc, end_utc),
                ).fetchall()
            ]
            if sessions:
                placeholders = ",".join("?" * len(sessions))
                attempts_rows = conn.execute(
                    f"SELECT target, correct FROM attempts WHERE session_id IN ({placeholders})",
                    sessions,
                ).fetchall()
        except sqlite3.OperationalError:
            pass  # DB never initialised; treat as empty day

    per_letter: dict[str, dict[str, int]] = {}
    for row in attempts_rows:
        bucket = per_letter.setdefault(row["target"], {"attempts": 0, "correct": 0})
        bucket["attempts"] += 1
        bucket["correct"] += int(row["correct"])

    letters_practiced: list[dict[str, Any]] = []
    for character, stats in per_letter.items():
        accuracy = round(100 * stats["correct"] / stats["attempts"]) if stats["attempts"] else 0
        letters_practiced.append({
            "character": character,
            "transliteration": _translit_for(character),
            "attempts": stats["attempts"],
            "correct": stats["correct"],
            "accuracy_pct": accuracy,
        })
    letters_practiced.sort(key=lambda d: (-d["accuracy_pct"], d["character"]))

    attempts_total = sum(r["attempts"] for r in letters_practiced)
    attempts_correct = sum(r["correct"] for r in letters_practiced)
    return {
        "date_label": date_label,
        "sessions_today": len(sessions),
        "attempts_total": attempts_total,
        "attempts_correct": attempts_correct,
        "letters_practiced": letters_practiced,
        "has_data": bool(sessions and attempts_total),
    }


_STUB_SUMMARY: dict[str, Any] = {
    "parent_summary_english": "No practice sessions yet today.",
    "letters_practiced": [],
    "strong_letters": [],
    "needs_practice": [],
    "suggested_next": [],
}


async def generate_english_summary(today_data: dict[str, Any]) -> dict[str, Any]:
    """One-shot Gemma 4 call. Returns parsed SessionSummary dict or an error stub.

    Skips the model call entirely when today_data has no attempts.
    """
    if not today_data.get("has_data"):
        return dict(_STUB_SUMMARY)

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return {**_STUB_SUMMARY, "error": "OPENROUTER_API_KEY missing"}

    payload = {
        "model": _MODEL_CLOUD,
        "messages": [
            {"role": "system", "content": SESSION_SUMMARY_PROMPT_V1},
            {"role": "user", "content": json.dumps(today_data, ensure_ascii=False)},
        ],
        "tools": [_SUMMARY_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "return_session_summary"}},
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            r = await client.post(_OPENROUTER_URL, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        return {**_STUB_SUMMARY, "error": f"http {e.response.status_code}: {e.response.text[:200]}"}
    except (httpx.RequestError, ValueError) as e:
        return {**_STUB_SUMMARY, "error": f"{type(e).__name__}: {e}"}

    try:
        tcs = data["choices"][0]["message"].get("tool_calls") or []
        if not tcs:
            return {**_STUB_SUMMARY, "error": "model did not call return_session_summary"}
        args_raw = tcs[0]["function"]["arguments"]
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        summary = SessionSummary.model_validate(args)
    except (KeyError, json.JSONDecodeError, ValidationError) as e:
        return {**_STUB_SUMMARY, "error": f"summary parse failed: {type(e).__name__}: {e}"}
    return summary.model_dump()
