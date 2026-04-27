"""mcp-agent (LastMile AI) implementation for BIRD-Interact.

mcp-agent is MCP-native: each agent is configured with a list of MCP
server names, and the SDK wires them up automatically. We use this to
attach the slayer MCP server in slayer mode without wrapping any of its
tools ourselves.

Native tools (`ask_user`, `submit_sql`, `submit_query`) are plain async
Python functions passed via `Agent.functions`. They close over per-task
state — no shared globals, no contextvars needed.
"""

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

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
    """Encoder/decoder user simulator using LiteLLM."""
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


def _build_native_functions(state: TaskState, query_mode: str) -> list:
    """Construct the native tool functions, closing over per-task state."""

    async def ask_user(question: str) -> str:
        """Ask the user a clarification question about their query."""
        return await _ask_user_impl(state, question)

    async def execute_sql(sql: str) -> str:
        """Execute a SQL query against the database and return results."""
        observation, _ = execute_env_action(
            f"execute({sql})", state.status, state.data_path_base
        )
        return str(observation)

    async def get_schema() -> str:
        """Get the database schema (CREATE TABLE statements with sample data)."""
        observation, _ = execute_env_action(
            "get_schema()", state.status, state.data_path_base
        )
        return str(observation)

    async def get_all_column_meanings() -> str:
        """Get the meanings/descriptions of all columns in the database."""
        observation, _ = execute_env_action(
            "get_all_column_meanings()", state.status, state.data_path_base
        )
        return str(observation)

    async def get_column_meaning(table_name: str, column_name: str) -> str:
        """Get the meaning of a specific column in a table."""
        action = f"get_column_meaning('{table_name}', '{column_name}')"
        observation, _ = execute_env_action(
            action, state.status, state.data_path_base
        )
        return str(observation)

    async def get_all_external_knowledge_names() -> str:
        """List all available external knowledge entry names for this database."""
        observation, _ = execute_env_action(
            "get_all_external_knowledge_names()", state.status, state.data_path_base
        )
        return str(observation)

    async def get_knowledge_definition(knowledge_name: str) -> str:
        """Get the definition of a specific external knowledge entry."""
        action = f"get_knowledge_definition('{knowledge_name}')"
        observation, _ = execute_env_action(
            action, state.status, state.data_path_base
        )
        return str(observation)

    async def get_all_knowledge_definitions() -> str:
        """Get all external knowledge definitions for this database."""
        observation, _ = execute_env_action(
            "get_all_knowledge_definitions()", state.status, state.data_path_base
        )
        return str(observation)

    async def submit_sql(sql: str) -> str:
        """Submit your final SQL query for evaluation. Only submit when confident."""
        observation, reward, p1, p2, finished = execute_submit_action(
            sql, state.status, state.data_path_base
        )
        state.result = {
            "phase1_passed": p1,
            "phase2_passed": p2,
            "total_reward": reward if reward is not None else 0.0,
            "finished": finished,
        }
        return str(observation)

    async def submit_query(query_json: str) -> str:
        """Submit your final SLayer query for evaluation. Translates to SQL
        deterministically and tests against ground truth.
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
        state.result = {
            "phase1_passed": p1,
            "phase2_passed": p2,
            "total_reward": reward if reward is not None else 0.0,
            "finished": finished,
            "submitted_sql": sql,
        }
        return f"Generated SQL:\n{sql}\n\nResult: {observation}"

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
    return [ask_user, submit_query]  # slayer mode — slayer MCP provides discovery


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

        storage = YAMLStorage(base_dir=state.slayer_storage_dir)
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


def _build_settings(query_mode: str, slayer_storage_dir: str):
    """Build mcp-agent Settings, registering the slayer MCP server in slayer mode."""
    from mcp_agent.config import MCPServerSettings, MCPSettings, Settings

    servers: dict = {}
    if query_mode == "slayer":
        cfg = slayer_mcp_stdio_config(slayer_storage_dir)
        servers["slayer"] = MCPServerSettings(
            name="slayer",
            transport="stdio",
            command=cfg["command"],
            args=cfg["args"],
            env=cfg["env"],
        )
    return Settings(mcp=MCPSettings(servers=servers))


class McpAgentAgent:
    """SystemAgent implementation using lastmile-ai/mcp-agent."""

    def __init__(
        self,
        slayer_storage_root: str | None = None,
        model: str = "claude-sonnet-4-5-20250929",
    ) -> None:
        self.slayer_storage_root = slayer_storage_root
        self.model = model

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
        from mcp_agent.agents.agent import Agent
        from mcp_agent.app import MCPApp
        from mcp_agent.workflows.llm.augmented_llm import RequestParams
        from mcp_agent.workflows.llm.augmented_llm_anthropic import AnthropicAugmentedLLM

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

        functions = _build_native_functions(state, query_mode)
        prompt = await _build_prompt(query_mode, eval_mode, task_data, budget, state)
        server_names = ["slayer"] if query_mode == "slayer" else []

        settings = _build_settings(query_mode, slayer_storage_dir)
        app = MCPApp(name="bird-interact-mcp-agent", settings=settings)

        try:
            async with app.run():
                agent = Agent(
                    name="bird_interact_agent",
                    instruction=prompt,
                    server_names=server_names,
                    functions=functions,
                )
                async with agent:
                    llm = await agent.attach_llm(AnthropicAugmentedLLM)
                    output = await llm.generate_str(
                        message=task_data["amb_user_query"],
                        request_params=RequestParams(model=self.model),
                    )
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
            "trajectory": [{"final_output": str(output)[:500]}],
            "error": None,
        }
