"""PydanticAI implementation for BIRD-Interact.

Per-task context is passed via PydanticAI's `deps` mechanism — no global
state, no subprocess. Tools access task data through `ctx.deps`.
"""

import json
import logging
import re
from typing import Any

from dataclasses import replace

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits

from bird_interact_agents.agents.claude_sdk.agent import MAX_MODEL_TURNS


def _make_prepare_tools(strict_value: bool):
    """Return a `prepare_tools` callback that forces a uniform `strict` on
    every tool definition right before each model request.

    Cerebras's OpenAI-compatible API rejects requests with inconsistent
    `strict` values across entries — PydanticAI's native @agent.tool
    defaults to None and MCP-server tools also come in as None, so the
    merged list violates the constraint. This callback is PydanticAI's
    documented mechanism for cross-source uniformity (see the example
    `turn_on_strict_if_openai` in pydantic_ai.tools).
    """

    async def _force_strict(
        ctx: RunContext, tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        return [replace(td, strict=strict_value) for td in tool_defs]

    return _force_strict

from bird_interact_agents.agents.claude_sdk.prompts import (
    RAW_A_INTERACT,
    RAW_C_INTERACT,
    SLAYER_A_INTERACT,
    SLAYER_C_INTERACT,
)
from bird_interact_agents.harness import (
    SampleStatus,
    _filter_knowledge_for_agent,
    _schema_cache,
    build_user_decoder_prompt,
    build_user_encoder_prompt,
    execute_env_action,
    execute_submit_action,
    load_db_data_if_needed,
    parse_encoder_response,
    slayer_mcp_stdio_config,
)

logger = logging.getLogger(__name__)


class TaskDeps(BaseModel):
    """Per-task dependencies injected into every tool call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: SampleStatus
    data_path_base: str
    user_sim_model: str = "anthropic/claude-haiku-4-5-20251001"
    user_sim_prompt_version: str = "v2"
    slayer_storage_dir: str = ""
    # Mutable scratch space — recorded by submit tools, read by the runner.
    result: dict | None = None
    # SLayer client/storage cache (initialised lazily)
    _slayer_client: Any = None
    _slayer_storage: Any = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slayer_client(deps: TaskDeps):
    if deps._slayer_client is None:
        from slayer.client.slayer_client import SlayerClient
        from slayer.storage.yaml_storage import YAMLStorage

        storage = YAMLStorage(base_dir=deps.slayer_storage_dir)
        client = SlayerClient(storage=storage)
        deps._slayer_client = client
        deps._slayer_storage = storage
    return deps._slayer_client


async def _ask_user_impl(deps: TaskDeps, question: str) -> str:
    import litellm

    db_name = deps.status.original_data["selected_database"]
    schema = _schema_cache.get(db_name, "")

    encoder_prompt = build_user_encoder_prompt(
        question, deps.status, schema, deps.user_sim_prompt_version
    )
    encoder_resp = await litellm.acompletion(
        model=deps.user_sim_model,
        messages=[{"role": "user", "content": encoder_prompt}],
    )
    encoder_action = parse_encoder_response(
        encoder_resp.choices[0].message.content or ""
    )

    decoder_prompt = build_user_decoder_prompt(
        question, encoder_action, deps.status, schema, deps.user_sim_prompt_version
    )
    decoder_resp = await litellm.acompletion(
        model=deps.user_sim_model,
        messages=[{"role": "user", "content": decoder_prompt}],
    )
    raw_response = decoder_resp.choices[0].message.content or ""

    match = re.search(r"<s>(.*?)</s>", raw_response, re.DOTALL)
    return match.group(1).strip() if match else raw_response.strip()


# ---------------------------------------------------------------------------
# Agent factory — one agent per (query_mode, eval_mode) combo, since
# PydanticAI agents register tools at construction time.
# ---------------------------------------------------------------------------

def _build_raw_a_agent(model: str, strict_value: bool = False) -> Agent:
    agent = Agent(
        model=model, deps_type=TaskDeps, retries=2,
        prepare_tools=_make_prepare_tools(strict_value),
    )

    @agent.tool
    async def execute_sql(ctx: RunContext[TaskDeps], sql: str) -> str:
        """Execute a SQL query against the database and return results."""
        observation, _ = execute_env_action(
            f"execute({sql})", ctx.deps.status, ctx.deps.data_path_base
        )
        return str(observation)

    @agent.tool
    async def get_schema(ctx: RunContext[TaskDeps]) -> str:
        """Get the database schema (CREATE TABLE statements with sample data)."""
        observation, _ = execute_env_action(
            "get_schema()", ctx.deps.status, ctx.deps.data_path_base
        )
        return str(observation)

    @agent.tool
    async def get_all_column_meanings(ctx: RunContext[TaskDeps]) -> str:
        """Get the meanings/descriptions of all columns in the database."""
        observation, _ = execute_env_action(
            "get_all_column_meanings()", ctx.deps.status, ctx.deps.data_path_base
        )
        return str(observation)

    @agent.tool
    async def get_column_meaning(
        ctx: RunContext[TaskDeps], table_name: str, column_name: str
    ) -> str:
        """Get the meaning of a specific column in a table."""
        action = f"get_column_meaning('{table_name}', '{column_name}')"
        observation, _ = execute_env_action(
            action, ctx.deps.status, ctx.deps.data_path_base
        )
        return str(observation)

    @agent.tool
    async def get_all_external_knowledge_names(ctx: RunContext[TaskDeps]) -> str:
        """List all available external knowledge entry names for this database."""
        observation, _ = execute_env_action(
            "get_all_external_knowledge_names()", ctx.deps.status, ctx.deps.data_path_base
        )
        return str(observation)

    @agent.tool
    async def get_knowledge_definition(
        ctx: RunContext[TaskDeps], knowledge_name: str
    ) -> str:
        """Get the definition of a specific external knowledge entry."""
        action = f"get_knowledge_definition('{knowledge_name}')"
        observation, _ = execute_env_action(
            action, ctx.deps.status, ctx.deps.data_path_base
        )
        return str(observation)

    @agent.tool
    async def get_all_knowledge_definitions(ctx: RunContext[TaskDeps]) -> str:
        """Get all external knowledge definitions for this database."""
        observation, _ = execute_env_action(
            "get_all_knowledge_definitions()", ctx.deps.status, ctx.deps.data_path_base
        )
        return str(observation)

    @agent.tool
    async def ask_user(ctx: RunContext[TaskDeps], question: str) -> str:
        """Ask the user a clarification question about their query."""
        return await _ask_user_impl(ctx.deps, question)

    @agent.tool
    async def submit_sql(ctx: RunContext[TaskDeps], sql: str) -> str:
        """Submit your final SQL query for evaluation. Only submit when confident."""
        observation, reward, p1, p2, finished = execute_submit_action(
            sql, ctx.deps.status, ctx.deps.data_path_base
        )
        ctx.deps.result = {
            "phase1_passed": p1,
            "phase2_passed": p2,
            "total_reward": reward if reward is not None else 0.0,
            "finished": finished,
        }
        return str(observation)

    return agent


def _build_raw_c_agent(model: str, strict_value: bool = False) -> Agent:
    agent = Agent(
        model=model, deps_type=TaskDeps, retries=2,
        prepare_tools=_make_prepare_tools(strict_value),
    )

    @agent.tool
    async def ask_user(ctx: RunContext[TaskDeps], question: str) -> str:
        """Ask the user a clarification question about their query."""
        return await _ask_user_impl(ctx.deps, question)

    @agent.tool
    async def submit_sql(ctx: RunContext[TaskDeps], sql: str) -> str:
        """Submit your final SQL query for evaluation."""
        observation, reward, p1, p2, finished = execute_submit_action(
            sql, ctx.deps.status, ctx.deps.data_path_base
        )
        ctx.deps.result = {
            "phase1_passed": p1,
            "phase2_passed": p2,
            "total_reward": reward if reward is not None else 0.0,
            "finished": finished,
        }
        return str(observation)

    return agent


def _build_slayer_agent(
    model: str, slayer_storage_dir: str, strict_value: bool = False,
) -> Agent:
    """Build a SLayer-mode agent (shared between a- and c-interact variants).

    Discovery tools come from the actual `slayer mcp` server attached as a
    toolset. We only register `ask_user` and `submit_query` natively.
    """
    cfg = slayer_mcp_stdio_config(slayer_storage_dir)
    slayer_server = MCPServerStdio(
        command=cfg["command"], args=cfg["args"], env=cfg["env"]
    )
    agent = Agent(
        model=model, deps_type=TaskDeps, retries=2, toolsets=[slayer_server],
        prepare_tools=_make_prepare_tools(strict_value),
    )

    @agent.tool
    async def ask_user(ctx: RunContext[TaskDeps], question: str) -> str:
        """Ask the user a clarification question."""
        return await _ask_user_impl(ctx.deps, question)

    @agent.tool
    async def submit_query(ctx: RunContext[TaskDeps], query_json: str) -> str:
        """Submit your final SLayer query for evaluation. Translates the
        SLayer query JSON to SQL and tests it against the ground truth.
        """
        try:
            query_dict = json.loads(query_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON — submission aborted: {e}"

        client = _slayer_client(ctx.deps)
        try:
            sql = client.sql_sync(query_dict)
        except Exception as e:
            return f"Could not generate SQL — submission aborted: {e}"

        observation, reward, p1, p2, finished = execute_submit_action(
            sql, ctx.deps.status, ctx.deps.data_path_base
        )
        ctx.deps.result = {
            "phase1_passed": p1,
            "phase2_passed": p2,
            "total_reward": reward if reward is not None else 0.0,
            "finished": finished,
            "submitted_sql": sql,
        }
        return f"Generated SQL:\n{sql}\n\nResult: {observation}"

    return agent


# ---------------------------------------------------------------------------
# Top-level agent class
# ---------------------------------------------------------------------------


class PydanticAIAgent:
    """SystemAgent implementation using PydanticAI."""

    def __init__(
        self,
        slayer_storage_root: str | None = None,
        model: str = "anthropic/claude-sonnet-4-5",
        strict: bool = False,
    ) -> None:
        from bird_interact_agents.model_string import to_pydantic_ai

        self.slayer_storage_root = slayer_storage_root
        # Accept the canonical LiteLLM-style `provider/model_id` and convert
        # to PydanticAI's `provider:model_id`. PydanticAI also accepts the
        # colon form natively, so this is idempotent for callers that
        # already pass that shape.
        self.model = to_pydantic_ai(model) if "/" in model else model
        self.strict = strict

    def _select_agent(
        self,
        query_mode: str,
        eval_mode: str,
        slayer_storage_dir: str = "",
    ) -> Agent:
        if query_mode == "raw" and eval_mode == "a-interact":
            return _build_raw_a_agent(self.model, self.strict)
        if query_mode == "raw" and eval_mode == "c-interact":
            return _build_raw_c_agent(self.model, self.strict)
        if query_mode == "slayer":
            # Same agent shape for a- and c-interact; the system prompt
            # differs in the runner.
            return _build_slayer_agent(
                self.model, slayer_storage_dir, self.strict,
            )
        raise ValueError(f"Unknown mode combo: {query_mode}/{eval_mode}")

    async def _build_prompt(
        self, query_mode: str, eval_mode: str, task_data: dict, budget: float, deps: TaskDeps
    ) -> str:
        user_query = task_data["amb_user_query"]
        db_name = task_data["selected_database"]

        if query_mode == "raw" and eval_mode == "a-interact":
            return RAW_A_INTERACT.format(
                budget=budget, db_name=db_name, user_query=user_query
            )
        if query_mode == "raw" and eval_mode == "c-interact":
            schema = _schema_cache.get(db_name, "")
            knowledge = _filter_knowledge_for_agent(db_name, task_data)
            knowledge_text = "\n".join(
                f"- {k}: {v.get('description', '') or v.get('definition', '')}"
                for k, v in (knowledge or {}).items()
            )
            return RAW_C_INTERACT.format(
                budget=budget, db_name=db_name, user_query=user_query,
                schema=schema, knowledge=knowledge_text or "(none)",
            )
        if query_mode == "slayer" and eval_mode == "a-interact":
            return SLAYER_A_INTERACT.format(budget=budget, user_query=user_query)
        if query_mode == "slayer" and eval_mode == "c-interact":
            from slayer.help import render_help
            from slayer.storage.yaml_storage import YAMLStorage

            storage = YAMLStorage(base_dir=deps.slayer_storage_dir)
            names = await storage.list_models()
            lines = []
            for name in names:
                m = await storage.get_model(name)
                dims = ", ".join(d.name for d in (m.dimensions or [])[:8]) if m else ""
                meas = ", ".join(x.name for x in (m.measures or [])[:8]) if m else ""
                lines.append(f"- {name}: dims=[{dims}] measures=[{meas}]")
            return SLAYER_C_INTERACT.format(
                budget=budget, user_query=user_query,
                slayer_help=render_help(),
                models_summary="\n".join(lines),
            )
        raise ValueError(f"Unknown mode combo: {query_mode}/{eval_mode}")

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
        db_name = task_data["selected_database"]
        instance_id = task_data["instance_id"]

        load_db_data_if_needed(db_name, data_path_base)
        status = SampleStatus(
            idx=0, original_data=task_data,
            remaining_budget=budget, total_budget=budget,
        )
        slayer_storage_dir = (
            f"{self.slayer_storage_root}/{db_name}" if self.slayer_storage_root else ""
        )

        deps = TaskDeps(
            status=status,
            data_path_base=data_path_base,
            user_sim_model=user_sim_model,
            user_sim_prompt_version=user_sim_prompt_version,
            slayer_storage_dir=slayer_storage_dir,
        )

        agent = self._select_agent(query_mode, eval_mode, slayer_storage_dir)
        prompt = await self._build_prompt(query_mode, eval_mode, task_data, budget, deps)

        try:
            # Lift PydanticAI's default request_limit (50) above our
            # MAX_MODEL_TURNS cap so long-tail tasks don't get killed
            # mid-flight before they can submit. Multiply by 2 because
            # one of our "turns" can map to multiple HTTP requests when
            # the model issues a tool call followed by its consumption
            # of the tool result in the same step.
            agent_run = await agent.run(
                user_prompt=task_data["amb_user_query"],
                instructions=prompt,
                deps=deps,
                usage_limits=UsageLimits(request_limit=MAX_MODEL_TURNS * 2),
            )
            output_text = str(agent_run.output)
        except Exception as e:
            logger.error("Agent error on %s: %s", instance_id, e)
            return {
                "task_id": instance_id, "instance_id": instance_id,
                "database": db_name,
                "phase1_passed": False, "phase2_passed": False,
                "total_reward": 0.0, "trajectory": [],
                "error": str(e),
            }

        result = deps.result or {}
        return {
            "task_id": instance_id,
            "instance_id": instance_id,
            "database": db_name,
            "phase1_passed": result.get("phase1_passed", False),
            "phase2_passed": result.get("phase2_passed", False),
            "total_reward": result.get("total_reward", 0.0),
            "trajectory": [{"final_output": output_text[:500]}],
            "error": None,
        }
