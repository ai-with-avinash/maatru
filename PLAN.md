# PLAN.md — Maatru Execution Plan (revised post-pivot)

**How to use this file:** Give Claude Code one phase at a time. Paste 
the phase block as a session opener along with a reminder to read 
CLAUDE.md and decisions.md first. Do not paste the whole plan in one 
session.

**Standard session opener:**
> Read CLAUDE.md and decisions.md first. We are starting Phase N. 
> Here is the phase: [paste phase block]. Confirm you understand the 
> scope and the explicit non-goals, then proceed step by step. Stop 
> and ask if any step requires a product decision.

**Project status as of 2026-05-10 (post-pivot):** Phase 0 complete. 
Phase 1 partially complete — Gates 1 and 2 passed, Gate 3 failed and 
triggered the pivot to Option A (drop vision, tap-to-recognize), 
Gates 4 and 5 still pending. Days remaining to deadline: 14.

---

## Phase 0: Project Setup — COMPLETE ✓
Original phase, completed 2026-05-09. See decisions.md.

---

## Phase 1: Day-1 Evals — PARTIALLY COMPLETE
Original phase, run 2026-05-09 to 2026-05-10.
- Gate 1 (Ollama vision): PASSED — moot for v1 now.
- Gate 2 (Telugu generation): PASSED.
- Gate 3 (Telugu handwriting): FAILED — triggered pivot.
- Gate 4 (TTS quality): pending; see Phase 1.5 below.
- Gate 5 (OpenRouter rate limits): partially verified; see Phase 1.5.

---

## Phase 1.5: Close out remaining Phase 1 gates (1-2 hours)

**Goal:** Run the Phase 1 steps that don't depend on the failed Gate 3 — 
TTS quality validation and OpenRouter rate-limit stress test. These 
inform the writeup's tradeoffs section and confirm v1 infrastructure.

**Steps:**
1. **Gate 4 — TTS quality validation.** Generate Telugu audio samples 
   for 5 prompts via Google Cloud TTS using both available Telugu 
   voices (te-IN-Standard-A, te-IN-Standard-B). Prompts to synthesize: 
   single vowel అ, single consonant క, simple greeting నమస్కారం, 
   2-letter word అమ్మ, encouragement phrase చాలా బాగా. Save as MP3 in 
   eval/results/tts_samples/. Have the Telugu reviewer rate each on 
   pronunciation accuracy and child-appropriate naturalness 
   (1-5 scale). Document the verdict and chosen voice in decisions.md.
2. **Gate 5 — OpenRouter rate-limit stress test.** Write a small 
   script eval/stress_openrouter.py that fires 50 sequential 
   short-prompt requests to google/gemma-4-31b-it:free in a loop over 
   2-3 minutes. Capture: total time, requests-per-minute, any 429 or 
   other errors, error rate. Save output to 
   eval/results/openrouter_ratelimit.txt. With BYOK already configured 
   via personal Google AI Studio key, expectation is no 429s. If 429s 
   appear, document threshold and add fallback to direct Google AI 
   Studio API.
3. **Append both gate results to decisions.md** with the dated format. 
   Gate 4 verdict, chosen voice, sample paths. Gate 5 numbers 
   (requests/min, error rate), implication for the writeup's 
   reliability story.

**Acceptance:** TTS voice chosen and documented. Rate-limit data 
captured. decisions.md updated. Phase 1 formally closed.

**Human-side action items:**
- Telugu reviewer listens to 10 TTS samples (5 phrases × 2 voices), 
  rates each, picks the better voice.
- Update .env's TTS_VOICE if the reviewer prefers Standard-B over 
  the default Standard-A.

---

## Phase 2: Architecture and Schemas (revised, ~half-day)

**Goal:** Update the model abstraction and prompt schemas to fit the 
pivoted product. Most of app/model.py from the original Phase 2 still 
applies; this phase adds the new Pydantic schemas for tap-to-recognize 
and updates query_gemma if needed.

**Note:** app/model.py was already implemented as 59 lines in the 
original Phase 2. Verify it still meets the new requirements; do not 
rewrite. The thinking parameter and structured-output handling are 
already in place.

**Steps:**
1. Verify app/model.py satisfies the new design:
   - Cloud path is the v1 default (model="cloud"). Already the case.
   - Image path support is retained for v2 hooks; not used in v1 flow.
   - Thinking mode opt-in works. Already verified.
   - Function calling / structured output works. Verify with a smoke 
     test using a trivial Pydantic schema before relying on it for 
     real schemas. **This is the "test before integrating" lesson 
     from Gate 3.**
2. Define core Pydantic schemas in app/prompts.py (NEW for v2):
   - `LetterEntry(character: str, transliteration: str, language: str)`
   - `LetterSet(language: str, theme: str, entries: list[LetterEntry])`
   - `RecognitionStep(target: LetterEntry, distractors: list[LetterEntry], step_index: int)` — 
     a single tap-to-recognize question with one correct letter and 3 distractors
   - `RecognitionFeedback(correct: bool, encouragement: str, retry_hint: Optional[str])`
   - `SessionStep(step_type: Literal["recognize_letter", "recognize_word", "read_aloud"], step_data: dict, target_skill: str, expected_difficulty: Literal["easy", "medium", "hard"])`
   - `SessionPlan(session_id: str, language: str, focus: str, steps: list[SessionStep], reasoning: str, fallback_used: bool)`
   - `SessionSummary(letters_practiced: list[str], strong_letters: list[str], needs_practice: list[str], suggested_next: list[str], parent_summary_english: str)`
3. Define the planner's tool schemas (also in app/prompts.py):
   - `get_recent_sessions(n: int)` — returns recent session summaries.
   - `get_letter_accuracy(letters: list[str])` — per-letter attempts and 
     accuracy.
   - `get_curriculum(language: str, scope: Literal["letters", "words"])` — 
     curriculum entries for that scope.
   These are SQLite reads only. No write capability.
4. Define versioned prompt templates in app/prompts.py as Python 
   constants. Examples: 
   `LETTER_RECOGNITION_DISTRACTORS_PROMPT_V1`, 
   `RECOGNITION_FEEDBACK_PROMPT_V1`, 
   `SESSION_SUMMARY_PROMPT_V1`. When revised, increment version. Old 
   versions stay in the file commented out for reference.
5. Smoke-test the structured-output capability with a trivial schema 
   BEFORE relying on it for real flows. Create eval/smoke_structured.py 
   that asks Gemma 4 to return a `LetterEntry` for a known input ("the 
   Telugu letter ka") and validates the response parses correctly. 
   Document result in decisions.md. **This is the test-before-integrate 
   discipline.**
6. Update writeup/draft.md "Why Gemma 4" section to remove vision claims 
   and emphasize multilingual generation, function calling, 256K 
   context, thinking mode for the planner. Cite Gate 2 PASS for 
   generation reliability.

**Acceptance:** Schemas defined. Prompts versioned. Smoke test passes 
with structured output. Writeup draft updated.

---

## Phase 3: Thin End-to-End Slice (Day 3, revised)

**Goal:** Working tap-to-recognize loop on one letter. Ugly, hardcoded, 
end-to-end. Prove the product is possible.

**Steps:**
1. Hardcode the target letter as అ in this phase. No curriculum logic 
   yet, no planner, no session storage.
2. Implement static/kid.html: a single page that displays the letter అ 
   in large font, a button "Hear it" that calls a backend endpoint to 
   play TTS, 4 option buttons below showing 4 Telugu letters (అ, ఆ, ఇ, 
   క — three hardcoded distractors), a result area for feedback after 
   tap.
3. Implement backend endpoints:
   - `GET /` — serves kid.html.
   - `POST /api/pronounce` — body `{character: "అ", language: "te"}`, 
     returns audio bytes from Google TTS.
   - `POST /api/check_recognition` — body `{target: "అ", chosen: "ఆ"}`, 
     calls query_gemma with the `RecognitionFeedback` schema, returns 
     feedback as JSON. Even though the correctness check is trivial 
     (string equality), routing through Gemma 4 makes the encouragement 
     and retry hints contextual ("you tapped ఆ which is similar but 
     longer; listen for the shorter sound").
4. Implement app/tts.py with `synthesize(text: str, language: str) -> bytes` 
   using Google Cloud TTS. Use the voice chosen in Phase 1.5 Gate 4.
5. Wire the frontend: vanilla JS for fetch calls, no framework. Display 
   the model's `encouragement` field directly. Use simple CSS — large 
   readable fonts, kid-friendly colors, no animations yet.
6. Test the loop yourself: open browser, see అ, hear pronunciation, tap 
   one of the 4 options, see feedback. Iterate until this loop works 
   end-to-end without manual intervention.
7. Append to decisions.md any frontend simplifications or unexpected 
   issues with the TTS/model integration.

**Acceptance:** End-to-end loop works in browser. From letter display 
to feedback display, no manual steps. Time per round-trip should be 
under 2 seconds (one Gemma 4 call + TTS).

**Critical:** if you cannot get the loop working by end of day 3, the 
project is in trouble. Stop and simplify ruthlessly — bypass Gemma 4 
for the feedback (use hardcoded "Yes!"/"Try again"), make TTS optional, 
strip styling. Make the loop work, then add back.

---

## Phase 4: Practice Loop Deepening (Days 4-6, revised)

**Goal:** Full Telugu vowel set, basic curriculum, session structure, 
distractor generation by Gemma 4, simple progress tracking.

**Steps:**
1. Define the Telugu curriculum in app/curriculum.py: a list of letter 
   entries covering the 16 Telugu vowels, then consonants in 
   pedagogical order. Each entry has the character, transliteration, 
   English example word, and a difficulty rank. This is hardcoded for 
   v1, not generated; reliability matters more than novelty here.
2. Implement app/session.py: SQLite schema with tables `sessions`, 
   `attempts`. Functions to start a session, record an attempt with 
   target letter / chosen letter / correctness / model feedback / 
   timestamp, end a session with summary stats. Session ID is a UUID.
3. Implement Gemma-4-driven distractor selection: given a target 
   letter, ask Gemma 4 for 3 plausible Telugu letter distractors using 
   the `LetterSet` schema and a prompt that controls difficulty 
   (easy = visually-distinct letters, medium = same vowel/consonant 
   class, hard = visually-similar pairs). Cache common combinations to 
   avoid repeated calls within a session.
4. Replace the hardcoded letter and distractors in the kid loop with 
   curriculum-driven selection. At session start, pick 5-7 letters using 
   a "least practiced" heuristic — never-attempted first, then 
   lowest-recent-accuracy. **This deterministic heuristic is also the 
   fallback path for Phase 5.5's planner.**
5. Add session navigation in the UI: progress indicator ("Letter 2 of 
   5"), "Next letter" button after feedback, session-end screen with 
   simple message ("Great job! You practiced 5 letters today."). Allow 
   one retry per letter — if kid taps wrong, show retry hint, on second 
   wrong attempt move on with a soft "we'll come back to this one."
6. After each attempt, store the model's feedback verbatim in SQLite. 
   This becomes the data source for the parent dashboard.
7. Test the loop on your own kids if available. Watch where they get 
   confused or bored. Note observations in decisions.md.
8. Update writeup/draft.md "What I Built" section with the curriculum 
   structure, distractor generation by Gemma 4, and session flow.

**Acceptance:** Full session of 5+ letters runs end to end. Progress 
persists across sessions. Curriculum picks sensibly different letters 
in subsequent sessions. Distractors are generated by Gemma 4 and feel 
appropriate (close-but-distinguishable letters, not random unrelated 
ones).

**Risk to watch:** scope creep. Resist adding spaced repetition, 
elaborate difficulty progression, multi-session arcs. Keep it simple.

---

## Phase 5: Parent Dashboard (Days 7-8, unchanged in spirit)

**Goal:** The differentiator. English summaries of Telugu practice. 
Polished enough to screenshot for the submission.

**Steps:**
1. Add a parent PIN to .env (e.g., `PARENT_PIN=4242`). On the parent 
   route, prompt for PIN, store in session cookie.
2. Implement app/parent.py with functions:
   - `get_today_summary(date)` — reads sessions and attempts from 
     SQLite for the given date.
   - `generate_english_summary(session_data) -> str` — calls 
     query_gemma with `SessionSummary` schema. The 256K context lets 
     you pass the full session history into one call.
3. Implement static/parent.html: dashboard view with today's session 
   count, list of letters practiced (Telugu character + English 
   transliteration), the model's English summary in a prominent card, 
   per-letter accuracy ("అ: 4/4 correct, ఆ: 2/3 correct, ఇ: 0/2 — needs 
   practice"), and "Suggested for tomorrow" section.
4. Endpoints: `GET /parent/today` returns dashboard data as JSON, 
   `GET /parent` serves parent.html.
5. Polish: this is the screenshot in the submission. Spend time on 
   layout, typography, color. Keep it clean and warm.
6. Update writeup/draft.md "What I Built" with parent dashboard 
   prominently. Plan the screenshot now.

**Acceptance:** Parent dashboard loads, shows today's data, English 
summary reads naturally, accuracy table is clear. The page is 
presentable in a screenshot.

---

## Phase 5.5: Session Planner — Agentic Layer 2 (Days 8-9, unchanged)

**Goal:** Build the agentic session planner. The architectural 
differentiator. Adaptive personalization at session boundaries.

**Read first:** Re-read the "Architecture Philosophy" section in 
CLAUDE.md before starting. The planner is intentionally constrained — 
runs once at session start, has read-only tools, emits a structured 
SessionPlan, and never reaches into the kid loop.

**Steps:**
1. Implement app/planner.py with `plan_session(kid_id: str, language: str, 
   force_fallback: bool = False) -> SessionPlan`. When `force_fallback` 
   is True, skip the agentic call and use the deterministic curriculum 
   heuristic from Phase 4.
2. The planner makes a single call to query_gemma with thinking mode 
   enabled, function calling enabled, and the three tool definitions. 
   Use cloud Gemma 4 31B (already the v1 default). 
   **Smoke-test tool calling first** with a trivial scenario before 
   building the real planner — Gate 3 lesson applies.
3. Implement the three tools as Python functions reading from SQLite. 
   Each returns a Pydantic-validated structure that the model receives 
   as tool output.
4. Write the planner's system prompt (`PLANNER_PROMPT_V1` in 
   app/prompts.py). Establishes: model is a session planner for an 
   early-literacy app; user is 5-8 year old; consistency matters more 
   than novelty; introduce new step types (word recognition, then 
   read-aloud if available) only when prerequisite letters are 
   mastered (mastery: 80%+ accuracy across 3+ attempts); session length 
   5-8 steps. The prompt should make the model justify its plan in the 
   `reasoning` field.
5. Build a 5-call eval for the planner: 5 fake session histories 
   (brand new, vowels-strong-consonants-weak, ready-for-words, 
   struggling-with-similar-letters, mostly-mastered). Run the planner 
   and verify the output `SessionPlan` matches what a literacy expert 
   would suggest. Save to eval/results/planner_scorecard.md.
6. Wire the planner into `/api/session/start`: calls `plan_session()`. 
   On success, returned `SessionPlan` becomes the session's step list. 
   On failure (timeout > 10s, JSON error, schema error, tool error), 
   log it and call again with `force_fallback=True`. The kid never 
   sees the failure.
7. Update static/kid.html to render whatever step type the planner 
   returns:
   - `recognize_letter`: existing flow (display letter, audio, 4 
     options, feedback).
   - `recognize_word`: display 2-letter Telugu word with 
     transliteration, audio, 4-option pick (one correct word, 3 
     distractor words). Same pattern.
   - `read_aloud`: optional Phase 6, see below.
8. Update parent dashboard to show the planner's `reasoning` field — 
   parents see *why* their kid practiced what they did today. This is 
   one of the strongest demo moments: "Today's session focused on 
   short-vowel-vs-long-vowel pairs because Aanya scored highly on 
   isolated vowels but struggles when they appear close together."
9. Update writeup/draft.md with the architectural story: deterministic 
   Layer 1 / agentic Layer 2 split, the planner's reasoning over 
   session history, the fallback safety net.
10. Append to decisions.md: planner prompt version, mastery threshold, 
    eval results, any tool-calling quirks discovered.

**Acceptance:** Planner runs at session start, produces sensible plans 
for the 5 eval scenarios, fallback works when forced, kid loop renders 
both letter and word recognition, parent dashboard shows the reasoning. 
End-to-end test: simulate a kid who's mastered vowels, start a session, 
verify the planner introduces word recognition.

**If you fall behind:**
- Cut the read_aloud step type (Phase 6 anyway).
- Keep the planner. The agentic call is the architectural story; 
  cutting it cuts the differentiator.

---

## Phase 6: Polish + Optional Read-Aloud (Days 10, 1 day)

**Goal:** Kid UX feels good. Demo-ready. Read-aloud track added only if 
time allows.

**Steps:**
1. Kid UI polish: encouraging visual feedback on success (simple CSS 
   animation), audio reward sound on correct attempts, larger touch 
   targets for tablet use, session-end celebration with stars or 
   similar simple effect.
2. Add error states for likely failure modes: TTS failure, model 
   timeout, planner timeout. Each should produce a kid-friendly 
   message ("Hmm, let me try that again — give me a moment").
3. **Optional: Read-aloud track.** If time allows, add the 
   `read_aloud` step type:
   - Display 2-line Telugu rhyme with transliteration.
   - Audio plays the rhyme once at slow pace.
   - "Tap when you're ready to read" button.
   - Browser captures kid's audio (MediaRecorder API), sends to a 
     backend endpoint that calls Google Cloud Speech-to-Text in 
     Telugu, then asks Gemma 4 to compare transcript to expected and 
     return encouraging feedback.
   - This adds Speech-to-Text as a new dependency on the cloud side — 
     enable Cloud Speech-to-Text API in the same GCP project as TTS, 
     same key works.
   - Cut without remorse if Phase 5.5 ran long.
4. Test on at least one tablet or phone browser. Adjust layout if 
   needed.
5. Solicit feedback from one or two real users (your own kids if 
   available). Note top 3 friction points and fix them.

**Acceptance:** Kid UI feels engaging and forgiving. Tablet layout is 
usable. Read-aloud demonstrated end-to-end if implemented; otherwise 
documented as v2.

---

## Phase 7: Writeup and Demo Video (Days 11-12)

**Goal:** Submission post drafted, demo video recorded.

**Steps:**
1. Complete writeup/draft.md. Length target: 1500-2500 words. Sections:
   - The personal hook: kids losing their mother tongue script.
   - Why existing solutions fail (parents can't teach what they 
     don't know).
   - **The honest engineering story** (this is the differentiator vs. 
     other submissions): "I started with a photo-feedback design 
     where kids would write characters on paper and Gemma 4 would 
     evaluate them. Day-1 evaluation showed Gemma 4's vision 
     capability does not currently read Telugu script reliably — 5% 
     local accuracy, 20% cloud accuracy on a graduated handwriting 
     eval, including failures on perfectly-rendered typed reference 
     characters. I pivoted to a design that uses Gemma 4 where it 
     actually shines: multilingual text generation, agentic session 
     planning, structured outputs via function calling, and 256K 
     context for full session history." Include the scorecard table 
     from eval/results/handwriting_scorecard.md.
   - Why Gemma 4 specifically (the revised five-point pitch).
   - What was built (with parent-dashboard screenshot, planner 
     reasoning example).
   - How it works (architecture diagram showing 
     deterministic-vs-agentic split).
   - Demo video link.
   - Tradeoffs and decisions (cite specific decisions.md entries: 
     local-vs-cloud, vision-tested-and-rejected, Telugu-only).
   - What's next (v2 with photo-feedback when models improve, 
     read-aloud, multi-language).
2. The architectural split (deterministic kid loop vs agentic planner) 
   is the central technical story. Tied with the honest negative-result 
   handling, this is the differentiator. Make both prominent.
3. Generate the architecture diagram. Use Mermaid in markdown if 
   dev.to renders it; otherwise simple PNG. Show: kid UI → FastAPI → 
   query_gemma (cloud 31B) for both kid loop and planner; planner 
   reads SQLite via tool calls; TTS as a side path; parent dashboard 
   on a separate route.
4. Record demo video, 2-3 minutes:
   - 15 seconds: the problem (b-roll, narration about script literacy 
     gap).
   - 30 seconds: the engineering pivot — show the eval data briefly, 
     mention the honest finding ("vision didn't work for Telugu, so I 
     redesigned"). This makes the rest of the video land harder.
   - 45 seconds: kid using the app — letter shown, audio plays, kid 
     taps the right answer, encouraging feedback.
   - 30 seconds: planner reasoning visible on parent dashboard ("Today 
     focused on X because...").
   - 30 seconds: parent dashboard walkthrough.
   - 15 seconds: close on personal stake.
5. Edit video in any tool. Export 1080p. Upload to YouTube unlisted, 
   embed in writeup.
6. Take parent dashboard screenshot at high resolution. Take 2-3 kid 
   UI screenshots.
7. Polish writeup tone — judges read many of these; the honest 
   pivot story plus personal hook is the memorable angle.

**Acceptance:** Writeup publishable. Video uploaded. Screenshots in 
writeup/assets/.

---

## Phase 8: Hardening (Days 13-14)

**Goal:** Find and fix demo-killers. Make README good enough for judges 
to clone and run.

**Steps:**
1. Run the full kid loop 5 times in a row, in different conditions: 
   indoor light (UI legibility), low light, after laptop reboot, after 
   running for hours. Note flakiness.
2. Run the parent dashboard 3 times — make sure it loads cleanly, 
   summary makes sense, no stale data.
3. Stress test: leave the app running for an hour, then test the loop. 
   Common failures: SQLite locks, OpenRouter session expiry. Fix or 
   document.
4. Write README.md with: project overview, the personal motivation in 
   2 paragraphs, the honest engineering pivot in 1 paragraph linking 
   to writeup for full story, prerequisites (Python 3.11+, OpenRouter 
   key, Google Cloud TTS key — both with free-tier links), setup steps 
   (clone, uv install, copy .env.example, run uvicorn), screenshots, 
   link to writeup and video, license (Apache 2.0 to match Gemma 4).
5. Verify the setup steps actually work: in a fresh shell, follow your 
   own README from scratch to running app. Time it. Should be under 
   10 minutes.
6. Final eval re-run: run all evals once more on the final code state. 
   Update writeup numbers if anything shifted.
7. Commit everything. Push to public GitHub repo. Verify the repo URL 
   works from incognito.

**Acceptance:** Demo loop is stable. README works for a stranger. Repo 
is public and clean.

---

## Phase 9: Submission (Day 15 morning IST)

**Goal:** Submit early. Buffer for platform issues.

**Steps:**
1. Re-read the dev.to submission template from the official launch 
   post. Use exact tags: `devchallenge`, `gemmachallenge`, `gemma`, 
   plus track-specific tag.
2. Paste writeup into a new dev.to post. Format check: code blocks 
   render, mermaid renders or replaced with PNG, video embed works, 
   screenshots display, links work.
3. Add the GitHub repo link prominently.
4. Submit using the "Build with Gemma 4" track.
5. Verify the post is live in incognito.
6. Done. Step away.

**Hard rule:** Submit before 6 PM IST on May 24 (well before the 11:59 
PM PDT deadline). Do not submit in the last 2 hours.

---

## Continuous Throughout (All Phases)

- decisions.md is append-only, dated, explains why. Every nontrivial 
  choice goes here.
- Eval suite runs after model-related changes.
- writeup/draft.md evolves continuously, not in a Phase 7 sprint.
- Scope discipline: if a feature is not in V1 Scope in CLAUDE.md, 
  don't build it. Note temptation in decisions.md and move on.

---

## If You Fall Behind

Cut order: read-aloud step type (Phase 6 step 3), Hindi generalization 
(can be added to Phase 6 if read-aloud is cut), session-end celebration 
polish, kid UI animations, planner's introduction of word recognition 
(stay on letter recognition only).

**Do not cut:** the deterministic kid loop, the parent dashboard with 
English summary, the session planner itself, the eval comparison data 
including the honest Gate 3 fail story, the demo video, the writeup. 
The kid loop, the planner, the parent dashboard, and the honest 
negative-result framing are the four things that win this submission.