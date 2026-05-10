"""Phase 2 step 5 / Gate 6: structured-output smoke test for Gemma 4 31B.

Bypasses query_gemma intentionally — see PLAN.md Phase 2 step 5 / 'Gate 6'.
Once response shape is verified, query_gemma will be extended to support
tools and this script becomes redundant.

Calls OpenRouter chat/completions with a forced tool_choice for the
return_letter_entry function, with retry-with-backoff matching the planner
architecture in decisions.md 2026-05-10 ("3 retries max; 1s, 3s, 9s waits
between attempts"). Each of the N outer calls may internally retry up to 3
times on HTTP 429, HTTP 502, request timeout, or missing tool_calls.

Acceptance: 5/5 outer calls succeed at the end of their retry budget.
"""
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.prompts import LETTER_ENTRY_SMOKE_PROMPT_V1, LetterEntry  # noqa: E402

RESULTS_DIR = REPO_ROOT / "eval" / "results"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
N_CALLS = 5
TIMEOUT_S = 60.0
RETRY_BACKOFFS_S = [1.0, 3.0, 9.0]  # before retry attempts 2, 3, 4. Source: decisions.md 2026-05-10.
RETRYABLE_HTTP = {429, 502}

LETTER_ENTRY_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "return_letter_entry",
        "description": "Return a single LetterEntry for the requested glyph.",
        "parameters": {
            "type": "object",
            "properties": {
                "character": {"type": "string", "description": "Letter glyph as Unicode."},
                "transliteration": {"type": "string", "description": "English transliteration."},
                "language": {"type": "string", "description": "ISO-639-1 language code.", "enum": ["te", "hi"]},
            },
            "required": ["character", "transliteration", "language"],
            "additionalProperties": False,
        },
    },
}


async def _single_attempt(client: httpx.AsyncClient, api_key: str, model: str) -> dict:
    """One HTTP attempt. Returns dict with: retry_reason (str|None — None means stop retrying),
    response data, latency, and any populated parse fields."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": LETTER_ENTRY_SMOKE_PROMPT_V1}],
        "tools": [LETTER_ENTRY_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "return_letter_entry"}},
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    out: dict = {"retry_reason": None, "raw": None, "used_tool_call": False, "tool_calls": None,
                 "parse_ok": False, "letter_entry": None, "parse_error": None, "error": None, "latency_ms": 0}
    t0 = time.perf_counter()
    try:
        r = await client.post(OPENROUTER_URL, headers=headers, json=payload, timeout=TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        out["error"] = f"http {e.response.status_code}: {e.response.text[:200]}"
        out["retry_reason"] = f"http_{e.response.status_code}" if e.response.status_code in RETRYABLE_HTTP else None
        return out
    except (httpx.TimeoutException,) as e:
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        out["error"] = f"{type(e).__name__}: {e}"
        out["retry_reason"] = "timeout"
        return out
    except (httpx.RequestError, ValueError) as e:
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        out["error"] = f"{type(e).__name__}: {e}"
        out["retry_reason"] = "request_error"
        return out

    out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    out["raw"] = data
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    tcs = msg.get("tool_calls") or []
    out["tool_calls"] = tcs
    out["used_tool_call"] = bool(tcs)
    if not tcs:
        out["parse_error"] = f"no tool_calls; content was: {msg.get('content')!r}"
        out["retry_reason"] = "missing_tool_calls"
        return out
    try:
        args_raw = tcs[0]["function"]["arguments"]
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        entry = LetterEntry.model_validate(args)
        out["parse_ok"] = True
        out["letter_entry"] = entry.model_dump()
    except (KeyError, json.JSONDecodeError) as e:
        out["parse_error"] = f"args extraction failed: {type(e).__name__}: {e}"
    except ValidationError as e:
        out["parse_error"] = f"pydantic validation failed: {e}"
    return out  # retry_reason stays None on parse errors (non-retryable per spec)


async def _one_call(client: httpx.AsyncClient, api_key: str, model: str) -> dict:
    """Wraps _single_attempt in the retry-with-backoff loop. 4 attempts max."""
    retry_reasons: list[str] = []
    cumulative_latency_ms = 0
    final: dict = {}
    for attempt_idx in range(len(RETRY_BACKOFFS_S) + 1):  # 4 attempts total
        if attempt_idx > 0:
            await asyncio.sleep(RETRY_BACKOFFS_S[attempt_idx - 1])
        attempt = await _single_attempt(client, api_key, model)
        cumulative_latency_ms += attempt["latency_ms"]
        final = attempt
        if attempt["retry_reason"] is None:
            break
        retry_reasons.append(f"attempt {attempt_idx + 1}: {attempt['retry_reason']}")

    final["retry_count"] = len(retry_reasons)
    final["retry_reasons"] = retry_reasons
    final["latency_ms"] = cumulative_latency_ms
    return final


def _outcome_label(rec: dict) -> str:
    if rec["used_tool_call"] and rec["parse_ok"]:
        return "ok"
    if rec["error"]:
        return "ERR"
    return "no-tool-call" if not rec["used_tool_call"] else "parse-fail"


async def _run() -> int:
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    model = os.getenv("MODEL_CLOUD", "google/gemma-4-31b-it:free")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY missing from .env", file=sys.stderr)
        return 2

    print(f"[gate6] {N_CALLS} forced-tool-call requests to {model} (retry budget: 3 retries / 1s/3s/9s)", flush=True)
    results: list[dict] = []
    async with httpx.AsyncClient() as client:
        for i in range(1, N_CALLS + 1):
            rec = await _one_call(client, api_key, model)
            rec["index"] = i
            results.append(rec)
            label = _outcome_label(rec)
            retry_note = f", {rec['retry_count']} retries" if rec["retry_count"] else ""
            detail = "" if label == "ok" else f" — {rec['error'] or rec['parse_error']}"
            print(f"[{i}/{N_CALLS}] {label} {rec['latency_ms']}ms{retry_note}{detail}", flush=True)

    success = sum(1 for r in results if r["used_tool_call"] and r["parse_ok"])
    tool_call_count = sum(1 for r in results if r["used_tool_call"])
    parse_count = sum(1 for r in results if r["parse_ok"])
    total_retries = sum(r["retry_count"] for r in results)
    retry_counts = [r["retry_count"] for r in results]
    ok_latencies = [r["latency_ms"] for r in results if r["used_tool_call"] and r["parse_ok"]]
    med = int(statistics.median(ok_latencies)) if ok_latencies else 0
    mx = max(ok_latencies) if ok_latencies else 0
    summary = {"success_count": success, "tool_call_count": tool_call_count, "parse_count": parse_count,
               "n_calls": N_CALLS, "median_latency_ms": med, "max_latency_ms": mx,
               "median_retry_count": int(statistics.median(retry_counts)), "total_retries_triggered": total_retries}

    print("\n=== Gate 6 summary (with retry) ===")
    print(f"  success (tool-call AND parse):  {success}/{N_CALLS}")
    print(f"  used tool-call mechanism:       {tool_call_count}/{N_CALLS}")
    print(f"  pydantic parse succeeded:       {parse_count}/{N_CALLS}")
    print(f"  total retries triggered:        {total_retries}")
    print(f"  median retries per outer call:  {summary['median_retry_count']}")
    print(f"  latency on success (cumulative): median {med}ms, max {mx}ms")

    sample_full = next((r["raw"] for r in results if r["used_tool_call"] and r["parse_ok"]), None)
    sample_retry = next((r for r in results if r["retry_count"] > 0), None)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"smoke_structured_{ts}.json"
    payload = {"timestamp": ts, "prompt_version": "LETTER_ENTRY_SMOKE_PROMPT_V1", "model": model,
               "results": results, "summary": summary, "sample_full_response": sample_full,
               "sample_retry_call": sample_retry}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")
    return 0 if success == N_CALLS else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
