"""Score the handwriting eval: parse model JSON, compare predicted character to expected, report accuracy by source tier and model."""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "eval" / "results"
SOURCES = ("typed", "adult", "child", "similar")
MODELS = ("local", "cloud")

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _latest_results_file() -> Path:
    files = sorted(RESULTS_DIR.glob("telugu_handwriting_*.json"))
    if not files:
        raise FileNotFoundError(f"no telugu_handwriting_*.json under {RESULTS_DIR}")
    return files[-1]


def _expected_from_path(image_path: str | None) -> str | None:
    if not image_path:
        return None
    return Path(image_path).name.split("_")[0]


def _source_from_path(image_path: str | None) -> str | None:
    if not image_path:
        return None
    parts = Path(image_path).name.split("_")
    return parts[1] if len(parts) >= 2 else None


def _extract_character(raw: str | None) -> tuple[str | None, str | None]:
    """Returns (predicted_character, parse_error). predicted is None when parse fails."""
    if raw is None:
        return None, "no response"
    text = _FENCE_RE.sub("", raw).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        match = _OBJ_RE.search(text)
        if not match:
            return None, "no JSON object found"
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            return None, f"JSONDecodeError: {e}"
    if not isinstance(obj, dict):
        return None, f"expected object, got {type(obj).__name__}"
    char = obj.get("character")
    if not isinstance(char, str) or not char:
        return None, "missing or non-string 'character' field"
    return char, None


def _score_entry(entry: dict) -> dict:
    expected = _expected_from_path(entry.get("image_path"))
    source = _source_from_path(entry.get("image_path"))
    out: dict = {
        "prompt_id": entry["prompt_id"],
        "image": Path(entry["image_path"]).name if entry.get("image_path") else None,
        "expected": expected,
        "source": source,
    }
    for m in MODELS:
        pred, err = _extract_character(entry.get(f"{m}_response"))
        out[f"{m}_predicted"] = pred
        out[f"{m}_parse_error"] = err
        out[f"{m}_correct"] = (pred is not None and expected is not None and pred == expected)
    return out


def _accuracy_matrix(scored: list[dict]) -> dict:
    matrix: dict = {m: {s: {"correct": 0, "total": 0} for s in SOURCES} for m in MODELS}
    overall: dict = {m: {"correct": 0, "total": 0} for m in MODELS}
    for s in scored:
        src = s["source"]
        for m in MODELS:
            if src in matrix[m]:
                matrix[m][src]["total"] += 1
                if s[f"{m}_correct"]:
                    matrix[m][src]["correct"] += 1
            overall[m]["total"] += 1
            if s[f"{m}_correct"]:
                overall[m]["correct"] += 1
    return {"by_source": matrix, "overall": overall}


def _fmt_pct(correct: int, total: int) -> str:
    if total == 0:
        return "n/a"
    return f"{correct}/{total} ({100 * correct / total:.0f}%)"


def _render_markdown(results_path: Path, scored: list[dict], acc: dict) -> str:
    lines: list[str] = []
    lines.append("# Handwriting Eval Scorecard")
    lines.append("")
    lines.append(f"Source: `{results_path.name}`")
    lines.append(f"Entries: {len(scored)}")
    lines.append("")
    lines.append("## Accuracy by source tier")
    lines.append("")
    header = "| source | " + " | ".join(MODELS) + " |"
    sep = "|" + "---|" * (len(MODELS) + 1)
    lines.append(header)
    lines.append(sep)
    for src in SOURCES:
        row = [src]
        for m in MODELS:
            cell = acc["by_source"][m][src]
            row.append(_fmt_pct(cell["correct"], cell["total"]))
        lines.append("| " + " | ".join(row) + " |")
    overall_row = ["**overall**"]
    for m in MODELS:
        cell = acc["overall"][m]
        overall_row.append(_fmt_pct(cell["correct"], cell["total"]))
    lines.append("| " + " | ".join(overall_row) + " |")
    lines.append("")
    lines.append("## Per-entry detail")
    lines.append("")
    lines.append("| prompt_id | image | expected | local_predicted | local_ok | cloud_predicted | cloud_ok | local_parse_error | cloud_parse_error |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for s in scored:
        lines.append(
            "| {pid} | {img} | {exp} | {lp} | {lo} | {cp} | {co} | {le} | {ce} |".format(
                pid=s["prompt_id"],
                img=s["image"] or "-",
                exp=s["expected"] or "-",
                lp=s["local_predicted"] or "-",
                lo="✓" if s["local_correct"] else "✗",
                cp=s["cloud_predicted"] or "-",
                co="✓" if s["cloud_correct"] else "✗",
                le=s["local_parse_error"] or "-",
                ce=s["cloud_parse_error"] or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) >= 2:
        results_path = Path(sys.argv[1])
        if not results_path.is_absolute():
            results_path = REPO_ROOT / results_path
    else:
        results_path = _latest_results_file()
    if not results_path.exists():
        print(f"ERROR: results file not found: {results_path}", file=sys.stderr)
        return 2

    payload = json.loads(results_path.read_text(encoding="utf-8"))
    entries = payload.get("results", payload if isinstance(payload, list) else [])
    scored = [_score_entry(e) for e in entries]
    acc = _accuracy_matrix(scored)

    md = _render_markdown(results_path, scored, acc)
    out_path = RESULTS_DIR / "handwriting_scorecard.md"
    out_path.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
