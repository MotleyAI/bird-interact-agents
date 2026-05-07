"""Per-task SQLite sink for benchmark results.

`run_evaluation` opens one DB per output dir (`<output_dir>/results.db`)
and inserts a row for each completed task — both successes and
failures — *immediately* after that task returns. This survives mid-run
crashes that the old end-of-run `eval.json` dump did not: every
completed task's data lands on disk before the next one starts.

Schema is intentionally narrow and stable: the columns are the
analysis-relevant fields (pass/fail, costs, SQLs, errors). Per-task
JSON blobs (token usage, full trajectory) live in TEXT columns so we
don't have to migrate the schema every time we add a derived metric.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import BaseModel


_TASK_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS task_results (
    run_id          TEXT NOT NULL,
    framework       TEXT NOT NULL,
    mode            TEXT NOT NULL,
    query_mode      TEXT NOT NULL,
    instance_id     TEXT NOT NULL,
    database        TEXT NOT NULL,
    started_at      REAL NOT NULL,
    duration_s      REAL NOT NULL,
    phase1_passed   INTEGER NOT NULL,
    phase2_passed   INTEGER NOT NULL,
    total_reward    REAL NOT NULL,
    submitted_sql   TEXT,
    submitted_query TEXT,
    ground_truth_sql TEXT,
    error           TEXT,
    usage_json      TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, framework, mode, query_mode, instance_id)
)
"""

_RUN_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS run_metadata (
    run_id          TEXT NOT NULL,
    framework       TEXT NOT NULL,
    mode            TEXT NOT NULL,
    agent_model     TEXT NOT NULL,
    user_sim_model  TEXT NOT NULL,
    started_at      REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, framework, mode)
)
"""


class TaskResultRow(BaseModel):
    """One row in `task_results`. Field order matches the DDL."""

    run_id: str
    framework: str
    mode: str
    query_mode: str
    instance_id: str
    database: str
    started_at: float
    duration_s: float
    phase1_passed: bool
    phase2_passed: bool
    total_reward: float
    submitted_sql: str | None = None
    submitted_query: str | None = None
    ground_truth_sql: str | None = None
    error: str | None = None
    usage_json: str = "{}"


def open_db(path: Path | str) -> sqlite3.Connection:
    """Open (or create) the results DB at `path` and ensure the schema
    exists. Caller is responsible for closing the connection."""
    conn = sqlite3.connect(str(path))
    conn.execute(_TASK_RESULTS_DDL)
    conn.execute(_RUN_METADATA_DDL)
    conn.commit()
    return conn


def insert_task_result(conn: sqlite3.Connection, row: TaskResultRow) -> None:
    """Upsert a task result. Re-inserting the same primary key replaces
    the prior row, supporting reruns/retries within an output dir."""
    conn.execute(
        """
        INSERT OR REPLACE INTO task_results
        (run_id, framework, mode, query_mode, instance_id, database,
         started_at, duration_s, phase1_passed, phase2_passed,
         total_reward, submitted_sql, submitted_query, ground_truth_sql,
         error, usage_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            row.run_id, row.framework, row.mode, row.query_mode,
            row.instance_id, row.database, row.started_at, row.duration_s,
            int(row.phase1_passed), int(row.phase2_passed),
            row.total_reward, row.submitted_sql, row.submitted_query,
            row.ground_truth_sql, row.error, row.usage_json,
        ),
    )
    conn.commit()


def insert_run_metadata(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    agent_model: str,
    user_sim_model: str,
    framework: str,
    mode: str,
    started_at: float = 0.0,
) -> None:
    """Record the per-run header so downstream tools (compare_results,
    failure-mode analysis) can correlate task rows with the model that
    produced them."""
    conn.execute(
        """
        INSERT OR REPLACE INTO run_metadata
        (run_id, framework, mode, agent_model, user_sim_model, started_at)
        VALUES (?,?,?,?,?,?)
        """,
        (run_id, framework, mode, agent_model, user_sim_model, started_at),
    )
    conn.commit()
