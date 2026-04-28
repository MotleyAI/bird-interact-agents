"""Agno (formerly Phidata) implementation for BIRD-Interact.

In SLayer mode the slayer MCP server is attached via `MCPTools` (Agno's
stdio MCP toolkit). Native tools are plain async closures over per-task
state — same pattern as the mcp-agent adapter.
"""

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from bird_interact_agents.agents._prompt_builders import (
    build_raw_c_interact_prompt,
    build_slayer_c_interact_prompt,
)
from bird_interact_agents.agents.claude_sdk.prompts import (
    RAW_A_INTERACT,
    SLAYER_A_INTERACT,
)
from bird_interact_agents.harness import (
    ACTION_COSTS,
    SampleStatus,
    _schema_cache,
    build_user_decoder_prompt,
    build_user_encoder_prompt,
    execute_env_action,
    execute_submit_action,
    load_db_data_if_needed,
    parse_encoder_response,
    slayer_mcp_stdio_config,
    update_budget,
)

logger = logging.getLogger(__name__)


class TaskState(BaseModel):
    """Per-task state, closed over by the native tool functions."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: SampleStatus
    data_path_base: str
    user_sim_model: str
    user_sim_prompt_version: str
    slayer_storage_dir: str = ""
    result: dict | None = None
    _slayer_client: Any = None
    _slayer_storage: Any = None


def _slayer_client(state: TaskState):
    if state._slayer_client is None:
        from slayer.client.slayer_client import SlayerClient
        from slayer.storage.yaml_storage import YAMLStorage

        storage = YAMLStorage(base_dir=state.slayer_storage_dir)
        state._slayer_client = SlayerClient(storage=storage)
        state._slayer_storage = storage
    return state._slayer_client


async def _ask_user_impl(state: TaskState, question: str) -> str:
    import litellm

    db_name = state.status.original_data["selected_database"]
    schema = _schema_cache.get(db_name, "")

    encoder_prompt = build_user_encoder_prompt(
        question, state.status, schema, state.user_sim_prompt_version
    )
    encoder_resp = await litellm.acompletion(
        model=state.user_sim_model,
        messages=[{"role": "user", "content": encoder_prompt}],
    )
    encoder_action = parse_encoder_response(
        encoder_resp.choices[0].message.content or ""
    )

    decoder_prompt = build_user_decoder_prompt(
        question, encoder_action, state.status, schema, state.user_sim_prompt_version
    )
    decoder_resp = await litellm.acompletion(
        model=state.user_sim_model,
        messages=[{"role": "user", "content": decoder_prompt}],
    )
    raw_response = decoder_resp.choices[0].message.content or ""

    match = re.search(r"<s>(.*?)</s>", raw_response, re.DOTALL)
    return match.group(1).strip() if match else raw_response.strip()


def _budget_note(status: SampleStatus) -> str:
    return (
        f"\n\n[Remaining budget: {status.remaining_budget:.1f}"
        f" / {status.total_budget:.1f}]"
    )


def _gate(action_name: str, status: SampleStatus, query_mode: str) -> str | None:
    """Reject a non-submit tool call when budget would go below submit cost.

    Mirrors `claude_sdk.agent._gate`. Honors `status.force_submit` and uses
    the right submit tool name for the active query mode.
    """
    if action_name.startswith("submit_"):
        return None
    submit_tool = "submit_query" if query_mode == "slayer" else "submit_sql"
    submit_cost = ACTION_COSTS[submit_tool]
    cost = ACTION_COSTS.get(action_name, 0)
    if status.force_submit or status.remaining_budget < cost + submit_cost:
        return (
            f"Budget exhausted ({status.remaining_budget:.1f} remaining, "
            f"{action_name} costs {cost}). You MUST call {submit_tool} now "
            "with your best answer."
        )
    return None


def _build_native_tools(
    state: TaskState, query_mode: str, eval_mode: str = "a-interact"
) -> list:
    """Construct the native tool functions, closing over per-task state.

    Each tool is a plain async function with a docstring — Agno auto-converts
    these into tool definitions for the model. Each non-submit tool gates on
    budget, executes, then `update_budget`s; submit tools `update_budget`
    after running.
    """

    async def _run_env(action_name: str, action_str: str) -> str:
        err = _gate(action_name, state.status, query_mode)
        if err is not None:
            return err
        observation, _ = execute_env_action(
            action_str, state.status, state.data_path_base
        )
        update_budget(state.status, action_name)
        return str(observation) + _budget_note(state.status)

    async def ask_user(question: str) -> str:
        """Ask the user a clarification question about their query."""
        err = _gate("ask_user", state.status, query_mode)
        if err is not None:
            return err
        answer = await _ask_user_impl(state, question)
        update_budget(state.status, "ask_user")
        return answer + _budget_note(state.status)

    async def execute_sql(sql: str) -> str:
        """Execute a SQL query against the database and return results."""
        return await _run_env("execute_sql", f"execute({sql})")

    async def get_schema() -> str:
        """Get the database schema (CREATE TABLE statements with sample data)."""
        return await _run_env("get_schema", "get_schema()")

    async def get_all_column_meanings() -> str:
        """Get the meanings/descriptions of all columns in the database."""
        return await _run_env("get_all_column_meanings", "get_all_column_meanings()")

    async def get_column_meaning(table_name: str, column_name: str) -> str:
        """Get the meaning of a specific column in a table."""
        action = f"get_column_meaning('{table_name}', '{column_name}')"
        return await _run_env("get_column_meaning", action)

    async def get_all_external_knowledge_names() -> str:
        """List all available external knowledge entry names for this database."""
        return await _run_env(
            "get_all_external_knowledge_names",
            "get_all_external_knowledge_names()",
        )

    async def get_knowledge_definition(knowledge_name: str) -> str:
        """Get the definition of a specific external knowledge entry."""
        action = f"get_knowledge_definition('{knowledge_name}')"
        return await _run_env("get_knowledge_definition", action)

    async def get_all_knowledge_definitions() -> str:
        """Get all external knowledge definitions for this database."""
        return await _run_env(
            "get_all_knowledge_definitions", "get_all_knowledge_definitions()"
        )

    async def submit_sql(sql: str) -> str:
        """Submit your final SQL query for evaluation. Only submit when confident."""
        observation, reward, p1, p2, finished = execute_submit_action(
            sql, state.status, state.data_path_base
        )
        update_budget(state.status, "submit_sql")
        state.result = {
            "phase1_passed": p1,
            "phase2_passed": p2,
            "total_reward": reward if reward is not None else 0.0,
            "finished": finished,
        }
        return str(observation) + _budget_note(state.status)

    async def submit_query(query_json: str) -> str:
        """Submit your final SLayer query for evaluation. Translates the
        SLayer query JSON to SQL deterministically and tests against
        ground truth.
        """
        try:
            query_dict = json.loads(query_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON — submission aborted: {e}"
        client = _slayer_client(state)
        try:
            sql = client.sql_sync(query_dict)
        except Exception as e:
            return f"Could not generate SQL — submission aborted: {e}"
        observation, reward, p1, p2, finished = execute_submit_action(
            sql, state.status, state.data_path_base
        )
        update_budget(state.status, "submit_query")
        state.result = {
            "phase1_passed": p1,
            "phase2_passed": p2,
            "total_reward": reward if reward is not None else 0.0,
            "finished": finished,
            "submitted_sql": sql,
        }
        return f"Generated SQL:\n{sql}\n\nResult: {observation}" + _budget_note(state.status)

    if query_mode == "raw" and eval_mode == "c-interact":
        return [ask_user, submit_sql]
    if query_mode == "raw":
        return [
            execute_sql,
            get_schema,
            get_all_column_meanings,
            get_column_meaning,
            get_all_external_knowledge_names,
            get_knowledge_definition,
            get_all_knowledge_definitions,
            ask_user,
            submit_sql,
        ]
    return [ask_user, submit_query]


async def _build_prompt(
    query_mode: str, eval_mode: str, task_data: dict, budget: float, state: TaskState
) -> str:
    user_query = task_data["amb_user_query"]
    db_name = task_data["selected_database"]

    if query_mode == "raw" and eval_mode == "a-interact":
        return RAW_A_INTERACT.format(
            budget=budget, db_name=db_name, user_query=user_query
        )
    if query_mode == "raw" and eval_mode == "c-interact":
        return await build_raw_c_interact_prompt(
            budget=budget,
            db_name=db_name,
            user_query=user_query,
            task_data=task_data,
        )
    if query_mode == "slayer" and eval_mode == "a-interact":
        return SLAYER_A_INTERACT.format(budget=budget, user_query=user_query)
    if query_mode == "slayer" and eval_mode == "c-interact":
        return await build_slayer_c_interact_prompt(
            budget=budget,
            user_query=user_query,
            slayer_storage_dir=state.slayer_storage_dir,
            db_name=db_name,
            task_data=task_data,
        )
    raise ValueError(f"Unknown mode combo: {query_mode}/{eval_mode}")


class AgnoAgent:
    """SystemAgent implementation using Agno."""

    def __init__(
        self,
        slayer_storage_root: str | None = None,
        model_id: str = "anthropic/claude-sonnet-4-5",
        strict: bool = False,
    ) -> None:
        self.slayer_storage_root = slayer_storage_root
        # Canonical LiteLLM-style "provider/model_id". For Anthropic we
        # construct an `agno.models.anthropic.Claude(id=...)` with the
        # bare model id; for everything else we use Agno's LiteLLM shim
        # which accepts the prefixed string verbatim.
        self.model_id = model_id
        self.strict = strict

    async def run_task(
        self,
        task_data: dict,
        data_path_base: str,
        budget: float,
        query_mode: str,
        eval_mode: str = "a-interact",
        user_sim_model: str = "anthropic/claude-haiku-4-5-20251001",
        user_sim_prompt_version: str = "v2",
    ) -> dict:
        from agno.agent import Agent
        from agno.tools.mcp import MCPTools

        from bird_interact_agents.model_string import is_anthropic, native_model_id

        if is_anthropic(self.model_id):
            from agno.models.anthropic import Claude
            # Anthropic doesn't have a tool-level strict concept; --strict
            # is silently a no-op for the anthropic/* path.
            agno_model = Claude(id=native_model_id(self.model_id))
        else:
            from agno.models.litellm import LiteLLM

            class _StrictLiteLLM(LiteLLM):
                """Force a uniform `strict` value on every tool dict in the
                outgoing litellm.completion request. agno's stock LiteLLM
                doesn't write strict; subclassing get_request_params is the
                surgical place to inject it."""

                def __init__(self, *a, _strict_value: bool, **kw):
                    super().__init__(*a, **kw)
                    self._strict_value = _strict_value

                def get_request_params(self, tools=None):
                    params = super().get_request_params(tools=tools)
                    for t in params.get("tools") or []:
                        t.setdefault("function", {})["strict"] = self._strict_value
                    return params

            agno_model = _StrictLiteLLM(id=self.model_id, _strict_value=self.strict)

        db_name = task_data["selected_database"]
        instance_id = task_data["instance_id"]
        load_db_data_if_needed(db_name, data_path_base)

        slayer_storage_dir = (
            f"{self.slayer_storage_root}/{db_name}" if self.slayer_storage_root else ""
        )
        state = TaskState(
            status=SampleStatus(
                idx=0, original_data=task_data,
                remaining_budget=budget, total_budget=budget,
            ),
            data_path_base=data_path_base,
            user_sim_model=user_sim_model,
            user_sim_prompt_version=user_sim_prompt_version,
            slayer_storage_dir=slayer_storage_dir,
        )

        native_tools = _build_native_tools(state, query_mode, eval_mode)
        prompt = await _build_prompt(query_mode, eval_mode, task_data, budget, state)

        async def _run_with_tools(tools_list: list) -> str:
            agent = Agent(
                model=agno_model,
                tools=tools_list,
                instructions=prompt,
            )
            response = await agent.arun(task_data["amb_user_query"])
            return str(response.content) if response and response.content else ""

        try:
            if query_mode == "slayer":
                cfg = slayer_mcp_stdio_config(slayer_storage_dir)
                async with MCPTools(
                    command=cfg["command"] + " " + " ".join(cfg["args"]),
                    env=cfg["env"],
                ) as slayer_mcp:
                    output = await _run_with_tools([slayer_mcp, *native_tools])
            else:
                output = await _run_with_tools(native_tools)
        except Exception as e:
            logger.error("Agent error on %s: %s", instance_id, e)
            return {
                "task_id": instance_id, "instance_id": instance_id,
                "database": db_name,
                "phase1_passed": False, "phase2_passed": False,
                "total_reward": 0.0, "trajectory": [],
                "error": str(e),
            }

        result = state.result or {}
        return {
            "task_id": instance_id,
            "instance_id": instance_id,
            "database": db_name,
            "phase1_passed": result.get("phase1_passed", False),
            "phase2_passed": result.get("phase2_passed", False),
            "total_reward": result.get("total_reward", 0.0),
            "trajectory": [{"final_output": output[:500]}],
            "error": None,
        }
