"""FastAPI entrypoint for Maatru. Phase 4: multi-step deterministic kid loop.

No Gemma 4 calls in any kid-loop endpoint per the planner-bundling
architecture (decisions.md 2026-05-10). /api/session/start picks letters via
the least-practiced heuristic and builds RecognitionStep-shaped payloads with
deterministic distractors + FALLBACK_FEEDBACK_VARIANTS. The kid loop reads
from that payload only. Phase 5.5 swaps the producer to the agentic planner;
the shape stays identical.
"""
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.curriculum import (
    FALLBACK_FEEDBACK_VARIANTS,
    TELUGU_CURRICULUM,
    select_distractors,
    select_session_letters,
)
from app.session import create_session, end_session, init_db, record_attempt
from app.tts import synthesize

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STATIC_DIR = _REPO_ROOT / "static"
_KID_HTML = _STATIC_DIR / "kid.html"


class PronounceRequest(BaseModel):
    character: str = Field(..., min_length=1)
    language: Literal["te", "hi"] = Field(default="te")


class SessionStartRequest(BaseModel):
    language: Literal["te", "hi"] = Field(default="te")
    session_size: int = Field(default=5, ge=1, le=10)


class StepLetter(BaseModel):
    character: str
    transliteration: str


class SessionStepDTO(BaseModel):
    step_index: int
    target: StepLetter
    distractors: list[StepLetter]
    feedback: dict[str, list[str]]


class SessionStartResponse(BaseModel):
    session_id: str
    language: str
    steps: list[SessionStepDTO]


class CheckRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    step_index: int = Field(..., ge=0)
    target: str = Field(..., min_length=1)
    chosen: str = Field(..., min_length=1)
    feedback_used: str = Field(..., min_length=1)


class CheckResponse(BaseModel):
    correct: bool


class SessionEndRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


app = FastAPI(title="Maatru", version="0.2.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def kid_root() -> FileResponse:
    if not _KID_HTML.is_file():
        raise HTTPException(status_code=500, detail="kid.html missing")
    return FileResponse(_KID_HTML, media_type="text/html")


@app.post("/api/pronounce")
async def api_pronounce(req: PronounceRequest) -> Response:
    try:
        audio = await synthesize(req.character, language=req.language)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"TTS failure: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/session/start", response_model=SessionStartResponse)
async def api_session_start(req: SessionStartRequest) -> SessionStartResponse:
    init_db()
    if req.language != "te":
        raise HTTPException(status_code=400, detail=f"language {req.language!r} not supported in v1")
    picks = select_session_letters(TELUGU_CURRICULUM, session_size=req.session_size)
    if not picks:
        raise HTTPException(status_code=500, detail="curriculum empty")
    steps: list[SessionStepDTO] = []
    for idx, entry in enumerate(picks):
        distractors = select_distractors(entry, "medium", TELUGU_CURRICULUM)
        steps.append(SessionStepDTO(
            step_index=idx,
            target=StepLetter(character=entry.character, transliteration=entry.letter.transliteration),
            distractors=[StepLetter(character=d.character, transliteration=d.letter.transliteration) for d in distractors],
            feedback=FALLBACK_FEEDBACK_VARIANTS,
        ))
    session_id = create_session(language=req.language, focus="phase 4 deterministic", fallback_used=True)
    return SessionStartResponse(session_id=session_id, language=req.language, steps=steps)


@app.post("/api/check_recognition", response_model=CheckResponse)
async def api_check_recognition(req: CheckRequest) -> CheckResponse:
    correct = req.target == req.chosen
    record_attempt(req.session_id, req.step_index, req.target, req.chosen, correct, req.feedback_used)
    return CheckResponse(correct=correct)


@app.post("/api/session/end")
async def api_session_end(req: SessionEndRequest) -> dict[str, bool]:
    end_session(req.session_id)
    return {"ok": True}
