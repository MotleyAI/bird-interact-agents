"""Thin adapter that imports BIRD-Interact's existing harness components.

The BIRD-Interact repo must be cloned locally and its path set via the
BIRD_BIRD_INTERACT_ROOT environment variable (or in .env).
"""

import sys
from pathlib import Path

from bird_interact_agents.config import settings


def _ensure_bird_interact_on_path() -> None:
    """Add the BIRD-Interact mini_interact_agent directory to sys.path."""
    root = Path(settings.bird_interact_root)
    if not root.is_dir():
        raise RuntimeError(
            f"BIRD-Interact root not found: {root}. "
            "Set the BIRD_BIRD_INTERACT_ROOT environment variable."
        )
    agent_root = settings.mini_interact_agent_root
    if not agent_root.is_dir():
        raise RuntimeError(
            f"mini_interact_agent directory not found: {agent_root}"
        )
    path_str = str(agent_root)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


_ensure_bird_interact_on_path()

# ---------------------------------------------------------------------------
# Re-export harness components
# ---------------------------------------------------------------------------

# Action execution (SQLite DB operations + submission evaluation)
from batch_run_bird_interact.action_handler_sqlite import (  # noqa: E402
    execute_env_action,
    execute_submit_action,
    load_db_data_if_needed,
    close_db_connection,
    get_db_connection,
    reset_and_reconnect_db,
    _schema_cache,
    _column_meanings_cache,
    _external_knowledge_cache,
    _filter_knowledge_for_agent,
)

# User simulator prompt building
from batch_run_bird_interact.prompt_utils import (  # noqa: E402
    build_user_encoder_prompt,
    build_user_decoder_prompt,
    parse_encoder_response,
)

# Sample status dataclass
from batch_run_bird_interact.sample_status import SampleStatus  # noqa: E402

# Budget calculation helpers
ACTION_COSTS = {
    "execute_sql": 1,
    "get_schema": 1,
    "get_all_column_meanings": 1,
    "get_column_meaning": 0.5,
    "get_all_external_knowledge_names": 0.5,
    "get_knowledge_definition": 0.5,
    "get_all_knowledge_definitions": 1,
    "ask_user": 2,
    "submit_sql": 3,
    "submit_query": 3,
    # SLayer tools
    "help": 0.5,
    "list_datasources": 0.5,
    "models_summary": 1,
    "inspect_model": 0.5,
    "query": 1,
}


def calculate_budget(task_data: dict, patience: int = 3) -> float:
    """Calculate bird-coin budget for a task.

    Formula: 6 + 2 * num_ambiguities + 2 * patience
    (matches BIRD-Interact ADK and non-ADK implementations).
    """
    amb_count = 0
    user_query_ambiguity = task_data.get("user_query_ambiguity", {})
    if "critical_ambiguity" in user_query_ambiguity:
        amb_count += len(user_query_ambiguity["critical_ambiguity"])
    if "knowledge_ambiguity" in task_data:
        amb_count += len(task_data["knowledge_ambiguity"])

    return 6 + 2 * amb_count + 2 * patience


def load_tasks(jsonl_path: str, limit: int | None = None) -> list[dict]:
    """Load tasks from a JSONL file."""
    import json

    tasks = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    if limit is not None:
        tasks = tasks[:limit]
    return tasks


# ---------------------------------------------------------------------------
# SLayer MCP server (stdio) — used by all framework agents in slayer mode.
# Each task spawns a per-DB instance pointing at the right model storage.
# ---------------------------------------------------------------------------

import os as _os
import shutil as _shutil
from pathlib import Path as _Path


def _resolve_slayer_command() -> str:
    """Locate the slayer CLI binary.

    Prefers `.venv/bin/slayer` next to our package (so the spawned subprocess
    uses the same Python environment), falls back to `slayer` on PATH.
    """
    # The .venv lives at the repo root; src/bird_interact_agents/harness.py
    # is two levels deep below repo root.
    repo_root = _Path(__file__).resolve().parent.parent.parent
    venv_slayer = repo_root / ".venv" / "bin" / "slayer"
    if venv_slayer.is_file() and _os.access(venv_slayer, _os.X_OK):
        return str(venv_slayer)
    on_path = _shutil.which("slayer")
    if on_path:
        return on_path
    raise RuntimeError(
        "slayer CLI not found. Install with `uv pip install motley-slayer` "
        "or `uv pip install -e ../slayer` and try again."
    )


def slayer_mcp_stdio_config(storage_dir: str) -> dict:
    """Return a stdio MCP server config for the per-task slayer storage.

    Frameworks adapt this dict to their own MCP-server config type.

    Keys:
        command: absolute path to the slayer binary
        args:    [`mcp`]
        env:     full env dict with SLAYER_STORAGE pointing at the per-DB store
    """
    env = _os.environ.copy()
    env["SLAYER_STORAGE"] = str(_Path(storage_dir).resolve())
    return {
        "command": _resolve_slayer_command(),
        "args": ["mcp"],
        "env": env,
    }
