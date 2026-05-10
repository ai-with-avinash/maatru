"""TTS wrapper. Single synthesize() interface over Google Cloud TTS.

Voice and speakingRate come from .env (Gate 4 verdict: te-IN-Standard-A, 0.85).
No caching in v1; per-step TTS caching is a Phase 6 mitigation.
"""
import base64
import os
from typing import Literal

import httpx
from dotenv import load_dotenv

load_dotenv()
_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
_DEFAULT_VOICE = os.getenv("TTS_VOICE", "te-IN-Standard-A")
_DEFAULT_SPEAKING_RATE = float(os.getenv("TTS_SPEAKING_RATE", "0.85"))
_TIMEOUT_S = 30.0
_LANGUAGE_CODE_MAP: dict[str, str] = {"te": "te-IN", "hi": "hi-IN"}


async def synthesize(text: str, language: Literal["te", "hi"] = "te") -> bytes:
    """Synthesize Telugu/Hindi text to MP3 bytes via Google Cloud TTS.

    Reads GOOGLE_TTS_API_KEY at call time. Raises RuntimeError on missing key
    or HTTP/protocol errors so FastAPI handlers can convert to 500 responses.
    """
    api_key = os.getenv("GOOGLE_TTS_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_TTS_API_KEY missing from environment")
    if language not in _LANGUAGE_CODE_MAP:
        raise ValueError(f"unsupported language: {language!r}")

    payload = {
        "input": {"text": text},
        "voice": {"languageCode": _LANGUAGE_CODE_MAP[language], "name": _DEFAULT_VOICE},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": _DEFAULT_SPEAKING_RATE},
    }
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
    return base64.b64decode(audio_b64)
