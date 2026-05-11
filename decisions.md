# Decisions Log

Append-only record of nontrivial decisions made during the Maatru build. 
Each entry is dated, names the decision, and captures the reasoning. Do 
not edit past entries — add new ones to supersede if a decision changes.

Format for new entries:

    ## YYYY-MM-DD — <short decision title>

    <2-5 sentences: what was decided, why, what alternatives were 
    considered, what the implication is for the build.>

---

## 2026-05-09 — Project initialization and stack selection

Project initialized. Stack: Python 3.11+ (uv selected 3.13.9 for the venv;
acceptable since pyproject pins requires-python >= 3.11), FastAPI for the 
backend, Ollama serving gemma4:e4b locally (M4 MacBook Air 16GB) plus 
OpenRouter `google/gemma-4-31b-it:free` for cloud comparison, SQLite for 
session storage, plain HTML + vanilla JavaScript for the frontend (no 
React/build tooling), `uv` for package management.

Dependencies installed in Phase 0: fastapi, uvicorn, python-dotenv, httpx, 
pillow, pydantic, python-multipart. Project structure follows the layout 
specified in CLAUDE.md.

Acceptance verified: uvicorn boots, GET /healthz returns {"status":"ok"}, 
.env created from .env.example with placeholders, .gitignore covers .venv/ 
.env/ __pycache__/ *.db/ eval/results/ writeup/assets/raw/ data/samples/private/.

## 2026-05-09 — TTS provider: Google Cloud TTS

Evaluated AI4Bharat IndicF5 local as a candidate for the local-first 
narrative. Setup in an isolated venv hit Python environment friction 
(transformers package not resolving in the venv despite reported successful 
install) that consumed the agreed time-box without producing test audio.

Decision: Ship Google Cloud Text-to-Speech for v1. The local-first privacy 
story remains intact for the privacy-sensitive components — Gemma 4 vision 
and reasoning run locally on E4B, so the kid's photographs and handwriting 
analysis never leave the device. TTS audio output is not privacy-sensitive 
because the audio says the same curriculum content every time regardless 
of the user, so cloud TTS is a defensible architectural choice.

Configured: TTS_PROVIDER=google, GOOGLE_TTS_API_KEY set. Phase 1 Gate 4 
will validate Google TTS Telugu voices (te-IN-Standard-A and te-IN-Standard-B) 
for child-appropriate naturalness and pronunciation, not run a side-by-side 
comparison with alternatives.

IndicF5 local deferred to v2. Writeup will frame the local/cloud split as 
intentional engineering: privacy-sensitive components local, non-sensitive 
components cloud.

## 2026-05-09 — Convention: TTS_PROVIDER values are lowercase snake_case

Established convention for `.env` provider/enum values: lowercase snake_case 
identifiers. This avoids needing `.lower()` calls at every config read site 
and matches standard Python configuration practice. Current valid values 
for TTS_PROVIDER: `google`, `ai4bharat_local`. API keys are case-sensitive 
and copied verbatim; provider names follow this convention.

## 2026-05-09 — API connectivity verified end-to-end

Both critical API paths tested via curl from the local environment:
- OpenRouter → Google AI Studio (BYOK) → Gemma 4 31B: returns valid Telugu 
  output. Auth working, no upstream rate limits with personal key (initial 
  test against the shared free pool returned 429; resolved by registering 
  a personal Google AI Studio key in OpenRouter Settings → Integrations).
- Google Cloud TTS → te-IN-Standard-A: produces playable Telugu MP3 with 
  acceptable pronunciation.

Phase 1 unblocked. Both eval paths (local Ollama for E4B, cloud OpenRouter 
for 31B comparison) are operational.

## 2026-05-09 — Known v2 deferral: blocking file I/O in query_gemma

Synchronous `Path.read_bytes()` inside the async `query_gemma` function is 
acceptable for v1 single-user sequential usage; defer aiofiles migration to 
v2 if concurrent uploads become a requirement.

## 2026-05-09 — First Gemma 4 output: model abstraction verified

Smoke-tested app/model.query_gemma directly: prompt "Say hello in 
Telugu in one word", model=cloud (Gemma 4 31B via OpenRouter BYOK), 
image_path=None. Returned ok=True with text "నమస్కారం (Namaskaram)". 

Confirms the OpenAI-compatible request shape, the BYOK routing 
through Google AI Studio, and the no-image code path all work. 
Eval runner can proceed with confidence on text-only generation 
prompts.

## 2026-05-09 — Phase 1 step 4: generation eval results

Ran telugu_generation eval (10 prompts, both models, sequential 
local-then-cloud). Results saved to eval/results/telugu_generation_20260509T191017Z.json.

Cloud (Gemma 4 31B via OpenRouter BYOK): 10/10 succeeded, median 4.8s, 
max 16.9s. tg_05 returned partly garbled output with mojibake and 
mixed scripts — flagged for Telugu reviewer attention as a possible 
failure mode for short-word-list generation.

Local (Gemma 4 E4B via Ollama on M4 16GB): 8/10 succeeded, median 28.9s, 
max 46.1s. Two timeouts (tg_05, tg_07) on the longest-output prompts. 
tg_01 took 32.8s, likely a cold-start artifact since subsequent prompts 
were faster.

Latency observations significantly worse than initial estimates 
(originally projected sub-second to 3s on E4B; reality is 8-46s on 
generation prompts). However, generation prompts produce 50-200+ output 
tokens; the kid loop produces 20-40 output tokens (short structured 
JSON). Decision deferred to handwriting eval (Phase 1 steps 6-9) which 
tests workload closer to actual kid-loop usage. 

Open questions for tomorrow:
- Does E4B handle short structured outputs (handwriting feedback shape) 
  in the 1-5s range, or is the kid loop architecturally broken?
- Does Telugu reviewer accept ≥8/10 cloud outputs as correct and 
  age-appropriate (Gate 2 acceptance)? If tg_05 fails review, may drop 
  to 9/10 or 8/10 depending on other prompt quality.
- Should query_gemma's default timeout be raised for eval use? 60s caught 
  two real failures correctly, so unclear it's the wrong number.

No architectural decisions taken tonight. Awaiting reviewer pass and 
handwriting eval data.

## 2026-05-10 — Phase 1 Gate 2: Telugu generation eval — PASS

Telugu-literate reviewer (Avinash's wife) reviewed all 10 cloud 
outputs from telugu_generation_20260509T191017Z.json. Verdict: 
≥8 of 10 correct Telugu and age-appropriate for 5-8 year olds, 
including tg_05 (the mojibake-flagged entry — Telugu content was 
acceptable despite formatting noise).

Gate 2 acceptance threshold met. Generation capability confirmed 
viable for the kid loop's curriculum-content needs. The 256K context 
plus multilingual support hypothesis from CLAUDE.md "Why Gemma 4" 
holds for Telugu specifically.

Proceeding to Phase 1 step 6 (handwriting samples already in place 
at eval/images/handwriting/) and step 7 onward.

Local E4B generation observations from step 4 (median 28.9s, two 
60s timeouts) remain open as a kid-loop architecture question. 
Handwriting eval will produce the data that decides whether E4B 
local can serve short structured outputs in acceptable latency, 
or whether the kid loop must move to cloud.

## 2026-05-10 — Phase 1 Gate 3: Telugu handwriting eval — FAIL (BOTH MODELS)

Ran telugu_handwriting eval (20 prompts, 4 source tiers × 5 each: typed, 
adult, child, similar). Results saved to 
eval/results/telugu_handwriting_20260509T193642Z.json. Scorecard at 
eval/results/handwriting_scorecard.md.

Accuracy by tier (correct identifications / 5 samples each):

| source  | local      | cloud       |
|---------|------------|-------------|
| typed   | 1/5 (20%)  | 1/5 (20%)   |
| adult   | 0/5 (0%)   | 1/5 (20%)   |
| child   | 0/5 (0%)   | 0/5 (0%)    |
| similar | 0/5 (0%)   | 2/5 (40%)   |
| overall | 1/20 (5%)  | 4/20 (20%)  |

CLAUDE.md Gate 3 thresholds (typed+adult ≥80%, child ≥60%) failed by 
60+ percentage points on both models. Local also had 3 hard timeouts 
(>60s) on a workload (short structured JSON output) that should have 
been the easier case.

This is not a "kid handwriting is hard" failure mode. Both models 
failed on TYPED REFERENCE — perfectly rendered Telugu characters on 
white background, the gimme tier of the eval. Two independent 
inference paths (Ollama local on M4 + OpenRouter→Google AI Studio→
Gemma 4 31B) both produced wrong-but-confident outputs (e.g., అ read 
as ని locally and as ౦ on cloud). Independent paths producing 
wrong-but-coherent outputs is the signature of a model knowledge gap 
on Telugu vision, not infrastructure or input-pipeline issues.

Spot-checked alternative explanations:
- Image encoding: ruled out. The MIME detection in app/model.py 
  correctly handles JPEG/PNG/HEIF; cloud got 4/20 correct including 
  2 of the genuinely-similar pairs, which means input is reaching the 
  model legibly. Encoding errors would produce uniform failure, not 
  the observed graduated-but-bad pattern.
- API throttling / quality degradation: ruled out. Cloud providers 
  don't quietly degrade output quality, and local E4B is running 
  entirely on-device with no external dependency. Anthropic Claude 
  Code session limits are unrelated to OpenRouter or Ollama.
- Cold-start / warm-up: ruled out. Warm-up call was added to runner 
  before the timed loop. Latencies stabilized after warm-up; the 
  accuracy problem persists across all 20 samples.

Conclusion: Gemma 4's vision capability does not currently read Telugu 
script reliably enough to be the foundation of a literacy product. 
This is a model training-data limitation, not a fixable engineering 
bug.

## 2026-05-10 — Architectural pivot: drop vision, keep mission (Option A)

In response to the Gate 3 failure, considered three options:
- (A) Drop vision-as-input from the kid loop. Keep the Telugu 
  literacy mission and the parent dashboard. Replace the 
  "write→photograph→feedback" interaction with audio-based 
  (read-aloud) and tap-based (multiple-choice recognition) 
  interactions that don't depend on Gemma 4 reading Telugu script.
- (B) Ship the broken vision feature as a negative-result writeup. 
  Rejected: contest judges score on effective use of the model; 
  negative results don't win the Build track.
- (C) Pivot to Hindi (Devanagari) where Gemma 4's vision may 
  perform better. Rejected: would lose the Hyderabad/Telugu 
  authenticity narrative which is the strongest emotional hook, 
  and Hindi vision performance is unverified — could fail the 
  same way and burn another half-day.

Decision: Option A. The mission ("kids losing their mother tongue 
because parents can't teach the script") is intact regardless of 
input modality. The strongest features of the original design — 
the parent dashboard with English summaries, the agentic session 
planner, the personal hook — all carry forward unchanged. Most of 
the existing infrastructure (model abstraction, eval harness, 
Telugu generation gate, decisions log) reuses directly. The 
architectural split (deterministic kid loop, agentic planner) 
also reuses; only the kid loop's input modality changes.

New v1 product shape:
- Kid sees a Telugu letter on screen with English transliteration.
- Audio plays the letter pronunciation (Google TTS, Gate 4 to 
  validate).
- Kid taps among 4 options to identify the letter they just heard 
  (Interaction 2: tap-to-recognize). This is the v1 core loop — 
  pure UI, no vision, no STT, ships fast.
- Optional Phase 6: if time permits, add Interaction 1 — kid reads 
  the letter or word aloud, audio captured and evaluated via 
  Google Cloud Speech-to-Text + Gemma 4 comparing transcription to 
  expected. Defer to v2 if Phase 6 gets cut.

What Gemma 4 does in the new design (still substantive):
- Generates curriculum content: letter sets, distractor options 
  for multiple-choice, simple words, rhymes (Gate 2 PASS confirms 
  this works).
- Runs the agentic session planner at session boundaries (Phase 
  5.5 unchanged — the planner is text-and-tool-calling, no vision).
- Produces parent dashboard English summaries from session data.
- Adapts difficulty based on kid's progress history (256K context 
  holds full history in a single call).

What changes in CLAUDE.md / PLAN.md:
- "Why Gemma 4" section: drop the multimodal-vision claim. Replace 
  with multilingual generation, function calling for structured 
  outputs, 256K context for stateless session reasoning, configurable 
  thinking mode for the planner, open weights for local generation 
  if desired in v2.
- V1 Scope: replace "Kid writes the letter on paper, photographs, 
  Gemma 4 evaluates" with "Kid taps the matching letter from 4 
  options after hearing it pronounced."
- Non-Goals: photo-feedback explicitly out of v1; vision-based 
  features are v2+.
- Phase 3 (thin slice): tap-to-recognize end-to-end on one letter 
  set, no vision pipeline.
- Phase 4-5: deepen the recognition loop and parent dashboard 
  unchanged in spirit, just no vision.
- Phase 5.5 planner: unchanged — was always text-and-tool-calling.
- Phase 6: read-aloud track as optional add (was Hindi 
  generalization; now read-aloud).
- Writeup framing: "I tried photo-feedback first, hit a model 
  capability boundary, pivoted to a design that uses Gemma 4 
  where it actually shines (multilingual generation + agentic 
  reasoning) instead of where the spec sheet promised it would 
  (Indic-script vision)." This honest engineering judgment IS 
  the architectural story for the writeup.

Lesson carrying forward: model spec sheets are claims to be 
tested, not facts. Day-1 evals saved 12 days of building on a 
broken foundation. The same discipline applies to remaining 
Gemma 4 capability claims (function calling reliability, 
thinking mode quality, 256K context utility) — verify with a 
small smoke test before integrating, not after.

Phase 1 step 10 (OpenRouter rate-limit stress test) and step 11 
(Gate 4 TTS quality check) still pending. Both apply unchanged 
to the new design. Resume after CLAUDE.md and PLAN.md are 
updated.

## 2026-05-10 — Phase 1.5 Gate 5: OpenRouter rate-limit stress test results

Ran eval/stress_openrouter.py: 50 sequential trivial-prompt requests 
("respond with the word ok") to google/gemma-4-31b-it:free via 
query_gemma(model="cloud") with BYOK (personal Google AI Studio 
key in OpenRouter). Full per-request log saved at 
eval/results/openrouter_ratelimit_20260510T043436Z.txt.

Results:
- Total wall time: 149.83s. Throughput: 20.02 requests/min.
- Success: 20/50 (40.0%).
- 429s: 12. One returned the explicit message "Rate limit exceeded: 
  free-models-per-min" with header X-RateLimit-Limit: 20 and 
  X-RateLimit-Remaining: 0. The 20.02 req/min throughput exactly 
  matches the 20-per-min cap — the cap is the binding constraint.
- 502s: 18. All carried upstream payload "Internal error 
  encountered. status: INTERNAL" from Google AI Studio (code 500 
  surfaced through OpenRouter as 502). Not rate-limit related; 
  upstream backend instability.
- Latency on the 20 successes: median 5302ms, p95 15421ms, max 
  15666ms.

Three orthogonal problems exposed:
1. **Rate cap.** Free tier hard-caps 20 req/min at OpenRouter's 
   free-models layer regardless of which key is used. Sustained 
   sequential load is rate-limited by design.
2. **Upstream instability.** ~36% of requests returned 502 from 
   Google AI Studio internal errors. Cannot be fixed client-side; 
   needs retry logic.
3. **Latency variance.** p95 of 15.4s and max of 15.7s on 
   successes far exceeds CLAUDE.md's sub-2s kid-loop budget. Even 
   when the call succeeds, the kid waits.

Implication: the kid loop cannot do many sequential Gemma 4 calls 
per session on free tier without retry pain and visible latency 
spikes. Architecture mitigation captured as a separate entry below.

## 2026-05-10 — Correction: BYOK fixed shared-pool 429s, not per-minute cap

The 2026-05-09 "API connectivity verified end-to-end" entry stated 
"no upstream rate limits with personal key." Gate 5 data shows that 
was overstated. BYOK (registering a personal Google AI Studio key 
in OpenRouter Settings → Integrations) eliminated the *shared-pool 
exhaustion* 429s seen during the initial test, but did not lift 
OpenRouter's free-models-per-min cap of 20/min, which is enforced 
at the free-tier layer and applies regardless of which key is used. 
This entry is a documentation correction; append-only discipline 
holds and the original entry stands as-is.

## 2026-05-10 — Architecture mitigation for free-tier reliability

In response to the Gate 5 findings (20 req/min cap, ~36% upstream 
502s, p95 15s latency), the following decisions are committed for 
implementation in upcoming phases:

1. **Bundle kid-session Gemma 4 calls into the planner.** The 
   Phase 5.5 session planner will pre-generate distractors and 
   feedback variants for every step in its single agentic call, so 
   the kid loop renders from the cached SessionPlan instead of 
   calling Gemma 4 per step. Reduces kid-session Gemma 4 calls 
   from ~14 (one per recognition + one per feedback across a 7-step 
   session) to 1 (the planner call at session start). This makes 
   the 20/min cap a non-issue for normal usage and drops kid-loop 
   latency to TTS + UI only.
2. **Retry-with-exponential-backoff on the planner call.** 1s, 3s, 
   9s waits between attempts; 3 retries max. On full failure, fall 
   back to the deterministic curriculum heuristic from Phase 4 
   (`force_fallback=True` path already specified in PLAN.md Phase 
   5.5 step 1). The kid never sees the failure.
3. **Cache Google Cloud TTS audio per (character, voice) pair.** 
   On-disk cache keyed by SHA of (text, voice, language). Most 
   curriculum letters repeat across sessions; cache hits will 
   dominate. Improves perceived speed during demo and reduces TTS 
   API spend.
4. **Defer paid OpenRouter credits.** Re-evaluate after Phase 3 
   thin-slice load testing. If the bundling decision (1) brings 
   kid-session calls to 1, free tier should suffice. Paid credits 
   become a Phase 8 hardening question, not a Phase 1.5 blocker.

These mitigations preserve the v1 cloud-only architecture without 
introducing new dependencies or relaxing the deterministic kid 
loop / agentic planner split from CLAUDE.md.

## 2026-05-10 — Phase 1.5 Gate 4: Google Cloud TTS quality — PASS

Generated 10 Telugu TTS samples (5 phrases × 2 voices) via 
eval/gen_tts_samples.py using Google Cloud TTS API, speakingRate=0.85, 
MP3 encoding, languageCode=te-IN. Samples saved to 
eval/tts_samples/ with manifest.txt for reviewer reference.

Phrases tested: అ (vowel), క (consonant), నమస్కారం (greeting), 
అమ్మ (word), చాలా బాగా (encouragement — highest-stakes phrase since 
it plays multiple times per kid session).

Telugu-literate reviewer (Avinash's wife) listened to all 10 samples 
and rated quality acceptable for child-appropriate use. Verdict: 
**te-IN-Standard-A** (female voice) chosen as the v1 default. 
Pronunciation accurate across all phrase types including isolated 
letters; tone warm enough for repeated kid exposure.

Configuration committed: TTS_PROVIDER=google, voice=te-IN-Standard-A, 
speakingRate=0.85, encoding=MP3. The voice and rate values will be 
read from .env in app/tts.py during Phase 3 wiring.

Gate 4 PASS. All four Day-1 evaluation gates that materially affect 
v1 viability are now resolved (Gate 1 vision: passed but moot post-pivot; 
Gate 2 generation: PASS; Gate 3 handwriting: FAIL → triggered pivot; 
Gate 4 TTS: PASS; Gate 5 rate limits: data captured, mitigations 
specified). Phase 1.5 formally closes.

## 2026-05-10 — Phase 1 formally closed

All Day-1 evaluation gates are resolved. The pivot from photo-feedback 
to tap-to-recognize stands; the architecture mitigation for free-tier 
reliability (planner bundling + retry + TTS caching) is committed for 
Phase 4-5.5 implementation; TTS voice and configuration are chosen.

Project state: Phase 0 ✓, Phase 1 ✓ (with pivot mid-phase), Phase 1.5 ✓.
Next: PLAN.md update to reflect planner-bundling architecture (Phases 
4 and 5.5 contracts changed), then Phase 2 (schema definitions for 
the bundled planner contract).

Days remaining to deadline: 14.

## 2026-05-11 — Phase 2 Gate 6: Structured-output / function-calling smoke test — PASS

Ran eval/smoke_structured.py against google/gemma-4-31b-it:free via 
OpenRouter (BYOK), forcing a tool_choice for a single 
return_letter_entry tool whose parameters mirror the LetterEntry 
Pydantic schema. Two runs total. Combined: 8 of 8 model responses 
returned valid tool calls with Pydantic-parseable arguments. The 
function-calling mechanism on Gemma 4 31B is reliable for the 
planner-bundling architecture (Phase 5.5 depends on it).

Run breakdown:
- Run 1 (no-retry, eval/results/smoke_structured_20260510T190320Z.json):
  3/5 succeeded; 2/5 hit upstream 502s from Google AI Studio 
  ("Internal error encountered" — same Gate 5 pattern). Of the 3 
  calls that reached the model, 3/3 used the tool-call mechanism 
  and 3/3 parsed cleanly into LetterEntry.
- Run 2 (retry-armed, eval/results/smoke_structured_20260510T190623Z.json):
  5/5 succeeded; 0 retries triggered (upstream cooperated). Latency 
  on success: median 3472ms, max 9283ms — within CLAUDE.md's 10s 
  planner-budget.

Response shape verified (matters for the future query_gemma 
extension and the Phase 5.5 planner code):
- choices[0].finish_reason == "tool_calls" is the success signal.
- choices[0].message.content is null on tool-call responses (no 
  parallel free-text content).
- choices[0].message.tool_calls[i].function.arguments is a JSON 
  STRING, not a parsed object — requires json.loads before pydantic 
  validation.
- choices[0].message.reasoning_details carries an 
  "reasoning.encrypted" blob (Google Gemini multi-turn reasoning 
  state) alongside tool calls. Not used in v1; flagged for Phase 5.5 
  if the planner ever needs to thread reasoning state across multiple 
  tool-call rounds.

Open question carried forward: retry-with-backoff under real 502 
load. The retry logic in eval/smoke_structured.py is paper-correct 
but did not fire in vivo this run. Phase 5.5 step 2's planner smoke 
test inherits responsibility for verifying retry behavior on the 
production planner call under realistic load. The eval/smoke_structured.py 
retry code is throwaway infrastructure and is not the implementation 
that ships.

Gate 6 PASS. Phase 2 step 5 acceptance met. Phase 5.5 can rely on 
Gemma 4 31B's function-calling mechanism without further capability 
gating.

## 2026-05-11 — Phase 2 closed

All Phase 2 acceptance criteria met:
- app/model.py default flipped to model="cloud" (verified by smoke 
  test).
- Pydantic schemas defined in app/prompts.py with discriminated 
  union on step_type, Language and Difficulty Literal aliases, 
  strict validation (min/max length on distractors, ge=0 on 
  step_index).
- Three planner tool definitions hand-built as OpenAI-compatible 
  function dicts: get_recent_sessions (n ≤ 30), get_letter_accuracy 
  (letters ≤ 200), get_curriculum (language + scope enums).
- Three versioned prompts: PLANNER_PROMPT_V1 (with cold-start 
  handling, bundled-output contract, difficulty rules matching 
  Phase 4 deterministic spec), SESSION_SUMMARY_PROMPT_V1, 
  LETTER_ENTRY_SMOKE_PROMPT_V1.
- Gate 6 PASS: 8/8 valid tool calls across two runs, 5/5 retry-armed 
  run, response shape verified for future query_gemma extension.
- writeup/draft.md "Why Gemma 4" section drafted (520 words, four 
  capabilities + rejected vision, every claim cited or quantified). 
  Open-weights point moved to Tradeoffs section.

Phase 2 deliverables establish the structured-output contract that 
Phase 5.5 (planner) and Phase 5 (parent dashboard summary) depend on. 
Function calling on Gemma 4 31B via OpenRouter is verified reliable; 
the planner-bundling architecture is buildable.

Next: Phase 3 — thin end-to-end slice (tap-to-recognize on one 
hardcoded letter, no curriculum logic, no planner, prove the 
product is possible).

Days remaining to deadline: 13.

## 2026-05-11 — Phase 3 closed: thin end-to-end slice working

The kid-loop thin slice runs end-to-end in the browser. Phase 3 
acceptance criteria met: from page load to feedback display, no 
manual steps between, no Gemma 4 calls during the loop, both
correct and wrong paths verified visually.

Files delivered:
- app/tts.py (50 lines) — synthesize() over Google Cloud TTS, 
  reads voice and speakingRate from .env per Gate 4 verdict.
- app/main.py (~75 lines) — /healthz, GET /, POST /api/pronounce, 
  POST /api/check_recognition. Hardcoded feedback pools 
  (_PHASE3_POSITIVE, _PHASE3_RETRY) replaced in Phase 5.5 by 
  per-step FeedbackVariants from the planner.
- static/kid.html (~155 lines) — layout, vanilla JS state machine, 
  Fisher-Yates shuffle on the 4 options, audio playback via 
  hidden <audio> element, visual feedback (green/red border) on 
  the tapped button.

Verification:
- TTS audio plays correct female Telugu (te-IN-Standard-A) on 
  "Hear it" tap. MP3 byte-matches eval/tts_samples/vowel_A.mp3 
  from Gate 4.
- Correct tap (అ): green border, positive feedback ("Perfect!" / 
  "Great!" / "Yes! That's అ" — randomization across reloads).
- Wrong tap (ఆ): red border, retry feedback ("Try again — listen 
  carefully" / "Not quite — listen for the sound").
- Page reload reshuffles option order — button positions verified 
  to vary across multiple loads.

What this proves architecturally:
- The bundling contract works in practice. The kid taps a button, 
  /api/check_recognition returns a hardcoded feedback string, no 
  Gemma 4 call occurs. When Phase 5.5 lands, the planner will 
  populate per-step FeedbackVariants in the SessionPlan; the kid 
  loop's contract stays identical, only the source of feedback 
  strings changes.
- Sub-second round-trip on tap, demonstrably faster than any 
  Gemma-4-in-the-loop alternative would be (Gate 5 showed p95 
  15.4s on Gemma 4 cloud calls).

Next: Phase 4 — practice loop deepening (curriculum, full vowel 
set, deterministic distractor selection from confusion_set, 
session storage in SQLite, retry-on-wrong UX). Days remaining: 13.

## 2026-05-11 — Phase 5 closed: parent dashboard with PIN gate and Gemma-4 English summary

The parent dashboard ships. PIN-gated, today's data aggregated from
SQLite, English summary paragraph generated by Gemma 4 once per
dashboard load. Failure of the model call degrades gracefully —
data renders, summary card shows a stub line. Empty state for days
with no sessions.

Files delivered:
- app/session.py (184 lines) — added settings table and 5 PIN/setting
  functions (get_setting, set_setting, get_parent_pin, set_parent_pin
  with 3-6 digit validation, is_parent_pin_default).
- app/parent.py (176 lines) — get_today_summary() aggregates IST
  midnight-to-midnight sessions and attempts; generate_english_summary()
  is one-shot Gemma 4 via direct OpenRouter POST, returns stub on
  no-data path or error path. Retry-with-backoff deferred to Phase 5.5
  (shared wrapper with planner) and Phase 8 (hardening).
- app/main.py (220 lines) — 4 new endpoints: GET /parent, POST
  /api/parent/login (with sleep(0.5) brute-force mitigation), POST
  /api/parent/change_pin (auth-required), GET /api/parent/today
  (auth-required, calls Gemma 4 once). Cookie-based session via
  _pin_token = SHA256(stored PIN); PIN change rotates the cookie.
- static/parent.html (409 lines) — three-state UI: login → must-
  change-PIN (forced first-time flow) → dashboard. Voluntary Change
  PIN flow accessible from dashboard header link with Cancel and
  toast confirmation. Letters grid, stats row, English summary card
  (orange left-border accent for prominence), strong/needs/suggested
  pill lists with defensive filter against comma-strings and duplicates.
- static/kid.html updates (256 lines) — added "Parent dashboard"
  footer link visible on all kid-page states.

Three bugs caught and fixed during Phase 5:

1. CSS specificity: `#practice { display: flex }` and `.end-card
   { display: flex }` rules had higher specificity than UA stylesheet's
   `[hidden] { display: none }`, causing the hidden attribute to
   silently fail. Result: end-of-session card leaked into the practice
   screen on the last step. Fixed by adding `[hidden] { display: none
   !important; }` to both kid.html and parent.html stylesheets.

2. Missing parent navigation: kid page had no link to /parent route,
   forcing parents to type URLs manually. Added discreet "Parent
   dashboard" footer link to kid.html (always visible) and reciprocal
   "Back to practice" link in parent.html header.

3. Model output quirk: Gemma 4 occasionally jammed multiple letters
   into a single array entry as a comma-separated string like
   '"ఇ", "ఆ", "జ"', visible in the needs_practice pill list. Fixed
   with two-layer defense: (a) added CRITICAL clause to
   SESSION_SUMMARY_PROMPT_V1 requiring single-glyph entries; (b)
   defensive frontend filter in renderPillSection rejecting non-string,
   empty, length > 4, or containing comma/quote/whitespace, plus
   Set-based dedupe.

Verification:
- PIN flow walked end-to-end in browser: default 4242 → wrong PIN
  shows error → correct PIN → forced change-PIN screen → set new
  PIN → dashboard loads with data.
- English summary paragraph reads naturally for a non-script-reading
  parent. Mentions letters by English transliteration, warm tone,
  forward-looking close. Example output: "Your child practiced a
  wide variety of vowels and consonants today. They were very
  confident with most of the letters, including the long vowels and
  several consonants. However, they struggled a bit more with the
  vowels i and aa, as well as the letters ja and kha, which we will
  continue to work on."
- Pill sections render clean single-glyph entries after the bundled
  fix. Verified across multiple model output samples.
- Graceful degradation verified organically via a real Gate-5-pattern
  502 during initial testing. Dashboard rendered data with "Summary
  unavailable" stub message in summary card.
- End-card visibility fix verified visually across all session steps
  (hidden during practice, appears with correct count after Done).
- Parent ↔ kid navigation works both directions.

Observed call latency: 5-7s median per /api/parent/today, consistent
with Gate 5 baseline (median 5.3s, p95 15.4s). Loading spinner
covers the wait. Acceptable for parent-triggered manual refresh;
would be unacceptable in kid loop, which is why kid loop has zero
Gemma 4 calls by architectural invariant.

Convention learned (carry into Phase 5.5):
Verification scripts that mutate production state must either use
isolated DB paths or clean up after. Phase 5 verification curl
tests changed the default PIN to 1357, which blocked the user's
subsequent browser walkthrough until SQLite was manually reset.
Phase 5.5 planner verification will create synthetic session
histories to test scenarios — those rows must not pollute the
production DB.

Architectural note for the writeup:
The parent dashboard is the first production code path that calls
Gemma 4 from a user-facing flow. The kid loop has zero model calls
(architectural invariant). The dashboard call is one-shot — Phase
5.5 adds a shared retry-with-backoff wrapper that both the planner
and this summary call will eventually use. This is the first
in-the-product evidence that the planner-bundling architecture
preserves UX even under free-tier reliability constraints: the kid
never waits for Gemma 4; the parent triggers the model call
manually and tolerates seconds of latency at dashboard load.

Days remaining to deadline: 13.