# Decisions Log — Maatru

Append-only record of nontrivial decisions. Each entry is dated and explains *why*, not just *what*. Do not edit prior entries; supersede with a new one if a decision changes.

## Entry template

```
## YYYY-MM-DD — <short title>
**Decision:** <what was chosen>
**Why:** <reason, including alternatives considered>
**Implication:** <what this commits us to / what it forecloses>
```

---

## 2026-05-09 — Project initialized
**Decision:** Stack chosen as Python 3.11+, FastAPI, Ollama (`gemma4:e4b` local) + OpenRouter (`google/gemma-4-31b-it:free` cloud), SQLite, plain HTML frontend. Package management via `uv`.
**Why:** Matches CLAUDE.md tech stack; uv is the fastest path on M-series; FastAPI gives async + multipart with no ceremony; SQLite single-file storage avoids any DB ops; plain HTML avoids build tooling and ships in hours, not days. The hybrid local/cloud model split is what gives the writeup its evidence-backed comparison numbers and protects the privacy story (kid's photos stay on E4B local).
**Implication:** All model calls funnel through one `query_gemma()` abstraction with `model="local"|"cloud"` switch. Anything that can't be served from this two-target abstraction (e.g., a third provider) will require a CLAUDE.md update before it ships.
