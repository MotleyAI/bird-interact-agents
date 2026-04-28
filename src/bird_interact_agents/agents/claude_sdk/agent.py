"""Claude Agent SDK implementation for BIRD-Interact."""

import contextvars
import json
import logging
import re

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
    tool,
)

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

MAX_MODEL_TURNS = 60

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-task context — uses contextvars so concurrent task runs don't collide.
# Each invocation of run_task() sets the var, and tools read from it.
# `_ctx` is exposed as a dict-like proxy for backward compat with tests.
# ---------------------------------------------------------------------------
_ctx_var: contextvars.ContextVar[dict] = contextvars.ContextVar("_ctx_var")


class _CtxProxy:
    """Dict-like proxy that reads/writes the current contextvar value.

    Tests do `agent_mod._ctx = {...}` and `agent_mod._ctx["key"]` — both
    work via this proxy by setting/reading the contextvar.
    """

    def __getitem__(self, key):
        return _ctx_var.get()[key]

    def __setitem__(self, key, value):
        _ctx_var.get()[key] = value

    def __contains__(self, key):
        try:
            return key in _ctx_var.get()
        except LookupError:
            return False

    def get(self, key, default=None):
        try:
            return _ctx_var.get().get(key, default)
        except LookupError:
            return default

    def update(self, *args, **kwargs):
        try:
            current = _ctx_var.get()
        except LookupError:
            current = {}
            _ctx_var.set(current)
        current.update(*args, **kwargs)


_ctx = _CtxProxy()


def _text(msg: str) -> dict:
    """Helper to build a tool return value."""
    return {"content": [{"type": "text", "text": str(msg)}]}


def _budget_note(status: SampleStatus) -> str:
    return (
        f"\n\n[Remaining budget: {status.remaining_budget:.1f}"
        f" / {status.total_budget:.1f}]"
    )


def _gate(action_name: str, status: SampleStatus) -> str | None:
    """Reject a non-submit tool call when budget would go below submit cost.

    Returns an error message to surface back to the agent, or None if OK.
    Mirrors the `force_submit` gating in the original mini_interact_agent
    and ADK before_tool_callback.
    """
    if action_name.startswith("submit_"):
        return None
    submit_tool = "submit_query" if _ctx.get("query_mode") == "slayer" else "submit_sql"
    submit_cost = ACTION_COSTS[submit_tool]
    cost = ACTION_COSTS.get(action_name, 0)
    if status.force_submit or status.remaining_budget < cost + submit_cost:
        return (
            f"Budget exhausted ({status.remaining_budget:.1f} remaining, "
            f"{action_name} costs {cost}). You MUST call {submit_tool} now "
            "with your best answer."
        )
    return None


async def _run_env(action_name: str, action_str: str) -> dict:
    """Shared body for raw exploration tools: gate → execute → bookkeep → annotate."""
    status: SampleStatus = _ctx["status"]
    err = _gate(action_name, status)
    if err is not None:
        return _text(err)
    observation, _ = execute_env_action(action_str, status, _ctx["data_path_base"])
    update_budget(status, action_name)
    return _text(str(observation) + _budget_note(status))


# ---------------------------------------------------------------------------
# Raw-mode tools — direct DB exploration + SQL execution
# ---------------------------------------------------------------------------

@tool("execute_sql", "Execute a SQL query against the database and return results", {"sql": str})
async def execute_sql(args: dict) -> dict:
    return await _run_env("execute_sql", f"execute({args['sql']})")


@tool("get_schema", "Get the database schema (CREATE TABLE statements with sample data)", {})
async def get_schema(args: dict) -> dict:
    return await _run_env("get_schema", "get_schema()")


@tool(
    "get_all_column_meanings",
    "Get the meanings/descriptions of all columns in the database",
    {},
)
async def get_all_column_meanings(args: dict) -> dict:
    return await _run_env("get_all_column_meanings", "get_all_column_meanings()")


@tool(
    "get_column_meaning",
    "Get the meaning of a specific column in a table",
    {"table_name": str, "column_name": str},
)
async def get_column_meaning(args: dict) -> dict:
    action = f"get_column_meaning('{args['table_name']}', '{args['column_name']}')"
    return await _run_env("get_column_meaning", action)


@tool(
    "get_all_external_knowledge_names",
    "List all available external knowledge entry names for this database",
    {},
)
async def get_all_external_knowledge_names(args: dict) -> dict:
    return await _run_env(
        "get_all_external_knowledge_names", "get_all_external_knowledge_names()"
    )


@tool(
    "get_knowledge_definition",
    "Get the definition of a specific external knowledge entry",
    {"knowledge_name": str},
)
async def get_knowledge_definition(args: dict) -> dict:
    action = f"get_knowledge_definition('{args['knowledge_name']}')"
    return await _run_env("get_knowledge_definition", action)


@tool(
    "get_all_knowledge_definitions",
    "Get all external knowledge definitions for this database",
    {},
)
async def get_all_knowledge_definitions(args: dict) -> dict:
    return await _run_env(
        "get_all_knowledge_definitions", "get_all_knowledge_definitions()"
    )


# ---------------------------------------------------------------------------
# Shared tools — user simulator + submission
# ---------------------------------------------------------------------------

async def _ask_user_impl(question: str) -> str:
    """Encoder/decoder user simulator using LiteLLM."""
    status: SampleStatus = _ctx["status"]
    db_name = status.original_data["selected_database"]
    schema = _schema_cache.get(db_name, "")
    model = _ctx.get("user_sim_model", "anthropic/claude-haiku-4-5-20251001")
    prompt_version = _ctx.get("user_sim_prompt_version", "v2")

    import litellm

    encoder_prompt = build_user_encoder_prompt(question, status, schema, prompt_version)
    encoder_resp = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": encoder_prompt}],
    )
    encoder_action = parse_encoder_response(
        encoder_resp.choices[0].message.content or ""
    )

    decoder_prompt = build_user_decoder_prompt(
        question, encoder_action, status, schema, prompt_version
    )
    decoder_resp = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": decoder_prompt}],
    )
    raw_response = decoder_resp.choices[0].message.content or ""

    match = re.search(r"<s>(.*?)</s>", raw_response, re.DOTALL)
    return match.group(1).strip() if match else raw_response.strip()


@tool(
    "ask_user",
    "Ask the user a clarification question about their query",
    {"question": str},
)
async def ask_user(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    err = _gate("ask_user", status)
    if err is not None:
        return _text(err)
    answer = await _ask_user_impl(args["question"])
    update_budget(status, "ask_user")
    _ctx["asks_used"] = _ctx.get("asks_used", 0) + 1

    suffix = _budget_note(status)
    # In c-interact, the budget IS the turn budget; surface remaining ask
    # rounds explicitly (matches ADK callbacks_cinteract.after_tool_callback).
    if _ctx.get("eval_mode") == "c-interact":
        max_asks = _ctx.get("max_asks", 0)
        remaining = max(0, max_asks - _ctx["asks_used"])
        suffix += (
            f"\n[Clarification turns remaining: {remaining}/{max_asks}]"
        )
    return _text(answer + suffix)


@tool(
    "submit_sql",
    "Submit your final SQL query for evaluation. Only submit when confident.",
    {"sql": str},
)
async def submit_sql(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    observation, reward, p1, p2, finished = execute_submit_action(
        args["sql"], status, _ctx["data_path_base"]
    )
    update_budget(status, "submit_sql")
    _ctx["result"] = {
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "observation": observation,
    }
    return _text(str(observation) + _budget_note(status))


# ---------------------------------------------------------------------------
# SLayer-mode tools — agent reaches SLayer through its native MCP server
# (configured in run_task via mcp_servers={"slayer": ...}). The only native
# wrapper we keep is `submit_query`, which uses an in-process SlayerClient
# to translate the agent's SLayer query into deterministic SQL and submit
# it through bird-interact's eval pipeline.
# ---------------------------------------------------------------------------

def _slayer_client():
    """Get or build a SlayerClient for the current task's DB (used by submit_query)."""
    client = _ctx.get("_slayer_client")
    if client is None:
        from slayer.client.slayer_client import SlayerClient
        from slayer.storage.yaml_storage import YAMLStorage

        storage_dir = _ctx["slayer_storage_dir"]
        storage = YAMLStorage(base_dir=storage_dir)
        client = SlayerClient(storage=storage)
        _ctx["_slayer_client"] = client
        _ctx["_slayer_storage"] = storage
    return client


@tool(
    "submit_query",
    (
        "Submit your final SLayer query for evaluation. The query is translated "
        "to SQL and tested against the ground truth."
    ),
    {"query_json": str},
)
async def submit_query(args: dict) -> dict:
    try:
        query_dict = json.loads(args["query_json"])
    except json.JSONDecodeError as e:
        return _text(f"Invalid JSON — submission aborted: {e}")

    client = _slayer_client()
    try:
        sql = client.sql_sync(query_dict)
    except Exception as e:
        return _text(f"Could not generate SQL — submission aborted: {e}")

    status: SampleStatus = _ctx["status"]
    observation, reward, p1, p2, finished = execute_submit_action(
        sql, status, _ctx["data_path_base"]
    )
    update_budget(status, "submit_query")
    _ctx["result"] = {
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "observation": observation,
        "submitted_sql": sql,
    }
    return _text(
        f"Generated SQL:\n{sql}\n\nResult: {observation}{_budget_note(status)}"
    )


# ---------------------------------------------------------------------------
# Tool lists
# ---------------------------------------------------------------------------

RAW_A_TOOLS = [
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

# c-interact: schema and knowledge are injected in the prompt; agent only
# clarifies and submits.
RAW_C_TOOLS = [ask_user, submit_sql]

# In SLayer mode, exploration tools (help, models_summary, inspect_model,
# query, list_datasources) come from the slayer MCP server itself —
# wired into ClaudeAgentOptions.mcp_servers. We also expose the native
# bird-interact knowledge tools so SLayer agents have the same access
# to external domain knowledge that raw agents do.
SLAYER_A_TOOLS = [
    get_all_external_knowledge_names,
    get_knowledge_definition,
    get_all_knowledge_definitions,
    ask_user,
    submit_query,
]
# c-interact slayer: knowledge is injected upfront in the prompt (matches
# raw c-interact's contract), so no separate knowledge tools are needed.
SLAYER_C_TOOLS = [ask_user, submit_query]


def _select_tools(query_mode: str, eval_mode: str) -> list:
    if query_mode == "raw" and eval_mode == "a-interact":
        return RAW_A_TOOLS
    if query_mode == "raw" and eval_mode == "c-interact":
        return RAW_C_TOOLS
    if query_mode == "slayer" and eval_mode == "a-interact":
        return SLAYER_A_TOOLS
    if query_mode == "slayer" and eval_mode == "c-interact":
        return SLAYER_C_TOOLS
    raise ValueError(f"Unknown mode combo: query_mode={query_mode} eval_mode={eval_mode}")


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

async def _build_prompt(
    query_mode: str, eval_mode: str, task_data: dict, budget: float
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
            slayer_storage_dir=_ctx["slayer_storage_dir"],
            db_name=db_name,
            task_data=task_data,
        )

    raise ValueError(f"Unknown mode combo: query_mode={query_mode} eval_mode={eval_mode}")


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class ClaudeSDKAgent:
    """SystemAgent implementation using the Claude Agent SDK.

    The SDK is locked to Anthropic models — passing a non-Anthropic
    `model` causes `run_task` to short-circuit with a skip-shaped row so
    the 3-way comparison still renders cleanly. Use a different
    framework (`pydantic_ai`, `smolagents`, ...) for non-Anthropic models.
    """

    def __init__(
        self,
        slayer_storage_root: str | None = None,
        model: str = "anthropic/claude-sonnet-4-5",
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
        from bird_interact_agents.model_string import is_anthropic

        instance_id = task_data["instance_id"]
        db_name = task_data["selected_database"]
        if not is_anthropic(self.model):
            msg = (
                f"claude_sdk requires an Anthropic model; got {self.model!r}. "
                "Skipped — use --framework pydantic_ai for non-Anthropic models."
            )
            logger.warning("[%s] %s", instance_id, msg)
            return {
                "task_id": instance_id,
                "instance_id": instance_id,
                "database": db_name,
                "phase1_passed": False,
                "phase2_passed": False,
                "total_reward": 0.0,
                "trajectory": [],
                "error": msg,
            }


        status = SampleStatus(
            idx=0,
            original_data=task_data,
            remaining_budget=budget,
            total_budget=budget,
        )
        load_db_data_if_needed(db_name, data_path_base)

        # Per-task SLayer storage path (only relevant for slayer query mode)
        slayer_storage_dir = (
            f"{self.slayer_storage_root}/{db_name}" if self.slayer_storage_root else ""
        )

        # Number of clarification turns the c-interact contract grants to the
        # agent — used for the post-ask_user "turns remaining" notice.
        from bird_interact_agents.harness import _ambiguity_count

        max_asks = _ambiguity_count(task_data) + 3  # +patience(3); matches ADK

        # Set the per-task context dict via contextvars — concurrent task
        # runs each get their own dict instance.
        _ctx_var.set({
            "status": status,
            "data_path_base": data_path_base,
            "user_sim_model": user_sim_model,
            "user_sim_prompt_version": user_sim_prompt_version,
            "slayer_storage_dir": slayer_storage_dir,
            "_slayer_client": None,
            "_slayer_storage": None,
            "result": None,
            "eval_mode": eval_mode,
            "query_mode": query_mode,
            "max_asks": max_asks,
            "asks_used": 0,
        })

        tools = _select_tools(query_mode, eval_mode)
        prompt = await _build_prompt(query_mode, eval_mode, task_data, budget)

        server = create_sdk_mcp_server(
            name="bird-interact-tools", version="1.0.0", tools=tools
        )
        tool_names = [f"mcp__bird-interact-tools__{t.name}" for t in tools]

        mcp_servers: dict = {"bird-interact-tools": server}
        if query_mode == "slayer":
            mcp_servers["slayer"] = slayer_mcp_stdio_config(slayer_storage_dir)
            # Allow the slayer MCP tools the agent will need
            slayer_tools = [
                "help",
                "list_datasources",
                "models_summary",
                "inspect_model",
                "query",
            ]
            tool_names.extend(f"mcp__slayer__{t}" for t in slayer_tools)

        options = ClaudeAgentOptions(
            system_prompt=prompt,
            mcp_servers=mcp_servers,
            allowed_tools=tool_names,
        )

        trajectory: list[dict] = []
        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(task_data["amb_user_query"])
                turns = 0
                async for msg in client.receive_response():
                    trajectory.append(
                        {"type": str(type(msg).__name__), "data": str(msg)[:500]}
                    )
                    # Count assistant model turns; cap at MAX_MODEL_TURNS to
                    # match the original mini_interact_agent (--max_turns=60)
                    # and ADK before_model_callback.
                    if type(msg).__name__ == "AssistantMessage":
                        turns += 1
                        if turns >= MAX_MODEL_TURNS:
                            logger.warning(
                                "Max model turns (%d) reached for %s; stopping.",
                                MAX_MODEL_TURNS, instance_id,
                            )
                            break
        except Exception as e:
            logger.error("Agent error on %s: %s", instance_id, e)
            return {
                "task_id": instance_id,
                "instance_id": instance_id,
                "database": db_name,
                "phase1_passed": False,
                "phase2_passed": False,
                "total_reward": 0.0,
                "trajectory": trajectory,
                "error": str(e),
            }

        result = _ctx.get("result") or {}
        return {
            "task_id": instance_id,
            "instance_id": instance_id,
            "database": db_name,
            "phase1_passed": result.get("phase1_passed", False),
            "phase2_passed": result.get("phase2_passed", False),
            "total_reward": result.get("total_reward", 0.0),
            "trajectory": trajectory,
            "error": None,
        }
