"""Verify SLayer mode tools work in isolation (no LLM)."""

import pytest

from bird_interact_agents.config import settings


@pytest.mark.asyncio
async def test_models_summary_tool():
    """The models_summary tool lists ingested SLayer models."""
    from bird_interact_agents.agents.claude_sdk import agent as agent_mod
    from bird_interact_agents.harness import load_db_data_if_needed, SampleStatus

    task_data = {
        "selected_database": "alien",
        "knowledge_ambiguity": [],
        "instance_id": "alien_1",
    }
    load_db_data_if_needed("alien", settings.db_path)
    agent_mod._ctx = {
        "status": SampleStatus(idx=0, original_data=task_data),
        "data_path_base": settings.db_path,
        "slayer_storage_dir": "./slayer_storage/alien",
        "_slayer_client": None,
        "_slayer_storage": None,
        "result": None,
    }

    result = await agent_mod.models_summary.handler({})
    text = result["content"][0]["text"]
    assert "observatories" in text
    assert "signals" in text


@pytest.mark.asyncio
async def test_inspect_model_tool():
    """The inspect_model tool returns dimensions and measures."""
    from bird_interact_agents.agents.claude_sdk import agent as agent_mod
    from bird_interact_agents.harness import load_db_data_if_needed, SampleStatus

    task_data = {
        "selected_database": "alien",
        "knowledge_ambiguity": [],
        "instance_id": "alien_1",
    }
    load_db_data_if_needed("alien", settings.db_path)
    agent_mod._ctx = {
        "status": SampleStatus(idx=0, original_data=task_data),
        "data_path_base": settings.db_path,
        "slayer_storage_dir": "./slayer_storage/alien",
        "_slayer_client": None,
        "_slayer_storage": None,
        "result": None,
    }

    result = await agent_mod.inspect_model.handler({"model_name": "observatories"})
    text = result["content"][0]["text"]
    assert "observstation" in text
    assert "dimensions" in text


@pytest.mark.asyncio
async def test_slayer_query_tool():
    """The slayer_query tool runs a query and returns rows + SQL."""
    import json

    from bird_interact_agents.agents.claude_sdk import agent as agent_mod
    from bird_interact_agents.harness import load_db_data_if_needed, SampleStatus

    task_data = {
        "selected_database": "alien",
        "knowledge_ambiguity": [],
        "instance_id": "alien_1",
    }
    load_db_data_if_needed("alien", settings.db_path)
    agent_mod._ctx = {
        "status": SampleStatus(idx=0, original_data=task_data),
        "data_path_base": settings.db_path,
        "slayer_storage_dir": "./slayer_storage/alien",
        "_slayer_client": None,
        "_slayer_storage": None,
        "result": None,
    }

    query = json.dumps(
        {
            "source_model": "observatories",
            "dimensions": ["observstation"],
            "limit": 3,
        }
    )
    result = await agent_mod.slayer_query.handler({"query_json": query})
    text = result["content"][0]["text"]
    payload = json.loads(text)
    assert "sql" in payload
    assert "SELECT" in payload["sql"]
    assert payload["row_count"] >= 1
