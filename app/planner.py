"""Layer 2 agentic session planner.

Single Gemma 4 call at session start with three read-only SQLite tools.
Returns a fully-bundled SessionPlan (per-step distractors and feedback
variants); the kid loop reads from the cached plan and never calls Gemma 4
mid-session. On retry exhaustion or unparseable output, falls back to the
deterministic curriculum heuristic from Phase 4.

Hard rules from CLAUDE.md / decisions.md 2026-05-10:
- Tools are read-only SQLite access. No writes. No external calls.
- One agentic call per session. Kid loop NEVER reaches the planner mid-session.
- session_id always comes from create_session(); model's value is overridden.

Note on db_path: the JSON-schema tools exposed to the model (PLANNER_TOOLS in
app/prompts.py) intentionally do not include db_path. The Python tool functions
below accept it as a kwarg so verify scripts can target an isolated DB. The
agentic dispatcher injects its configured db_path on every call.
"""
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from app.curriculum import (
    FALLBACK_FEEDBACK_VARIANTS,
    TELUGU_CURRICULUM,
    select_distractors,
    select_session_letters,
)
from app.prompts import (
    PLANNER_PROMPT_V1,
    PLANNER_TOOLS,
    FeedbackVariants,
    RecognitionStep,
    SessionPlan,
    SessionStep,
)
from app.session import DEFAULT_DB_PATH, _connect, create_session

load_dotenv()

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_MODEL_CLOUD = os.getenv("MODEL_CLOUD", "google/gemma-4-31b-it:free")
_DEFAULT_TIMEOUT_S = 60.0
_DEFAULT_BACKOFF: list[int] = [1, 3, 9]
_DEFAULT_MAX_ATTEMPTS = 3  # retries after the first call; total HTTP attempts = 1 + max_attempts
_RETRYABLE_HTTP = {429, 502}
_AGENTIC_LOOP_CAP = 8


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# SQLite read tools (Python implementations behind PLANNER_TOOLS schemas).
# ---------------------------------------------------------------------------


def get_recent_sessions(n: int, db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Most recent n sessions (newest first), each with letters_practiced rollup.

    `reasoning` is None for sessions written by the deterministic fallback
    (fallback_used=1) and the persisted planner reasoning otherwise.
    """
    n = max(1, min(int(n), 30))
    out: list[dict[str, Any]] = []
    with _connect(db_path) as conn:
        try:
            session_rows = conn.execute(
                "SELECT id, started_at, language, fallback_used, reasoning "
                "FROM sessions ORDER BY started_at DESC LIMIT ?",
                (n,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        for sr in session_rows:
            try:
                attempt_rows = conn.execute(
                    "SELECT target, correct FROM attempts WHERE session_id = ?",
                    (sr["id"],),
                ).fetchall()
            except sqlite3.OperationalError:
                attempt_rows = []
            per_letter: dict[str, dict[str, int]] = {}
            for ar in attempt_rows:
                bucket = per_letter.setdefault(ar["target"], {"attempts": 0, "correct": 0})
                bucket["attempts"] += 1
                bucket["correct"] += int(ar["correct"])
            letters_practiced = [
                {"character": char, "attempts": s["attempts"], "correct": s["correct"]}
                for char, s in per_letter.items()
            ]
            row_dict = dict(sr)
            reasoning = None if row_dict.get("fallback_used") else row_dict.get("reasoning")
            out.append({
                "session_id": sr["id"],
                "started_at": sr["started_at"],
                "language": sr["language"],
                "letters_practiced": letters_practiced,
                "reasoning": reasoning,
            })
    return out


def get_letter_accuracy(letters: list[str], db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Per-letter aggregate accuracy across all sessions.

    Letters with no attempts return accuracy=0.0 and last_attempted_at=None.
    """
    if not letters:
        return []
    capped = [str(c) for c in letters[:200]]
    out: list[dict[str, Any]] = []
    with _connect(db_path) as conn:
        for c in capped:
            try:
                rows = conn.execute(
                    "SELECT correct, attempted_at FROM attempts "
                    "WHERE target = ? ORDER BY attempted_at ASC",
                    (c,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            total = len(rows)
            correct = sum(int(r["correct"]) for r in rows)
            last_at = rows[-1]["attempted_at"] if rows else None
            accuracy = round(correct / total, 4) if total else 0.0
            out.append({
                "character": c,
                "total_attempts": total,
                "correct_attempts": correct,
                "accuracy": accuracy,
                "last_attempted_at": last_at,
            })
    return out


def get_curriculum(language: str, scope: Literal["letters", "words"]) -> list[dict[str, Any]]:
    """Curriculum entries for the requested language+scope.

    v1 supports only language='te' + scope='letters'. Words scope and Hindi
    return [] — the planner must not crash on these and should fall back to
    letter recognition.
    """
    if language != "te" or scope != "letters":
        return []
    return [
        {
            "character": e.character,
            "transliteration": e.letter.transliteration,
            "difficulty_rank": e.difficulty_rank,
            "confusion_set": list(e.confusion_set),
            "category": e.category,
        }
        for e in TELUGU_CURRICULUM
    ]


# ---------------------------------------------------------------------------
# Retry-with-backoff wrapper (also reused by app/parent.py in Phase 8).
# ---------------------------------------------------------------------------


async def call_gemma_with_retry(
    messages: list[dict],
    tools: list[dict],
    tool_choice: dict | str | None = None,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: list[int] = _DEFAULT_BACKOFF,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict:
    """One agentic Gemma 4 call to OpenRouter with retry-with-backoff.

    `max_attempts` is the number of RETRIES after the first call (default 3 →
    4 total HTTP attempts). `backoff_seconds[i]` is the wait before retry i+1.

    Retries on: HTTP 429, HTTP 502, request timeout, missing/empty tool_calls
    in the response, JSON parse failure on tool-call arguments.
    Does NOT retry on Pydantic validation errors — those are caller-side and
    don't change shape on retry.

    Returns the raw OpenRouter response dict on success.
    Raises RuntimeError on retry exhaustion (includes attempt count + reason).
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY missing from environment")
    payload: dict[str, Any] = {"model": _MODEL_CLOUD, "messages": messages, "tools": tools}
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    total_attempts = 1 + max(0, int(max_attempts))
    last_reason = "no attempts made"

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for attempt_idx in range(total_attempts):
            if attempt_idx > 0:
                wait = backoff_seconds[min(attempt_idx - 1, len(backoff_seconds) - 1)]
                _stderr(
                    f"[planner-retry] {_utc_iso()} attempt {attempt_idx + 1}/{total_attempts} "
                    f"after {wait}s — prior reason: {last_reason}"
                )
                await asyncio.sleep(wait)

            try:
                r = await client.post(_OPENROUTER_URL, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                last_reason = f"http_{code}: {e.response.text[:200]}"
                if code in _RETRYABLE_HTTP:
                    continue
                raise RuntimeError(f"non-retryable HTTP {code}: {e.response.text[:200]}") from e
            except httpx.TimeoutException as e:
                last_reason = f"timeout: {e}"
                continue
            except (httpx.RequestError, ValueError) as e:
                last_reason = f"{type(e).__name__}: {e}"
                continue

            try:
                msg = data["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as e:
                last_reason = f"malformed response (no choices/message): {e}"
                continue

            tcs = msg.get("tool_calls") or []
            if not tcs:
                content_repr = repr(msg.get("content"))[:200]
                last_reason = f"missing tool_calls; content={content_repr}"
                continue

            parse_failed = False
            for tc in tcs:
                args_raw = tc.get("function", {}).get("arguments", "")
                if isinstance(args_raw, str):
                    try:
                        json.loads(args_raw)
                    except json.JSONDecodeError as e:
                        last_reason = f"tool_call args JSON parse failed: {e}"
                        parse_failed = True
                        break
            if parse_failed:
                continue

            return data

    raise RuntimeError(
        f"call_gemma_with_retry exhausted {total_attempts} attempts; last reason: {last_reason}"
    )


# ---------------------------------------------------------------------------
# Final-output tool (return_session_plan) and dispatch helpers.
# ---------------------------------------------------------------------------


def _build_return_session_plan_tool() -> dict:
    """OpenAI-compatible function-tool whose params mirror SessionPlan."""
    letter_entry_schema = {
        "type": "object",
        "properties": {
            "character": {"type": "string", "description": "Letter glyph as Unicode."},
            "transliteration": {"type": "string", "description": "English transliteration."},
            "language": {"type": "string", "enum": ["te", "hi"]},
        },
        "required": ["character", "transliteration", "language"],
        "additionalProperties": False,
    }
    feedback_variants_schema = {
        "type": "object",
        "properties": {
            "positive": {
                "type": "array", "items": {"type": "string"},
                "minItems": 3, "maxItems": 3,
                "description": "Three encouragement strings; vary tone, no repeats.",
            },
            "retry": {
                "type": "array", "items": {"type": "string"},
                "minItems": 2, "maxItems": 2,
                "description": "Two hint-shaped strings shown after the first wrong attempt.",
            },
        },
        "required": ["positive", "retry"],
        "additionalProperties": False,
    }
    recognition_step_schema = {
        "type": "object",
        "properties": {
            "step_type": {"type": "string", "enum": ["recognize_letter"]},
            "target": letter_entry_schema,
            "distractors": {
                "type": "array", "items": letter_entry_schema,
                "minItems": 3, "maxItems": 3,
                "description": "Exactly 3 plausible wrong-answer letters.",
            },
            "step_index": {"type": "integer", "minimum": 0},
            "feedback": feedback_variants_schema,
        },
        "required": ["step_type", "target", "distractors", "step_index", "feedback"],
        "additionalProperties": False,
    }
    session_step_schema = {
        "type": "object",
        "properties": {
            "step_data": recognition_step_schema,
            "target_skill": {
                "type": "string",
                "description": "Skill label, e.g. 'short-vowel-recognition' or 'similar-pair-discrimination'.",
            },
            "expected_difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
        },
        "required": ["step_data", "target_skill", "expected_difficulty"],
        "additionalProperties": False,
    }
    return {
        "type": "function",
        "function": {
            "name": "return_session_plan",
            "description": (
                "Terminal action: return the full bundled SessionPlan for today. The kid "
                "loop will render directly from this output and the model is not called "
                "again during the session. Every step must include exactly 3 distractors "
                "and a FeedbackVariants pool of 3 positive + 2 retry strings. Set "
                "fallback_used=false. session_id may be any placeholder; the system "
                "overrides it with the real UUID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "language": {"type": "string", "enum": ["te", "hi"]},
                    "focus": {"type": "string", "description": "Short label for today's emphasis."},
                    "reasoning": {
                        "type": "string",
                        "description": "2-4 sentences in plain English shown verbatim to the parent.",
                    },
                    "fallback_used": {"type": "boolean"},
                    "steps": {
                        "type": "array",
                        "items": session_step_schema,
                        "minItems": 5,
                        "maxItems": 8,
                    },
                },
                "required": ["session_id", "language", "focus", "steps", "reasoning", "fallback_used"],
                "additionalProperties": False,
            },
        },
    }


_RETURN_SESSION_PLAN_TOOL = _build_return_session_plan_tool()
_ALL_TOOLS = PLANNER_TOOLS + [_RETURN_SESSION_PLAN_TOOL]


def _execute_read_tool(name: str, args: dict, db_path: str | Path) -> Any:
    """Dispatch a planner read tool. Returns JSON-serialisable result.

    Errors are returned as {error: ...} rather than raised so the model can
    correct course on its next turn instead of crashing the agentic loop.
    """
    try:
        if name == "get_recent_sessions":
            return get_recent_sessions(int(args.get("n", 5)), db_path=db_path)
        if name == "get_letter_accuracy":
            letters = args.get("letters", [])
            if not isinstance(letters, list):
                return {"error": "letters must be an array of strings"}
            return get_letter_accuracy([str(c) for c in letters], db_path=db_path)
        if name == "get_curriculum":
            return get_curriculum(
                str(args.get("language", "te")),
                str(args.get("scope", "letters")),
            )
        return {"error": f"unknown tool: {name}"}
    except (ValueError, TypeError, sqlite3.Error) as e:
        return {"error": f"tool {name!r} failed: {type(e).__name__}: {e}"}


def _bundling_violations(plan: SessionPlan) -> list[str]:
    """Stricter-than-Pydantic semantic checks on a parsed SessionPlan.

    Pydantic only enforces shapes (3 distractors, 3 positive feedback variants,
    etc.). The bundling contract additionally requires: target glyph absent
    from its own distractors; distractors mutually distinct; correct feedback
    pool sizes. Same retry policy as Pydantic validation: a violation is a
    model-side content failure, so the planner falls back without retrying.
    """
    issues: list[str] = []
    for s in plan.steps:
        rs = s.step_data
        target_char = rs.target.character
        distractor_chars = [d.character for d in rs.distractors]
        if target_char in distractor_chars:
            issues.append(f"step {rs.step_index}: target {target_char!r} appears in distractors")
        if len(set(distractor_chars)) != len(distractor_chars):
            issues.append(f"step {rs.step_index}: duplicate distractors {distractor_chars}")
        if len(rs.feedback.positive) != 3:
            issues.append(f"step {rs.step_index}: positive feedback count is {len(rs.feedback.positive)}, expected 3")
        if len(rs.feedback.retry) != 2:
            issues.append(f"step {rs.step_index}: retry feedback count is {len(rs.feedback.retry)}, expected 2")
    return issues


def _replayable_assistant_message(msg: dict) -> dict:
    """Reduce an OpenRouter assistant message to the fields safe to POST back.

    Preserves reasoning_details specifically because Gemini-via-OpenRouter
    requires the encrypted reasoning blob to be threaded across multi-turn
    tool-calling rounds (see decisions.md 2026-05-11 Gate 6 note).
    """
    out: dict[str, Any] = {"role": "assistant"}
    if msg.get("content") is not None:
        out["content"] = msg["content"]
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
    if "reasoning_details" in msg:
        out["reasoning_details"] = msg["reasoning_details"]
    return out


# ---------------------------------------------------------------------------
# Deterministic fallback plan (also the planner's safety net).
# ---------------------------------------------------------------------------


def build_deterministic_session_plan(
    language: str = "te",
    db_path: str | Path = DEFAULT_DB_PATH,
    session_size: int = 5,
) -> SessionPlan:
    """Phase-4-equivalent SessionPlan, used when the agentic call fails or is forced off."""
    if language != "te":
        raise ValueError(f"language {language!r} not supported in v1")
    picks = select_session_letters(TELUGU_CURRICULUM, session_size=session_size, db_path=db_path)
    if not picks:
        raise RuntimeError("curriculum produced no picks; cannot build fallback plan")
    feedback = FeedbackVariants(
        positive=FALLBACK_FEEDBACK_VARIANTS["positive"][:3],
        retry=FALLBACK_FEEDBACK_VARIANTS["retry"][:2],
    )
    steps: list[SessionStep] = []
    for idx, entry in enumerate(picks):
        distractors = select_distractors(entry, "medium", TELUGU_CURRICULUM)
        steps.append(
            SessionStep(
                step_data=RecognitionStep(
                    step_type="recognize_letter",
                    target=entry.letter,
                    distractors=[d.letter for d in distractors],
                    step_index=idx,
                    feedback=feedback,
                ),
                target_skill="letter-recognition",
                expected_difficulty="medium",
            )
        )
    reasoning = (
        "Deterministic curriculum plan: prioritized least-practiced letters with "
        "medium-difficulty distractors drawn from each target's confusion set."
    )
    session_id = create_session(
        language=language,
        focus="planner fallback",
        fallback_used=True,
        reasoning=None,
        db_path=db_path,
    )
    return SessionPlan(
        session_id=session_id,
        language=language,
        focus="planner fallback",
        steps=steps,
        reasoning=reasoning,
        fallback_used=True,
    )


# ---------------------------------------------------------------------------
# Main entrypoint.
# ---------------------------------------------------------------------------


async def plan_session(
    kid_id: str = "default",
    language: str = "te",
    force_fallback: bool = False,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> SessionPlan:
    """Run the agentic session planner. Falls back to deterministic on any failure.

    Single-call architecture: combines PLANNER_PROMPT_V1 + the three read tools +
    return_session_plan. The model may interleave tool calls to read history;
    the agentic loop is capped at _AGENTIC_LOOP_CAP iterations.

    On success: validates the model's output against SessionPlan, overrides
    session_id with create_session()'s UUID and fallback_used=False, returns.
    On any failure (retries exhausted, validation error, loop cap reached):
    returns build_deterministic_session_plan() output. The kid never sees it.
    """
    _ = kid_id  # v1 single-user; reserved for v2 multi-kid support
    if force_fallback:
        _stderr(f"[planner] {_utc_iso()} force_fallback=True; skipping agentic call")
        return build_deterministic_session_plan(language=language, db_path=db_path)
    if language != "te":
        _stderr(f"[planner] {_utc_iso()} language {language!r} not supported in v1; falling back")
        return build_deterministic_session_plan(language="te", db_path=db_path)

    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    user_msg = (
        f"Plan today's session for the kid. Today is {today}. Language: te. "
        "Use the read tools as needed to gather context, then call "
        "return_session_plan with the full bundled SessionPlan."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PLANNER_PROMPT_V1},
        {"role": "user", "content": user_msg},
    ]

    try:
        for iteration in range(_AGENTIC_LOOP_CAP):
            response = await call_gemma_with_retry(
                messages=messages,
                tools=_ALL_TOOLS,
                tool_choice="auto",
            )
            assistant_msg = response["choices"][0]["message"]
            tool_calls = assistant_msg.get("tool_calls") or []

            final_tc = next(
                (tc for tc in tool_calls if tc.get("function", {}).get("name") == "return_session_plan"),
                None,
            )
            if final_tc is not None:
                args_raw = final_tc["function"]["arguments"]
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                try:
                    parsed = SessionPlan.model_validate(args)
                except ValidationError as e:
                    _stderr(f"[planner] {_utc_iso()} return_session_plan validation failed: {e}; falling back")
                    return build_deterministic_session_plan(language=language, db_path=db_path)
                violations = _bundling_violations(parsed)
                if violations:
                    _stderr(f"[planner] {_utc_iso()} bundling violations {violations}; falling back")
                    return build_deterministic_session_plan(language=language, db_path=db_path)
                session_id = create_session(
                    language=language,
                    focus=parsed.focus,
                    fallback_used=False,
                    reasoning=parsed.reasoning,
                    db_path=db_path,
                )
                return parsed.model_copy(update={"session_id": session_id, "fallback_used": False})

            messages.append(_replayable_assistant_message(assistant_msg))
            for tc in tool_calls:
                fname = tc.get("function", {}).get("name", "")
                args_raw = tc.get("function", {}).get("arguments", "{}")
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                except json.JSONDecodeError as e:
                    args = {"_arg_parse_error": str(e)}
                result = _execute_read_tool(fname, args if isinstance(args, dict) else {}, db_path)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": fname,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        _stderr(
            f"[planner] {_utc_iso()} agentic loop hit cap of {_AGENTIC_LOOP_CAP} "
            "iterations without final plan; falling back"
        )
        return build_deterministic_session_plan(language=language, db_path=db_path)

    except RuntimeError as e:
        _stderr(f"[planner] {_utc_iso()} retry exhausted: {e}; falling back")
        return build_deterministic_session_plan(language=language, db_path=db_path)


__all__ = [
    "get_recent_sessions",
    "get_letter_accuracy",
    "get_curriculum",
    "call_gemma_with_retry",
    "plan_session",
    "build_deterministic_session_plan",
]
