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
import re
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


# ---------------------------------------------------------------------------
# Budget bookkeeping — mirrors `claude_sdk.agent._gate`. Centralised here so
# every adapter shares one authoritative gate + budget-update path.
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
    observation, reward, p1, p2, finished = execute_submit_action(
        sql, state.status, state.data_path_base,
    )
    update_budget(state.status, "submit_sql")
    state.result = {
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "submitted_sql": sql,
        "submitted_query": None,
    }
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
    try:
        query_dict = json.loads(query_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON — submission aborted: {e}"

    client = slayer_client_factory(state)
    try:
        sql = client.sql_sync(query_dict)
    except Exception as e:
        return f"Could not generate SQL — submission aborted: {e}"

    observation, reward, p1, p2, finished = execute_submit_action(
        sql, state.status, state.data_path_base,
    )
    update_budget(state.status, "submit_query")
    state.result = {
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "submitted_sql": sql,
        "submitted_query": query_json,
    }
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
