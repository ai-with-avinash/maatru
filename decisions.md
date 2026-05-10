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