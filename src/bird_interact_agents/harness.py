"""Thin adapter that imports BIRD-Interact's existing harness components.

The BIRD-Interact repo must be cloned locally and its path set via the
BIRD_BIRD_INTERACT_ROOT environment variable (or in .env).
"""

import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from bird_interact_agents.config import settings
from bird_interact_agents.hard8_preprocessor import (
    build_task_variant_storage,
    extract_deleted_kb_ids,
)


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

# Maximum number of assistant turns per task. Consumed by every adapter to
# cap runaway loops independent of the bird-coin budget.
MAX_MODEL_TURNS = 60

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


def _ambiguity_count(task_data: dict) -> int:
    n = 0
    user_query_ambiguity = task_data.get("user_query_ambiguity", {})
    if "critical_ambiguity" in user_query_ambiguity:
        n += len(user_query_ambiguity["critical_ambiguity"])
    if "knowledge_ambiguity" in task_data:
        n += len(task_data["knowledge_ambiguity"])
    return n


def calculate_budget(
    task_data: dict, patience: int = 3, mode: str = "a-interact"
) -> float:
    """Calculate bird-coin budget for a task.

    a-interact: ENV_INTERACT(3) + SUBMIT(3) + 2*amb + 2*patience.
        Default patience=3 reproduces the original mini_interact_agent
        result with user_patience_budget=6 (= 12 + 2*amb).
    c-interact: ask_cost*(amb + patience) + submit_cost.
        Reproduces ADK's discrete turn budget (n_amb+patience clarification
        turns + 1 submit) using the existing coin plumbing.
    """
    amb = _ambiguity_count(task_data)
    if mode == "a-interact":
        return 6 + 2 * amb + 2 * patience
    if mode == "c-interact":
        return ACTION_COSTS["ask_user"] * (amb + patience) + ACTION_COSTS["submit_sql"]
    raise ValueError(f"Unsupported budget mode: {mode}")


def update_budget(status: "SampleStatus", action_name: str) -> tuple[float, bool]:
    """Decrement remaining_budget by the cost of action_name.

    Mirrors the bookkeeping in the original mini_interact_agent's
    `update_budget` (see batch_run_bird_interact/main.py): subtract the cost,
    set force_submit when at-or-below cost. Returns the new remaining budget
    and the force_submit flag.
    """
    cost = ACTION_COSTS.get(action_name, 0)
    status.remaining_budget = max(0.0, status.remaining_budget - cost)
    if status.remaining_budget <= ACTION_COSTS["submit_sql"]:
        status.force_submit = True
    return status.remaining_budget, status.force_submit


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


def finalize_result_row(
    row: dict,
    *,
    deleted_kb_ids: list[int],
    slayer_storage_dir: str,
) -> dict:
    """Stamp HARD-8 bookkeeping onto an adapter's result row.

    ``variant_storage_path`` is set only when the row's task actually
    used a deletion variant (i.e. ``deleted_kb_ids`` is non-empty);
    otherwise it stays ``None`` so canonical-storage rows can be told
    apart from variant rows in the results JSON.
    """
    row["deleted_kb_ids"] = deleted_kb_ids
    row["variant_storage_path"] = slayer_storage_dir if deleted_kb_ids else None
    return row


def _task_variant_workdir(instance_id: str) -> Path:
    """Per-task scratch dir for HARD-8 variant storage.

    Lives under ``$TMPDIR/bird_interact_w5_variants/<instance_id>/``.
    Reused (overwritten) across runs of the same task — content is
    rewritten from scratch each time so stale deletions don't leak.
    """
    p = Path(tempfile.gettempdir()) / "bird_interact_w5_variants" / instance_id
    p.mkdir(parents=True, exist_ok=True)
    return p


async def resolve_task_storage_dir(
    *,
    slayer_storage_root: Optional[str],
    db_name: str,
    task_data: dict,
    query_mode: str,
) -> Tuple[str, list[int]]:
    """Resolve the per-task SLayer storage path, applying HARD-8 deletions.

    Returns ``(slayer_storage_dir, deleted_kb_ids)``.

    - In raw mode or when ``slayer_storage_root`` is unset: returns
      ``("", [])``. (The downstream slayer MCP launch is gated on
      ``query_mode == "slayer"`` in each adapter, so the empty string
      never reaches ``slayer_mcp_stdio_config``.)
    - In slayer mode without HARD-8 deletions: returns
      ``("<root>/<db_name>", [])`` — the canonical per-DB YAML.
    - In slayer mode with deletions: builds a task-scoped variant
      under ``$TMPDIR/bird_interact_w5_variants/<instance_id>/`` with
      matching entities dropped, and returns its path + the sorted
      deletion list.
    """
    if query_mode != "slayer" or not slayer_storage_root:
        return "", []
    deleted = sorted(extract_deleted_kb_ids(task_data))
    if not deleted:
        return f"{slayer_storage_root}/{db_name}", []
    instance_id = task_data["instance_id"]
    variant_dir = await build_task_variant_storage(
        canonical_storage_root=Path(slayer_storage_root),
        db_name=db_name,
        deleted_kb_ids=set(deleted),
        work_dir=_task_variant_workdir(instance_id),
    )
    return str(variant_dir), deleted


def slayer_mcp_stdio_config(storage_dir: str) -> dict:
    """Return a stdio MCP server config for the per-task slayer storage.

    Frameworks adapt this dict to their own MCP-server config type.

    Keys:
        command: absolute path to the slayer binary
        args:    [`mcp`]
        env:     full env dict with SLAYER_STORAGE pointing at the per-DB store

    Raises:
        ValueError: if storage_dir is empty/None. We refuse to silently fall
            back to CWD because Path("").resolve() does — that would point
            SLayer at whatever directory the run happens to start in.
    """
    if not storage_dir:
        raise ValueError(
            "slayer_mcp_stdio_config requires a non-empty storage_dir; "
            "set --slayer-storage-root (or pass slayer_storage_root explicitly) "
            "when running slayer mode."
        )
    env = _os.environ.copy()
    env["SLAYER_STORAGE"] = str(_Path(storage_dir).resolve())
    return {
        "command": _resolve_slayer_command(),
        "args": ["mcp"],
        "env": env,
    }
