# CLAUDE.md — Maatru: Mother-Tongue Literacy Companion

## Project Identity
**Name:** Maatru (working title — "mother" in Sanskrit-derived Indic languages)
**One-line pitch:** A local-first AI companion that helps urban Indian English-medium kids learn to read and write their mother tongue, designed for parents who themselves can't read the script.
**Submission target:** Google Gemma 4 Challenge on dev.to — "Build with Gemma 4" track
**Deadline:** May 24, 2026, 11:59 PM PDT (≈ May 25, 12:30 PM IST)
**Days remaining at project start:** 15

## The Problem (Why This Exists)
Urban Indian families increasingly raise English-medium children who never learn to read or write their mother tongue. The parents themselves are fluent speakers but often non-fluent readers/writers of the script — they can speak Telugu/Hindi/Tamil with their kids but cannot teach them the script, cannot check homework in the script, cannot pick suitable practice material. Within one generation, script literacy disappears even when spoken fluency partially survives.

Generic language-learning apps assume a self-motivated adult learner or an involved literate teacher. They fail this specific user: a 5-8 year old whose parent cannot read what they are practicing.

## The User
**Primary user:** Children aged 5-8 in urban Indian households, English-medium schooling, with parents who speak the mother tongue but cannot read/write it confidently.
**Secondary user (critical):** The parent — who needs to feel the kid is learning meaningfully without being able to verify it directly. The parent dashboard is in English and translates the kid's progress.
**Initial language:** Telugu (Hyderabad context, builder's mother tongue, authentic problem authorship).
**Generalization proof:** Hindi as a second language, demonstrated minimally to show the architecture is language-agnostic.

## Why Gemma 4 Specifically
This project uses Gemma 4 because it specifically enables capabilities other models cannot match for this use case:
1. **Native multimodality** — image input means the kid can write on paper, photograph, get feedback. No external OCR pipeline.
2. **Multilingual coverage (140+ languages)** — Indic script generation and reading in the same model, no separate translation layer.
3. **Open weights, local deployment** — kids' photos and voice never leave the device. The privacy story is the differentiator that closed APIs cannot match.
4. **256K context** — entire curriculum, kid's session history, recent attempts all fit in a single context window. No vector DB, no RAG infrastructure needed. Architectural simplification.
5. **E4B variant runs on edge** — story extends to "this works on a parent's phone or a Raspberry Pi 5," which is real because E4B is real.
6. **Native function calling** — used for structured outputs (letter identification with confidence, parent dashboard summaries, next-session suggestions).
7. **Configurable thinking mode** — opt-in for harder cases like ambiguous handwriting; off by default for fast UX.

A submission that uses Gemma 4 generically (could-have-been-any-LLM) loses on the judging rubric. Every architectural decision should ladder back to one of the seven points above.

## Architecture Philosophy (Read Before Writing Any Code)
This project deliberately splits its architecture into two layers with different design rules. Confusing the two is the most likely way to break the build.

**Layer 1 — Deterministic Kid Loop (the user-facing interaction).**
Every kid-facing interaction is a *single* model call with structured input and structured output. No reasoning loops. No multi-step agent behavior. No autonomous tool selection during the kid's practice session. The kid sees a letter, hears it, writes, photographs, gets feedback. Same rhythm, same shape, every time. This is non-negotiable.

Reasoning for Layer 1's strict determinism:
- The user is 5-8 years old. Pedagogically, early literacy practice requires *consistency and ritual*, not adaptive cleverness during the loop.
- Latency budget is sub-second per interaction on E4B local. Multi-step reasoning loops break that budget and force a fall back to cloud, which kills the privacy story.
- Predictability is debuggability. On demo day, the loop must work the same way every time.

**Layer 2 — Adaptive Session Planner (the intelligence layer).**
At session boundaries (kid taps "Start practice today"), a single agentic call runs with tool access to the SQLite history. The planner uses thinking mode and function calling to reason over progress patterns, identify what the kid is ready for, and emit a structured `SessionPlan` that the deterministic Layer 1 then executes step by step.

Reasoning for Layer 2's agentic design:
- Latency is not user-facing in the same way — kid taps "Start" and waits 3-5 seconds for the plan to load. Acceptable.
- Personalization compounds with interaction history, and the planner is where Gemma 4's reasoning mode and function calling demonstrate value the rubric rewards.
- The planner can decide higher-order things: "this kid has mastered vowels, time to introduce 2-letter words" or "she's been struggling with conjuncts; today's session reinforces the foundation rather than advancing." This is the adaptive tutor behavior — gated to session boundaries where it belongs.
- The planner can introduce new exercise types as it sees fit: letter recognition, word reading, short-rhyme reading, pronunciation evaluation. The kid loop renders whatever the planner asks for.

**The split is the architectural story for the writeup.** "Deterministic execution where consistency matters; agentic planning where reasoning matters." This is a deliberate, defensible design — judges who understand the space will recognize it as judgment rather than capability theater.

**Hard rules that follow from this split:**
- The kid loop NEVER calls the planner mid-session. Once the session plan is loaded, execution is deterministic until the session ends.
- The planner NEVER renders UI or controls the kid loop directly. It produces a structured `SessionPlan` and that's the end of its responsibility.
- Tools available to the planner are SQLite reads only: `get_recent_sessions`, `get_letter_accuracy`, `get_curriculum`. No write tools. No external API calls. No multi-turn user interaction.
- If the planner fails (timeout, error, unparseable output), the system falls back to the deterministic curriculum heuristic. The build never blocks on the planner working.

## Model Strategy
**Primary build target:** `gemma4:e4b` running locally via Ollama on M4 MacBook Air 16GB.
**Comparison/eval reference:** `google/gemma-4-31b-it:free` via OpenRouter (262K context, multimodal, free tier, 3s latency, 24 tps).
**Abstraction:** All model calls go through a single `query_gemma(prompt, image_path=None, model="local")` function. `model="local"` hits Ollama at `http://localhost:11434/v1`, `model="cloud"` hits OpenRouter. Both use OpenAI-compatible endpoints with identical request shape.

**Why hybrid:**
- E4B local powers the demo (sub-second responses, no network, privacy story intact).
- 31B cloud generates the comparison numbers in the writeup ("E4B achieved X% on Telugu handwriting; 31B achieved Y% at the cost of 3s+ latency unsuitable for child UX").
- Evidence-backed model selection is what the judging rubric explicitly rewards.

**Thinking mode:** off by default. Opt-in only for ambiguous handwriting recognition cases. Document each call site that uses it.

## Hardware Constraints
- MacBook Air M4, 16GB unified memory, macOS Sequoia 15.5
- Ollama serving E4B (~6-7GB runtime). Ceiling above this risks swap on demo day.
- Do not pull Gemma 4 12B/27B for runtime. 31B comparison happens via cloud only.
- Memory pressure must stay green during demo recording.

## V1 Scope (What We Are Building)
**Core kid loop (Layer 1 — deterministic):**
1. Kid sees a Telugu letter on screen, hears it pronounced (TTS).
2. Kid writes the letter on paper, photographs with device camera or upload.
3. Gemma 4 evaluates the photo, gives encouraging feedback ("Looks great!" / "Try the curve here").
4. Session continues through the steps the planner laid out, each step rendered the same way.
5. Session ends with a celebration screen.

**Session planner (Layer 2 — agentic):**
- Runs once at session start. Reads recent session history via tool calls.
- Decides today's session: which letters, whether to introduce new step types (word reading, rhyme reading), how many steps, difficulty level.
- Emits a structured `SessionPlan` that the kid loop executes step by step.
- Falls back to deterministic curriculum heuristic if the planner fails.

**Parent dashboard (the differentiator):**
- Login via simple PIN (no auth complexity).
- Today's session summary in English: letters practiced, model's assessment, sample of kid's writing.
- Suggested practice for tomorrow.
- This is the screenshot that goes in the submission post. Must look polished.

**Generalization proof:** Same flow works for Hindi (Devanagari) by config change. Demonstrated briefly in submission.

## Non-Goals (V1 Will NOT Have)
- Spaced repetition scheduling (planner uses simpler reasoning over recent history).
- Multi-kid profiles (single user assumed).
- Curriculum beyond letters, 2-3 letter words, and short rhymes (no full literacy progression).
- Mobile native app (web UI on tablet/laptop is fine).
- Cloud sync, accounts, payments.
- Third language beyond Telugu + Hindi proof.
- Streak counters, leaderboards, gamification beyond session-end celebration.
- Voice input from kid for the writing loop (output audio only; input is photo or button). Voice input is acceptable for the rhyme-reading step type if the planner introduces it.
- Production-grade auth, rate limiting, error reporting.
- **Agentic behavior inside the kid loop** — the planner runs only at session boundaries. The kid loop never calls the planner mid-session.
- **Write tools for the planner** — the planner reads history but does not modify state. State changes happen through the deterministic kid loop's normal flow.

When in doubt, cut scope. Depth over breadth. Demo > features.

## Tech Stack
- **Language:** Python 3.11+ (matches OCR framework conventions, fastest path).
- **Model serving (local):** Ollama with `gemma4:e4b`, OpenAI-compatible endpoint.
- **Model access (cloud):** OpenRouter, model ID `google/gemma-4-31b-it:free`.
- **Backend:** FastAPI (lightweight, async, easy multipart for image uploads).
- **Frontend:** Plain HTML + minimal JavaScript, served from FastAPI. No React/build tooling. Speed to ship over engineering elegance.
- **Storage:** SQLite for session history. Single file. No migrations framework.
- **TTS:** Decision pending Day 1 eval. Candidates: Google Cloud TTS (Telugu), AI4Bharat IndicTTS, ElevenLabs (fallback if Indic quality elsewhere fails).
- **Package management:** `uv` (faster than pip, single-file lockfile, M-series friendly). Standard `venv` if `uv` unavailable.
- **Secrets:** `.env` file via `python-dotenv`. Never committed. `.env.example` with placeholders is committed.

## Project Structure
```
maatru/
├── CLAUDE.md                # This file (project context)
├── PLAN.md                  # Phased execution plan
├── decisions.md             # Decision log (append-only)
├── README.md                # User-facing
├── .env.example             # Template for secrets
├── .gitignore
├── pyproject.toml           # uv-managed deps
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entrypoint
│   ├── model.py             # query_gemma() abstraction (local + cloud)
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
│   ├── prompts/             # Eval prompt sets (telugu_gen.json, etc.)
│   ├── images/              # Handwriting samples for eval
│   ├── run_eval.py          # Runs evals against both local and cloud
│   └── results/             # Eval outputs, comparison tables
├── data/
│   ├── reference/           # Reference Telugu/Hindi character images
│   └── samples/             # Test photos for development
└── writeup/
    ├── draft.md             # dev.to submission draft (start Day 1)
    └── assets/              # Demo video, screenshots, diagrams
```

## Working Conventions for Claude Code Sessions
1. **Read this file at the start of every session.** Confirm the current phase from PLAN.md before writing code.
2. **One phase per session.** Do not jump ahead. If a phase is blocked, document the blocker in decisions.md and stop.
3. **Vertical slices, not horizontal layers.** Build end-to-end thin paths first. Refuse to scaffold "the whole model layer" or "the whole UI" without an end-to-end working example.
4. **Use `/clear` between unrelated tasks.** Sessions over 90 minutes degrade. Fresh sessions with sharp context > long stale sessions.
5. **Append to decisions.md, do not edit.** Every "we chose X because Y" gets a dated entry. This stops re-litigation across sessions.
6. **Run the eval suite after every model-related change.** `python eval/run_eval.py` should always pass before considering a change done.
7. **Do not make product decisions.** If asked "should the dashboard be in English?" — refuse, route the question to the human. Execution decisions only.
8. **Keep abstractions minimal.** No more than 30 lines of switch logic between local/cloud. If complexity grows, simplify by cutting one path.
9. **No new dependencies without explicit approval.** Justify every package added to `pyproject.toml` in decisions.md.
10. **The writeup is part of the deliverable.** When implementing a feature, also note in `writeup/draft.md` what claim it supports.

## Day-1 Go/No-Go Gates (Must Pass Before Building)
These are the conditions under which the v1 plan above is viable. If any fail, stop and consult the human before proceeding.

**Gate 1: Ollama vision works.**
- Test: `ollama run gemma4:e4b "describe this image" /path/to/test.jpg` returns coherent description.
- Pass: vision pipeline functional.
- Fail: investigate Ollama version (need 0.5+); fallback to MLX or HuggingFace transformers.

**Gate 2: Telugu generation acceptable.**
- Test: 10 prompts asking for Telugu letters, words, simple sentences for ages 5-8.
- Acceptance: ≥8/10 outputs verified correct and age-appropriate by Telugu-literate human.
- Fail (≤5/10): pivot to curated word list, model used only for feedback and audio narration. Update CLAUDE.md scope.
- Ambiguous (6-7/10): run 10 more prompts, retest.

**Gate 3: Telugu handwriting recognition acceptable.**
- Test: 20 photographed Telugu characters (5 typed reference, 5 adult clean handwriting, 5 child-style sloppy, 5 visually similar pairs).
- Acceptance — clear samples (typed + adult): ≥80% correct.
- Acceptance — child samples: ≥60% correct (but failing here triggers reframe, not pivot).
- Fail clear samples: photo-feedback feature is dead. Pivot to audio-only practice loop.
- Fail only child samples: reframe handwriting feedback as "encouragement and reference" not "strict grader."

**Gate 4: TTS quality acceptable.**
- Test: 3 Telugu sentences via Google Cloud TTS Telugu and AI4Bharat IndicTTS, listened by Telugu-fluent human.
- Acceptance: at least one option sounds natural enough for repeated child listening.
- Fail both: text-and-image-only build, audio as v2.

**Gate 5: OpenRouter free tier sufficient for dev.**
- Test: 50 sequential requests to `google/gemma-4-31b-it:free` over 3 minutes.
- Acceptance: no 429 errors, completes successfully.
- Fail: switch to Google AI Studio direct (Gemini API), or budget $5-10 for paid OpenRouter usage.

## Current Phase
See PLAN.md. Update this section after each phase completes:
- [ ] Phase 0: Setup
- [ ] Phase 1: Day-1 evals and gates
- [ ] Phase 2: Architecture and model abstraction
- [ ] Phase 3: Thin end-to-end slice
- [ ] Phase 4: Practice loop deepening
- [ ] Phase 5: Parent dashboard
- [ ] Phase 5.5: Session planner (agentic Layer 2)
- [ ] Phase 6: Polish (Hindi cut if behind schedule)
- [ ] Phase 7: Writeup and demo video
- [ ] Phase 8: Hardening
- [ ] Phase 9: Submission

## Out-of-Scope Conversations
If the human asks about any of the following, redirect — these are settled or not for Claude Code to decide:
- Which language to build for first (Telugu, decided).
- Whether to use Ollama or other local runtime (Ollama, decided unless Gate 1 fails).
- Whether to add a feature outside the V1 Scope list (no, by default; document in decisions.md if reconsidered).
- UX/UI strategic decisions ("should kids see a streak counter?") — route to human.
