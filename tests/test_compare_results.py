"""Verify compare_results.py reads token usage from each leg and surfaces
agent / user-sim cost columns in the markdown output and JSON file."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_compare(base: Path) -> str:
    """Invoke the script the same way `run_three_way.sh` does and return
    its stdout."""
    res = subprocess.run(
        [sys.executable, "-m", "scripts.compare_results", str(base)],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, check=True,
    )
    return res.stdout


def _write_eval_json(
    path: Path, *, agent_in: int, agent_out: int,
    user_sim_in: int, user_sim_out: int,
    total_duration_s: float = 0.0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "mode": "a-interact",
        "query_mode": "raw",
        "framework": "pydantic_ai",
        "total_tasks": 1,
        "phase1_count": 0, "phase1_rate": 0.0,
        "phase2_count": 0, "phase2_rate": 0.0,
        "total_reward": 0.0, "average_reward": 0.0,
        "total_duration_s": total_duration_s,
        "avg_duration_s": total_duration_s,
        "p50_duration_s": total_duration_s,
        "max_duration_s": total_duration_s,
        "total_usage": {
            "prompt_tokens": agent_in + user_sim_in,
            "completion_tokens": agent_out + user_sim_out,
            "reasoning_tokens": 0,
            "cache_read_tokens": 0,
            "n_calls": 2,
            "cost_usd": 0.42,
            "agent_cost_usd": 0.30,
            "user_sim_cost_usd": 0.12,
            "partial": False,
            "breakdown": [
                {"name": "agent::m", "scope": "agent", "model": "m",
                 "prompt_tokens": agent_in, "completion_tokens": agent_out,
                 "reasoning_tokens": 0, "cache_read_tokens": 0,
                 "n_calls": 1, "cost_usd": 0.30},
                {"name": "user_sim::u", "scope": "user_sim", "model": "u",
                 "prompt_tokens": user_sim_in, "completion_tokens": user_sim_out,
                 "reasoning_tokens": 0, "cache_read_tokens": 0,
                 "n_calls": 1, "cost_usd": 0.12},
            ],
        },
        "results": [
            {"instance_id": "x_1", "task_id": "x_1",
             "phase1_passed": False, "phase2_passed": False,
             "total_reward": 0.0, "error": None},
        ],
    }
    path.write_text(json.dumps(blob))


def test_compare_results_surfaces_usage(tmp_path):
    base = tmp_path / "3way"
    # raw and slayer eval.json's
    _write_eval_json(
        base / "raw" / "eval.json",
        agent_in=10_000, agent_out=2_000,
        user_sim_in=5_000, user_sim_out=500,
    )
    _write_eval_json(
        base / "slayer" / "eval.json",
        agent_in=8_000, agent_out=1_500,
        user_sim_in=4_000, user_sim_out=400,
    )
    # original/results.jsonl + token_usage_*.json (matching analyze_tokens
    # output shape)
    orig_dir = base / "original"
    orig_dir.mkdir(parents=True)
    (orig_dir / "results.jsonl").write_text(
        json.dumps({
            "instance_id": "x_1", "phase1_completed": False,
            "task_finished": False, "last_reward": 0.0,
        }) + "\n"
    )
    (orig_dir / "token_usage_anthropic_claude-sonnet-4-5.json").write_text(
        json.dumps({
            "turn_1": {
                "num_samples": 1, "model": "anthropic/claude-sonnet-4-5",
                "avg_prompt_tokens": 6_000, "avg_completion_tokens": 1_000,
                "avg_reasoning_tokens": 0, "avg_total_output_tokens": 1_000,
            },
            "turn_2": {
                "num_samples": 1, "model": "anthropic/claude-sonnet-4-5",
                "avg_prompt_tokens": 9_000, "avg_completion_tokens": 1_500,
                "avg_reasoning_tokens": 0, "avg_total_output_tokens": 1_500,
            },
        })
    )

    stdout = _run_compare(base)

    # Markdown table now includes usage columns.
    assert "agent tok" in stdout
    assert "user-sim tok" in stdout
    assert "$ agent" in stdout
    assert "$ total" in stdout

    # comparison.json carries usage per leg.
    blob = json.loads((base / "comparison.json").read_text())
    assert "usage" in blob
    assert "raw" in blob["usage"]
    raw_u = blob["usage"]["raw"]
    assert raw_u["prompt_tokens"] == 15_000
    assert raw_u["agent_cost_usd"] == 0.30

    # original leg derives prompt totals from analyze_tokens output
    # (sum across turns).
    orig_u = blob["usage"]["original"]
    assert orig_u["prompt_tokens"] == 15_000  # 6_000 + 9_000
    assert orig_u["completion_tokens"] == 2_500


def test_compare_results_surfaces_timing(tmp_path):
    """Per-leg duration totals land in comparison.json and the markdown
    table gains avg-dur / total-dur columns."""
    base = tmp_path / "3way"
    _write_eval_json(
        base / "raw" / "eval.json",
        agent_in=10, agent_out=2, user_sim_in=5, user_sim_out=1,
        total_duration_s=12.5,
    )
    _write_eval_json(
        base / "slayer" / "eval.json",
        agent_in=8, agent_out=1, user_sim_in=4, user_sim_out=0,
        total_duration_s=9.25,
    )
    orig_dir = base / "original"
    orig_dir.mkdir(parents=True)
    (orig_dir / "results.jsonl").write_text(
        json.dumps({
            "instance_id": "x_1", "phase1_completed": False,
            "task_finished": False, "last_reward": 0.0,
        }) + "\n"
    )
    (orig_dir / "duration.json").write_text(
        json.dumps({"total_duration_s": 35.7, "n_tasks": 1, "avg_duration_s": 35.7})
    )

    stdout = _run_compare(base)

    # Markdown table now includes timing columns.
    assert "avg dur" in stdout
    assert "total dur" in stdout

    blob = json.loads((base / "comparison.json").read_text())
    assert "timing" in blob
    assert blob["timing"]["raw"]["total_duration_s"] == pytest.approx(12.5)
    assert blob["timing"]["slayer"]["total_duration_s"] == pytest.approx(9.25)
    assert blob["timing"]["original"]["total_duration_s"] == pytest.approx(35.7)


def test_orig_usage_falls_back_to_per_turn_jsonl(tmp_path):
    """When `analyze_tokens` failed (or never ran) and no
    `token_usage_*.json` exists, original tokens are recovered by
    summing `token_usage` from each `results.jsonl.agent_raw_turn_*.jsonl`."""
    base = tmp_path / "3way"
    _write_eval_json(
        base / "raw" / "eval.json",
        agent_in=10, agent_out=2, user_sim_in=5, user_sim_out=1,
    )
    _write_eval_json(
        base / "slayer" / "eval.json",
        agent_in=8, agent_out=1, user_sim_in=4, user_sim_out=0,
    )
    orig_dir = base / "original"
    orig_dir.mkdir(parents=True)
    (orig_dir / "results.jsonl").write_text(
        json.dumps({
            "instance_id": "x_1", "phase1_completed": False,
            "task_finished": False, "last_reward": 0.0,
        }) + "\n"
    )
    # Two per-turn files; analyze_tokens never ran (no token_usage_*.json).
    for i, (p, c) in enumerate([(1000, 200), (2000, 400)], start=1):
        (orig_dir / f"results.jsonl.agent_raw_turn_{i}.jsonl").write_text(
            json.dumps({
                "prompt": "...", "id": "x_1", "response": "...",
                "token_usage": {
                    "prompt_tokens": p, "completion_tokens": c,
                    "reasoning_tokens": 0,
                },
            }) + "\n"
        )

    _run_compare(base)
    blob = json.loads((base / "comparison.json").read_text())
    orig_u = blob["usage"]["original"]
    assert orig_u["prompt_tokens"] == 3000
    assert orig_u["completion_tokens"] == 600


def test_orig_usage_costs_when_model_known(tmp_path):
    """When `original/duration.json` records the agent_model, the
    fallback prices the per-turn tokens via `litellm.cost_per_token` so
    `agent_cost_usd` is non-zero (matching what raw/slayer report)."""
    base = tmp_path / "3way"
    _write_eval_json(
        base / "raw" / "eval.json",
        agent_in=10, agent_out=2, user_sim_in=5, user_sim_out=1,
    )
    _write_eval_json(
        base / "slayer" / "eval.json",
        agent_in=8, agent_out=1, user_sim_in=4, user_sim_out=0,
    )
    orig_dir = base / "original"
    orig_dir.mkdir(parents=True)
    (orig_dir / "results.jsonl").write_text(
        json.dumps({
            "instance_id": "x_1", "phase1_completed": False,
            "task_finished": False, "last_reward": 0.0,
        }) + "\n"
    )
    (orig_dir / "duration.json").write_text(
        json.dumps({
            "total_duration_s": 60.0, "n_tasks": 1, "avg_duration_s": 60.0,
            "agent_model": "anthropic/claude-haiku-4-5-20251001",
        })
    )
    (orig_dir / "results.jsonl.agent_raw_turn_1.jsonl").write_text(
        json.dumps({
            "prompt": "...", "id": "x_1", "response": "...",
            "token_usage": {
                "prompt_tokens": 100_000, "completion_tokens": 5_000,
                "reasoning_tokens": 0,
            },
        }) + "\n"
    )

    _run_compare(base)
    blob = json.loads((base / "comparison.json").read_text())
    orig_u = blob["usage"]["original"]
    assert orig_u["prompt_tokens"] == 100_000
    assert orig_u["completion_tokens"] == 5_000
    # Haiku 4.5 pricing in litellm should be $1/M in + $5/M out → ~$0.125
    # but we don't pin to an exact number to stay robust against table
    # updates — just assert it's > 0.
    assert orig_u["agent_cost_usd"] > 0
    assert orig_u["cost_usd"] == pytest.approx(orig_u["agent_cost_usd"])
