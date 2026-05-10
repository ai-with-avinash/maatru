# The Problem

## Why Existing Solutions Fail

## Why Gemma 4

Maatru is built around four Gemma 4 capabilities that the eval suite
confirmed are real, plus one capability that the eval suite confirmed
is *not* real for this language and that the architecture now avoids.

**1. Multilingual text generation (Gate 2 PASS).** Gemma 4 generates
every piece of Telugu content the kid sees: distractor letters,
feedback phrases, 2-letter practice words, and the rhymes used in the
optional read-aloud track. A Telugu-literate reviewer rated 8 of 10
cloud generation outputs as correct and age-appropriate for 5-8 year
olds in the Day-1 evaluation
(`eval/results/telugu_generation_20260509T191017Z.json`). No curated
content database — the model produces Telugu output natively, with no
translation layer. The same path generalizes to Hindi via a one-field
config change.

**2. Native function calling with structured outputs (Gate 6 PASS).**
Phase 2's smoke test forced tool calls across two runs to
`google/gemma-4-31b-it:free` via OpenRouter; 8 of 8 model responses
returned valid tool calls and 8 of 8 parsed cleanly into a Pydantic
`LetterEntry`. Median latency was 3.5s, max 9.3s — within the 10s
planner budget. This makes the entire session planner possible:
`SessionPlan`, `RecognitionStep`, `FeedbackVariants`, and
`SessionSummary` all flow through function calling, so the JSON
contracts are guaranteed shape, not prompt-engineering luck.

**3. 256K context for stateless session reasoning.** The session
planner reads the kid's full curriculum, recent history, and
per-letter accuracy in a single call via three read-only SQLite
tools — no vector DB, no RAG. The 256K window makes that
simplification possible. It also lets the planner *bundle* every
step's distractors and feedback variants into its single response —
the architectural answer to Gate 5's stress test, which showed
OpenRouter's free tier hard-caps at 20 req/min with ~36% upstream
502s under sustained load. Even when calls succeed, p95 latency was
15.4 seconds — too slow for the kid's tap loop. Bundling collapses
a naïve ~14-call kid session into one planner call at session
start, plus zero model calls during the practice loop.

**4. Configurable thinking mode for the planner.** Thinking mode tells
Gemma 4 to spend extra reasoning tokens before answering — a hidden
scratchpad that improves multi-step decisions at the cost of a few
extra seconds. Maatru uses it in exactly one place: the agentic session
planner. The kid loop runs with it off: consistency and sub-second
responsiveness matter more than reasoning depth, and a 5-year-old
tapping a letter does not benefit from the model second-guessing
itself. The planner has to reason over recent attempts, identify
mastery patterns, and pair confusable letters deliberately — exactly
the kind of multi-step decision thinking mode exists for. The 3-5s
latency it pays is invisible to the kid — a single "Starting today's
practice…" screen before the first letter appears. Two layers, two
design rules, one model.

**What Gemma 4 is NOT used for in v1: Indic-script vision.** Day-1
Gate 3 evaluation showed Gemma 4 reads Telugu handwriting at 5%
local accuracy and 20% cloud accuracy, including 20% on
perfectly-rendered typed reference characters. This is a model
training-data gap, not an engineering bug. The product was
redesigned around it; the writeup is honest about it; v2 will
revisit when the capability catches up.

## What I Built

## How It Works

## Demo

## Tradeoffs and Decisions

**Open weights as a v2 path, not a v1 claim.** Gemma 4 ships with open
weights, which would in principle let Maatru run end-to-end on the
user's own machine for full offline privacy. v1 does not use this:
Day-1 evals showed local E4B latency on a 16GB M4 is unworkable for
the kid loop (8-46s text generation, structured outputs frequently
hit the 60s timeout). v1 ships cloud-only via OpenRouter. The
open-weights story is the right v2 direction once consumer hardware
catches up to E4B's compute needs, and no closed API can match that
future flexibility — but it is not a v1 capability and the writeup
does not claim it as one.

## What's Next
