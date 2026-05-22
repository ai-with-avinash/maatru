# Maatru

A Telugu literacy companion for kids whose parents can speak the language but lost the script.

## What this is

Maatru is a small web app for parents like me — Telugu speakers raising kids in English-medium schools, who can't comfortably teach the Telugu writing system because we've lost it ourselves. A kid taps Start, hears a Telugu letter spoken aloud, and taps the matching letter from four options. After five letters they see a "Great job" card. A separate parent dashboard (PIN-gated) shows what the kid practiced — in English — alongside the AI's pedagogical reasoning for why those letters were chosen.

Built for the [dev.to Gemma 4 Challenge: Build with Gemma 4](https://dev.to/challenges/google-gemma-2026-05-06).

## Architecture at a glance

Two layers, deliberately separated:

- **Layer 1 (kid loop):** Deterministic, zero Gemma 4 calls during a session. Renders from a cached SessionPlan. Sub-second response on every tap.
- **Layer 2 (planner):** One agentic Gemma 4 call at session start. Uses function calling to read the kid's history from SQLite, then returns a bundled SessionPlan with target letters, distractors, feedback variants, and a paragraph of pedagogical reasoning visible on the parent dashboard.

The planner call is wrapped in retry-with-backoff (1s, 3s, 9s) with a deterministic curriculum fallback if Gemma 4 is unreachable. The kid never sees the model fail.

See [`decisions.md`](./decisions.md) for the full engineering log including the pivot story, evaluation gates, architectural rationale, and every nontrivial decision made during the build.

## Setup

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/ai-with-avinash/maatru.git
cd maatru
uv sync
cp .env.example .env
# Edit .env: add OPENROUTER_API_KEY and GOOGLE_TTS_API_KEY
```

## Run

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open:

- Kid loop: http://localhost:8000
- Parent dashboard: http://localhost:8000/parent (default PIN: `4242`, forced change on first login)

## Repo map

```
app/             FastAPI backend, planner, tools, TTS
static/          kid.html and parent.html (vanilla JS, no build step)
eval/            verification scripts, scorecards, Gate-3 handwriting samples
writeup/         dev.to article draft and assets
data/            SQLite database and TTS cache (gitignored)
decisions.md     engineering log (append-only, dated entries)
CLAUDE.md        project identity and architectural rules
PLAN.md          phased build plan
.env.example     environment variable template
pyproject.toml   dependencies (uv-managed)
```

## License

Apache-2.0 — see [LICENSE](./LICENSE).
