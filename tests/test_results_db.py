"""Per-task SQLite sink — flushed after each task completes so a mid-run
crash never throws away completed-task data."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


def test_open_db_creates_schema(tmp_path):
    from bird_interact_agents.results_db import open_db

    path = tmp_path / "results.db"
    conn = open_db(path)
    cur = conn.cursor()
    tables = {
        row[0] for row in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "task_results" in tables
    assert "run_metadata" in tables


def test_insert_task_result_round_trip(tmp_path):
    from bird_interact_agents.results_db import (
        TaskResultRow, insert_task_result, open_db,
    )

    conn = open_db(tmp_path / "results.db")
    row = TaskResultRow(
        run_id="3way_smoke",
        framework="pydantic_ai",
        mode="a-interact",
        query_mode="raw",
        instance_id="alien_1",
        database="alien",
        started_at=1730000000.0,
        duration_s=42.5,
        phase1_passed=False,
        phase2_passed=False,
        total_reward=0.0,
        submitted_sql="SELECT 1",
        submitted_query=None,
        ground_truth_sql="SELECT * FROM telescopes",
        error=None,
        usage_json='{"prompt_tokens": 100, "completion_tokens": 20}',
    )
    insert_task_result(conn, row)

    rows = list(conn.execute("SELECT instance_id, query_mode, submitted_sql FROM task_results"))
    assert rows == [("alien_1", "raw", "SELECT 1")]


def test_insert_task_result_replaces_on_conflict(tmp_path):
    """Re-inserting the same primary-key tuple overwrites the prior row —
    supports retries / re-runs of a single task within an output dir."""
    from bird_interact_agents.results_db import (
        TaskResultRow, insert_task_result, open_db,
    )

    conn = open_db(tmp_path / "results.db")

    def _row(reward: float, mode: str = "a-interact") -> "TaskResultRow":
        return TaskResultRow(
            run_id="x", framework="pydantic_ai", mode=mode,
            query_mode="raw", instance_id="alien_1", database="alien",
            started_at=0.0, duration_s=0.0,
            phase1_passed=False, phase2_passed=False, total_reward=reward,
            submitted_sql=None, submitted_query=None, ground_truth_sql=None,
            error=None, usage_json="{}",
        )

    insert_task_result(conn, _row(0.0))
    insert_task_result(conn, _row(1.0))

    rows = list(conn.execute("SELECT total_reward FROM task_results"))
    assert rows == [(1.0,)]


def test_insert_task_result_distinguishes_modes(tmp_path):
    """Same (run_id, framework, query_mode, instance_id) under different
    `mode`s must coexist — `mode` is part of the primary key. Without it,
    `INSERT OR REPLACE` would silently clobber per-mode rows in mixed-mode
    runs (e.g. a-interact and c-interact for the same task)."""
    from bird_interact_agents.results_db import (
        TaskResultRow, insert_task_result, open_db,
    )

    conn = open_db(tmp_path / "results.db")

    def _row(reward: float, mode: str) -> "TaskResultRow":
        return TaskResultRow(
            run_id="x", framework="pydantic_ai", mode=mode,
            query_mode="raw", instance_id="alien_1", database="alien",
            started_at=0.0, duration_s=0.0,
            phase1_passed=False, phase2_passed=False, total_reward=reward,
            submitted_sql=None, submitted_query=None, ground_truth_sql=None,
            error=None, usage_json="{}",
        )

    insert_task_result(conn, _row(0.5, "a-interact"))
    insert_task_result(conn, _row(0.7, "c-interact"))

    rows = sorted(conn.execute(
        "SELECT mode, total_reward FROM task_results ORDER BY mode"
    ))
    assert rows == [("a-interact", 0.5), ("c-interact", 0.7)]


def test_insert_run_metadata_records_run(tmp_path):
    from bird_interact_agents.results_db import (
        insert_run_metadata, open_db,
    )

    conn = open_db(tmp_path / "results.db")
    insert_run_metadata(
        conn,
        run_id="3way_smoke",
        agent_model="anthropic/claude-haiku-4-5-20251001",
        user_sim_model="anthropic/claude-haiku-4-5-20251001",
        framework="pydantic_ai",
        mode="a-interact",
    )
    rows = list(conn.execute(
        "SELECT run_id, agent_model, framework FROM run_metadata"
    ))
    assert rows == [(
        "3way_smoke",
        "anthropic/claude-haiku-4-5-20251001",
        "pydantic_ai",
    )]


def test_insert_task_result_persists_to_disk(tmp_path):
    """The DB write must survive a process restart (no in-memory only).
    Open a fresh connection and read back the row."""
    from bird_interact_agents.results_db import (
        TaskResultRow, insert_task_result, open_db,
    )

    db_path = tmp_path / "results.db"
    conn = open_db(db_path)
    insert_task_result(conn, TaskResultRow(
        run_id="x", framework="pydantic_ai", mode="a-interact",
        query_mode="raw", instance_id="alien_1", database="alien",
        started_at=0.0, duration_s=1.5, phase1_passed=True,
        phase2_passed=False, total_reward=0.5,
        submitted_sql="S1", submitted_query=None, ground_truth_sql="GT",
        error=None, usage_json="{}",
    ))
    conn.close()

    fresh = sqlite3.connect(db_path)
    rows = list(fresh.execute(
        "SELECT instance_id, phase1_passed, submitted_sql, ground_truth_sql FROM task_results"
    ))
    assert rows == [("alien_1", 1, "S1", "GT")]
