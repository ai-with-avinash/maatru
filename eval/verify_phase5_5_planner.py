"""Phase 5.5 Half A step A4: planner verification across 5 fake histories.

Seeds an isolated SQLite DB with each scenario, calls plan_session(), validates
the SessionPlan against the bundled-output contract, runs scenario-specific
acceptance checks, and writes a markdown scorecard to eval/results/.

Scenarios (per Half A spec):
  1. brand_new — empty history (cold-start path).
  2. vowels_strong — 5 sessions, all 15 vowels at 100% accuracy.
  3. ready_for_words — 10 sessions, vowels mastered, 50% of consonants mastered.
  4. struggling_with_similar — 5 sessions with ఎ/ఏ pair confused (50% accuracy).
  5. mostly_mastered — 15 sessions, all letters at 80%+ accuracy.

Acceptance for Half A:
  - 4 of 5 scenarios produce a model-driven SessionPlan (fallback_used=False);
    1 fallback acceptable because Gate 5 measured ~36% upstream 502 rate.
  - Forced-fallback path produces fallback_used=True with deterministic reasoning.
  - Scenario 4 actually pairs ఎ with ఏ in at least one step.
  - Scenario 1 cold start uses easy difficulty + first vowels per PLANNER_PROMPT_V1.

Isolated DB lives at eval/results/planner_verify.db (gitignored). Reset between
scenarios so each starts from a known state. Production data/maatru.db is never
touched.
"""
import asyncio
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.curriculum import TELUGU_CONSONANTS_FIRST_10, TELUGU_VOWELS  # noqa: E402
from app.planner import plan_session  # noqa: E402
from app.prompts import SessionPlan  # noqa: E402
from app.session import _connect, init_db  # noqa: E402

VERIFY_DB = REPO_ROOT / "eval" / "results" / "planner_verify.db"
RESULTS_DIR = REPO_ROOT / "eval" / "results"


def _reset_db() -> None:
    if VERIFY_DB.exists():
        VERIFY_DB.unlink()
    init_db(VERIFY_DB)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_session(started_at: datetime, fallback: bool = True, reasoning: str | None = None) -> str:
    """Direct INSERT — bypasses create_session() so the verify script can place
    sessions on controlled timestamps without sleeping between them.
    """
    sid = str(uuid.uuid4())
    with _connect(VERIFY_DB) as conn:
        conn.execute(
            "INSERT INTO sessions (id, started_at, ended_at, language, focus, fallback_used, reasoning) "
            "VALUES (?, ?, NULL, 'te', 'verify-seed', ?, ?)",
            (sid, _iso(started_at), 1 if fallback else 0, reasoning),
        )
    return sid


def _seed_attempts(session_id: str, base_dt: datetime, attempts: list[tuple[str, str, bool]]) -> None:
    """Direct INSERT batch. attempts = [(target, chosen, correct), ...]."""
    with _connect(VERIFY_DB) as conn:
        for idx, (target, chosen, ok) in enumerate(attempts):
            ts = _iso(base_dt + timedelta(seconds=idx))
            conn.execute(
                "INSERT INTO attempts (session_id, step_index, target, chosen, correct, feedback, attempted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, idx, target, chosen, 1 if ok else 0, "Yes!" if ok else "Try again", ts),
            )


# ---------------------------------------------------------------------------
# Scenario seeding
# ---------------------------------------------------------------------------


_NOW = datetime.now(timezone.utc).replace(microsecond=0)
_VOWEL_CHARS = [v.character for v in TELUGU_VOWELS]
_CONSONANT_CHARS = [c.character for c in TELUGU_CONSONANTS_FIRST_10]
_NON_VOWEL_DISTRACTOR = TELUGU_CONSONANTS_FIRST_10[0].character  # 'క' — used as wrong-answer placeholder


def _scenario_brand_new() -> None:
    _reset_db()  # nothing else to do


def _scenario_vowels_strong() -> None:
    _reset_db()
    # 5 sessions; each session has all 15 vowels at 100% (each attempt correct).
    for s_idx in range(5):
        sid = _seed_session(_NOW - timedelta(days=5 - s_idx))
        _seed_attempts(
            sid,
            _NOW - timedelta(days=5 - s_idx, hours=1),
            [(v, v, True) for v in _VOWEL_CHARS],
        )


def _scenario_ready_for_words() -> None:
    _reset_db()
    # 10 sessions. All vowels: 4 attempts each, 100% (>= 3 attempts, 80%+).
    # First 5 consonants (క ఖ గ ఘ చ): 3 attempts each, 100%. Last 5: untouched.
    for s_idx in range(10):
        sid = _seed_session(_NOW - timedelta(days=10 - s_idx))
        atts: list[tuple[str, str, bool]] = []
        # Each session covers 6 vowels (rotating) and 3 of the first 5 consonants.
        for j in range(6):
            v = _VOWEL_CHARS[(s_idx + j) % len(_VOWEL_CHARS)]
            atts.append((v, v, True))
        mastered_consonants = _CONSONANT_CHARS[:5]
        for j in range(3):
            c = mastered_consonants[(s_idx + j) % len(mastered_consonants)]
            atts.append((c, c, True))
        _seed_attempts(sid, _NOW - timedelta(days=10 - s_idx, hours=1), atts)


def _scenario_struggling_with_similar() -> None:
    _reset_db()
    # 5 sessions; ఎ and ఏ each get 2 attempts per session (50% accuracy each).
    # Other vowels get a couple of correct attempts so the planner has signal that
    # the kid can otherwise read vowels — making the ఎ/ఏ confusion stand out.
    for s_idx in range(5):
        sid = _seed_session(_NOW - timedelta(days=5 - s_idx))
        atts: list[tuple[str, str, bool]] = [
            ("ఎ", "ఏ", False),
            ("ఎ", "ఎ", True),
            ("ఏ", "ఎ", False),
            ("ఏ", "ఏ", True),
            ("అ", "అ", True),
            ("ఆ", "ఆ", True),
            ("ఇ", "ఇ", True),
        ]
        _seed_attempts(sid, _NOW - timedelta(days=5 - s_idx, hours=1), atts)


def _scenario_mostly_mastered() -> None:
    _reset_db()
    # 15 sessions; every letter (vowels + first 10 consonants) at >=80% accuracy.
    all_chars = _VOWEL_CHARS + _CONSONANT_CHARS
    for s_idx in range(15):
        sid = _seed_session(_NOW - timedelta(days=15 - s_idx))
        atts: list[tuple[str, str, bool]] = []
        # 5 letters per session, mostly correct (4/5 = 80%).
        for j in range(5):
            c = all_chars[(s_idx * 3 + j) % len(all_chars)]
            ok = j != 4  # last attempt wrong → 80% per session
            atts.append((c, c if ok else _NON_VOWEL_DISTRACTOR, ok))
        _seed_attempts(sid, _NOW - timedelta(days=15 - s_idx, hours=1), atts)


SCENARIOS: list[tuple[str, callable]] = [
    ("brand_new", _scenario_brand_new),
    ("vowels_strong", _scenario_vowels_strong),
    ("ready_for_words", _scenario_ready_for_words),
    ("struggling_with_similar", _scenario_struggling_with_similar),
    ("mostly_mastered", _scenario_mostly_mastered),
]


# ---------------------------------------------------------------------------
# Per-scenario assertions (return list of (label, ok, detail))
# ---------------------------------------------------------------------------


_FIRST_FIVE_VOWELS = set(_VOWEL_CHARS[:5])  # అ ఆ ఇ ఈ ఉ — per cold-start clause


def _checks_brand_new(plan: SessionPlan) -> list[tuple[str, bool, str]]:
    if plan.fallback_used:
        return [("cold-start uses easy + first vowels", False, "skipped: planner fell back")]
    targets = {s.step_data.target.character for s in plan.steps}
    easy_count = sum(1 for s in plan.steps if s.expected_difficulty == "easy")
    in_first_five = targets & _FIRST_FIVE_VOWELS
    return [
        ("5 steps", len(plan.steps) == 5, f"got {len(plan.steps)}"),
        (
            "all targets are first-5 vowels",
            targets <= _FIRST_FIVE_VOWELS,
            f"unexpected: {sorted(targets - _FIRST_FIVE_VOWELS)}",
        ),
        (
            "covers >=4 of the first 5 vowels",
            len(in_first_five) >= 4,
            f"covered {sorted(in_first_five)}",
        ),
        ("all steps easy difficulty", easy_count == len(plan.steps), f"easy: {easy_count}/{len(plan.steps)}"),
    ]


def _checks_vowels_strong(plan: SessionPlan) -> list[tuple[str, bool, str]]:
    if plan.fallback_used:
        return [("introduces consonants or pushes harder", False, "skipped: planner fell back")]
    targets = [s.step_data.target.character for s in plan.steps]
    consonant_targets = [t for t in targets if t in _CONSONANT_CHARS]
    return [
        (
            "introduces consonants OR uses hard difficulty on vowels",
            bool(consonant_targets) or any(s.expected_difficulty == "hard" for s in plan.steps),
            f"consonants: {consonant_targets}",
        ),
    ]


def _checks_ready_for_words(plan: SessionPlan) -> list[tuple[str, bool, str]]:
    # v1 has no word curriculum (get_curriculum returns [] for words). Planner
    # must NOT crash and should focus on remaining unmastered consonants.
    if plan.fallback_used:
        return [("did not crash on missing word curriculum", True, "fell back to deterministic; acceptable")]
    targets = [s.step_data.target.character for s in plan.steps]
    unmastered_consonants = set(_CONSONANT_CHARS[5:])  # last 5 consonants seeded as untouched
    overlap = set(targets) & unmastered_consonants
    return [
        ("did not crash on missing word curriculum", True, "model produced a SessionPlan"),
        (
            "targets at least one unmastered consonant",
            bool(overlap),
            f"overlap with unmastered consonants: {sorted(overlap)}; targets: {targets}",
        ),
    ]


def _checks_struggling_with_similar(plan: SessionPlan) -> list[tuple[str, bool, str]]:
    if plan.fallback_used:
        return [("ఎ/ఏ deliberately paired", False, "skipped: planner fell back")]
    paired = False
    for s in plan.steps:
        target = s.step_data.target.character
        distractors = {d.character for d in s.step_data.distractors}
        if (target == "ఎ" and "ఏ" in distractors) or (target == "ఏ" and "ఎ" in distractors):
            paired = True
            break
    targets = [s.step_data.target.character for s in plan.steps]
    return [
        (
            "at least one step pairs ఎ as target with ఏ in distractors (or vice versa)",
            paired,
            f"targets: {targets}",
        ),
    ]


def _checks_mostly_mastered(plan: SessionPlan) -> list[tuple[str, bool, str]]:
    if plan.fallback_used:
        return [("varied targets", False, "skipped: planner fell back")]
    targets = [s.step_data.target.character for s in plan.steps]
    return [("varied targets (no repeats)", len(set(targets)) == len(targets), f"targets: {targets}")]


CHECKS: dict[str, Any] = {
    "brand_new": _checks_brand_new,
    "vowels_strong": _checks_vowels_strong,
    "ready_for_words": _checks_ready_for_words,
    "struggling_with_similar": _checks_struggling_with_similar,
    "mostly_mastered": _checks_mostly_mastered,
}


# ---------------------------------------------------------------------------
# Universal bundling-contract checks (every successful plan must satisfy)
# ---------------------------------------------------------------------------


def _bundling_checks(plan: SessionPlan) -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    rows.append(("5-8 steps", 5 <= len(plan.steps) <= 8, f"got {len(plan.steps)}"))
    for s in plan.steps:
        rs = s.step_data
        rows.append((
            f"step {rs.step_index}: 3 distractors",
            len(rs.distractors) == 3,
            f"got {len(rs.distractors)}",
        ))
        rows.append((
            f"step {rs.step_index}: 3 positive feedback variants",
            len(rs.feedback.positive) == 3,
            f"got {len(rs.feedback.positive)}",
        ))
        rows.append((
            f"step {rs.step_index}: 2 retry feedback variants",
            len(rs.feedback.retry) == 2,
            f"got {len(rs.feedback.retry)}",
        ))
        rows.append((
            f"step {rs.step_index}: target not in distractors",
            rs.target.character not in {d.character for d in rs.distractors},
            f"target {rs.target.character}",
        ))
    return rows


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"planner_scorecard_{ts}.md"
    rows: list[dict[str, Any]] = []

    for name, seed_fn in SCENARIOS:
        print(f"\n========== scenario: {name} ==========", flush=True)
        seed_fn()
        try:
            plan = await plan_session(db_path=VERIFY_DB)
            error: str | None = None
        except Exception as e:  # defensive — plan_session should always return
            plan = None
            error = f"{type(e).__name__}: {e}"

        scenario_summary: dict[str, Any] = {"scenario": name, "error": error}
        if plan is None:
            scenario_summary["fallback_used"] = None
            scenario_summary["bundling_pass"] = False
            scenario_summary["scenario_pass"] = False
            scenario_summary["plan_summary"] = None
            scenario_summary["check_rows"] = []
            scenario_summary["bundle_rows"] = []
            print(f"  ERROR: {error}")
            rows.append(scenario_summary)
            continue

        bundle_rows = _bundling_checks(plan)
        scenario_rows = CHECKS[name](plan)
        bundling_pass = all(ok for _, ok, _ in bundle_rows)
        scenario_pass = all(ok for _, ok, _ in scenario_rows)

        scenario_summary["fallback_used"] = plan.fallback_used
        scenario_summary["bundling_pass"] = bundling_pass
        scenario_summary["scenario_pass"] = scenario_pass
        scenario_summary["plan_summary"] = {
            "session_id": plan.session_id,
            "focus": plan.focus,
            "reasoning": plan.reasoning,
            "steps": [
                {
                    "step_index": s.step_data.step_index,
                    "target": s.step_data.target.character,
                    "transliteration": s.step_data.target.transliteration,
                    "distractors": [d.character for d in s.step_data.distractors],
                    "expected_difficulty": s.expected_difficulty,
                    "target_skill": s.target_skill,
                }
                for s in plan.steps
            ],
        }
        scenario_summary["check_rows"] = scenario_rows
        scenario_summary["bundle_rows"] = bundle_rows

        print(f"  fallback_used: {plan.fallback_used}")
        print(f"  bundling_pass: {bundling_pass}")
        print(f"  scenario_pass: {scenario_pass}")
        print(f"  reasoning: {plan.reasoning}")
        for s in plan.steps:
            rs = s.step_data
            d = " ".join(d.character for d in rs.distractors)
            print(f"    step {rs.step_index} [{s.expected_difficulty}] target={rs.target.character} distractors=[{d}] skill={s.target_skill}")
        for label, ok, detail in scenario_rows:
            mark = "PASS" if ok else "FAIL"
            print(f"    [{mark}] {label} — {detail}")
        rows.append(scenario_summary)

    # Forced-fallback sanity (separate, doesn't count toward 4-of-5)
    print("\n========== forced fallback sanity ==========", flush=True)
    _reset_db()
    fb_plan = await plan_session(force_fallback=True, db_path=VERIFY_DB)
    fb_pass = (
        fb_plan.fallback_used is True
        and fb_plan.reasoning.startswith("Deterministic")
        and 5 <= len(fb_plan.steps) <= 8
    )
    print(f"  fallback_used={fb_plan.fallback_used} reasoning={fb_plan.reasoning!r}")
    print(f"  forced-fallback pass: {fb_pass}")

    model_driven = sum(1 for r in rows if r["fallback_used"] is False)
    bundling_passes = sum(1 for r in rows if r["bundling_pass"])
    scenario_passes = sum(1 for r in rows if r["scenario_pass"])

    # ---------- write scorecard ----------
    lines: list[str] = []
    lines.append(f"# Phase 5.5 planner scorecard — {ts}")
    lines.append("")
    lines.append(f"- model: from MODEL_CLOUD env (default `google/gemma-4-31b-it:free`)")
    lines.append(f"- isolated DB: `{VERIFY_DB.relative_to(REPO_ROOT)}`")
    lines.append(f"- model-driven SessionPlans: **{model_driven}/{len(rows)}** (acceptance: ≥4)")
    lines.append(f"- bundling-contract passes: **{bundling_passes}/{len(rows)}**")
    lines.append(f"- scenario-specific passes: **{scenario_passes}/{len(rows)}**")
    lines.append(f"- forced-fallback sanity: **{'PASS' if fb_pass else 'FAIL'}**")
    lines.append("")
    lines.append("## Per-scenario results")
    lines.append("")
    lines.append("| scenario | fallback_used | bundling | scenario-checks | error |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['scenario']} | {r['fallback_used']} | "
            f"{'PASS' if r['bundling_pass'] else 'FAIL'} | "
            f"{'PASS' if r['scenario_pass'] else 'FAIL'} | "
            f"{r['error'] or ''} |"
        )
    lines.append("")
    lines.append("## Plan details per scenario")
    for r in rows:
        lines.append("")
        lines.append(f"### {r['scenario']}")
        if r["plan_summary"] is None:
            lines.append(f"- crashed: `{r['error']}`")
            continue
        lines.append(f"- session_id: `{r['plan_summary']['session_id']}`")
        lines.append(f"- focus: `{r['plan_summary']['focus']}`")
        lines.append(f"- reasoning: {r['plan_summary']['reasoning']}")
        lines.append("")
        lines.append("| step | difficulty | target (translit) | distractors | skill |")
        lines.append("|---|---|---|---|---|")
        for st in r["plan_summary"]["steps"]:
            lines.append(
                f"| {st['step_index']} | {st['expected_difficulty']} | "
                f"{st['target']} ({st['transliteration']}) | "
                f"{' '.join(st['distractors'])} | {st['target_skill']} |"
            )
        lines.append("")
        lines.append("Scenario checks:")
        for label, ok, detail in r["check_rows"]:
            lines.append(f"- {'PASS' if ok else 'FAIL'} — {label} — {detail}")
        lines.append("")
        lines.append("Bundling checks:")
        for label, ok, detail in r["bundle_rows"]:
            if not ok:
                lines.append(f"- FAIL — {label} — {detail}")
        if all(ok for _, ok, _ in r["bundle_rows"]):
            lines.append("- all bundling checks PASS")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps({"rows": rows, "forced_fallback_pass": fb_pass}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"\nscorecard: {out_path}")
    print(f"json:      {json_path}")
    print(f"\nmodel-driven SessionPlans: {model_driven}/{len(rows)} (need >= 4)")
    print(f"forced-fallback sanity: {'PASS' if fb_pass else 'FAIL'}")
    return 0 if (model_driven >= 4 and fb_pass) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
