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


# ---------------------------------------------------------------------------
# Raw-mode tools — direct DB exploration + SQL execution
# ---------------------------------------------------------------------------

@tool("execute_sql", "Execute a SQL query against the database and return results", {"sql": str})
async def execute_sql(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    observation, _ = execute_env_action(
        f"execute({args['sql']})", status, _ctx["data_path_base"]
    )
    return _text(observation)


@tool("get_schema", "Get the database schema (CREATE TABLE statements with sample data)", {})
async def get_schema(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    observation, _ = execute_env_action("get_schema()", status, _ctx["data_path_base"])
    return _text(observation)


@tool(
    "get_all_column_meanings",
    "Get the meanings/descriptions of all columns in the database",
    {},
)
async def get_all_column_meanings(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    observation, _ = execute_env_action(
        "get_all_column_meanings()", status, _ctx["data_path_base"]
    )
    return _text(observation)


@tool(
    "get_column_meaning",
    "Get the meaning of a specific column in a table",
    {"table_name": str, "column_name": str},
)
async def get_column_meaning(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    action = f"get_column_meaning('{args['table_name']}', '{args['column_name']}')"
    observation, _ = execute_env_action(action, status, _ctx["data_path_base"])
    return _text(observation)


@tool(
    "get_all_external_knowledge_names",
    "List all available external knowledge entry names for this database",
    {},
)
async def get_all_external_knowledge_names(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    observation, _ = execute_env_action(
        "get_all_external_knowledge_names()", status, _ctx["data_path_base"]
    )
    return _text(observation)


@tool(
    "get_knowledge_definition",
    "Get the definition of a specific external knowledge entry",
    {"knowledge_name": str},
)
async def get_knowledge_definition(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    action = f"get_knowledge_definition('{args['knowledge_name']}')"
    observation, _ = execute_env_action(action, status, _ctx["data_path_base"])
    return _text(observation)


@tool(
    "get_all_knowledge_definitions",
    "Get all external knowledge definitions for this database",
    {},
)
async def get_all_knowledge_definitions(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    observation, _ = execute_env_action(
        "get_all_knowledge_definitions()", status, _ctx["data_path_base"]
    )
    return _text(observation)


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
    answer = await _ask_user_impl(args["question"])
    return _text(answer)


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
    _ctx["result"] = {
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "observation": observation,
    }
    return _text(observation)


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
    _ctx["result"] = {
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "observation": observation,
        "submitted_sql": sql,
    }
    return _text(f"Generated SQL:\n{sql}\n\nResult: {observation}")


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
# wired into ClaudeAgentOptions.mcp_servers. We only register the native
# bird-interact tools here.
SLAYER_A_TOOLS = [ask_user, submit_query]
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
        # Inject schema + knowledge directly
        schema = _schema_cache.get(db_name, "")
        knowledge = _filter_knowledge_for_agent(db_name, task_data)
        knowledge_text = "\n".join(
            f"- {k}: {v.get('description', '') or v.get('definition', '')}"
            for k, v in (knowledge or {}).items()
        )
        return RAW_C_INTERACT.format(
            budget=budget,
            db_name=db_name,
            user_query=user_query,
            schema=schema,
            knowledge=knowledge_text or "(no external knowledge available)",
        )

    if query_mode == "slayer" and eval_mode == "a-interact":
        return SLAYER_A_INTERACT.format(budget=budget, user_query=user_query)

    if query_mode == "slayer" and eval_mode == "c-interact":
        # Inject SLayer help text + models summary up front
        from slayer.help import render_help
        from slayer.storage.yaml_storage import YAMLStorage

        storage = YAMLStorage(base_dir=_ctx["slayer_storage_dir"])
        names = await storage.list_models()
        lines = []
        for name in names:
            m = await storage.get_model(name)
            dims = ", ".join(d.name for d in (m.dimensions or [])[:8]) if m else ""
            meas = ", ".join(x.name for x in (m.measures or [])[:8]) if m else ""
            lines.append(f"- {name}: dims=[{dims}] measures=[{meas}]")
        return SLAYER_C_INTERACT.format(
            budget=budget,
            user_query=user_query,
            slayer_help=render_help(),
            models_summary="\n".join(lines),
        )

    raise ValueError(f"Unknown mode combo: query_mode={query_mode} eval_mode={eval_mode}")


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class ClaudeSDKAgent:
    """SystemAgent implementation using the Claude Agent SDK."""

    def __init__(self, slayer_storage_root: str | None = None) -> None:
        self.slayer_storage_root = slayer_storage_root

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
                async for msg in client.receive_response():
                    trajectory.append(
                        {"type": str(type(msg).__name__), "data": str(msg)[:500]}
                    )
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
