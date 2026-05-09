# PLAN.md — Maatru Execution Plan (15 Days)

**How to use this file:** Give Claude Code one phase at a time. Paste the phase block as a session opener along with a reminder to read CLAUDE.md first. Do not paste the whole plan in one session — Claude Code will try to scaffold too far ahead.

**Standard session opener:**
> Read CLAUDE.md and decisions.md first. We are starting Phase N. Here is the phase: [paste phase block]. Confirm you understand the scope and the explicit non-goals, then proceed step by step. Stop and ask if any step requires a product decision.

---

## Phase 0: Project Setup (1-2 hours, Day 1 morning)

**Goal:** Repo, environment, dependencies, secrets, no product code yet.

**Steps:**
1. Create project directory `maatru/` and initialize a git repo. Add `.gitignore` covering `.venv`, `.env`, `__pycache__`, `*.db`, `eval/results/`, `writeup/assets/raw/`, `data/samples/private/`.
2. Create `pyproject.toml` using `uv init`. If `uv` is unavailable, fall back to `python -m venv .venv` and a `requirements.txt`.
3. Add initial dependencies: `fastapi`, `uvicorn`, `python-dotenv`, `httpx`, `pillow`, `pydantic`, `python-multipart`. Install via `uv add ...` or `pip install`.
4. Create the directory structure exactly as specified in CLAUDE.md under "Project Structure." All `__init__.py` files empty. All other `.py` files contain only a module-level docstring describing purpose.
5. Create `.env.example` with the keys: `OPENROUTER_API_KEY=`, `OLLAMA_BASE_URL=http://localhost:11434/v1`, `MODEL_LOCAL=gemma4:e4b`, `MODEL_CLOUD=google/gemma-4-31b-it:free`, `TTS_PROVIDER=`, `GOOGLE_TTS_API_KEY=`. Copy to `.env` (which is gitignored) for the human to fill in.
6. Create `decisions.md` with a header, an empty entry template, and the first entry: today's date, "Project initialized. Stack: Python 3.11, FastAPI, Ollama (E4B local) + OpenRouter (31B cloud), SQLite, plain HTML frontend."
7. Create `writeup/draft.md` with section headers only: `# The Problem`, `## Why Existing Solutions Fail`, `## Why Gemma 4`, `## What I Built`, `## How It Works`, `## Demo`, `## Tradeoffs and Decisions`, `## What's Next`. No content yet.
8. Verify the FastAPI app boots: a single `app/main.py` with one endpoint `GET /healthz` returning `{"status": "ok"}`. Run `uvicorn app.main:app --reload` and confirm 200 response on localhost.

**Acceptance:** `uvicorn` runs without errors. `git status` clean except for tracked files. `.env` exists with placeholders, `.env.example` is committed. `decisions.md` has one entry.

**Human-side action items (parallel to Claude Code work):**
- Sign up at openrouter.ai, create an API key, paste into `.env`.
- Verify Ollama version: `ollama --version` should be 0.5+. Update if older.
- Confirm `gemma4:e4b` is pulled: `ollama list`.

---

## Phase 1: Day-1 Evals and Go/No-Go Gates (3-4 hours, Day 1 afternoon)

**Goal:** Run all 5 gates from CLAUDE.md. Get pass/fail decisions before any product code.

**Steps:**
1. Implement `app/model.py` with the `query_gemma(prompt, image_path=None, model="local", thinking=False)` function. Both branches (local Ollama, cloud OpenRouter) use OpenAI-compatible chat completions endpoint. Image is base64-encoded into the message content per the OpenAI vision format. Handle errors and timeouts gracefully — return a structured error object, do not raise. **Hard limit: 60 lines of code total. If it grows beyond that, you are over-engineering.**
2. Write `eval/run_eval.py` that takes a prompt set name, runs each prompt against both local and cloud, saves outputs to `eval/results/<set_name>_<timestamp>.json`. Output schema: `{prompt_id, prompt_text, image_path, local_response, cloud_response, local_latency_ms, cloud_latency_ms, error}`.
3. Create `eval/prompts/telugu_generation.json` with 10 prompts:
   - "Generate the Telugu vowel అ. Provide its English transliteration and a sample word."
   - "Write a 3-word Telugu sentence a 6-year-old can understand. Provide transliteration and English translation."
   - "List the first 5 Telugu vowels with English transliterations."
   - "Translate 'the cat is sleeping' into Telugu using Telugu script. Provide transliteration."
   - "Generate 5 simple two-letter Telugu words suitable for early readers (ages 5-7). Provide transliterations."
   - "What is the Telugu word for 'mother'? Provide the script form, transliteration, and one example sentence."
   - "Generate a 4-line Telugu rhyme suitable for a 5-year-old. Provide transliteration."
   - "List 3 Telugu words that start with the letter క. Include transliteration and English meaning."
   - "Write the Telugu numbers 1 through 5 in script. Provide their names in transliteration."
   - "Translate the question 'what is your name?' into Telugu in script and transliteration."
4. Run the generation eval: `python eval/run_eval.py telugu_generation`. Save results.
5. **STOP HERE for human review.** Generation eval results need a Telugu-literate human to verify before proceeding. Do not run the handwriting eval until generation passes.
6. Once generation passes (human signoff in decisions.md), capture handwriting samples. Human action: print/handwrite the 20-character set, photograph in normal indoor lighting, save to `eval/images/handwriting/`. Naming convention: `<character>_<source>_<index>.jpg` where source is one of `typed`, `adult`, `child`, `similar`.
7. Create `eval/prompts/telugu_handwriting.json` with 20 entries each referencing one of the photographed images. The prompt for each: "This image shows a single Telugu character. Identify which Telugu character it is. Respond as JSON: {\"character\": \"<the character>\", \"transliteration\": \"<roman>\", \"confidence\": \"high|medium|low\"}."
8. Run handwriting eval: `python eval/run_eval.py telugu_handwriting`. Save results.
9. Score the handwriting eval: write a small `eval/score_handwriting.py` that reads the results, compares the model's `character` field against the expected character (encoded in the filename), and outputs accuracy split by source (typed, adult, child, similar). Print to console and save markdown table to `eval/results/handwriting_scorecard.md`.
10. Run the OpenRouter rate-limit stress test: a 30-line script that fires 50 simple text requests to the cloud model in a loop, prints any 429s or other errors, reports total time and requests-per-minute achieved. Save output to `eval/results/openrouter_ratelimit.txt`.
11. Append all four eval results (generation pass/fail, handwriting scorecard, rate-limit findings, TTS — pending) to `decisions.md` with the date, the gate name, the result, and the implication for the build.

**Acceptance:** Gates 1, 2, 3, 5 from CLAUDE.md have documented pass/fail status in `decisions.md`. Gate 4 (TTS) is human-side and may run in parallel.

**If any gate fails:** stop and route to human. Update CLAUDE.md scope section with the pivot decision before proceeding to Phase 2.

---

## Phase 2: Architecture and Model Abstraction (Day 2)

**Goal:** Solidify the layer between the app and Gemma 4. Add structured outputs via function calling. Write the "Why Gemma 4" section of the writeup.

**Steps:**
1. Extend `app/model.py` to support structured outputs via function calling. Add a parameter `response_schema` to `query_gemma`. When provided, the function should request structured JSON from the model and validate the response against the schema using Pydantic.
2. Define core Pydantic schemas in `app/prompts.py`:
   - `LetterIdentification(character: str, transliteration: str, confidence: Literal["high", "medium", "low"], notes: str)`
   - `HandwritingFeedback(recognized: bool, character_seen: Optional[str], encouragement: str, specific_tip: Optional[str])`
   - `SessionSummary(letters_practiced: list[str], strong_letters: list[str], needs_practice: list[str], suggested_next: list[str], parent_summary_english: str)`
   - `SessionStep(step_type: Literal["letter_practice", "word_reading", "rhyme_reading"], content: str, transliteration: str, target_skill: str, expected_difficulty: Literal["easy", "medium", "hard"])`
   - `SessionPlan(session_id: str, language: str, focus: str, steps: list[SessionStep], reasoning: str, fallback_used: bool)`
3. Define the planner's tool schemas (also in `app/prompts.py`). These are the OpenAI-compatible function definitions the agentic planner will use:
   - `get_recent_sessions(n: int)` — returns a list of recent session summaries with letters practiced and accuracy.
   - `get_letter_accuracy(letters: list[str])` — returns per-letter attempt counts and accuracy from history.
   - `get_curriculum(language: str, scope: Literal["letters", "words", "rhymes"])` — returns the curriculum entries available for that scope.
   These tools read from SQLite only. No write capability. No external calls.
3. Define versioned prompt templates in `app/prompts.py` as Python constants. Include version comment on each. Examples: `LETTER_FEEDBACK_PROMPT_V1`, `SESSION_SUMMARY_PROMPT_V1`. When the human revises a prompt, increment the version. Old versions stay in the file commented out for reference.
4. Write a small CLI test harness `app/dev_cli.py` that lets the human invoke `query_gemma` from the command line: `python -m app.dev_cli letter_feedback --image path/to/image.jpg --target అ`. Useful for quick debugging without running the full app.
5. Update `writeup/draft.md` "Why Gemma 4" section. Cite specific capabilities being used: multimodal vision, multilingual generation, function calling for structured outputs, 256K context for session history, E4B for local edge deployment. Tie each to a specific file or feature in the codebase. **This section is updated continuously through the project — start it here and revise as the build evolves.**
6. Append to `decisions.md`: prompt versioning convention, schema design choices, any deviations from the plan.

**Acceptance:** `python -m app.dev_cli` works for basic letter identification. Schemas defined. Writeup draft has a real "Why Gemma 4" section with specific references.

---

## Phase 3: Thin End-to-End Slice (Day 3)

**Goal:** Working kid loop on one letter. Ugly, hardcoded, end-to-end. This is the day you prove the product is possible.

**Steps:**
1. Hardcode the target letter as అ in this phase. No curriculum logic yet.
2. Implement `static/kid.html`: a single page that displays the letter అ in large font, a button "Hear it" that calls a backend endpoint to play TTS, a file input or webcam capture for photo upload, a "Check my writing" button that submits the photo, and a result area that displays the model's feedback.
3. Implement backend endpoints:
   - `GET /` — serves `kid.html`.
   - `POST /api/pronounce` — body `{character: "అ"}`, returns audio bytes from TTS provider.
   - `POST /api/check` — multipart form with image file and target character, calls `query_gemma` with the `HandwritingFeedback` schema, returns the feedback as JSON.
4. Implement `app/tts.py` with a single `synthesize(text: str, language: str) -> bytes` function. Use the TTS provider chosen in Phase 1 Gate 4. If TTS gate failed, this returns a placeholder beep and the human is alerted.
5. Wire the frontend: vanilla JS for fetch calls, no framework. Display the model's `encouragement` and `specific_tip` fields directly. Use simple CSS — large readable fonts, kid-friendly colors, no animations yet.
6. Test the loop yourself: open browser, see అ, hear pronunciation, photograph a hand-drawn అ, submit, see feedback. Iterate until this loop works end-to-end without manual intervention.
7. Append to `decisions.md`: TTS provider chosen, any frontend simplifications.

**Acceptance:** End-to-end loop works in browser. From letter display to feedback display, no manual steps. Time per round-trip should be under 5 seconds with E4B local.

**Critical:** if you cannot get the loop working by end of day 3, the project is in trouble. Stop and simplify ruthlessly. Cut TTS, cut feedback richness, cut everything except "show letter, accept photo, return one-word verdict." Make the loop work, then add back.

---

## Phase 4: Practice Loop Deepening (Days 4-6)

**Goal:** Full Telugu vowel set, basic curriculum, session structure, simple progress tracking.

**Steps:**
1. Define the Telugu curriculum in `app/curriculum.py`: a list of letter sets in order — vowels (16 chars), then consonants in pedagogical order. Each entry has the character, transliteration, English example word, and a difficulty rank.
2. Implement `app/session.py`: SQLite schema with tables `sessions`, `attempts`. Functions to start a session, record an attempt with letter and model feedback, end a session with summary stats. Session ID is a UUID.
3. Replace the hardcoded letter in the kid loop with curriculum-driven selection: at session start, pick 5-7 letters using a "least practiced" heuristic — letters never attempted come first, then letters with the lowest recent accuracy. Store the session plan in the session record. **This deterministic heuristic is also the fallback path for Phase 5.5's planner — when the planner fails or isn't ready, the system uses this logic.**
4. Add session navigation in the UI: progress indicator ("Letter 2 of 5"), "Next letter" button after feedback, session-end screen with simple message ("Great job! You practiced 5 letters today.").
5. After each attempt, store the model's feedback verbatim in SQLite. This becomes the data source for the parent dashboard.
6. Test the loop on your own kids if available. Watch where they get confused or bored. Note observations in `decisions.md` — these inform Phase 6 polish.
7. Update `writeup/draft.md` "What I Built" section with the curriculum and session structure described.

**Acceptance:** Full session of 5+ letters runs end to end. Progress is persisted across sessions. Curriculum picks sensibly different letters in subsequent sessions.

**Risk to watch:** scope creep. Resist adding spaced repetition, difficulty progression, multi-session arcs. Keep it to "least-practiced first" heuristic.

---

## Phase 5: Parent Dashboard (Days 7-8)

**Goal:** The differentiator. English summaries of Telugu practice. Polished enough to screenshot for the submission.

**Steps:**
1. Add a parent PIN to `.env` (e.g., `PARENT_PIN=4242`). On the parent route, prompt for PIN, store in session cookie. No real auth — this is a single-family demo.
2. Implement `app/parent.py` with functions:
   - `get_today_summary(date)` — reads sessions and attempts from SQLite for the given date, builds a structured summary.
   - `generate_english_summary(session_data) -> str` — calls `query_gemma` with `SessionSummary` schema and a prompt that takes the structured session data and produces an English summary written for a parent who doesn't read Telugu. The 256K context lets you pass the full session history into one call.
3. Implement `static/parent.html`: dashboard view with today's session count, list of letters practiced (showing the Telugu character + English transliteration), the model's English summary in a prominent card, a sample of 2-3 of the kid's actual photographed attempts shown small with the model's feedback, and "Suggested for tomorrow" section.
4. Endpoint `GET /parent/today` — returns the dashboard data as JSON. Endpoint `GET /parent` — serves `parent.html`.
5. Polish: this is the screenshot in the submission. Spend time on layout, typography, color. Look at well-designed parent-app dashboards for inspiration but do not copy. Keep it clean and warm, not corporate.
6. Add a "share with family" button that does nothing functionally but is visible — it sells the social vision in the demo without requiring implementation.
7. Update `writeup/draft.md` "What I Built" with parent dashboard prominently. Plan the screenshot now.

**Acceptance:** Parent dashboard loads, shows today's data, English summary reads naturally, sample images display correctly. The page is presentable in a screenshot.

---

## Phase 5.5: Session Planner — Agentic Layer 2 (Days 8-9, 1.5-2 days)

**Goal:** Build the agentic session planner. This is the architectural differentiator. Adaptive personalization at session boundaries, not during the kid loop.

**Read this first:** Re-read the "Architecture Philosophy" section in CLAUDE.md before starting. The planner is intentionally constrained — it runs once at session start, has read-only tools, emits a structured `SessionPlan`, and never reaches into the kid loop. Violating any of these rules breaks the architecture.

**Steps:**
1. Implement `app/planner.py` with the function `plan_session(kid_id: str, language: str, force_fallback: bool = False) -> SessionPlan`. When `force_fallback` is True, skip the agentic call and use the deterministic curriculum heuristic (this is the demo-day safety net).
2. The planner makes **a single call** to `query_gemma` with thinking mode enabled, function calling enabled, and the three tool definitions from Phase 2 (`get_recent_sessions`, `get_letter_accuracy`, `get_curriculum`). Use the cloud model `google/gemma-4-31b-it:free` for the planner specifically — its reasoning quality is meaningfully better here, latency is acceptable at session boundaries (3-5s), and the comparison numbers between local and cloud reasoning go into the writeup. The kid loop still uses local E4B.
3. Implement the three tools as Python functions that read from SQLite. Each returns a Pydantic-validated structure that the model receives as tool output. **Tools are pure read functions. Verify this in code review.**
4. Write the planner's system prompt (`PLANNER_PROMPT_V1` in `app/prompts.py`). The prompt establishes: the model is a session planner for an early-literacy app; the user is a 5-8 year old; consistency matters more than novelty; introduce new step types (word reading, rhyme reading) only when prerequisite letters are mastered (mastery threshold: 80%+ accuracy across 3+ attempts); keep total session length to 5-8 steps. The prompt should make the model justify its plan in the `reasoning` field.
5. Build a 5-call eval for the planner: 5 fake session histories representing different kid states (brand new, vowels-strong-consonants-weak, ready-for-words, struggling-with-conjuncts, advanced-rhyme-ready). For each, run the planner and verify the output `SessionPlan` matches what a literacy expert would suggest. Save to `eval/results/planner_scorecard.md`. This is also writeup material.
6. Wire the planner into `/api/session/start`: when the kid taps "Start practice today," the backend calls `plan_session()`. If the call succeeds, the returned `SessionPlan` becomes the session's step list. If it fails (timeout > 10s, JSON parse error, schema validation error, tool error), log the failure and call again with `force_fallback=True` to use the deterministic heuristic. The kid never sees the failure.
7. Update `static/kid.html` to render whatever step type the planner returns:
   - `letter_practice`: existing flow (display letter, audio, photo, feedback).
   - `word_reading`: display 2-3 letter Telugu word, kid reads aloud, mic captures audio, send to Gemma 4 for pronunciation evaluation, return encouraging feedback. **If audio input from kid is too complex to ship reliably in remaining time, fall back to "kid taps 'I read it' button after reading aloud" — judges still see the new step type without the speech recognition risk.**
   - `rhyme_reading`: display 2-line Telugu rhyme with transliteration, audio plays the rhyme once, kid reads aloud, same evaluation path as word_reading.
8. Update the parent dashboard to show the planner's `reasoning` field — parents see *why* their kid practiced what they did today. This is one of the strongest demo moments: "Today's session focused on conjuncts because Aanya has mastered all 16 vowels but still mixes up క్ష and జ్ఞ in writing." Make sure this shows clearly in the dashboard.
9. Update `writeup/draft.md` with the architectural story: deterministic Layer 1 / agentic Layer 2 split, the planner's reasoning over session history, the planner running on cloud 31B for reasoning quality vs. kid loop on local E4B for privacy and speed, the fallback safety net.
10. Append to `decisions.md`: planner prompt version, mastery threshold chosen, any tool schema deviations, eval results.

**Acceptance:** Planner runs at session start, produces sensible plans for the 5 eval scenarios, fallback works when forced, kid loop renders all three step types, parent dashboard shows the reasoning. End-to-end test: simulate a kid who's mastered vowels, start a session, verify the planner introduces word reading.

**If you fall behind in this phase:**
- Cut the rhyme reading step type. Keep letter and word reading.
- Cut the audio input for word reading; use the "I read it" button.
- Keep the planner itself. The agentic call is the architectural story; cutting it cuts the differentiator.

---

## Phase 6: Polish (Days 10, may compress to 1 day)

**Goal:** Kid UX feels good. Demo-ready. Hindi included only if time allows.

**Steps:**
1. Kid UI polish: encouraging visual feedback on success (simple CSS animation, no heavy library), audio reward sound on correct attempts, larger touch targets for tablet use, session-end celebration with animated stars or similar simple effect.
2. Add error states for the failure modes likely to appear in demo: blurry photo, photo with no character visible, TTS failure, model timeout, planner timeout. Each should produce a kid-friendly message ("Hmm, I couldn't see clearly — try taking the photo again with more light").
3. **Hindi support (optional, cut first if behind):** Extend `app/curriculum.py` with Devanagari vowels. Add a language toggle on the kid UI (default Telugu, switch to Hindi). Verify the same loop works in Hindi by running 3-4 letters end to end. Document any quality differences in `decisions.md`. The planner's tool already accepts a language parameter, so the planner side should work without changes.
4. Test on at least one tablet or phone browser. Adjust layout if needed.
5. Solicit feedback from one or two real users (your own kids ideally). Note the top 3 friction points and fix them.

**Acceptance:** Kid UI feels engaging and forgiving. Tablet layout is usable. Hindi works on at least the vowel set if time permitted.

---

## Phase 7: Writeup and Demo Video (Days 11-12)

**Goal:** Submission post drafted, demo video recorded.

**Steps:**
1. Complete `writeup/draft.md`. Each section is now substantive, not skeletal. Length target: 1500-2500 words. Include: the personal hook (kids losing their mother tongue script), why existing solutions fail, why Gemma 4 specifically (with eval comparison numbers from Phase 1), what was built (with parent-dashboard screenshot), how it works (architecture diagram showing the deterministic-vs-agentic split), the planner's reasoning shown with a concrete example, demo (link to video), tradeoffs (E4B local vs 31B cloud comparison numbers, deterministic-vs-agentic decision), what's next.
2. **Make the architectural split the central technical story.** Many submissions will use Gemma 4 generically. Your differentiator is the deliberate two-layer architecture: deterministic single-call kid loop on local E4B for consistency and privacy, agentic planner on cloud 31B at session boundaries for reasoning quality. Frame this as a judgment call rather than a capability demonstration. Quote from your `decisions.md` if helpful.
3. Generate the architecture diagram. Use Mermaid in the markdown if dev.to renders it; otherwise a simple PNG drawn in any tool. Show: kid UI → FastAPI → query_gemma (local E4B) for the kid loop; session start → planner → query_gemma (cloud 31B) with tool calls to SQLite → SessionPlan back to kid loop; parallel branch to OpenRouter for evals; TTS as a side path.
4. Record demo video, 2-3 minutes:
   - 15 seconds: the problem (b-roll of a kid + parent, narration about the script literacy gap).
   - 45 seconds: kid using the app — letter shown, audio plays, kid writes, photo, encouraging feedback. Use a real kid if possible.
   - 30 seconds: **the planner's intelligence visible** — show "Start practice today" tap, brief loading, then the parent-dashboard reasoning field showing why this session was planned. This is the agentic moment; do not skip it.
   - 30 seconds: parent dashboard walkthrough.
   - 20 seconds: technical highlight — show the eval comparison, the architectural split diagram, mention E4B local + 31B cloud, mention 256K context for session history.
   - 15 seconds: close on the personal stake — "I built this for my own kids."
4. Edit video in any tool (iMovie, DaVinci Resolve, even QuickTime trim+merge). Export at 1080p, under 100MB if possible.
5. Upload video to YouTube as unlisted, embed link in the writeup.
6. Take the parent dashboard screenshot at high resolution. Take 2-3 kid UI screenshots.
7. Polish the writeup once more for tone — judges read many of these, so the personal hook in the first paragraph matters more than technical depth.

**Acceptance:** Writeup is publishable. Video is uploaded. Screenshots are in `writeup/assets/`.

---

## Phase 8: Hardening (Days 13-14)

**Goal:** Find and fix demo-killers. Make the README good enough for judges to clone and run.

**Steps:**
1. Run the full kid loop 5 times in a row, in different conditions: indoor light, low light, with the laptop battery low, after a fresh laptop reboot, after the laptop has been running for hours. Note any flakiness.
2. Run the parent dashboard 3 times — make sure it loads cleanly, summary makes sense, no stale data issues.
3. Stress test: leave the app running for an hour, then test the loop. Common failures: SQLite locks, Ollama process drift. Fix or document.
4. Write `README.md` with: project overview, the personal motivation in 2 paragraphs, prerequisites (Ollama, gemma4:e4b model pulled, OpenRouter key for evals only — not required to run), setup steps (clone, install with uv, copy .env.example, run uvicorn), screenshots, link to writeup and video, license (Apache 2.0 to match Gemma 4).
5. Verify the setup steps actually work: in a fresh shell, follow your own README from scratch to running app. Time it. Should be under 10 minutes including model pull.
6. Final eval re-run: run all evals once more on the final code state. Update the comparison numbers in the writeup if anything shifted.
7. Commit everything. Push to a public GitHub repo. Verify the repo URL works from incognito.

**Acceptance:** Demo loop is stable. README works for a stranger. Repo is public and clean.

---

## Phase 9: Submission (Day 15 morning IST)

**Goal:** Submit early. Buffer for platform issues.

**Steps:**
1. Re-read the dev.to submission template from the official launch post. Use the exact tags required: `devchallenge`, `gemmachallenge`, `gemma`, plus any track-specific tag mentioned in the launch post.
2. Paste the writeup into a new dev.to post. Format check: code blocks render, mermaid diagram renders or is replaced with PNG, video embed works, screenshots display, links work.
3. Add the GitHub repo link prominently in the post.
4. Submit using the "Build with Gemma 4" track (not "Write About Gemma 4").
5. Verify the post is live and viewable in incognito.
6. Done. Step away from the computer.

**Hard rule:** Submit before 6 PM IST on May 24 (which is well before the 11:59 PM PDT deadline). Do not submit in the last 2 hours — platform issues spike.

---

## Continuous Throughout (All Phases)

- **decisions.md** is append-only, dated, and explains why. Every nontrivial choice goes here.
- **Eval suite** runs after any model-related change. If evals regress, fix or revert before continuing.
- **Writeup draft** evolves continuously, not in a Phase 7 sprint. Every phase touches `writeup/draft.md` minimally.
- **Scope discipline:** if a feature is not in the V1 Scope list in CLAUDE.md, it does not get built. Period. Note the temptation in decisions.md and move on.

---

## If You Fall Behind

In order, cut: Hindi generalization (Phase 6 step 3), rhyme-reading step type (Phase 5.5 step 7), audio input for word reading replaced with "I read it" button, session-end celebration polish (Phase 6 step 1 partial), parent dashboard "share with family" button, kid UI animations.

**Do not cut, in priority order:** the deterministic kid loop (core demo), the parent dashboard with English summary, the session planner itself (architectural differentiator — even with rhyme-reading cut, the planner choosing letters and word reading is still the agentic story), the eval comparison numbers, the demo video, the writeup. The kid loop, the planner, and the parent dashboard are the three things judges will remember.
