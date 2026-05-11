"""FastAPI entrypoint for Maatru.

Phase 5.5 wired plan_session() into /api/session/start: that endpoint is now
the SOLE producer of session rows for kid-driven flows. plan_session() runs
the agentic planner (and falls back to the deterministic builder on retry
exhaustion or bundling violation). The returned SessionPlan carries
session_id, distractors, feedback variants, and reasoning — kid loop reads
from that payload directly with zero further model calls during the session.
"""
import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.parent import generate_english_summary, get_today_summary
from app.planner import build_deterministic_session_plan, plan_session
from app.prompts import SessionPlan
from app.session import (
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
# Hard ceiling on /api/session/start latency. plan_session() owns its own
# retry-then-fallback logic; this wait_for is a backstop against unexpected
# agentic-loop hangs (e.g., a tool round that never terminates). With
# 4 HTTP attempts × ~15s p95 + (1+3+9) backoff = ~73s worst case if no
# safety net; capping at 45s preserves kid-loop UX even in that edge.
_SESSION_START_HARD_TIMEOUT_S = 45.0


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
    """language is the only request field the planner consumes; the planner
    decides session length (5-8 steps) per its own pedagogical reasoning."""

    language: Literal["te", "hi"] = Field(default="te")


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


@app.post("/api/session/start", response_model=SessionPlan)
async def api_session_start(req: SessionStartRequest) -> SessionPlan:
    """Run the agentic planner; return a fully-bundled SessionPlan.

    Latency is 5-15s on the model-driven path and 1-2s when fallback fires.
    plan_session() owns retries and internal fallback; the wait_for here is
    a double-protection backstop so the kid never sees a hung agentic loop
    surface as a frontend timeout. On wait_for timeout, force the
    deterministic fallback (which also creates the session row) so the kid
    loop always lands on a usable SessionPlan within ~46s.
    """
    init_db()
    if req.language != "te":
        raise HTTPException(status_code=400, detail=f"language {req.language!r} not supported in v1")
    try:
        plan = await asyncio.wait_for(
            plan_session(language=req.language),
            timeout=_SESSION_START_HARD_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        print(
            f"[main] session/start exceeded {_SESSION_START_HARD_TIMEOUT_S}s — forcing fallback",
            file=sys.stderr,
            flush=True,
        )
        plan = build_deterministic_session_plan(language=req.language)
    return plan


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
        "session_plans": today_data["session_plans"],
        "summary": {k: summary.get(k, []) if k != "parent_summary_english" else summary.get(k, "") for k in summary_keys},
        "summary_error": summary.get("error"),
    }
