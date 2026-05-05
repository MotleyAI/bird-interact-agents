"""HARD-8 preprocessor: build per-task SLayer model variants by dropping
entities whose ``meta.kb_id`` (or any element of ``meta.kb_ids``) appears
in the task's ``knowledge_ambiguity[*].deleted_knowledge`` list.

Used by the slayer-mode harness to mask KB-derived entities that the
benchmark intentionally hides from the agent. The canonical per-DB
YAML at ``slayer_models/<db>/`` is never modified — variants are
written to a task-scoped scratch directory and discarded by the runner.

The mini-interact dataset uses a single int per ambiguity entry:
``{"deleted_knowledge": 52, ...}``. We accept either int or list-of-int
to be robust.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from slayer.core.models import SlayerModel
from slayer.storage.yaml_storage import YAMLStorage


def extract_deleted_kb_ids(task_data: dict) -> set[int]:
    """Flatten ``knowledge_ambiguity[*].deleted_knowledge`` into an int set.

    Each ambiguity entry's ``deleted_knowledge`` is normally a single int;
    a list of ints is also accepted. Empty / missing returns an empty set.
    """
    out: set[int] = set()
    for item in task_data.get("knowledge_ambiguity") or []:
        dk = item.get("deleted_knowledge")
        if dk is None:
            continue
        if isinstance(dk, list):
            for x in dk:
                out.add(int(x))
        else:
            out.add(int(dk))
    return out


def _entity_kb_ids(meta: Optional[Dict[str, Any]]) -> set[int]:
    """Return the KB ids referenced by an entity via its ``meta`` dict.

    Accepts either ``meta.kb_id`` (single int) or ``meta.kb_ids`` (list
    of ints), per the translate-mini-interact-kb skill contract.
    """
    if not meta:
        return set()
    ids: set[int] = set()
    if meta.get("kb_id") is not None:
        ids.add(int(meta["kb_id"]))
    kb_ids = meta.get("kb_ids")
    if kb_ids:
        for x in kb_ids:
            ids.add(int(x))
    return ids


def _apply_deletions(model: SlayerModel, deleted: set[int]) -> Optional[SlayerModel]:
    """Return a new ``SlayerModel`` with deletion-matching entities dropped,
    or ``None`` if the model itself should be dropped.
    """
    if _entity_kb_ids(model.meta) & deleted:
        return None
    surviving_columns = [
        c for c in model.columns if not (_entity_kb_ids(c.meta) & deleted)
    ]
    surviving_measures = [
        m for m in model.measures if not (_entity_kb_ids(m.meta) & deleted)
    ]
    surviving_aggregations = [
        a for a in model.aggregations if not (_entity_kb_ids(a.meta) & deleted)
    ]
    if (
        len(surviving_columns) == len(model.columns)
        and len(surviving_measures) == len(model.measures)
        and len(surviving_aggregations) == len(model.aggregations)
    ):
        return model
    # model_copy keeps untouched fields (joins, filters, source_queries, etc.)
    return model.model_copy(
        update={
            "columns": surviving_columns,
            "measures": surviving_measures,
            "aggregations": surviving_aggregations,
        }
    )


async def build_task_variant_storage(
    *,
    canonical_storage_root: Path,
    db_name: str,
    deleted_kb_ids: set[int],
    work_dir: Path,
) -> Path:
    """Build a per-task SLayer YAMLStorage with HARD-8 deletions applied.

    Parameters
    ----------
    canonical_storage_root
        The ``slayer_models/`` root containing per-DB folders.
    db_name
        The DB name (folder name under ``canonical_storage_root``).
    deleted_kb_ids
        KB ids to mask. Empty set short-circuits and returns the
        canonical ``<root>/<db_name>`` path with no copy.
    work_dir
        Task-scoped scratch directory. The variant is written to
        ``<work_dir>/<db_name>/``.

    Returns
    -------
    Path
        The base_dir to hand to ``YAMLStorage`` / ``SLAYER_STORAGE`` for
        this task.
    """
    canonical = canonical_storage_root / db_name
    if not deleted_kb_ids:
        return canonical
    src = YAMLStorage(base_dir=str(canonical))
    variant_root = work_dir / db_name
    variant_root.mkdir(parents=True, exist_ok=True)
    dst = YAMLStorage(base_dir=str(variant_root))

    ds = await src.get_datasource(db_name)
    if ds is not None:
        await dst.save_datasource(ds)

    for name in await src.list_models():
        model = await src.get_model(name)
        if model is None:
            continue
        kept = _apply_deletions(model, deleted_kb_ids)
        if kept is not None:
            await dst.save_model(kept)
    return variant_root
