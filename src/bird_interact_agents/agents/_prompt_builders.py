"""Shared prompt builders for c-interact mode across all framework adapters.

The c-interact contract is: schema/knowledge/models are injected up-front,
agent only clarifies and submits. All five adapters (claude_sdk, pydantic_ai,
agno, mcp_agent, smolagents) must produce byte-identical prompts so that
cross-framework eval scores compare like-for-like.

Knowledge is serialized as JSON to mirror the upstream BIRD-Interact-ADK
reference (db_environment/server.py:368-385 — `json.dumps(visible, indent=2)`).
"""

import json

from slayer.help import render_help
from slayer.storage.yaml_storage import YAMLStorage

from bird_interact_agents.agents.claude_sdk.prompts import (
    RAW_C_INTERACT,
    SLAYER_C_INTERACT,
)
from bird_interact_agents.harness import (
    _filter_knowledge_for_agent,
    _schema_cache,
)


def _format_knowledge(db_name: str, task_data: dict) -> str:
    knowledge = _filter_knowledge_for_agent(db_name, task_data) or {}
    if not knowledge:
        return "(no external knowledge available)"
    return json.dumps(list(knowledge.values()), indent=2)


async def build_raw_c_interact_prompt(
    *,
    budget: float,
    db_name: str,
    user_query: str,
    task_data: dict,
) -> str:
    schema = _schema_cache.get(db_name, "")
    return RAW_C_INTERACT.format(
        budget=budget,
        db_name=db_name,
        user_query=user_query,
        schema=schema,
        knowledge=_format_knowledge(db_name, task_data),
    )


async def build_slayer_c_interact_prompt(
    *,
    budget: float,
    user_query: str,
    slayer_storage_dir: str,
    db_name: str,
    task_data: dict,
) -> str:
    storage = YAMLStorage(base_dir=slayer_storage_dir)
    names = await storage.list_models()
    lines = []
    for name in names:
        m = await storage.get_model(name)
        if m is None:
            continue
        dims = ", ".join(d.name for d in (m.dimensions or []))
        meas = ", ".join(x.name for x in (m.measures or []))
        lines.append(f"- {name}: dims=[{dims}] measures=[{meas}]")
    return SLAYER_C_INTERACT.format(
        budget=budget,
        user_query=user_query,
        slayer_help=render_help(),
        models_summary="\n".join(lines),
        knowledge=_format_knowledge(db_name, task_data),
    )
