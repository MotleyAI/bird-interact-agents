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
    _schema_cache,
    build_user_decoder_prompt,
    build_user_encoder_prompt,
    execute_env_action,
    execute_submit_action,
    parse_encoder_response,
)
from bird_interact_agents.usage import acompletion_tracked


# ---------------------------------------------------------------------------
# bird-interact discovery + submission
# ---------------------------------------------------------------------------

def run_env_action(state: Any, spec: ToolSpec, **kwargs: str) -> str:
    """Render `spec` to an action string and dispatch via the harness."""
    action = render_action(spec, **kwargs)
    observation, _ = execute_env_action(action, state.status, state.data_path_base)
    return str(observation)


def submit_raw_sql(state: Any, sql: str) -> str:
    """Submit a raw SQL query and record the submission on `state.result`."""
    observation, reward, p1, p2, finished = execute_submit_action(
        sql, state.status, state.data_path_base,
    )
    state.result = {
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "submitted_sql": sql,
        "submitted_query": None,
    }
    return str(observation)


def submit_slayer_query(
    state: Any,
    query_json: str,
    slayer_client_factory: Callable[[Any], Any],
) -> str:
    """Submit a SLayer JSON query: render to SQL, then evaluate.

    Records both the original JSON DSL and the rendered SQL on
    `state.result`. Returns a friendly observation string for the agent
    (or an error message if the JSON is malformed / the SLayer client
    rejects the query).
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
    state.result = {
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "submitted_sql": sql,
        "submitted_query": query_json,
    }
    return f"Generated SQL:\n{sql}\n\nResult: {observation}"


# ---------------------------------------------------------------------------
# User simulator (encoder + decoder via litellm)
# ---------------------------------------------------------------------------

async def ask_user_impl(state: Any, question: str) -> str:
    """Two-stage user simulator: encoder extracts an intent, decoder
    renders the user's reply. Both LLM calls are routed through
    `acompletion_tracked` so usage lands on `state.usage`.
    """
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
    return match.group(1).strip() if match else raw_response.strip()
