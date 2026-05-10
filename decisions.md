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