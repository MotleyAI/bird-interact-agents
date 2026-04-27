"""Verify the Claude SDK tool functions work in isolation (no LLM)."""

import pytest

from bird_interact_agents.config import settings


@pytest.mark.asyncio
async def test_get_schema_tool():
    """The get_schema tool returns schema text."""
    from bird_interact_agents.agents.claude_sdk import agent as agent_mod
    from bird_interact_agents.harness import load_db_data_if_needed, SampleStatus

    task_data = {
        "selected_database": "alien",
        "knowledge_ambiguity": [],
        "instance_id": "alien_1",
    }
    load_db_data_if_needed("alien", settings.db_path)
    agent_mod._ctx_var.set({
        "status": SampleStatus(idx=0, original_data=task_data),
        "data_path_base": settings.db_path,
        "slayer_storage_dir": "",
        "_slayer_client": None,
        "_slayer_storage": None,
        "result": None,
    })

    result = await agent_mod.get_schema.handler({})
    assert "content" in result
    assert "CREATE TABLE" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_execute_sql_tool():
    """The execute_sql tool runs a query and returns results."""
    from bird_interact_agents.agents.claude_sdk import agent as agent_mod
    from bird_interact_agents.harness import load_db_data_if_needed, SampleStatus

    task_data = {
        "selected_database": "alien",
        "knowledge_ambiguity": [],
        "instance_id": "alien_1",
    }
    load_db_data_if_needed("alien", settings.db_path)
    agent_mod._ctx_var.set({
        "status": SampleStatus(idx=0, original_data=task_data),
        "data_path_base": settings.db_path,
        "slayer_storage_dir": "",
        "_slayer_client": None,
        "_slayer_storage": None,
        "result": None,
    })

    result = await agent_mod.execute_sql.handler({"sql": "SELECT 1"})
    assert "content" in result
    assert "1" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_submit_correct_sql_tool():
    """Submitting ground-truth SQL via the tool marks phase1 passed."""
    from bird_interact_agents.agents.claude_sdk import agent as agent_mod
    from bird_interact_agents.harness import (
        load_db_data_if_needed,
        load_tasks,
        SampleStatus,
    )

    tasks = load_tasks(settings.data_path, limit=1)
    task = tasks[0]
    db_name = task["selected_database"]
    load_db_data_if_needed(db_name, settings.db_path)
    agent_mod._ctx_var.set({
        "status": SampleStatus(idx=0, original_data=task),
        "data_path_base": settings.db_path,
        "slayer_storage_dir": "",
        "_slayer_client": None,
        "_slayer_storage": None,
        "result": None,
    })

    sol_sql = task["sol_sql"][0] if isinstance(task["sol_sql"], list) else task["sol_sql"]
    await agent_mod.submit_sql.handler({"sql": sol_sql})

    result = agent_mod._ctx_var.get().get("result")
    assert result is not None
    assert result["phase1_passed"] is True
