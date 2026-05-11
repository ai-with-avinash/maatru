"""Telugu curriculum data + deterministic distractor and session-letter selection.

Phase 4 substrate. Hand-curated; not model-generated. The planner in Phase 5.5
will reuse `select_distractors` for its fallback path and may override with
its own pedagogical pairings, but the data here is the source of truth.

ఌ (vocalic l) is omitted from TELUGU_VOWELS as archaic — modern primary-school
Telugu material teaches 15 vowels (అ … అః). Consonants are limited to the first
10 stops in classical varga order (k-, c-, ṭ-vargas without their nasals) per
PLAN.md Phase 4 step 1; the rest of the alphabet is post-v1 scope.
"""
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.prompts import LetterEntry
from app.session import DEFAULT_DB_PATH, get_letter_attempts

Category = Literal["vowel", "consonant"]
Difficulty = Literal["easy", "medium", "hard"]


class CurriculumEntry(BaseModel):
    """A LetterEntry plus pedagogical metadata used by selection rules."""

    letter: LetterEntry = Field(..., description="The underlying letter primitive.")
    difficulty_rank: int = Field(..., ge=1, description="1=easiest within its category.")
    confusion_set: list[str] = Field(
        ...,
        description="Glyphs of letters easily confused with this one. 1-3 entries.",
        min_length=1,
        max_length=3,
    )
    category: Category = Field(..., description="vowel or consonant.")

    @property
    def character(self) -> str:
        return self.letter.character


def _v(rank: int, char: str, translit: str, confusion: list[str]) -> CurriculumEntry:
    return CurriculumEntry(
        letter=LetterEntry(character=char, transliteration=translit, language="te"),
        difficulty_rank=rank,
        confusion_set=confusion,
        category="vowel",
    )


def _c(rank: int, char: str, translit: str, confusion: list[str]) -> CurriculumEntry:
    return CurriculumEntry(
        letter=LetterEntry(character=char, transliteration=translit, language="te"),
        difficulty_rank=rank,
        confusion_set=confusion,
        category="consonant",
    )


# 15 Telugu vowels in classical akshara-mala order.
TELUGU_VOWELS: list[CurriculumEntry] = [
    _v(1, "అ", "a", ["ఆ", "అం"]),
    _v(2, "ఆ", "aa", ["అ"]),
    _v(3, "ఇ", "i", ["ఈ"]),
    _v(4, "ఈ", "ii", ["ఇ"]),
    _v(5, "ఉ", "u", ["ఊ"]),
    _v(6, "ఊ", "uu", ["ఉ"]),
    _v(7, "ఋ", "r̥", ["ఇ"]),
    _v(8, "ఎ", "e", ["ఏ"]),
    _v(9, "ఏ", "ee", ["ఎ", "ఐ"]),
    _v(10, "ఐ", "ai", ["ఏ", "ఎ"]),
    _v(11, "ఒ", "o", ["ఓ"]),
    _v(12, "ఓ", "oo", ["ఒ", "ఔ"]),
    _v(13, "ఔ", "au", ["ఓ"]),
    _v(14, "అం", "am", ["అః", "అ"]),
    _v(15, "అః", "aha", ["అం"]),
]

# First 10 consonants, k-/c-/ṭ-varga stops (classical varga order, nasals omitted).
TELUGU_CONSONANTS_FIRST_10: list[CurriculumEntry] = [
    _c(1, "క", "ka", ["ఖ", "చ"]),
    _c(2, "ఖ", "kha", ["క"]),
    _c(3, "గ", "ga", ["ఘ"]),
    _c(4, "ఘ", "gha", ["గ"]),
    _c(5, "చ", "ca", ["ఛ", "క"]),
    _c(6, "ఛ", "cha", ["చ"]),
    _c(7, "జ", "ja", ["ఝ"]),
    _c(8, "ఝ", "jha", ["జ"]),
    _c(9, "ట", "ṭa", ["ఠ"]),
    _c(10, "ఠ", "ṭha", ["ట"]),
]

TELUGU_CURRICULUM: list[CurriculumEntry] = TELUGU_VOWELS + TELUGU_CONSONANTS_FIRST_10


# Generic feedback pool used when the planner has not populated per-step variants.
# Phase 5.5 replaces this with model-authored, letter-specific FeedbackVariants
# embedded in each RecognitionStep of the SessionPlan.
FALLBACK_FEEDBACK_VARIANTS: dict[str, list[str]] = {
    "positive": [
        "Yes!",
        "Great!",
        "Perfect!",
        "That's right!",
        "Wonderful!",
        "Yes, exactly!",
    ],
    "retry": [
        "Try again — listen carefully",
        "Not quite — listen for the sound",
        "Listen once more",
        "It's a different one",
    ],
}


def _by_char(curriculum: list[CurriculumEntry], char: str) -> CurriculumEntry | None:
    return next((c for c in curriculum if c.character == char), None)


def select_distractors(
    target: CurriculumEntry,
    difficulty: Difficulty,
    curriculum: list[CurriculumEntry],
    rng: random.Random | None = None,
) -> list[CurriculumEntry]:
    """Pick exactly 3 distractors from the curriculum per the difficulty rule.

    easy   = 3 from the opposite category.
    medium = 2 same-category outside confusion_set + 1 from confusion_set.
    hard   = 3 from confusion_set; backfill with same-category visually-similar
             letters if confusion_set has fewer than 3.

    Never includes the target itself. Pure function aside from the supplied rng.
    """
    rng = rng or random.Random()
    same_category = [c for c in curriculum if c.category == target.category and c.character != target.character]
    other_category = [c for c in curriculum if c.category != target.category]
    confusion_entries = [e for e in (_by_char(curriculum, ch) for ch in target.confusion_set) if e is not None]

    if difficulty == "easy":
        return rng.sample(other_category, 3)

    if difficulty == "medium":
        outside_confusion = [c for c in same_category if c.character not in target.confusion_set]
        picks = rng.sample(outside_confusion, 2) if len(outside_confusion) >= 2 else outside_confusion[:2]
        if confusion_entries:
            picks.append(rng.choice(confusion_entries))
        # Backfill if we somehow ended short (tiny curriculum / sparse confusion data).
        while len(picks) < 3:
            candidate = rng.choice(same_category)
            if candidate.character not in {p.character for p in picks}:
                picks.append(candidate)
        return picks[:3]

    # hard
    picks = list(confusion_entries)
    if len(picks) < 3:
        # Visually-similar same-category fillers: any same-category letter whose
        # confusion_set overlaps with the target's, prioritised first.
        target_confusion = set(target.confusion_set)
        overlap = [
            c for c in same_category
            if c.character not in {p.character for p in picks}
            and (set(c.confusion_set) & target_confusion or c.character in target_confusion)
        ]
        rng.shuffle(overlap)
        picks.extend(overlap)
    while len(picks) < 3:
        candidate = rng.choice(same_category)
        if candidate.character not in {p.character for p in picks} and candidate.character != target.character:
            picks.append(candidate)
    return picks[:3]


def select_session_letters(
    curriculum: list[CurriculumEntry],
    session_size: int = 5,
    rng: random.Random | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[CurriculumEntry]:
    """Least-practiced heuristic. Reads SQLite via session.get_letter_attempts.

    Buckets curriculum entries:
      - never_attempted: no records
      - low_recent: <60% accuracy in the last 5 attempts
      - neutral: everything else
    Returns up to session_size entries in priority order (never_attempted by
    difficulty_rank, low_recent by oldest-attempt-first, neutral random).
    """
    rng = rng or random.Random()
    never_attempted: list[CurriculumEntry] = []
    low_recent: list[tuple[CurriculumEntry, str]] = []  # (entry, last_attempted_at)
    neutral: list[CurriculumEntry] = []

    for entry in curriculum:
        attempts = get_letter_attempts(entry.character, db_path=db_path)
        if not attempts:
            never_attempted.append(entry)
            continue
        recent = sorted(attempts, key=lambda a: a["attempted_at"], reverse=True)[:5]
        accuracy = sum(1 for a in recent if a["correct"]) / len(recent)
        if accuracy < 0.6:
            low_recent.append((entry, recent[0]["attempted_at"]))
        else:
            neutral.append(entry)

    never_attempted.sort(key=lambda e: e.difficulty_rank)
    low_recent.sort(key=lambda pair: pair[1])  # oldest first
    rng.shuffle(neutral)

    ordered = never_attempted + [e for e, _ in low_recent] + neutral
    return ordered[:session_size]
