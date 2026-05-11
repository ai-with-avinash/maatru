"""Phase 5.5 Half A step A1: smoke-test the three planner SQLite read tools.

Seeds an isolated DB with a couple of synthetic sessions, then calls each
tool the planner exposes to Gemma 4. Prints output shapes so they can be
eyeballed against the JSON-schema definitions in app/prompts.PLANNER_TOOLS.
"""
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.planner import (  # noqa: E402
    get_curriculum,
    get_letter_accuracy,
    get_recent_sessions,
)
from app.session import (  # noqa: E402
    create_session,
    end_session,
    init_db,
    record_attempt,
)

VERIFY_DB = REPO_ROOT / "eval" / "results" / "smoke_planner_tools.db"


def _seed(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    init_db(db_path)
    s1 = create_session(language="te", focus="vowel intro", fallback_used=True, db_path=db_path)
    for idx, (target, chosen, ok) in enumerate([
        ("అ", "అ", True),
        ("ఆ", "ఆ", True),
        ("ఇ", "ఈ", False),
        ("ఈ", "ఈ", True),
    ]):
        record_attempt(s1, idx, target, chosen, ok, "Yes!" if ok else "Try again", db_path=db_path)
    end_session(s1, db_path=db_path)
    time.sleep(1.1)  # session timestamps live at second precision; force a strictly-later s2
    s2 = create_session(
        language="te",
        focus="similar-pair drill",
        fallback_used=False,
        reasoning="Pair ఎ/ఏ deliberately after recent confusion.",
        db_path=db_path,
    )
    for idx, (target, chosen, ok) in enumerate([
        ("ఎ", "ఏ", False),
        ("ఏ", "ఎ", False),
        ("ఎ", "ఎ", True),
        ("అ", "అ", True),
    ]):
        record_attempt(s2, idx, target, chosen, ok, "Listen again" if not ok else "Great!", db_path=db_path)
    end_session(s2, db_path=db_path)


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    _seed(VERIFY_DB)

    _section("get_recent_sessions(n=5)")
    sessions = get_recent_sessions(5, db_path=VERIFY_DB)
    print(f"returned {len(sessions)} sessions (newest first)")
    print(json.dumps(sessions, ensure_ascii=False, indent=2))
    assert len(sessions) == 2
    assert sessions[0]["started_at"] >= sessions[1]["started_at"], "not sorted desc by started_at"
    assert sessions[0]["reasoning"] is not None, "planner-driven session should keep reasoning"
    assert sessions[1]["reasoning"] is None, "fallback session should report reasoning=None"

    _section("get_recent_sessions(n=999) — capped")
    capped = get_recent_sessions(999, db_path=VERIFY_DB)
    assert len(capped) == 2, "cap behaviour off"
    print(f"n=999 returned {len(capped)} (DB only has 2; cap to 30 still allows up to 2)")

    _section("get_letter_accuracy(letters=['ఎ','ఏ','క','అ'])")
    accuracy = get_letter_accuracy(["ఎ", "ఏ", "క", "అ"], db_path=VERIFY_DB)
    print(json.dumps(accuracy, ensure_ascii=False, indent=2))
    by_char = {a["character"]: a for a in accuracy}
    assert by_char["ఎ"]["total_attempts"] == 2 and by_char["ఎ"]["correct_attempts"] == 1
    assert by_char["ఏ"]["accuracy"] == 0.0  # 0/1
    assert by_char["క"]["total_attempts"] == 0 and by_char["క"]["last_attempted_at"] is None
    assert by_char["అ"]["accuracy"] == 1.0  # 2/2

    _section("get_curriculum('te', 'letters') — first 3 entries shown")
    curriculum = get_curriculum("te", "letters")
    print(f"returned {len(curriculum)} entries; first 3:")
    print(json.dumps(curriculum[:3], ensure_ascii=False, indent=2))
    assert len(curriculum) == 25  # 15 vowels + 10 first-varga consonants
    assert all({"character", "transliteration", "difficulty_rank", "confusion_set", "category"} <= set(e) for e in curriculum)

    _section("get_curriculum('te', 'words') — v1 returns []")
    words = get_curriculum("te", "words")
    print(f"returned {len(words)} entries (expected 0)")
    assert words == []

    _section("get_curriculum('hi', 'letters') — v1 returns []")
    hi = get_curriculum("hi", "letters")
    print(f"returned {len(hi)} entries (expected 0)")
    assert hi == []

    print("\nA1 smoke test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
