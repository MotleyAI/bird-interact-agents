"""Side-by-side comparison of original / raw / slayer eval results.

Reads:
    <dir>/original/results.jsonl   (original mini_interact_agent format)
    <dir>/raw/eval.json            (our run.py output)
    <dir>/slayer/eval.json         (our run.py output)

Writes <dir>/comparison.json and prints a summary table.

Each version's per-task record is normalised to:
    {instance_id, phase1_passed, phase2_passed, total_reward, error}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

VERSIONS = ("original", "raw", "slayer")


def _first_present(row: dict, *keys: str, default: Any = None) -> Any:
    """Return the first key whose value is not None.

    Unlike `a or b`, this preserves explicit `False` and `0` — important for
    `phase1_passed=False` / `total_reward=0` not getting flipped to the next
    fallback's value.
    """
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return default


def _norm_orig(row: dict) -> dict | None:
    """Upstream main.py serialises the SampleStatus dataclass directly:
    instance_id is nested under `original_data`, phase status is reported
    via `phase1_completed` / `task_finished` (the latter signals the
    follow-up phase finished), reward via `last_reward`. We keep the
    bird-interact-agents-shaped fallbacks first so this also accepts
    ad-hoc rows in our own format.

    Returns None when no `instance_id` can be recovered — caller drops the
    row rather than collapsing it under an empty key (which would let one
    malformed record overwrite another).
    """
    od = row.get("original_data") or {}
    iid = (
        row.get("instance_id")
        or od.get("instance_id")
        or row.get("task_id")
    )
    if not iid:
        return None
    return {
        "instance_id": iid,
        "phase1_passed": bool(
            _first_present(row, "phase1_passed", "phase1_completed", default=False)
        ),
        "phase2_passed": bool(
            _first_present(row, "phase2_passed", "task_finished", default=False)
        ),
        "total_reward": float(
            _first_present(row, "total_reward", "last_reward", default=0.0)
        ),
        "error": row.get("error"),
    }


def _norm_ours(row: dict) -> dict | None:
    """Like `_norm_orig` but for our own `eval.json` shape. Returns None on
    missing instance_id so the caller drops the row instead of merging
    multiple rows under the empty-string key."""
    iid = row.get("instance_id") or row.get("task_id")
    if not iid:
        return None
    return {
        "instance_id": iid,
        "phase1_passed": bool(row.get("phase1_passed")),
        "phase2_passed": bool(row.get("phase2_passed")),
        "total_reward": float(row.get("total_reward") or 0.0),
        "error": row.get("error"),
    }


def _load_original(path: Path, *, allow_missing: bool) -> list[dict]:
    if not path.is_file():
        if allow_missing:
            return []
        raise FileNotFoundError(
            f"Expected results file not found: {path}. "
            "Pass --allow-missing to treat absent files as empty results."
        )
    rows: list[dict] = []
    skipped = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            norm = _norm_orig(json.loads(line))
            if norm is None:
                skipped += 1
                continue
            rows.append(norm)
    if skipped:
        print(f"[compare_results] {path}: skipped {skipped} row(s) with missing instance_id")
    return rows


def _load_ours(path: Path, *, allow_missing: bool) -> list[dict]:
    if not path.is_file():
        if allow_missing:
            return []
        raise FileNotFoundError(
            f"Expected results file not found: {path}. "
            "Pass --allow-missing to treat absent files as empty results."
        )
    blob = json.loads(path.read_text())
    rows: list[dict] = []
    skipped = 0
    for r in blob.get("results", []):
        norm = _norm_ours(r)
        if norm is None:
            skipped += 1
            continue
        rows.append(norm)
    if skipped:
        print(f"[compare_results] {path}: skipped {skipped} row(s) with missing instance_id")
    return rows


def _aggregate(rows: list[dict]) -> dict:
    n = len(rows) or 1
    return {
        "n": len(rows),
        "phase1_rate": sum(r["phase1_passed"] for r in rows) / n,
        "phase2_rate": sum(r["phase2_passed"] for r in rows) / n,
        "avg_reward": sum(r["total_reward"] for r in rows) / n,
        "errors": sum(1 for r in rows if r.get("error")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dir", help="Directory containing original/, raw/, slayer/")
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Treat absent results files as empty datasets instead of failing. "
        "Off by default so a misrouted/failed run doesn't silently turn into "
        "a misleading 0%/0-reward report.",
    )
    args = parser.parse_args()

    base = Path(args.dir)
    rows_by_version = {
        "original": _load_original(
            base / "original" / "results.jsonl", allow_missing=args.allow_missing
        ),
        "raw": _load_ours(
            base / "raw" / "eval.json", allow_missing=args.allow_missing
        ),
        "slayer": _load_ours(
            base / "slayer" / "eval.json", allow_missing=args.allow_missing
        ),
    }
    by_id: dict[str, dict[str, dict]] = {}
    for v, rows in rows_by_version.items():
        for r in rows:
            by_id.setdefault(r["instance_id"], {})[v] = r

    summary = {v: _aggregate(rows) for v, rows in rows_by_version.items()}
    out = {"summary": summary, "per_task": by_id}
    (base / "comparison.json").write_text(json.dumps(out, indent=2))

    # ── Markdown table to stdout ────────────────────────────────────────
    print("\n## Aggregate\n")
    print("| version | n | P1 rate | P2 rate | avg reward | errors |")
    print("|---|---|---|---|---|---|")
    for v in VERSIONS:
        s = summary[v]
        print(
            f"| {v} | {s['n']} | {s['phase1_rate']:.2%} | "
            f"{s['phase2_rate']:.2%} | {s['avg_reward']:.3f} | {s['errors']} |"
        )

    print("\n## Per-task P1\n")
    print("| instance_id | original | raw | slayer |")
    print("|---|---|---|---|")
    for iid in sorted(by_id):
        cells = [
            "✓" if by_id[iid].get(v, {}).get("phase1_passed") else
            ("✗" if v in by_id[iid] else "—")
            for v in VERSIONS
        ]
        print(f"| {iid} | {cells[0]} | {cells[1]} | {cells[2]} |")

    print(f"\nWrote {base / 'comparison.json'}")


if __name__ == "__main__":
    main()
