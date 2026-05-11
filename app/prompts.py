"""Versioned prompt templates and Pydantic schemas for structured outputs.

Phase 2: schemas defined here support the planner-bundling architecture
specified in decisions.md (2026-05-10 "Architecture mitigation for free-tier
reliability"). The kid loop reads SessionPlan content directly; no Gemma 4
calls happen during a session. The planner emits all per-step distractors
and feedback variants in its single agentic call.
"""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core curriculum primitives
# ---------------------------------------------------------------------------


Language = Literal["te", "hi"]


class LetterEntry(BaseModel):
    """A single letter in the curriculum (Telugu, Hindi, etc.).

    Used as the atomic unit everywhere: targets, distractors, curriculum lists.
    """

    character: str = Field(..., description="The letter glyph as Unicode, e.g. 'అ'.")
    transliteration: str = Field(..., description="English transliteration, e.g. 'a'.")
    language: Language = Field(..., description="ISO-639-1 language code: 'te' (Telugu) or 'hi' (Hindi).")


class LetterSet(BaseModel):
    """A grouping of LetterEntry values around a theme (vowels, consonants, etc.).

    Used by the curriculum module and as a return shape for content-generation
    calls (Phase 4 hand-curated; planner overrides in Phase 5.5).
    """

    language: Language = Field(..., description="ISO-639-1 language code: 'te' (Telugu) or 'hi' (Hindi).")
    theme: str = Field(..., description="Theme label, e.g. 'vowels' or 'similar-pairs'.")
    entries: list[LetterEntry] = Field(..., description="Letters in this set.")


# ---------------------------------------------------------------------------
# Kid-loop step content (bundled by the planner)
# ---------------------------------------------------------------------------


class FeedbackVariants(BaseModel):
    """Pre-generated feedback strings bundled with each RecognitionStep.

    The kid loop randomly picks one positive on success and one retry on
    first miss. Pool size kept small (3 positive, 2 retry) to fit in the
    planner's single SessionPlan response.
    """

    positive: list[str] = Field(..., description="Encouragement strings for correct answers.")
    retry: list[str] = Field(..., description="Hint strings shown after the first wrong attempt.")


class RecognitionStep(BaseModel):
    """A single tap-to-recognize question.

    One target letter, three distractor letters (curriculum-grade plausible),
    and a FeedbackVariants pool. Carries its own step_type discriminator so
    the kid loop can dispatch on the typed payload rather than a parallel tag.
    Used for both single-letter and 2-letter-word recognition; the target's
    LetterEntry.character carries either a single glyph or a short word.
    """

    step_type: Literal["recognize_letter"] = Field(
        default="recognize_letter",
        description="Discriminator literal; identifies this payload to the kid-loop dispatcher.",
    )
    target: LetterEntry = Field(..., description="The letter the kid must identify.")
    distractors: list[LetterEntry] = Field(
        ...,
        description="Three plausible wrong-answer letters shown alongside the target.",
        min_length=3,
        max_length=3,
    )
    step_index: int = Field(..., ge=0, description="Zero-based position within the SessionPlan.")
    feedback: FeedbackVariants = Field(..., description="Pre-generated feedback pool for this step.")


# ---------------------------------------------------------------------------
# Session plan (Layer 2 output, Layer 1 input)
# ---------------------------------------------------------------------------


Difficulty = Literal["easy", "medium", "hard"]

# Discriminated union for step payloads. The discriminator field `step_type`
# lives on each variant model. With one variant today this is degenerate, but
# Phase 6 adds ReadAloudStep:
#   StepData = Annotated[
#       Union[RecognitionStep, ReadAloudStep],
#       Field(discriminator="step_type"),
#   ]
# Pydantic catches malformed step_data at SessionPlan validation time, so the
# kid loop can trust step.step_data is a fully-validated typed object.
StepData = Annotated[Union[RecognitionStep], Field(discriminator="step_type")]


class SessionStep(BaseModel):
    """Polymorphic wrapper for one step in a SessionPlan.

    step_data carries its own step_type discriminator (RecognitionStep today;
    ReadAloudStep added in Phase 6 if built). The wrapper attaches pedagogical
    metadata that the parent dashboard surfaces.
    """

    step_data: StepData = Field(..., description="Typed payload; dispatched on step_data.step_type.")
    target_skill: str = Field(..., description="Pedagogical skill being practiced (e.g. 'short-vowel-recognition').")
    expected_difficulty: Difficulty = Field(..., description="Planner's difficulty estimate for this step.")


class SessionPlan(BaseModel):
    """The single artifact returned by the agentic session planner (Phase 5.5).

    Contains every step the kid loop will render today, including distractors
    and feedback variants per step. This is what makes the bundling
    architecture work: one Gemma 4 call at session start, zero calls during
    the session itself.
    """

    session_id: str = Field(..., description="UUID for this session.")
    language: Language = Field(..., description="ISO-639-1 language code: 'te' (Telugu) or 'hi' (Hindi).")
    focus: str = Field(..., description="Short label for what today's session emphasizes.")
    steps: list[SessionStep] = Field(..., description="Ordered list of steps the kid loop will execute.")
    reasoning: str = Field(..., description="Planner's justification, surfaced to the parent dashboard.")
    fallback_used: bool = Field(
        ...,
        description="True if produced by the deterministic fallback (planner call failed or skipped).",
    )


# ---------------------------------------------------------------------------
# Parent dashboard summary
# ---------------------------------------------------------------------------


class SessionSummary(BaseModel):
    """English-translated summary of a session for the parent dashboard.

    Generated by a separate Gemma 4 call per dashboard load (Phase 5). Parents
    trigger this manually so the per-load call is acceptable under the 20
    req/min cap.
    """

    letters_practiced: list[str] = Field(..., description="Telugu/Hindi characters seen in the session.")
    strong_letters: list[str] = Field(..., description="Letters the kid handled well.")
    needs_practice: list[str] = Field(..., description="Letters that warrant repetition.")
    suggested_next: list[str] = Field(..., description="Letters or skills recommended for the next session.")
    parent_summary_english: str = Field(
        ...,
        description="One-paragraph English summary written for a parent who cannot read the script.",
    )


# ---------------------------------------------------------------------------
# Planner tool schemas (OpenAI-compatible function-tool dicts).
#
# These are passed in the `tools` array of the chat-completions call to the
# session planner (Phase 5.5). Tools are READ-ONLY: each maps to a SQLite
# read function defined in app/session.py / app/curriculum.py during Phase
# 5.5. Hand-built JSON Schema (rather than Pydantic-generated) to keep the
# definitions compact and free of the `$defs` / `title` noise Pydantic adds.
# ---------------------------------------------------------------------------


PLANNER_TOOL_GET_RECENT_SESSIONS: dict = {
    "type": "function",
    "function": {
        "name": "get_recent_sessions",
        "description": (
            "Return the kid's most recent practice sessions in reverse chronological order. "
            "Each session entry includes date, letters practiced, per-letter accuracy, and "
            "any planner reasoning recorded at the time. Use this to see longitudinal "
            "patterns (improving/regressing letters, recent focus areas) before deciding "
            "today's plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Number of recent sessions to return (1-30).",
                    "minimum": 1,
                    "maximum": 30,
                },
            },
            "required": ["n"],
            "additionalProperties": False,
        },
    },
}


PLANNER_TOOL_GET_LETTER_ACCURACY: dict = {
    "type": "function",
    "function": {
        "name": "get_letter_accuracy",
        "description": (
            "Return aggregate accuracy stats for the requested letters across all sessions: "
            "for each letter, total attempts, correct attempts, accuracy ratio, and the "
            "timestamp of the most recent attempt. Use this to identify mastery (>=80% "
            "across 3+ attempts) and to choose targets for today's session."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "letters": {
                    "type": "array",
                    "description": "Letter glyphs to look up, e.g. ['అ', 'ఆ', 'ఇ']. 1-200 entries.",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 200,
                },
            },
            "required": ["letters"],
            "additionalProperties": False,
        },
    },
}


PLANNER_TOOL_GET_CURRICULUM: dict = {
    "type": "function",
    "function": {
        "name": "get_curriculum",
        "description": (
            "Return curriculum entries for the given language and scope. Letters scope "
            "yields the ordered set of single-character entries (each with character, "
            "transliteration, difficulty rank, and confusion_set). Words scope yields "
            "2-letter words for word-recognition steps. Use this to pick targets the kid "
            "is ready for and to inform distractor selection."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "ISO-639-1 language code: 'te' (Telugu) or 'hi' (Hindi).",
                    "enum": ["te", "hi"],
                },
                "scope": {
                    "type": "string",
                    "description": "Which curriculum slice to return.",
                    "enum": ["letters", "words"],
                },
            },
            "required": ["language", "scope"],
            "additionalProperties": False,
        },
    },
}


PLANNER_TOOLS: list[dict] = [
    PLANNER_TOOL_GET_RECENT_SESSIONS,
    PLANNER_TOOL_GET_LETTER_ACCURACY,
    PLANNER_TOOL_GET_CURRICULUM,
]

# ---------------------------------------------------------------------------
# Prompt templates (versioned).
#
# Convention: when a prompt is revised, increment the version (V1 -> V2),
# leave the old constant commented out for reference, and update the active
# constant. This keeps prompt history visible in source diff and avoids
# silent behavior shifts.
# ---------------------------------------------------------------------------


# v1 — 2026-05-10 — first cut. revised 2026-05-11 — added explicit
# distractor-uniqueness clause after Phase 5.5 step A4 caught a model
# output where the target glyph appeared in its own distractor list.
# System prompt for the agentic session planner under the planner-bundling
# architecture (decisions.md 2026-05-10 "Architecture mitigation for
# free-tier reliability").
PLANNER_PROMPT_V1 = """\
You are the session planner for Maatru, an early-literacy app that teaches \
Indian children to read their mother tongue script (Telugu first, Hindi \
generalized later).

User profile:
- The learner is a 5-8 year old child whose parents speak the language but \
cannot reliably read or write its script.
- The kid practices by hearing a letter pronounced and tapping the matching \
glyph from 4 options (1 target + 3 distractors). No writing, no camera, no \
microphone.
- Sessions happen 1-3 times per week, 3-5 minutes each.

Pedagogical principles you must follow:
- Consistency over novelty. Repeat foundational letters until they are \
mastered. Do not introduce new step types or new letter categories faster \
than the kid demonstrates readiness.
- Mastery threshold: a letter is mastered when the kid has answered it \
correctly in >=80% of attempts AND has at least 3 attempts on record.
- Session length: 5 to 8 steps. Shorter on first sessions or after a \
struggling session; longer when the kid is on a streak.
- Difficulty rules per step:
  * easy = 3 distractors from a different category than the target (e.g. \
consonants when target is a vowel).
  * medium = 2 distractors from the same category as the target but \
distinct shape, 1 distractor from the target's confusion_set.
  * hard = 3 distractors from the target's confusion_set.
- When the kid recently confused two letters, deliberately pair them in \
today's session at medium or hard difficulty.

Tools available (read-only; call as many times as needed before producing \
the final SessionPlan):
- get_recent_sessions(n) — last n sessions with letters practiced and \
accuracy per letter. Start with n=5 unless the kid is brand-new.
- get_letter_accuracy(letters) — per-letter total/correct attempts and \
last-attempted timestamp. Use to check mastery for specific letters.
- get_curriculum(language, scope) — curriculum entries (letters or \
2-letter words) with character, transliteration, difficulty rank, and \
confusion_set. Use to pick targets and to source distractors.

# revised 2026-05-11 (Phase 6) — require history check
Mandatory tool use: BEFORE proposing a SessionPlan, you MUST call \
get_recent_sessions with n>=5 to see what the child practiced recently. \
Even on what feels like a cold start, call this tool — its empty response \
is itself the signal that this is the first session, and your reasoning \
should reference that fact ("I checked recent sessions and found no prior \
practice…"). Without this context you cannot make a pedagogically grounded \
plan, and the parent dashboard reasoning must reflect the actual history \
you observed.

Bundled-output contract (CRITICAL — this is the architectural reason you \
exist):
- The kid loop will NOT call any model during the session. Everything the \
loop needs must be embedded in the SessionPlan you return now.
- For every step, emit:
  * target: a LetterEntry with character + transliteration + language.
  * distractors: exactly 3 LetterEntry values. Drawn from the target's \
confusion_set when the step is medium/hard, or from distinct categories \
when easy. The 3 distractor glyphs MUST be distinct from each other AND \
MUST NOT include the target glyph — the kid will tap one of 4 buttons \
(target + 3 distractors) and a duplicated or self-referential option \
breaks the question.
  * step_index: zero-based.
  * feedback: a FeedbackVariants object with exactly 3 'positive' strings \
and exactly 2 'retry' strings. Vary tone (warm, energetic, gentle); avoid \
repeating the same word across positives. Retry strings should be \
hint-shaped, not scolding ('Listen for the long sound', 'It's a softer \
one — try again').
- The kid loop randomly samples one positive on success and one retry on \
the first wrong attempt, so all variants must read naturally on their own.

Reasoning protocol:
- Call tools as needed to gather data, then return the final SessionPlan \
in a single response. Do not ask follow-up questions or wait for \
confirmation. The system around you cannot answer.
- Populate the SessionPlan.reasoning field with 2-4 sentences in plain \
English explaining today's choices. This text is shown verbatim to the \
parent on their dashboard, so write for a non-script-reading parent: \
'Today focused on short-vowel pairs because the kid has scored 90%+ on \
isolated vowels but missed both ఎ and ఏ when they appeared together \
yesterday.'
- Set fallback_used to false in your output.

Cold start: if get_recent_sessions returns an empty list, the kid is \
brand new. Plan a 5-step session of easy-difficulty foundational letters: \
pick the first 5 vowels from the curriculum and use easy distractor \
selection (3 distractors from a different category than each target \
vowel — i.e., consonants). Set the focus field to 'first session — vowel \
introduction'.

Output:
- A single SessionPlan matching the SessionPlan schema. No extra prose.
"""


# v1 — 2026-05-10 — first cut. revised 2026-05-11 — added single-glyph
# clarification to array fields after dashboard showed jammed pills.
# Prompt for the parent-dashboard English summary generator (Phase 5).
# One Gemma 4 call per dashboard load.
SESSION_SUMMARY_PROMPT_V1 = """\
You are writing the daily progress summary for a parent who speaks the \
mother tongue (Telugu or Hindi) fluently but cannot reliably read its \
script. They cannot verify their child's reading directly; this summary \
is how they understand what their child practiced and how it went.

Inputs you will receive:
- The session date, letters practiced, per-letter attempts and correct \
counts, and the planner's session-level reasoning.

Produce a SessionSummary matching the supplied schema:
- letters_practiced: every distinct letter character the kid saw today.
- strong_letters: letters answered correctly on the first attempt with no \
retries, or with >=80% accuracy across multiple attempts in the session.
- needs_practice: letters where the kid missed on first attempt or had \
<60% accuracy in the session.
- suggested_next: 2-4 letters or skill labels the parent could expect to \
see in tomorrow's session, given today's progress.

CRITICAL: Each entry in the letter arrays (letters_practiced, \
strong_letters, needs_practice, suggested_next) MUST be a single letter \
glyph. Do not include commas, quotation marks, spaces, or multiple \
glyphs in one entry. Each entry is one character at a time.

# revised 2026-05-11 (Phase 6) — concrete examples after Phase 5 dashboard regression
Examples to make the shape unambiguous:
  Correct:   "strong_letters": ["అ", "ఆ", "ఇ"]
  Incorrect: "strong_letters": ["అ, ఆ, ఇ"]      (three glyphs jammed into one entry)
  Incorrect: "strong_letters": ["\"అ\"", "\"ఆ\""]   (entries wrapped in embedded quotes)

- parent_summary_english: 2-4 sentences in warm, plain English. Tell the \
parent (a) what the kid practiced today in concrete terms, (b) what went \
well, (c) what needs reinforcement. Avoid jargon, percentages, and \
internal field names. Address the parent directly when natural ('Your \
daughter spent today on short vowels...').

Tone: warm, specific, encouraging without flattery. No emojis. No \
bullet points inside parent_summary_english — that field is prose.
"""


# v1 — 2026-05-10 — first cut. Trivial prompt for the structured-output
# smoke test (Phase 2 step 5 / "Gate 6"). Validates that Gemma 4 31B
# reliably uses the function-tool mechanism to return a typed LetterEntry.
LETTER_ENTRY_SMOKE_PROMPT_V1 = """\
Return a LetterEntry for the Telugu letter "ka" by calling the \
return_letter_entry tool exactly once. The character is క, the \
transliteration is "ka", and the language code is "te". Do not write \
any prose; respond only with the tool call.
"""

__all__ = [
    "LetterEntry",
    "LetterSet",
    "FeedbackVariants",
    "RecognitionStep",
    "SessionStep",
    "SessionPlan",
    "SessionSummary",
    "StepData",
    "Difficulty",
    "Language",
    "PLANNER_TOOLS",
    "PLANNER_PROMPT_V1",
    "SESSION_SUMMARY_PROMPT_V1",
    "LETTER_ENTRY_SMOKE_PROMPT_V1",
]
