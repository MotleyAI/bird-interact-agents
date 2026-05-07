"""Shared per-task helpers used by every framework adapter.

`submit_raw_sql`, `submit_slayer_query`, `ask_user_impl`, and
`run_env_action` are the authoritative implementations of the
operations each adapter exposes as tools. Adapter files contain only
the framework-specific decoration; the bodies live here.

State is duck-typed — every adapter's per-task object (`TaskDeps`,
`TaskState`, contextvar dict) just needs to expose the attributes the
helpers touch (`status`, `data_path_base`, `usage`, `result`,
`user_sim_model`, `user_sim_prompt_version`).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from typing import Any, Callable

from bird_interact_agents.agents._tool_specs import ToolSpec, render_action
from bird_interact_agents.harness import (
    ACTION_COSTS,
    _schema_cache,
    build_user_decoder_prompt,
    build_user_encoder_prompt,
    execute_env_action,
    execute_submit_action,
    parse_encoder_response,
    update_budget,
)
from bird_interact_agents.usage import acompletion_tracked

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Diagnostic capture: snapshot result rows for offline failure analysis.
# ---------------------------------------------------------------------------

# Number of rows kept in the snapshot's `sample_rows`. Bigger samples make the
# results.db payloads heavy without adding much analytic value — most failure
# modes show up in the first row or in the column header.
_SNAPSHOT_SAMPLE_SIZE = 5
# Total rows examined to compute `row_count`. Past this we mark the snapshot
# truncated so analysis code can be aware (BIRD-Interact's own MAX_ROWS=10000).
_SNAPSHOT_MAX_ROWS = 10000


def _jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return f"<bytes:{len(value)}>"
    return value


def _first_sql(value: Any) -> str | None:
    """sol_sql is sometimes a string, sometimes a list; pick the first
    non-empty string."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item
    return None


def capture_result_snapshot(
    sql: str | None,
    db_name: str,
    data_path_base: str,
) -> dict | None:
    """Run `sql` against the canonical SQLite file and return a serialisable
    snapshot — column names + inferred Python types + row count + a small
    head sample.

    Side-effect-free: opens a private connection and never touches the
    BIRD-Interact connection cache. SELECTs run after `execute_submit_action`
    (which reset the DB at task start) see canonical data — adequate for the
    DBs used in this benchmark, which have no Management/phase-2 tasks.

    Returns None when `sql` is empty or the DB file is absent. On any
    runtime error returns `{"error": "<type>: <msg>"}` rather than raising,
    so failures here don't sink the run.
    """
    if not sql or not sql.strip():
        return None
    db_path = os.path.join(data_path_base, db_name, f"{db_name}.sqlite")
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchmany(_SNAPSHOT_MAX_ROWS + 1)
            truncated = len(rows) > _SNAPSHOT_MAX_ROWS
            if truncated:
                rows = rows[:_SNAPSHOT_MAX_ROWS]
            col_names = [d[0] for d in (cur.description or [])]
            sample = rows[:_SNAPSHOT_SAMPLE_SIZE]
            types: list[str] = []
            for i, _ in enumerate(col_names):
                inferred = "null"
                for row in rows:
                    if i < len(row) and row[i] is not None:
                        inferred = type(row[i]).__name__
                        break
                types.append(inferred)
            return {
                "columns": [
                    {"name": n, "type": t} for n, t in zip(col_names, types)
                ],
                "row_count": len(rows),
                "row_count_truncated": truncated,
                "sample_rows": [
                    [_jsonable(v) for v in row] for row in sample
                ],
            }
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 — capture every failure mode
        logger.debug("capture_result_snapshot failed for %s: %s", db_name, e)
        return {"error": f"{type(e).__name__}: {e}"}


def classify_submission(
    *,
    p1: bool,
    p2: bool,
    observation: str | None,
    json_failed: bool = False,
    translation_failed: bool = False,
    infrastructure_failed: bool = False,
) -> str:
    """Bucket one submission outcome into a coarse status string.

    The string is the primary axis the user uses for offline failure-mode
    analysis. SQL-runtime vs. wrong-result is detected by string-matching the
    canonical evaluator's observation message (see
    `execute_submit_action`).
    """
    if json_failed:
        return "json_error"
    if translation_failed:
        return "translation_error"
    if infrastructure_failed:
        return "infrastructure_error"
    if p2:
        return "passed_phase2"
    if p1:
        return "passed_phase1"
    obs = (observation or "").lower()
    if (
        "error executing submitted sql" in obs
        or "submitted sql execution timed out" in obs
        or "error processing submission" in obs
    ):
        return "sql_runtime_error"
    return "wrong_result"


def _diagnostic_payload(
    *,
    submitted_sql: str | None,
    sample_status: Any,
    data_path_base: str,
    observation: str | None,
    p1: bool,
    p2: bool,
    json_failed: bool = False,
    translation_failed: bool = False,
    infrastructure_failed: bool = False,
) -> dict[str, Any]:
    """Build the dict that `submit_*` writes onto `state.result` for the
    diagnostic columns: predicted/gold snapshots + classifier verdict +
    the raw evaluator observation, keyed by the phase the call ran in."""
    db_name = sample_status.original_data["selected_database"]
    sol_sql = _first_sql(sample_status.original_data.get("sol_sql"))
    pre_phase = getattr(sample_status, "current_phase", 1)

    skip_snapshots = json_failed or translation_failed
    predicted = (
        capture_result_snapshot(submitted_sql, db_name, data_path_base)
        if not skip_snapshots else None
    )
    gold = (
        capture_result_snapshot(sol_sql, db_name, data_path_base)
        if not skip_snapshots else None
    )

    payload: dict[str, Any] = {
        "submission_status": classify_submission(
            p1=p1, p2=p2, observation=observation,
            json_failed=json_failed,
            translation_failed=translation_failed,
            infrastructure_failed=infrastructure_failed,
        ),
        "predicted_result_json": (
            json.dumps(predicted, default=str)
            if predicted is not None else None
        ),
        "gold_result_json": (
            json.dumps(gold, default=str) if gold is not None else None
        ),
    }
    if pre_phase == 2:
        payload["phase2_observation"] = observation
    else:
        payload["phase1_observation"] = observation
    return payload


# ---------------------------------------------------------------------------
# Budget bookkeeping. Centralised so every adapter shares one authoritative
# budget-update path; `claude_sdk.agent._gate` does pre-call rejection only.
# ---------------------------------------------------------------------------

def _budget_note(state: Any) -> str:
    status = state.status
    return (
        f"\n\n[Remaining budget: {status.remaining_budget:.1f}"
        f" / {status.total_budget:.1f}]"
    )


def gate_or_none(state: Any, action_name: str, query_mode: str) -> str | None:
    """Return a "you must submit" message if the call should be rejected,
    or None if it should proceed.

    Submit tools always proceed (they're the way out of force_submit).
    Honors `state.status.force_submit` and respects the right submit-tool
    name for the active query mode.
    """
    if action_name.startswith("submit_"):
        return None
    submit_tool = "submit_query" if query_mode == "slayer" else "submit_sql"
    submit_cost = ACTION_COSTS[submit_tool]
    cost = ACTION_COSTS.get(action_name, 0)
    if state.status.force_submit or state.status.remaining_budget < cost + submit_cost:
        return (
            f"Budget exhausted ({state.status.remaining_budget:.1f} remaining, "
            f"{action_name} costs {cost}). You MUST call {submit_tool} now "
            "with your best answer."
        )
    return None


# ---------------------------------------------------------------------------
# bird-interact discovery + submission
# ---------------------------------------------------------------------------

def run_env_action(
    state: Any, spec: ToolSpec, query_mode: str = "raw", **kwargs: str,
) -> str:
    """Render `spec` to an action string and dispatch via the harness.

    Applies budget gating + bookkeeping so a non-submit tool is rejected
    when `state.status.force_submit` is set or budget would drop below
    submit cost. Successful calls update_budget and append a remaining-
    budget note.
    """
    err = gate_or_none(state, spec.name, query_mode)
    if err is not None:
        return err
    action = render_action(spec, **kwargs)
    observation, _ = execute_env_action(action, state.status, state.data_path_base)
    update_budget(state.status, spec.name)
    return str(observation) + _budget_note(state)


def submit_raw_sql(state: Any, sql: str) -> str:
    """Submit a raw SQL query and record the submission on `state.result`.

    `submit_sql` is exempt from gate rejection — it's the way out of
    force_submit — but it still calls update_budget so subsequent reward
    accounting matches the upstream harness.
    """
    pre_phase = getattr(state.status, "current_phase", 1)
    infra_failed = False
    try:
        observation, reward, p1, p2, finished = execute_submit_action(
            sql, state.status, state.data_path_base,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("execute_submit_action raised on %s", sql[:80])
        observation = f"Error processing submission: {e}"
        reward, p1, p2, finished = 0.0, False, False, False
        infra_failed = True
    update_budget(state.status, "submit_sql")
    diag = _diagnostic_payload(
        submitted_sql=sql,
        sample_status=state.status,
        data_path_base=state.data_path_base,
        observation=observation,
        p1=p1,
        p2=p2,
        infrastructure_failed=infra_failed,
    )
    prior = state.result or {}
    state.result = {
        **prior,
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "submitted_sql": sql,
        "submitted_query": None,
        # Diagnostic fields. _diagnostic_payload writes phaseN_observation
        # only for the phase this call ran in; we keep the other one from
        # `prior` so a phase-2 submission doesn't blank out a stored phase-1
        # message.
        **diag,
    }
    if pre_phase == 1:
        state.result["phase2_observation"] = prior.get("phase2_observation")
    else:
        state.result["phase1_observation"] = prior.get("phase1_observation")
    return str(observation) + _budget_note(state)


def submit_slayer_query(
    state: Any,
    query_json: str,
    slayer_client_factory: Callable[[Any], Any],
) -> str:
    """Submit a SLayer JSON query: render to SQL, then evaluate.

    Records both the original JSON DSL and the rendered SQL on
    `state.result`. Returns a friendly observation string for the agent
    (or an error message if the JSON is malformed / the SLayer client
    rejects the query). Budget bookkeeping mirrors `submit_raw_sql`.
    """
    pre_phase = getattr(state.status, "current_phase", 1)
    prior = state.result or {}

    def _record(*, sql: str | None, observation: str | None,
                reward: float, p1: bool, p2: bool, finished: bool,
                json_failed: bool = False, translation_failed: bool = False,
                infrastructure_failed: bool = False) -> None:
        diag = _diagnostic_payload(
            submitted_sql=sql,
            sample_status=state.status,
            data_path_base=state.data_path_base,
            observation=observation,
            p1=p1, p2=p2,
            json_failed=json_failed,
            translation_failed=translation_failed,
            infrastructure_failed=infrastructure_failed,
        )
        state.result = {
            **prior,
            "phase1_passed": p1,
            "phase2_passed": p2,
            "total_reward": reward,
            "finished": finished,
            "submitted_sql": sql,
            "submitted_query": query_json,
            **diag,
        }
        if pre_phase == 1:
            state.result["phase2_observation"] = prior.get("phase2_observation")
        else:
            state.result["phase1_observation"] = prior.get("phase1_observation")

    try:
        query_dict = json.loads(query_json)
    except json.JSONDecodeError as e:
        update_budget(state.status, "submit_query")
        msg = f"Invalid JSON — submission aborted: {e}"
        _record(sql=None, observation=msg, reward=0.0,
                p1=False, p2=False, finished=False, json_failed=True)
        return msg + _budget_note(state)

    client = slayer_client_factory(state)
    try:
        sql = client.sql_sync(query_dict)
    except Exception as e:
        update_budget(state.status, "submit_query")
        msg = f"Could not generate SQL — submission aborted: {e}"
        _record(sql=None, observation=msg, reward=0.0,
                p1=False, p2=False, finished=False, translation_failed=True)
        return msg + _budget_note(state)

    infra_failed = False
    try:
        observation, reward, p1, p2, finished = execute_submit_action(
            sql, state.status, state.data_path_base,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("execute_submit_action raised on slayer-rendered SQL")
        observation = f"Error processing submission: {e}"
        reward, p1, p2, finished = 0.0, False, False, False
        infra_failed = True
    update_budget(state.status, "submit_query")
    _record(
        sql=sql,
        observation=observation,
        reward=reward if reward is not None else 0.0,
        p1=p1, p2=p2, finished=finished,
        infrastructure_failed=infra_failed,
    )
    return f"Generated SQL:\n{sql}\n\nResult: {observation}" + _budget_note(state)


# ---------------------------------------------------------------------------
# User simulator (encoder + decoder via litellm)
# ---------------------------------------------------------------------------

async def ask_user_impl(
    state: Any, question: str, query_mode: str | None = None,
) -> str:
    """Two-stage user simulator: encoder extracts an intent, decoder
    renders the user's reply. Both LLM calls are routed through
    `acompletion_tracked` so usage lands on `state.usage`.

    When `query_mode` is provided, applies the same budget gating as
    `run_env_action`: a force_submit-set status returns a "you must
    submit" message instead of running the user-sim. Successful calls
    decrement the budget by the cost of `ask_user`.
    """
    if query_mode is not None:
        err = gate_or_none(state, "ask_user", query_mode)
        if err is not None:
            return err

    db_name = state.status.original_data["selected_database"]
    schema = _schema_cache.get(db_name, "")

    encoder_prompt = build_user_encoder_prompt(
        question, state.status, schema, state.user_sim_prompt_version,
    )
    encoder_resp = await acompletion_tracked(
        state.usage,
        scope="user_sim",
        model=state.user_sim_model,
        messages=[{"role": "user", "content": encoder_prompt}],
    )
    encoder_action = parse_encoder_response(
        encoder_resp.choices[0].message.content or ""
    )

    decoder_prompt = build_user_decoder_prompt(
        question, encoder_action, state.status, schema, state.user_sim_prompt_version,
    )
    decoder_resp = await acompletion_tracked(
        state.usage,
        scope="user_sim",
        model=state.user_sim_model,
        messages=[{"role": "user", "content": decoder_prompt}],
    )
    raw_response = decoder_resp.choices[0].message.content or ""

    match = re.search(r"<s>(.*?)</s>", raw_response, re.DOTALL)
    answer = match.group(1).strip() if match else raw_response.strip()

    if query_mode is not None:
        update_budget(state.status, "ask_user")
        return answer + _budget_note(state)
    return answer
