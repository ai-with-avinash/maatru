"""Phase 5.5 Half A step A3: smoke-test plan_session end-to-end.

Two calls: (1) forced-fallback path against a fresh isolated DB, (2) live
agentic planner call against the same isolated DB. Prints both SessionPlans
so the bundling contract (target + 3 distractors + 3-positive/2-retry
feedback per step) can be eyeballed.
"""
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.planner import plan_session  # noqa: E402
from app.session import init_db  # noqa: E402

VERIFY_DB = REPO_ROOT / "eval" / "results" / "smoke_planner_full.db"


def _summarise(plan) -> dict:
    return {
        "session_id": plan.session_id,
        "language": plan.language,
        "focus": plan.focus,
        "fallback_used": plan.fallback_used,
        "reasoning": plan.reasoning,
        "steps": [
            {
                "step_index": s.step_data.step_index,
                "expected_difficulty": s.expected_difficulty,
                "target_skill": s.target_skill,
                "target": s.step_data.target.character,
                "transliteration": s.step_data.target.transliteration,
                "distractors": [d.character for d in s.step_data.distractors],
                "positive_count": len(s.step_data.feedback.positive),
                "retry_count": len(s.step_data.feedback.retry),
                "positive_sample": s.step_data.feedback.positive[0] if s.step_data.feedback.positive else None,
            }
            for s in plan.steps
        ],
    }


async def _run() -> int:
    if VERIFY_DB.exists():
        VERIFY_DB.unlink()
    init_db(VERIFY_DB)

    print("=== forced-fallback (no model call) ===")
    fb = await plan_session(force_fallback=True, db_path=VERIFY_DB)
    print(json.dumps(_summarise(fb), ensure_ascii=False, indent=2))
    assert fb.fallback_used is True, "force_fallback should produce fallback_used=True"
    assert fb.reasoning.startswith("Deterministic"), "fallback reasoning must start with 'Deterministic'"
    assert 5 <= len(fb.steps) <= 8

    print("\n=== live agentic planner call (cold-start DB) ===")
    live = await plan_session(db_path=VERIFY_DB)
    print(json.dumps(_summarise(live), ensure_ascii=False, indent=2))
    assert 5 <= len(live.steps) <= 8, f"expected 5-8 steps, got {len(live.steps)}"
    for step in live.steps:
        rs = step.step_data
        assert len(rs.distractors) == 3, "every step must have exactly 3 distractors"
        assert len(rs.feedback.positive) == 3, "feedback.positive must be exactly 3"
        assert len(rs.feedback.retry) == 2, "feedback.retry must be exactly 2"
        assert rs.target.character not in {d.character for d in rs.distractors}, "target leaked into distractors"

    if live.fallback_used:
        print("\nNOTE: live call fell back to deterministic (planner failure or upstream 502 storm).")
    else:
        print("\nlive planner produced model-driven SessionPlan; reasoning:", live.reasoning)

    print("\nA3 smoke test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
