"""Phase 1.5 Gate 4: generate Telugu TTS samples for human review.

Produces 10 MP3s (5 phrases x 2 voices) in eval/tts_samples/, plus a manifest.txt
listing each file with text, transliteration, and voice.
"""
import asyncio
import base64
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "eval" / "tts_samples"
TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
LANGUAGE_CODE = "te-IN"
SPEAKING_RATE = 0.85

PHRASES: list[dict[str, str]] = [
    {"label": "vowel", "text": "అ", "translit": "a"},
    {"label": "consonant", "text": "క", "translit": "ka"},
    {"label": "greeting", "text": "నమస్కారం", "translit": "namaskaram"},
    {"label": "word", "text": "అమ్మ", "translit": "amma"},
    {"label": "encouragement", "text": "చాలా బాగా", "translit": "chala baga"},
]
VOICES: list[dict[str, str]] = [
    {"suffix": "A", "name": "te-IN-Standard-A"},
    {"suffix": "B", "name": "te-IN-Standard-B"},
]


async def _synthesize(client: httpx.AsyncClient, api_key: str, text: str, voice_name: str) -> bytes:
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": LANGUAGE_CODE, "name": voice_name},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": SPEAKING_RATE},
    }
    r = await client.post(TTS_URL, params={"key": api_key}, json=payload)
    r.raise_for_status()
    audio_b64 = r.json()["audioContent"]
    return base64.b64decode(audio_b64)


async def _run() -> None:
    load_dotenv()
    api_key = os.getenv("GOOGLE_TTS_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_TTS_API_KEY missing from .env")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest_lines: list[str] = [
        "Gate 4 — Telugu TTS samples for human review",
        f"speakingRate={SPEAKING_RATE}, encoding=MP3, languageCode={LANGUAGE_CODE}",
        "Rate each on (1) pronunciation accuracy and (2) child-appropriate naturalness, 1-5 scale.",
        "",
        f"{'filename':<32} {'voice':<6} {'translit':<14} text",
        "-" * 72,
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        for phrase in PHRASES:
            for voice in VOICES:
                filename = f"{phrase['label']}_{voice['suffix']}.mp3"
                out_path = OUT_DIR / filename
                print(f"[tts] {filename} <- {phrase['text']} ({voice['name']})", flush=True)
                audio = await _synthesize(client, api_key, phrase["text"], voice["name"])
                out_path.write_bytes(audio)
                manifest_lines.append(
                    f"{filename:<32} {voice['suffix']:<6} {phrase['translit']:<14} {phrase['text']}"
                )

    manifest_path = OUT_DIR / "manifest.txt"
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(f"\nSaved {len(PHRASES) * len(VOICES)} samples to {OUT_DIR}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    asyncio.run(_run())
