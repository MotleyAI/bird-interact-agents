"""Tests for scripts/select_tasks.py and scripts/compare_results.py.

Imports the script modules by file path so they can be tested without
installing them as a package.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


compare_results = _load_module("compare_results", SCRIPTS_DIR / "compare_results.py")


# ── compare_results._norm_orig ───────────────────────────────────────────


def test_norm_orig_preserves_false_phase_flag():
    row = {
        "instance_id": "t1",
        "phase1_passed": False,
        "phase1_completed": True,
    }
    out = compare_results._norm_orig(row)
    assert out["phase1_passed"] is False, "explicit False must not be flipped to fallback"


def test_norm_orig_preserves_zero_reward():
    row = {
        "instance_id": "t1",
        "total_reward": 0,
        "last_reward": 1,
    }
    out = compare_results._norm_orig(row)
    assert out["total_reward"] == 0.0, "explicit 0 must not be flipped to fallback"


def test_norm_orig_falls_back_when_primary_missing():
    row = {
        "instance_id": "t1",
        "phase1_completed": True,
        "task_finished": True,
        "last_reward": 0.7,
    }
    out = compare_results._norm_orig(row)
    assert out["phase1_passed"] is True
    assert out["phase2_passed"] is True
    assert out["total_reward"] == pytest.approx(0.7)


def test_norm_orig_defaults_when_all_missing():
    out = compare_results._norm_orig({"instance_id": "t1"})
    assert out["phase1_passed"] is False
    assert out["phase2_passed"] is False
    assert out["total_reward"] == 0.0


def test_norm_orig_treats_none_as_missing():
    row = {
        "instance_id": "t1",
        "phase1_passed": None,
        "phase1_completed": True,
    }
    out = compare_results._norm_orig(row)
    assert out["phase1_passed"] is True


# ── select_tasks: record-based pagination + --out-jsonl ─────────────────


def _write_jsonl_with_blanks(path: Path, rows: list[dict]) -> None:
    """Write rows interleaved with blank lines, to exercise the bug
    where raw-line pagination drifts off the record sequence."""
    chunks: list[str] = []
    for r in rows:
        chunks.append(json.dumps(r))
        chunks.append("")  # blank line after each record
    path.write_text("\n".join(chunks) + "\n")


def _run_select_tasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "select_tasks.py"), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_select_tasks_pagination_skips_records_not_lines(tmp_path: Path):
    data = tmp_path / "tasks.jsonl"
    _write_jsonl_with_blanks(
        data, [{"instance_id": f"t{i}"} for i in range(6)]
    )
    out_ids = tmp_path / "ids.txt"
    _run_select_tasks(
        "--data", str(data),
        "--start", "2",
        "--limit", "3",
        "--out", str(out_ids),
    )
    selected = out_ids.read_text().strip().splitlines()
    # Records 2, 3, 4 — NOT raw lines 2..4 (which would include blanks).
    assert selected == ["t2", "t3", "t4"]


def test_select_tasks_emits_filtered_jsonl(tmp_path: Path):
    data = tmp_path / "tasks.jsonl"
    rows = [{"instance_id": f"t{i}", "payload": i} for i in range(5)]
    data.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    out_ids = tmp_path / "ids.txt"
    out_jsonl = tmp_path / "tasks_filtered.jsonl"
    _run_select_tasks(
        "--data", str(data),
        "--limit", "3",
        "--out", str(out_ids),
        "--out-jsonl", str(out_jsonl),
    )

    selected_ids = out_ids.read_text().strip().splitlines()
    assert selected_ids == ["t0", "t1", "t2"]

    emitted = [
        json.loads(line) for line in out_jsonl.read_text().splitlines() if line.strip()
    ]
    assert [r["instance_id"] for r in emitted] == selected_ids
    assert [r["payload"] for r in emitted] == [0, 1, 2]


def test_select_tasks_no_jsonl_when_flag_omitted(tmp_path: Path):
    data = tmp_path / "tasks.jsonl"
    data.write_text(json.dumps({"instance_id": "only"}) + "\n")
    out_ids = tmp_path / "ids.txt"
    _run_select_tasks(
        "--data", str(data),
        "--limit", "1",
        "--out", str(out_ids),
    )
    # No --out-jsonl path provided → nothing extra written.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ids.txt", "tasks.jsonl"]
