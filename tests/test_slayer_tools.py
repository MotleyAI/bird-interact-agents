"""Verify the SLayer-mode native tools (only `submit_query` remains; the
discovery tools come from the actual `slayer mcp` server, not us)."""

import json

import pytest

from bird_interact_agents.config import settings


@pytest.mark.asyncio
async def test_submit_query_tool_with_valid_slayer_query():
    """`submit_query` translates a SLayer query JSON to SQL and submits it."""
    from bird_interact_agents.agents.claude_sdk import agent as agent_mod
    from bird_interact_agents.harness import (
        SampleStatus,
        load_db_data_if_needed,
        load_tasks,
    )

    tasks = load_tasks(settings.data_path, limit=1)
    task = tasks[0]
    db_name = task["selected_database"]
    load_db_data_if_needed(db_name, settings.db_path)

    agent_mod._ctx_var.set({
        "status": SampleStatus(idx=0, original_data=task),
        "data_path_base": settings.db_path,
        "slayer_storage_dir": f"./slayer_storage/{db_name}",
        "_slayer_client": None,
        "_slayer_storage": None,
        "result": None,
    })

    # Trivial valid SLayer query — exercises sql_sync + execute_submit_action.
    # Likely won't match the gold answer but should not error during translate.
    query = json.dumps({
        "source_model": "observatories",
        "dimensions": ["observstation"],
        "limit": 1,
    })
    result = await agent_mod.submit_query.handler({"query_json": query})
    text = result["content"][0]["text"]
    assert "Generated SQL:" in text
    assert "SELECT" in text


@pytest.mark.asyncio
async def test_submit_query_tool_with_invalid_json():
    """`submit_query` rejects invalid JSON cleanly."""
    from bird_interact_agents.agents.claude_sdk import agent as agent_mod
    from bird_interact_agents.harness import (
        SampleStatus,
        load_db_data_if_needed,
    )

    task_data = {
        "selected_database": "alien",
        "knowledge_ambiguity": [],
        "instance_id": "alien_1",
    }
    load_db_data_if_needed("alien", settings.db_path)

    agent_mod._ctx_var.set({
        "status": SampleStatus(idx=0, original_data=task_data),
        "data_path_base": settings.db_path,
        "slayer_storage_dir": "./slayer_storage/alien",
        "_slayer_client": None,
        "_slayer_storage": None,
        "result": None,
    })

    result = await agent_mod.submit_query.handler({"query_json": "not json"})
    text = result["content"][0]["text"]
    assert "Invalid JSON" in text or "submission aborted" in text


def test_slayer_a_tools_include_knowledge_for_parity():
    """SLAYER_A_TOOLS exposes the bird-interact knowledge tools so SLayer
    agents have the same access to external domain knowledge that raw
    agents do (slayer MCP handles SLayer schema discovery)."""
    from bird_interact_agents.agents.claude_sdk import agent as agent_mod

    names = {t.name for t in agent_mod.SLAYER_A_TOOLS}
    assert names == {
        "ask_user",
        "submit_query",
        "get_all_external_knowledge_names",
        "get_knowledge_definition",
        "get_all_knowledge_definitions",
    }


def test_slayer_c_tools_only_native():
    """SLAYER_C_TOOLS stays minimal — knowledge is injected upfront in the
    c-interact prompt, no fetch tool needed."""
    from bird_interact_agents.agents.claude_sdk import agent as agent_mod

    names = {t.name for t in agent_mod.SLAYER_C_TOOLS}
    assert names == {"ask_user", "submit_query"}
