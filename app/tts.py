"""TTS wrapper. Single synthesize() interface over Google Cloud TTS.

Voice and speakingRate come from .env (Gate 4 verdict: te-IN-Standard-A, 0.85).
Disk cache (Phase 6, decisions.md 2026-05-10 mitigation 3): MP3 bytes are
written to data/tts_cache/<sha16>.mp3 keyed by sha256(text|voice|language).
Cache hits skip the Google Cloud TTS call entirely — most curriculum letters
repeat across sessions, so hits dominate after one warm-up run.
"""
import base64
import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv

load_dotenv()
_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
_DEFAULT_VOICE = os.getenv("TTS_VOICE", "te-IN-Standard-A")
_DEFAULT_SPEAKING_RATE = float(os.getenv("TTS_SPEAKING_RATE", "0.85"))
_TIMEOUT_S = 30.0
_LANGUAGE_CODE_MAP: dict[str, str] = {"te": "te-IN", "hi": "hi-IN"}

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TTS_CACHE_DIR = _REPO_ROOT / "data" / "tts_cache"


def _cache_key(text: str, voice: str, language_code: str) -> str:
    h = hashlib.sha256(f"{text}|{voice}|{language_code}".encode("utf-8")).hexdigest()
    return h[:16]


def _cache_path(key: str) -> Path:
    return _TTS_CACHE_DIR / f"{key}.mp3"


async def synthesize(text: str, language: Literal["te", "hi"] = "te") -> bytes:
    """Synthesize Telugu/Hindi text to MP3 bytes via Google Cloud TTS, with disk cache.

    Reads GOOGLE_TTS_API_KEY at call time. Raises RuntimeError on missing key
    or HTTP/protocol errors so FastAPI handlers can convert to 500 responses.
    """
    if language not in _LANGUAGE_CODE_MAP:
        raise ValueError(f"unsupported language: {language!r}")
    language_code = _LANGUAGE_CODE_MAP[language]
    key = _cache_key(text, _DEFAULT_VOICE, language_code)
    path = _cache_path(key)
    if path.is_file() and path.stat().st_size > 0:
        print(f"[tts] HIT key={key} (text={text})", file=sys.stderr, flush=True)
        return path.read_bytes()

    api_key = os.getenv("GOOGLE_TTS_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_TTS_API_KEY missing from environment")

    payload = {
        "input": {"text": text},
        "voice": {"languageCode": language_code, "name": _DEFAULT_VOICE},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": _DEFAULT_SPEAKING_RATE},
    }
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        try:
            r = await client.post(_TTS_URL, params={"key": api_key}, json=payload)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"TTS http {e.response.status_code}: {e.response.text[:200]}") from e
        except (httpx.RequestError, ValueError) as e:
            raise RuntimeError(f"TTS request failed: {type(e).__name__}: {e}") from e
    audio_b64 = data.get("audioContent")
    if not audio_b64:
        raise RuntimeError("TTS response missing audioContent")
    audio_bytes = base64.b64decode(audio_b64)
    elapsed = time.perf_counter() - t0
    try:
        _TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
        print(f"[tts] MISS key={key} synth in {elapsed:.2f}s (text={text})", file=sys.stderr, flush=True)
    except OSError as e:
        # Cache write failure is non-fatal — surface as a log line, still return audio.
        print(f"[tts] MISS key={key} synth in {elapsed:.2f}s; cache write failed: {e}", file=sys.stderr, flush=True)
    return audio_bytes
