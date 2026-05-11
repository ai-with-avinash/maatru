"""FastAPI entrypoint for Maatru. Phase 4: multi-step deterministic kid loop.

No Gemma 4 calls in any kid-loop endpoint per the planner-bundling
architecture (decisions.md 2026-05-10). /api/session/start picks letters via
the least-practiced heuristic and builds RecognitionStep-shaped payloads with
deterministic distractors + FALLBACK_FEEDBACK_VARIANTS. The kid loop reads
from that payload only. Phase 5.5 swaps the producer to the agentic planner;
the shape stays identical.
"""
import asyncio
import hashlib
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.curriculum import (
    FALLBACK_FEEDBACK_VARIANTS,
    TELUGU_CURRICULUM,
    select_distractors,
    select_session_letters,
)
from app.parent import generate_english_summary, get_today_summary
from app.session import (
    create_session,
    end_session,
    get_parent_pin,
    init_db,
    is_parent_pin_default,
    record_attempt,
    set_parent_pin,
)
from app.tts import synthesize

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STATIC_DIR = _REPO_ROOT / "static"
_KID_HTML = _STATIC_DIR / "kid.html"
_PARENT_HTML = _STATIC_DIR / "parent.html"
_COOKIE_NAME = "maatru_parent"
_WRONG_PIN_SLEEP_S = 0.5


def _pin_token(pin: str) -> str:
    return "ok-" + hashlib.sha256(pin.encode("utf-8")).hexdigest()[:32]


async def require_parent_auth(maatru_parent: str | None = Cookie(default=None)) -> None:
    init_db()
    expected = _pin_token(get_parent_pin())
    if maatru_parent != expected:
        raise HTTPException(status_code=401, detail="parent auth required")


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


class ParentLoginRequest(BaseModel):
    pin: str = Field(..., min_length=1)


class ParentLoginResponse(BaseModel):
    ok: bool
    must_change_pin: bool


class ParentChangePinRequest(BaseModel):
    current_pin: str = Field(..., min_length=1)
    new_pin: str = Field(..., min_length=1)


app = FastAPI(title="Maatru", version="0.3.0")


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


@app.get("/parent")
async def parent_root() -> FileResponse:
    if not _PARENT_HTML.is_file():
        raise HTTPException(status_code=500, detail="parent.html missing")
    return FileResponse(_PARENT_HTML, media_type="text/html")


@app.post("/api/parent/login", response_model=ParentLoginResponse)
async def api_parent_login(req: ParentLoginRequest, response: Response) -> ParentLoginResponse:
    init_db()
    if req.pin != get_parent_pin():
        await asyncio.sleep(_WRONG_PIN_SLEEP_S)
        raise HTTPException(status_code=401, detail="incorrect PIN")
    response.set_cookie(_COOKIE_NAME, _pin_token(req.pin), httponly=True, samesite="strict", path="/")
    return ParentLoginResponse(ok=True, must_change_pin=is_parent_pin_default())


@app.post("/api/parent/change_pin")
async def api_parent_change_pin(
    req: ParentChangePinRequest,
    response: Response,
    _auth: None = Depends(require_parent_auth),
) -> dict[str, bool]:
    if req.current_pin != get_parent_pin():
        raise HTTPException(status_code=403, detail="current PIN incorrect")
    try:
        set_parent_pin(req.new_pin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    response.set_cookie(_COOKIE_NAME, _pin_token(req.new_pin), httponly=True, samesite="strict", path="/")
    return {"ok": True}


@app.get("/api/parent/today")
async def api_parent_today(_auth: None = Depends(require_parent_auth)) -> dict:
    today_data = get_today_summary()
    summary = await generate_english_summary(today_data)
    summary_keys = ("parent_summary_english", "strong_letters", "needs_practice", "suggested_next")
    return {
        "date_label": today_data["date_label"],
        "sessions_today": today_data["sessions_today"],
        "attempts_total": today_data["attempts_total"],
        "attempts_correct": today_data["attempts_correct"],
        "letters_practiced": today_data["letters_practiced"],
        "summary": {k: summary.get(k, []) if k != "parent_summary_english" else summary.get(k, "") for k in summary_keys},
        "summary_error": summary.get("error"),
    }
