"""Phase 5.5 Half A step A2: smoke-test call_gemma_with_retry.

Reuses the LETTER_ENTRY tool from Gate 6 / eval/smoke_structured.py. One
forced tool_choice call. Should succeed in attempt 1 under normal upstream
conditions; retry log lines (stderr) appear if Gemini returns a 502.
"""
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.planner import call_gemma_with_retry  # noqa: E402
from app.prompts import LETTER_ENTRY_SMOKE_PROMPT_V1, LetterEntry  # noqa: E402

LETTER_ENTRY_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "return_letter_entry",
        "description": "Return a single LetterEntry for the requested glyph.",
        "parameters": {
            "type": "object",
            "properties": {
                "character": {"type": "string"},
                "transliteration": {"type": "string"},
                "language": {"type": "string", "enum": ["te", "hi"]},
            },
            "required": ["character", "transliteration", "language"],
            "additionalProperties": False,
        },
    },
}


async def _run() -> int:
    response = await call_gemma_with_retry(
        messages=[{"role": "user", "content": LETTER_ENTRY_SMOKE_PROMPT_V1}],
        tools=[LETTER_ENTRY_TOOL],
        tool_choice={"type": "function", "function": {"name": "return_letter_entry"}},
    )
    msg = response["choices"][0]["message"]
    tcs = msg.get("tool_calls") or []
    print(f"tool_calls returned: {len(tcs)}")
    args_raw = tcs[0]["function"]["arguments"]
    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
    entry = LetterEntry.model_validate(args)
    print(f"parsed LetterEntry: {entry.model_dump()}")
    print("A2 smoke test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
