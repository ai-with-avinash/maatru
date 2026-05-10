"""Single abstraction over Gemma 4: local Ollama (E4B) and cloud OpenRouter (31B)."""
import base64
import mimetypes
import os
from pathlib import Path
from typing import Any
import httpx
from dotenv import load_dotenv

load_dotenv()
_OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
_OPENROUTER_URL = "https://openrouter.ai/api/v1"
_MODEL_LOCAL = os.getenv("MODEL_LOCAL", "gemma4:e4b")
_MODEL_CLOUD = os.getenv("MODEL_CLOUD", "google/gemma-4-31b-it:free")
_DEFAULT_TIMEOUT = 60.0


def _build_messages(prompt: str, image_path: str | Path | None) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if image_path is not None:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return [{"role": "user", "content": content}]


async def query_gemma(
    prompt: str,
    image_path: str | Path | None = None,
    model: str = "cloud",
    thinking: bool = False,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Single call to Gemma 4. Returns {ok, text, error, raw}; never raises."""
    if model == "local":
        url, model_id = f"{_OLLAMA_URL}/chat/completions", _MODEL_LOCAL
        headers = {"Content-Type": "application/json"}
    elif model == "cloud":
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return {"ok": False, "text": None, "error": "OPENROUTER_API_KEY missing", "raw": None}
        url, model_id = f"{_OPENROUTER_URL}/chat/completions", _MODEL_CLOUD
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    else:
        return {"ok": False, "text": None, "error": f"unknown model: {model}", "raw": None}

    payload: dict[str, Any] = {"model": model_id, "messages": _build_messages(prompt, image_path)}
    if thinking:
        payload["reasoning"] = {"effort": "medium"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        return {"ok": True, "text": data["choices"][0]["message"]["content"], "error": None, "raw": data}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "text": None, "error": f"http {e.response.status_code}: {e.response.text[:200]}", "raw": None}
    except (httpx.RequestError, KeyError, ValueError) as e:
        return {"ok": False, "text": None, "error": f"{type(e).__name__}: {e}", "raw": None}
