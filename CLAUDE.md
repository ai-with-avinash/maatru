# CLAUDE.md — Maatru: Mother-Tongue Literacy Companion (post-pivot v2)

## Project Identity
**Name:** Maatru ("mother" in Sanskrit-derived Indic languages)
**One-line pitch:** A local-first AI companion that helps urban Indian 
English-medium kids learn to recognize and read their mother tongue, 
designed for parents who themselves can't read the script.
**Submission target:** Google Gemma 4 Challenge on dev.to — "Build with 
Gemma 4" track
**Deadline:** May 24, 2026, 11:59 PM PDT (≈ May 25, 12:30 PM IST)

## Project History (Why This Document Was Rewritten)
The original v1 design (2026-05-09) was built around a "kid writes the 
letter on paper, photographs, Gemma 4 evaluates" interaction. Day-1 
evaluations on 2026-05-10 showed Gemma 4's vision capability does not 
read Telugu script reliably (5% local accuracy, 20% cloud accuracy on a 
graduated handwriting eval, including failures on perfectly-rendered 
typed reference characters). See decisions.md entries dated 2026-05-10 
for the full data.

The product was pivoted to Option A: drop vision input, keep the 
literacy mission. The kid-facing interaction is now tap-to-recognize 
(audio cue, 4-option multiple choice). All remaining Gemma 4 
capabilities (multilingual text generation, function calling, 256K 
context, agentic planning) carry forward unchanged. Most existing 
infrastructure (model abstraction, eval harness, Telugu generation gate, 
project structure) reuses directly. This document reflects the pivoted 
v2 design.

## The Problem (Why This Exists, Unchanged)
Urban Indian families increasingly raise English-medium children who 
never learn to read or write their mother tongue. The parents themselves 
are fluent speakers but often non-fluent readers/writers of the script. 
Within one generation, script literacy disappears even when spoken 
fluency partially survives.

Generic language-learning apps assume a self-motivated adult learner or 
an involved literate teacher. They fail this specific user: a 5-8 year 
old whose parent cannot read what they are practicing.

## The User (Unchanged)
**Primary user:** Children aged 5-8 in urban Indian households, 
English-medium schooling, with parents who speak the mother tongue but 
cannot read/write it confidently.
**Secondary user (critical):** The parent — who needs to feel the kid is 
learning meaningfully without being able to verify it directly. The 
parent dashboard is in English and translates the kid's progress.
**Initial language:** Telugu.
**Generalization proof:** Hindi as a second language, demonstrated 
minimally if time permits.

## Why Gemma 4 (Revised after Gate 3 fail)
This project uses Gemma 4 because it specifically enables capabilities 
other models cannot match for this use case. The original design 
included vision-of-Indic-script as one such capability; Day-1 evals 
showed this is not currently reliable, so the design was revised to use 
Gemma 4 only where it genuinely shines:

1. **Multilingual text generation (140+ languages, Telugu confirmed via 
   Gate 2 PASS)** — Gemma 4 generates curriculum content directly: 
   letter sets, distractor options for multiple-choice exercises, simple 
   words, rhymes for read-aloud practice. No external translation layer.
2. **Native function calling** — used for structured outputs throughout: 
   curriculum generation returns `LetterSet`, kid feedback returns 
   `RecognitionFeedback`, parent dashboard returns `SessionSummary`, 
   planner returns `SessionPlan`. Reliable structured JSON without 
   prompt-engineering hacks.
3. **256K context** — entire curriculum + kid's session history + 
   current task all fit in a single context window. The agentic planner 
   reads full history in one call. No vector DB, no RAG. Architectural 
   simplification specifically enabled by Gemma 4's context size.
4. **Configurable thinking mode** — opt-in for the agentic session 
   planner where reasoning quality justifies the 3-5s latency at 
   session boundaries. Off by default for the kid-loop interactions 
   where speed matters.
5. **Open weights, local-capable** — while v1 ships with cloud-served 
   31B for quality, the architecture would let v2 swap to local-served 
   E4B for full offline use. Closed APIs cannot match this future-path 
   flexibility.

**What Gemma 4 is NOT used for in v1:** vision input on Indic scripts. 
This is documented as a tested-and-rejected approach, not a missing 
feature. The writeup will be honest about this finding.

A submission that uses Gemma 4 generically loses on the judging rubric. 
Every architectural decision should ladder back to one of the five 
points above.

## Architecture Philosophy (Unchanged in spirit; vision references removed)
This project deliberately splits its architecture into two layers with 
different design rules. Confusing the two is the most likely way to 
break the build.

**Layer 1 — Deterministic Kid Loop (the user-facing interaction).**
Every kid-facing interaction is a *single* model call (or zero, for 
pure-UI steps) with structured input and structured output. No 
reasoning loops. No multi-step agent behavior during the kid's practice 
session. The kid sees a letter, hears it, taps the matching option from 
4, gets feedback. Same rhythm, same shape, every time. This is 
non-negotiable.

Reasoning for Layer 1's strict determinism:
- The user is 5-8 years old. Pedagogically, early literacy practice 
  requires *consistency and ritual*, not adaptive cleverness during the 
  loop.
- Latency budget per interaction is sub-2-second on cloud Gemma 4 31B. 
  Multi-step reasoning loops break that budget.
- Predictability is debuggability. On demo day, the loop must work the 
  same way every time.

**Layer 2 — Adaptive Session Planner (the intelligence layer).**
At session boundaries (kid taps "Start practice today"), a single 
agentic call runs with tool access to the SQLite history. The planner 
uses thinking mode and function calling to reason over progress 
patterns, identify what the kid is ready for, and emit a structured 
`SessionPlan` that the deterministic Layer 1 then executes step by 
step.

Reasoning for Layer 2's agentic design:
- Latency is not user-facing in the same way — kid taps "Start" and 
  waits 3-5 seconds for the plan to load. Acceptable.
- Personalization compounds with interaction history, and the planner 
  is where Gemma 4's reasoning mode and function calling demonstrate 
  value the rubric rewards.
- The planner can decide higher-order things: "this kid has mastered 
  vowels, time to introduce 2-letter words" or "she's been struggling 
  with similar-sounding letters; today's session reinforces the 
  foundation." This is the adaptive tutor behavior — gated to session 
  boundaries where it belongs.

**The split is the architectural story for the writeup.** "Deterministic 
execution where consistency matters; agentic planning where reasoning 
matters." This is a deliberate, defensible design.

**Hard rules:**
- The kid loop NEVER calls the planner mid-session. Once the session 
  plan is loaded, execution is deterministic until the session ends.
- The planner NEVER renders UI or controls the kid loop directly. It 
  produces a structured `SessionPlan` and that's the end of its 
  responsibility.
- Tools available to the planner are SQLite reads only: 
  `get_recent_sessions`, `get_letter_accuracy`, `get_curriculum`. No 
  write tools. No external API calls. No multi-turn user interaction.
- If the planner fails (timeout, error, unparseable output), the system 
  falls back to a deterministic curriculum heuristic. The build never 
  blocks on the planner working.

## Model Strategy (Revised)
**Primary build target:** `google/gemma-4-31b-it:free` via OpenRouter 
(BYOK with personal Google AI Studio key). Cloud-only for v1 because 
local E4B latency on M4 16GB is unacceptable for kid-loop UX (Day-1 
evals showed 8-46s on text generation, 9-60s on structured outputs).

**Local deferred to v2.** The original local-first privacy story is 
retired in v1 — the kid-loop interactions don't include camera or 
microphone input by design, so the privacy-sensitive content (kid's 
photos, kid's voice) never exists in the first place. There is nothing 
sensitive flowing to the cloud beyond the kid's tap choices and 
session progress, which is comparable to any educational app.

**Abstraction:** All model calls go through the existing 
`query_gemma(prompt, image_path=None, model="cloud", thinking=False)` 
function in `app/model.py`. The `model="local"` path stays in the code 
as a v2 hook but is not used in v1 product flow. Eval harness can still 
exercise both for completeness if useful for the writeup's tradeoff 
section.

**Thinking mode:** off by default. Opt-in only for the agentic planner 
(Phase 5.5) where reasoning quality justifies latency.

## V1 Scope (What We Are Building, Pivoted)
**Core kid loop (Layer 1 — deterministic, tap-to-recognize):**
1. Kid taps "Start practice today." Session planner runs (Layer 2) and 
   loads today's session.
2. Kid sees a Telugu letter on screen with its English transliteration 
   below it.
3. Audio plays the letter pronunciation (Google Cloud TTS, Telugu voice).
4. Kid sees 4 options below the letter — one correct, three plausible 
   distractors generated by Gemma 4 from the curriculum. Kid taps the 
   one that matches what they heard.
5. Encouraging feedback: "Yes! That's అ" or "Try again — listen carefully 
   for the sound." Distractor logic encourages re-attempting once before 
   advancing.
6. Session continues through the steps the planner laid out, each step 
   rendered the same way.
7. Session ends with a celebration screen.

**Session planner (Layer 2 — agentic):**
- Runs once at session start. Reads recent session history via tool 
  calls.
- Decides today's session: which letters, distractor difficulty (close 
  vs. distinct), how many steps.
- Emits a structured `SessionPlan` that the kid loop executes step by 
  step.
- Falls back to deterministic curriculum heuristic if the planner fails.

**Parent dashboard (the differentiator, unchanged):**
- Login via simple PIN (no auth complexity).
- Today's session summary in English: letters practiced, accuracy, 
  patterns the kid is mastering or struggling with.
- Sample of letters where the kid succeeded vs. struggled, displayed 
  with English transliterations so non-Telugu-reading parents can 
  follow along.
- Suggested practice for tomorrow.
- The English-summary-of-Telugu-practice feature is the screenshot in 
  the submission. Must look polished.

**Generalization proof:** Same flow works for Hindi (Devanagari) by 
config change. Demonstrated briefly if Phase 6 has time.

## Non-Goals (V1 Will NOT Have)
- **Photo-feedback / handwriting recognition** — tested in Phase 1, 
  failed (Gate 3). Documented as a tested-and-rejected feature, not a 
  missing one. v2+ if model capability improves.
- **Voice input from kid** — read-aloud track is optional Phase 6 add. 
  Not in v1 critical path.
- **Local model serving for the kid loop** — cloud-only for v1 because 
  of E4B latency. v2+ if E4B improves or if user has GPU.
- Spaced repetition scheduling (planner uses recency + accuracy 
  heuristic).
- Multi-kid profiles (single user assumed).
- Curriculum beyond letters and 2-letter words (no full literacy 
  progression).
- Mobile native app (web UI on tablet/laptop is fine).
- Cloud sync, accounts, payments.
- Third language beyond Telugu + Hindi proof.
- Streak counters, leaderboards, gamification beyond session-end 
  celebration.
- Production-grade auth, rate limiting, error reporting.
- **Agentic behavior inside the kid loop** — the planner runs only at 
  session boundaries. The kid loop never calls the planner mid-session.
- **Write tools for the planner** — the planner reads history but does 
  not modify state. State changes happen through the deterministic kid 
  loop's normal flow.

When in doubt, cut scope. Depth over breadth. Demo > features.

## Tech Stack (Mostly Unchanged)
- **Language:** Python 3.11+ (running 3.13 in venv).
- **Model access:** OpenRouter, model ID `google/gemma-4-31b-it:free`, 
  BYOK via personal Google AI Studio key.
- **Local model serving (deferred):** Ollama + `gemma4:e4b`, kept in the 
  code abstraction as a v2 hook.
- **Backend:** FastAPI (lightweight, async, easy multipart for any 
  future audio uploads).
- **Frontend:** Plain HTML + minimal JavaScript, served from FastAPI. No 
  React/build tooling.
- **Storage:** SQLite for session history. Single file. No migrations 
  framework.
- **TTS:** Google Cloud TTS (te-IN-Standard-A or B), Gate 4 to validate 
  child-appropriate quality.
- **Package management:** `uv` (currently working with Python 3.13.9 
  venv).
- **Secrets:** `.env` file via `python-dotenv`. Never committed. 
  `.env.example` with placeholders is committed.

## Project Structure (Unchanged from original)
```
maatru/
├── CLAUDE.md                # This file (project context)
├── PLAN.md                  # Phased execution plan (revised post-pivot)
├── decisions.md             # Decision log (append-only)
├── README.md                # User-facing
├── .env.example             # Template for secrets
├── .gitignore
├── pyproject.toml           # uv-managed deps
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entrypoint
│   ├── model.py             # query_gemma() abstraction (cloud primary, local v2)
│   ├── prompts.py           # All prompt templates, versioned
│   ├── tts.py               # TTS wrapper
│   ├── session.py           # Session state, SQLite I/O
│   ├── curriculum.py        # Letter sets, ordering, fallback heuristic
│   ├── planner.py           # Layer 2: agentic session planner with tool-calling
│   └── parent.py            # Parent dashboard logic and English summaries
├── static/                  # HTML, CSS, JS for kid UI and parent dashboard
│   ├── kid.html
│   ├── parent.html
│   ├── style.css
│   └── app.js
├── eval/
│   ├── prompts/             # Eval prompt sets (telugu_generation.json, etc.)
│   ├── images/              # Handwriting samples (kept for the writeup's negative-result section)
│   ├── run_eval.py          # Runs evals against both local and cloud
│   ├── score_handwriting.py # Scorer (used for the Gate 3 fail data)
│   └── results/             # Eval outputs, comparison tables
├── data/
│   └── reference/           # Reference Telugu/Hindi character data (text, not images)
└── writeup/
    ├── draft.md             # dev.to submission draft
    └── assets/              # Demo video, screenshots, diagrams
```

## Working Conventions for Claude Code Sessions
1. **Read this file at the start of every session.** Confirm the 
   current phase from PLAN.md before writing code.
2. **One phase per session.** Do not jump ahead. If a phase is blocked, 
   document the blocker in decisions.md and stop.
3. **Vertical slices, not horizontal layers.** Build end-to-end thin 
   paths first. Refuse to scaffold "the whole model layer" or "the 
   whole UI" without an end-to-end working example.
4. **Use `/clear` between unrelated tasks.** Sessions over 90 minutes 
   degrade. Fresh sessions with sharp context > long stale sessions.
5. **Append to decisions.md, do not edit.** Every "we chose X because Y" 
   gets a dated entry.
6. **Run the eval suite after every model-related change.** 
   `python eval/run_eval.py <set>` should always succeed before 
   considering a change done.
7. **Do not make product decisions.** If a step requires one, stop and 
   route to the human.
8. **Keep abstractions minimal.** No more than 30 lines of switch logic 
   between local/cloud. If complexity grows, simplify by cutting one 
   path.
9. **No new dependencies without explicit approval.** Justify every 
   package added to `pyproject.toml` in decisions.md.
10. **The writeup is part of the deliverable.** When implementing a 
    feature, also note in `writeup/draft.md` what claim it supports.
11. **Test capability claims before integrating.** Lesson from the 
    Gate 3 fail: spec sheets are claims, not facts. Before sinking 
    days into a Gemma 4 capability (function calling, thinking mode, 
    256K context utility), run a small smoke test that tests the 
    specific use you plan to make of it.

## Day-1 Go/No-Go Gates (POST-Phase 1 STATUS)
- **Gate 1 (Ollama vision works):** PASSED on 2026-05-09. Now moot for 
  v1 since vision is dropped from the kid loop.
- **Gate 2 (Telugu generation acceptable):** PASSED on 2026-05-10. 
  ≥8/10 cloud outputs verified correct and age-appropriate by Telugu 
  reviewer. This gate is the critical one for the pivoted product 
  because curriculum and feedback content all depend on it.
- **Gate 3 (Telugu handwriting recognition):** FAILED on 2026-05-10. 
  Both models scored ≤20% across all tiers including typed reference. 
  Triggered the architectural pivot. See decisions.md for full data.
- **Gate 4 (TTS quality):** PENDING. Google Cloud TTS keys verified, 
  basic sample plays correctly. Phase 1 step 11 will validate 
  child-appropriate naturalness with a Telugu listener.
- **Gate 5 (OpenRouter free tier sufficient):** PARTIALLY VERIFIED. 
  BYOK with personal Google AI Studio key resolved the shared-pool 
  429s. Phase 1 step 10 will run the formal stress test for the 
  writeup's "tradeoffs" section.

## Current Phase
See PLAN.md (revised). Update this section after each phase completes:
- [x] Phase 0: Setup
- [~] Phase 1: Day-1 evals (Gates 1, 2 pass; Gate 3 fail triggered 
       pivot; Gates 4, 5 pending)
- [ ] Phase 2: Architecture and model abstraction (already partially 
       done; revisit for new schemas)
- [ ] Phase 3: Thin end-to-end slice (now: tap-to-recognize on one 
       letter)
- [ ] Phase 4: Practice loop deepening
- [ ] Phase 5: Parent dashboard
- [ ] Phase 5.5: Session planner (agentic Layer 2)
- [ ] Phase 6: Polish (read-aloud track if time, else cut Hindi)
- [ ] Phase 7: Writeup and demo video
- [ ] Phase 8: Hardening
- [ ] Phase 9: Submission

## Out-of-Scope Conversations
If the human asks about any of the following, redirect — these are 
settled or not for Claude Code to decide:
- Whether to retry photo-feedback with different prompts or models 
  (no, settled by Gate 3 data — see decisions.md 2026-05-10 entry).
- Whether to use Ollama or other local runtime for the kid loop (no, 
  cloud-only for v1).
- Which language to build for first (Telugu, decided).
- Whether to add a feature outside the V1 Scope list (no, by default).
- UX/UI strategic decisions ("should kids see a streak counter?") — 
  route to human.