"""Phase 4 Half A verification.

Exercises curriculum + session modules end-to-end, no UI involvement:
- init_db(), select_session_letters() against empty DB (cold start path).
- select_distractors() at medium difficulty for each picked letter.
- create_session() + record_attempt() x5 (3 correct, 2 wrong).
- end_session().
- Re-run select_session_letters() and verify the priority shifts: the
  wrong-answered letters from session 1 should rank above neutral ones.

Uses an isolated DB at data/phase4_verify.db so it does not pollute the
production data/maatru.db. The temp DB is removed at the start of each run.
"""
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.curriculum import (  # noqa: E402
    FALLBACK_FEEDBACK_VARIANTS, TELUGU_CURRICULUM, select_distractors, select_session_letters,
)
from app.session import (  # noqa: E402
    create_session, end_session, get_letter_attempts, init_db, record_attempt,
)

VERIFY_DB = REPO_ROOT / "data" / "phase4_verify.db"


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    if VERIFY_DB.exists():
        VERIFY_DB.unlink()
    init_db(VERIFY_DB)
    rng = random.Random(42)  # seeded so distractor picks are reproducible

    _print_header("Step 1: select_session_letters on empty DB")
    first_session = select_session_letters(TELUGU_CURRICULUM, session_size=5, rng=rng, db_path=VERIFY_DB)
    print("picked letters (target / translit / rank):")
    for entry in first_session:
        print(f"  {entry.character}\t{entry.letter.transliteration}\trank {entry.difficulty_rank}\t{entry.category}")

    _print_header("Step 2: select_distractors (medium) for each picked letter")
    for entry in first_session:
        distractors = select_distractors(entry, "medium", TELUGU_CURRICULUM, rng=rng)
        d_chars = " ".join(d.character for d in distractors)
        print(f"  target {entry.character} -> distractors: {d_chars}")
        assert len(distractors) == 3, f"expected 3 distractors, got {len(distractors)}"
        assert entry.character not in {d.character for d in distractors}, "target leaked into distractors"

    _print_header("Step 3: simulate sessions covering most of the curriculum")
    # To exercise the low_recent vs neutral bucket comparison, the never_attempted
    # bucket has to be drained first. Attempt 22 of 25 letters across two sessions;
    # 4 of them get wrong answers so they enter the low_recent bucket.
    wrong_target_indices = {3, 7, 14, 19}  # indices into TELUGU_CURRICULUM
    wrong_letters: list[str] = []
    session_id = create_session(language="te", focus="phase4 verify", fallback_used=True, db_path=VERIFY_DB)
    print(f"session_id = {session_id}")
    for idx, entry in enumerate(TELUGU_CURRICULUM[:22]):
        correct = idx not in wrong_target_indices
        # Pick a chosen letter that is not the target when wrong.
        chosen = entry.character if correct else next(
            c.character for c in TELUGU_CURRICULUM if c.character != entry.character
        )
        feedback = rng.choice(FALLBACK_FEEDBACK_VARIANTS["positive" if correct else "retry"])
        record_attempt(session_id, idx, entry.character, chosen, correct, feedback, db_path=VERIFY_DB)
        if not correct:
            wrong_letters.append(entry.character)
    end_session(session_id, db_path=VERIFY_DB)
    print(f"attempted {22} letters; wrong-answered: {wrong_letters} (rank in TELUGU_CURRICULUM: {sorted(wrong_target_indices)})")

    _print_header("Step 4: get_letter_attempts spot-check on a wrong-answered letter")
    sample = wrong_letters[0]
    recs = get_letter_attempts(sample, db_path=VERIFY_DB)
    print(f"  attempts on {sample}: {len(recs)}")
    for r in recs:
        print(f"    {r}")

    _print_header("Step 5: select_session_letters — second session, larger size")
    # 3 letters remain never_attempted (indices 22, 23, 24). With session_size=8,
    # the heuristic must pick those 3 first, then drain low_recent (the 4 wrong),
    # then start filling from neutral letters. Order within the picked list is
    # what the test verifies.
    second_session = select_session_letters(TELUGU_CURRICULUM, session_size=8, rng=rng, db_path=VERIFY_DB)
    print("second-session picks (in returned order):")
    for entry in second_session:
        attempts = get_letter_attempts(entry.character, db_path=VERIFY_DB)
        if not attempts:
            bucket = "never_attempted"
        else:
            recent = sorted(attempts, key=lambda a: a["attempted_at"], reverse=True)[:5]
            acc = sum(1 for a in recent if a["correct"]) / len(recent)
            bucket = f"low_recent ({acc:.0%})" if acc < 0.6 else f"neutral ({acc:.0%})"
        print(f"  {entry.character}\trank {entry.difficulty_rank}\t{bucket}")

    _print_header("Step 6: heuristic acceptance checks")
    picks = [e.character for e in second_session]
    bucket_of: dict[str, str] = {}
    for c in picks:
        recs = get_letter_attempts(c, db_path=VERIFY_DB)
        if not recs:
            bucket_of[c] = "never_attempted"
        else:
            acc = sum(1 for r in sorted(recs, key=lambda a: a["attempted_at"], reverse=True)[:5] if r["correct"])
            bucket_of[c] = "low_recent" if acc / min(5, len(recs)) < 0.6 else "neutral"
    bucket_seq = [bucket_of[c] for c in picks]
    print(f"bucket sequence in returned order: {bucket_seq}")

    # Check 1: never_attempted entries (the 3 unattempted) come before any low_recent.
    first_low_recent_idx = next((i for i, b in enumerate(bucket_seq) if b == "low_recent"), len(bucket_seq))
    last_never_attempted_idx = max((i for i, b in enumerate(bucket_seq) if b == "never_attempted"), default=-1)
    if last_never_attempted_idx > first_low_recent_idx:
        print("FAIL: never_attempted should rank above low_recent")
        return 1

    # Check 2: low_recent entries come before any neutral entries.
    first_neutral_idx = next((i for i, b in enumerate(bucket_seq) if b == "neutral"), len(bucket_seq))
    last_low_recent_idx = max((i for i, b in enumerate(bucket_seq) if b == "low_recent"), default=-1)
    if last_low_recent_idx > first_neutral_idx:
        print("FAIL: low_recent should rank above neutral")
        return 1

    # Check 3: wrong-answered letters that fit within the session must all appear.
    wrong_in_picks = [w for w in wrong_letters if w in picks]
    print(f"wrong-letters appearing in 8-letter second session: {wrong_in_picks} of {len(wrong_letters)}")
    if len(wrong_in_picks) < min(len(wrong_letters), 8 - 3):  # 8 slots - 3 never_attempted = 5 for low_recent + neutral
        print("FAIL: low_recent letters did not fully populate available slots")
        return 1

    print("\nHalf A verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
