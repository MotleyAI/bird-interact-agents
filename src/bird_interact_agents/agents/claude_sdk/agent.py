"""Claude Agent SDK implementation for BIRD-Interact."""

import logging
import re

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
    tool,
)

from bird_interact_agents.agents.claude_sdk.prompts import RAW_A_INTERACT, SLAYER_A_INTERACT
from bird_interact_agents.harness import (
    SampleStatus,
    _schema_cache,
    build_user_decoder_prompt,
    build_user_encoder_prompt,
    execute_env_action,
    execute_submit_action,
    load_db_data_if_needed,
    parse_encoder_response,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level task context — set by the agent before each task run.
# Tools read from this to know which DB, task, etc. they're operating on.
# ---------------------------------------------------------------------------
_ctx: dict = {}


def _text(msg: str) -> dict:
    """Helper to build a tool return value."""
    return {"content": [{"type": "text", "text": msg}]}


# ---------------------------------------------------------------------------
# Raw-mode tools
# ---------------------------------------------------------------------------

@tool("execute_sql", "Execute a SQL query against the database and return results", {"sql": str})
async def execute_sql(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    action = f"execute({args['sql']})"
    observation, success = execute_env_action(action, status, _ctx["data_path_base"])
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


@tool(
    "ask_user",
    "Ask the user a clarification question about their query",
    {"question": str},
)
async def ask_user(args: dict) -> dict:
    status: SampleStatus = _ctx["status"]
    db_name = status.original_data["selected_database"]
    schema = _schema_cache.get(db_name, "")
    model = _ctx.get("user_sim_model", "anthropic/claude-haiku-4-5-20251001")
    prompt_version = _ctx.get("user_sim_prompt_version", "v2")

    # Build encoder prompt and call LLM
    encoder_prompt = build_user_encoder_prompt(
        args["question"], status, schema, prompt_version
    )
    import litellm

    encoder_resp = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": encoder_prompt}],
    )
    encoder_action = parse_encoder_response(
        encoder_resp.choices[0].message.content or ""
    )

    # Build decoder prompt and call LLM
    decoder_prompt = build_user_decoder_prompt(
        args["question"], encoder_action, status, schema, prompt_version
    )
    decoder_resp = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": decoder_prompt}],
    )
    raw_response = decoder_resp.choices[0].message.content or ""

    # Extract between <s>...</s> tags
    match = re.search(r"<s>(.*?)</s>", raw_response, re.DOTALL)
    answer = match.group(1).strip() if match else raw_response.strip()

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
    # Store result for the runner to collect
    _ctx["result"] = {
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "finished": finished,
        "observation": observation,
    }
    return _text(observation if isinstance(observation, str) else str(observation))


# ---------------------------------------------------------------------------
# Tool lists
# ---------------------------------------------------------------------------

RAW_TOOLS = [
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

# SLayer tools will be added in a later phase
SLAYER_TOOLS: list = []


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class ClaudeSDKAgent:
    """SystemAgent implementation using the Claude Agent SDK."""

    async def run_task(
        self,
        task_data: dict,
        data_path_base: str,
        budget: float,
        query_mode: str,
        user_sim_model: str = "anthropic/claude-haiku-4-5-20251001",
        user_sim_prompt_version: str = "v2",
    ) -> dict:
        global _ctx

        db_name = task_data["selected_database"]
        user_query = task_data["amb_user_query"]
        instance_id = task_data["instance_id"]

        # Set up harness state
        status = SampleStatus(
            idx=0,
            original_data=task_data,
            remaining_budget=budget,
            total_budget=budget,
        )
        load_db_data_if_needed(db_name, data_path_base)

        # Set module-level context for tools
        _ctx = {
            "status": status,
            "data_path_base": data_path_base,
            "user_sim_model": user_sim_model,
            "user_sim_prompt_version": user_sim_prompt_version,
            "result": None,
        }

        # Select tools and prompt
        if query_mode == "raw":
            tools = RAW_TOOLS
            prompt = RAW_A_INTERACT.format(
                budget=budget, db_name=db_name, user_query=user_query
            )
        else:
            if not SLAYER_TOOLS:
                raise NotImplementedError("SLayer mode tools not yet implemented")
            tools = SLAYER_TOOLS
            prompt = SLAYER_A_INTERACT.format(budget=budget, user_query=user_query)

        # Create in-process MCP server with tools
        server = create_sdk_mcp_server(
            name="bird-interact-tools", version="1.0.0", tools=tools
        )

        tool_names = [f"mcp__bird-interact-tools__{t.name}" for t in tools]

        options = ClaudeAgentOptions(
            system_prompt=prompt,
            mcp_servers={"bird-interact-tools": server},
            allowed_tools=tool_names,
        )

        # Run the agent
        trajectory: list[dict] = []
        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(user_query)
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
