"""Eval harness: runs a named prompt set against both local and cloud Gemma 4, saves timestamped results."""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.model import query_gemma  # noqa: E402

PROMPTS_DIR = REPO_ROOT / "eval" / "prompts"
RESULTS_DIR = REPO_ROOT / "eval" / "results"


def _resolve_image_path(image_path: str | None) -> str | None:
    if not image_path:
        return None
    p = Path(image_path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(p)


async def _run_one(entry: dict) -> dict:
    prompt_id = entry.get("prompt_id") or entry.get("id") or "unnamed"
    prompt_text = entry["prompt_text"]
    image_path = _resolve_image_path(entry.get("image_path"))

    result: dict = {
        "prompt_id": prompt_id,
        "prompt_text": prompt_text,
        "image_path": image_path,
        "local_response": None,
        "cloud_response": None,
        "local_latency_ms": None,
        "cloud_latency_ms": None,
        "error": None,
    }
    errors: list[str] = []

    t0 = time.perf_counter()
    local = await query_gemma(prompt_text, image_path=image_path, model="local")
    result["local_latency_ms"] = int((time.perf_counter() - t0) * 1000)
    if local["ok"]:
        result["local_response"] = local["text"]
    else:
        errors.append(f"local: {local['error']}")

    t1 = time.perf_counter()
    cloud = await query_gemma(prompt_text, image_path=image_path, model="cloud")
    result["cloud_latency_ms"] = int((time.perf_counter() - t1) * 1000)
    if cloud["ok"]:
        result["cloud_response"] = cloud["text"]
    else:
        errors.append(f"cloud: {cloud['error']}")

    if errors:
        result["error"] = "; ".join(errors)
    return result


async def _warmup_local() -> None:
    # Throwaway local call before the timed loop. Ollama keeps the model in memory
    # for keep_alive after the first request, so the first prompt of a run otherwise
    # absorbs the cold-start cost (observed ~30s on tg_01 in the generation eval).
    # Failures here are not fatal — the timed loop will surface them per-prompt.
    print("[warmup] local model...", flush=True)
    t = time.perf_counter()
    res = await query_gemma("ping", model="local", timeout=120.0)
    dur = int((time.perf_counter() - t) * 1000)
    status = "ok" if res["ok"] else f"failed ({res['error']})"
    print(f"[warmup] {status} in {dur}ms", flush=True)


async def _run_set(set_name: str) -> Path:
    prompt_file = PROMPTS_DIR / f"{set_name}.json"
    if not prompt_file.exists():
        raise FileNotFoundError(f"prompt set not found: {prompt_file}")
    entries = json.loads(prompt_file.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError(f"expected JSON list at top level of {prompt_file}, got {type(entries).__name__}")

    await _warmup_local()

    results: list[dict] = []
    total = len(entries)
    for i, entry in enumerate(entries, start=1):
        label = entry.get("prompt_id") or entry.get("id") or f"entry_{i}"
        print(f"[{i}/{total}] {label}", flush=True)
        res = await _run_one(entry)
        if res["error"]:
            print(f"    ! {res['error']}", flush=True)
        else:
            print(f"    local {res['local_latency_ms']}ms / cloud {res['cloud_latency_ms']}ms", flush=True)
        results.append(res)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"{set_name}_{ts}.json"
    payload = {"set_name": set_name, "timestamp": ts, "results": results}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an eval prompt set against local + cloud Gemma 4.")
    parser.add_argument("set_name", help="Name of prompt set (without .json), e.g. telugu_generation")
    args = parser.parse_args()
    try:
        asyncio.run(_run_set(args.set_name))
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except (ValueError, KeyError) as e:
        print(f"ERROR: malformed prompt set: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
