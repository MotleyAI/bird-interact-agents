"""Side-by-side comparison of original / raw / slayer eval results.

Reads:
    <dir>/original/results.jsonl                (original harness)
    <dir>/original/token_usage_<model>.json     (analyze_tokens output)
    <dir>/raw/eval.json                         (our run.py output)
    <dir>/slayer/eval.json                      (our run.py output)

Writes <dir>/comparison.json and prints a summary table.

Each version's per-task record is normalised to:
    {instance_id, phase1_passed, phase2_passed, total_reward, error}

Token usage is aggregated per leg into:
    {prompt_tokens, completion_tokens, agent_cost_usd, user_sim_cost_usd,
     cost_usd, partial}
The original leg only records agent-side tokens (user-sim is not
captured by upstream `analyze_tokens`), so its `user_sim_cost_usd`
field is `None` and the "user-sim tok" cell renders as a dash.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

VERSIONS = ("original", "raw", "slayer")


def _norm_orig(row: dict) -> dict:
    """Upstream main.py serialises the SampleStatus dataclass directly:
    instance_id is nested under `original_data`, phase status is reported
    via `phase1_completed` / `task_finished` (the latter signals the
    follow-up phase finished), reward via `last_reward`. We keep the
    bird-interact-agents-shaped fallbacks first so this also accepts
    ad-hoc rows in our own format.
    """
    od = row.get("original_data") or {}
    return {
        "instance_id": (
            row.get("instance_id")
            or od.get("instance_id")
            or row.get("task_id")
            or ""
        ),
        "phase1_passed": bool(
            row.get("phase1_passed")
            or row.get("phase1_completed")
        ),
        "phase2_passed": bool(
            row.get("phase2_passed")
            or row.get("task_finished")
        ),
        "total_reward": float(
            row.get("total_reward")
            or row.get("last_reward")
            or 0.0
        ),
        "error": row.get("error"),
    }


def _norm_ours(row: dict) -> dict:
    return {
        "instance_id": row.get("instance_id") or row.get("task_id") or "",
        "phase1_passed": bool(row.get("phase1_passed")),
        "phase2_passed": bool(row.get("phase2_passed")),
        "total_reward": float(row.get("total_reward") or 0.0),
        "error": row.get("error"),
    }


def _load_original(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(_norm_orig(json.loads(line)))
    return rows


def _load_ours(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    blob = json.loads(path.read_text())
    return [_norm_ours(r) for r in blob.get("results", [])]


def _aggregate(rows: list[dict]) -> dict:
    n = len(rows) or 1
    return {
        "n": len(rows),
        "phase1_rate": sum(r["phase1_passed"] for r in rows) / n,
        "phase2_rate": sum(r["phase2_passed"] for r in rows) / n,
        "avg_reward": sum(r["total_reward"] for r in rows) / n,
        "errors": sum(1 for r in rows if r.get("error")),
    }


def _empty_usage() -> dict:
    return {
        "prompt_tokens": 0, "completion_tokens": 0,
        "reasoning_tokens": 0, "cache_read_tokens": 0,
        "n_calls": 0, "cost_usd": 0.0,
        "agent_cost_usd": 0.0, "user_sim_cost_usd": 0.0,
        "partial": False,
    }


def _load_ours_usage(eval_path: Path) -> dict:
    if not eval_path.is_file():
        return _empty_usage()
    blob = json.loads(eval_path.read_text())
    u = blob.get("total_usage")
    if not u:
        return _empty_usage()
    # Split prompt/completion totals by scope from breakdown[] so the
    # comparison table can show agent vs user-sim columns separately.
    agent_in = sum(
        r["prompt_tokens"] for r in u.get("breakdown", []) if r["scope"] == "agent"
    )
    agent_out = sum(
        r["completion_tokens"] for r in u.get("breakdown", []) if r["scope"] == "agent"
    )
    user_in = sum(
        r["prompt_tokens"] for r in u.get("breakdown", []) if r["scope"] == "user_sim"
    )
    user_out = sum(
        r["completion_tokens"] for r in u.get("breakdown", []) if r["scope"] == "user_sim"
    )
    return {
        "prompt_tokens": u.get("prompt_tokens", 0),
        "completion_tokens": u.get("completion_tokens", 0),
        "reasoning_tokens": u.get("reasoning_tokens", 0),
        "cache_read_tokens": u.get("cache_read_tokens", 0),
        "n_calls": u.get("n_calls", 0),
        "agent_prompt_tokens": agent_in,
        "agent_completion_tokens": agent_out,
        "user_sim_prompt_tokens": user_in,
        "user_sim_completion_tokens": user_out,
        "agent_cost_usd": u.get("agent_cost_usd", 0.0),
        "user_sim_cost_usd": u.get("user_sim_cost_usd", 0.0),
        "cost_usd": u.get("cost_usd", 0.0),
        "partial": u.get("partial", False),
    }


def _load_orig_usage(orig_dir: Path) -> dict:
    """Sum per-turn aggregates produced by upstream `analyze_tokens`.

    Upstream only records agent-side tokens — user-sim is not captured —
    so we leave `user_sim_cost_usd=None` and reuse `litellm.cost_per_token`
    to compute the agent cost so original / raw / slayer are priced
    consistently.
    """
    empty = {
        **_empty_usage(),
        "agent_prompt_tokens": 0, "agent_completion_tokens": 0,
        "user_sim_prompt_tokens": 0, "user_sim_completion_tokens": 0,
        "user_sim_cost_usd": None,
        "partial": True,
    }
    if not orig_dir.is_dir():
        return empty
    matches = list(orig_dir.glob("token_usage_*.json"))
    if not matches:
        # Fall back to summing per-turn `token_usage` blobs directly.
        out = _load_orig_usage_from_turns(orig_dir)
        if out["prompt_tokens"] == 0:
            return empty
        # We don't know which model produced these tokens here — skip
        # cost calc; caller can add `--price-overrides` or rerun
        # `analyze_tokens` separately to fill it in.
        return out

    blob = json.loads(matches[0].read_text())
    prompt = 0
    completion = 0
    reasoning = 0
    n_calls = 0
    model = ""
    for stats in blob.values():
        n = int(stats.get("num_samples") or 0)
        prompt += int(stats.get("avg_prompt_tokens") or 0) * n
        completion += int(stats.get("avg_completion_tokens") or 0) * n
        reasoning += int(stats.get("avg_reasoning_tokens") or 0) * n
        n_calls += n
        model = stats.get("model", model)

    try:
        import litellm
        p_cost, c_cost = litellm.cost_per_token(
            model=model, prompt_tokens=prompt, completion_tokens=completion,
        )
        agent_cost = p_cost + c_cost
    except Exception:
        agent_cost = 0.0

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "cache_read_tokens": 0,
        "n_calls": n_calls,
        "agent_prompt_tokens": prompt,
        "agent_completion_tokens": completion,
        "user_sim_prompt_tokens": 0,
        "user_sim_completion_tokens": 0,
        "agent_cost_usd": agent_cost,
        "user_sim_cost_usd": None,
        "cost_usd": agent_cost,
        "partial": True,  # user-sim missing
    }


def _fmt_tok(n: int) -> str:
    return f"{n / 1000:.1f}K" if n else "—"


def _fmt_usd(v) -> str:
    return f"${v:.2f}" if isinstance(v, (int, float)) else "—"


def _fmt_dur(v) -> str:
    if not isinstance(v, (int, float)) or v <= 0:
        return "—"
    if v < 60:
        return f"{v:.1f}s"
    return f"{v / 60:.1f}m"


def _empty_timing() -> dict:
    return {
        "total_duration_s": 0.0,
        "avg_duration_s": 0.0,
        "p50_duration_s": 0.0,
        "max_duration_s": 0.0,
    }


def _load_ours_timing(eval_path: Path) -> dict:
    if not eval_path.is_file():
        return _empty_timing()
    blob = json.loads(eval_path.read_text())
    return {
        "total_duration_s": float(blob.get("total_duration_s") or 0.0),
        "avg_duration_s": float(blob.get("avg_duration_s") or 0.0),
        "p50_duration_s": float(blob.get("p50_duration_s") or 0.0),
        "max_duration_s": float(blob.get("max_duration_s") or 0.0),
    }


def _load_orig_timing(orig_dir: Path) -> dict:
    """Read leg-total wall-clock from `original/duration.json`. Per-task
    timing is not captured for the original leg, so `avg/p50/max_duration_s`
    only reflect the leg-wide average if `n_tasks` was recorded."""
    path = orig_dir / "duration.json"
    if not path.is_file():
        return _empty_timing()
    blob = json.loads(path.read_text())
    total = float(blob.get("total_duration_s") or 0.0)
    avg = float(blob.get("avg_duration_s") or 0.0)
    return {
        "total_duration_s": total,
        "avg_duration_s": avg,
        # We don't have per-task durations to compute p50/max; report avg.
        "p50_duration_s": avg,
        "max_duration_s": avg,
    }


def _load_orig_usage_from_turns(orig_dir: Path) -> dict:
    """Sum `token_usage` from each `results.jsonl.agent_raw_turn_*.jsonl`
    when `analyze_tokens` couldn't run (e.g. because its hard-coded
    pricing whitelist rejects the model). Each per-turn file contains
    one line per task processed in that turn.

    If `duration.json` records `agent_model`, price the totals via
    `litellm.cost_per_token` so the original leg's `$ agent` column
    populates without re-running upstream's analyze_tokens.
    """
    prompt = 0
    completion = 0
    reasoning = 0
    n_calls = 0
    for f in sorted(orig_dir.glob("results.jsonl.agent_raw_turn_*.jsonl")):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                u = row.get("token_usage") or {}
                if not u:
                    continue
                prompt += int(u.get("prompt_tokens") or 0)
                completion += int(u.get("completion_tokens") or 0)
                reasoning += int(u.get("reasoning_tokens") or 0)
                n_calls += 1

    agent_cost = 0.0
    duration_path = orig_dir / "duration.json"
    if duration_path.is_file():
        try:
            model = json.loads(duration_path.read_text()).get("agent_model")
        except Exception:
            model = None
        if model and prompt:
            try:
                import litellm
                p_cost, c_cost = litellm.cost_per_token(
                    model=model,
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                )
                agent_cost = p_cost + c_cost
            except Exception:
                agent_cost = 0.0

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "cache_read_tokens": 0,
        "n_calls": n_calls,
        "agent_prompt_tokens": prompt,
        "agent_completion_tokens": completion,
        "user_sim_prompt_tokens": 0,
        "user_sim_completion_tokens": 0,
        "agent_cost_usd": agent_cost,
        "user_sim_cost_usd": None,
        "cost_usd": agent_cost,
        "partial": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dir", help="Directory containing original/, raw/, slayer/")
    args = parser.parse_args()

    base = Path(args.dir)
    rows_by_version = {
        "original": _load_original(base / "original" / "results.jsonl"),
        "raw": _load_ours(base / "raw" / "eval.json"),
        "slayer": _load_ours(base / "slayer" / "eval.json"),
    }
    by_id: dict[str, dict[str, dict]] = {}
    for v, rows in rows_by_version.items():
        for r in rows:
            by_id.setdefault(r["instance_id"], {})[v] = r

    summary = {v: _aggregate(rows) for v, rows in rows_by_version.items()}
    usage = {
        "original": _load_orig_usage(base / "original"),
        "raw": _load_ours_usage(base / "raw" / "eval.json"),
        "slayer": _load_ours_usage(base / "slayer" / "eval.json"),
    }
    timing = {
        "original": _load_orig_timing(base / "original"),
        "raw": _load_ours_timing(base / "raw" / "eval.json"),
        "slayer": _load_ours_timing(base / "slayer" / "eval.json"),
    }
    out = {
        "summary": summary, "usage": usage, "timing": timing,
        "per_task": by_id,
    }
    (base / "comparison.json").write_text(json.dumps(out, indent=2))

    # ── Markdown table to stdout ────────────────────────────────────────
    print("\n## Aggregate\n")
    print(
        "| version | n | P1 rate | P2 rate | avg reward | errors | "
        "agent tok in/out | user-sim tok in/out | $ agent | $ user-sim | $ total | "
        "avg dur | total dur |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for v in VERSIONS:
        s = summary[v]
        u = usage[v]
        t = timing[v]
        agent_in = u.get("agent_prompt_tokens", 0)
        agent_out = u.get("agent_completion_tokens", 0)
        user_in_n = u.get("user_sim_prompt_tokens", 0)
        user_out_n = u.get("user_sim_completion_tokens", 0)
        user_cell = (
            "— / —"
            if u["user_sim_cost_usd"] is None
            else f"{_fmt_tok(user_in_n)}/{_fmt_tok(user_out_n)}"
        )
        # Original leg only has leg-total wall-clock; show the avg derived
        # from total / n_tasks but not p50/max.
        avg_dur_cell = (
            "—" if v == "original" and s["n"] == 0 else _fmt_dur(t["avg_duration_s"])
        )
        print(
            f"| {v} | {s['n']} | {s['phase1_rate']:.2%} | "
            f"{s['phase2_rate']:.2%} | {s['avg_reward']:.3f} | {s['errors']} | "
            f"{_fmt_tok(agent_in)}/{_fmt_tok(agent_out)} | "
            f"{user_cell} | "
            f"{_fmt_usd(u['agent_cost_usd'])} | "
            f"{_fmt_usd(u['user_sim_cost_usd'])} | "
            f"{_fmt_usd(u['cost_usd'])} | "
            f"{avg_dur_cell} | {_fmt_dur(t['total_duration_s'])} |"
        )
    if any(usage[v]["partial"] for v in VERSIONS):
        print(
            "\n> Note: rows marked partial omit user-sim tokens "
            "(upstream `analyze_tokens` records agent-side only) or "
            "agent-side tokens (mcp_agent SDK does not expose them)."
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
