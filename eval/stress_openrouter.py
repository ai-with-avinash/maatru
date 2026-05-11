"""Phase 1.5 Gate 5: stress test OpenRouter Gemma 4 31B with 50 sequential short prompts."""
import asyncio
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.model import query_gemma  # noqa: E402

RESULTS_DIR = REPO_ROOT / "eval" / "results"
N_REQUESTS = 50
PROMPT = "respond with the word ok"


async def _run() -> Path:
    print(f"[stress] {N_REQUESTS} sequential cloud requests starting", flush=True)
    records: list[dict] = []
    wall_start = time.perf_counter()

    for i in range(1, N_REQUESTS + 1):
        t0 = time.perf_counter()
        res = await query_gemma(PROMPT, model="cloud")
        latency_ms = int((time.perf_counter() - t0) * 1000)
        err = res["error"] if not res["ok"] else None
        is_429 = bool(err and err.startswith("http 429"))
        records.append({"index": i, "latency_ms": latency_ms, "ok": res["ok"], "error": err, "is_429": is_429})
        marker = "ok" if res["ok"] else ("429" if is_429 else "ERR")
        print(f"[{i:02d}/{N_REQUESTS}] {marker} {latency_ms}ms" + (f" — {err}" if err else ""), flush=True)

    wall_total_s = time.perf_counter() - wall_start
    successes = [r for r in records if r["ok"]]
    n_ok = len(successes)
    n_429 = sum(1 for r in records if r["is_429"])
    n_other_err = N_REQUESTS - n_ok - n_429
    rpm = (N_REQUESTS / wall_total_s) * 60 if wall_total_s > 0 else 0.0
    ok_latencies = [r["latency_ms"] for r in successes]
    if ok_latencies:
        med = int(statistics.median(ok_latencies))
        p95 = int(statistics.quantiles(ok_latencies, n=20)[18]) if len(ok_latencies) >= 20 else max(ok_latencies)
        mx = max(ok_latencies)
    else:
        med = p95 = mx = 0

    summary_lines = [
        "=== Gate 5: OpenRouter rate-limit stress test ===",
        f"model: google/gemma-4-31b-it:free (BYOK via personal Google AI Studio key)",
        f"requests: {N_REQUESTS} sequential, prompt='{PROMPT}'",
        f"total wall time: {wall_total_s:.2f}s",
        f"throughput: {rpm:.2f} requests/min",
        f"success: {n_ok}/{N_REQUESTS} ({n_ok / N_REQUESTS * 100:.1f}%)",
        f"429s: {n_429}",
        f"other errors: {n_other_err}",
        f"latency on success — median: {med}ms, p95: {p95}ms, max: {mx}ms",
    ]
    summary = "\n".join(summary_lines)
    print("\n" + summary, flush=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"openrouter_ratelimit_{ts}.txt"
    raw_lines = [
        f"{r['index']:02d}\t{'ok' if r['ok'] else ('429' if r['is_429'] else 'ERR')}\t{r['latency_ms']}ms"
        + (f"\t{r['error']}" if r["error"] else "")
        for r in records
    ]
    out.write_text(summary + "\n\n--- per-request log ---\n" + "\n".join(raw_lines) + "\n", encoding="utf-8")
    print(f"\nSaved: {out}", flush=True)
    return out


if __name__ == "__main__":
    asyncio.run(_run())
