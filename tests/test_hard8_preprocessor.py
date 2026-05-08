"""Tests for the HARD-8 preprocessor.

Covers extraction of deleted KB ids from a task record and the
``build_task_variant_storage`` happy paths + edge cases against a
real ``YAMLStorage`` round-trip.
"""

from pathlib import Path

import pytest

from slayer.core.models import (
    Aggregation,
    AggregationParam,
    Column,
    DatasourceConfig,
    ModelMeasure,
    SlayerModel,
)
from slayer.storage.yaml_storage import YAMLStorage

from bird_interact_agents.hard8_preprocessor import (
    build_task_variant_storage,
    extract_deleted_kb_ids,
)


# ---------------------------------------------------------------------------
# extract_deleted_kb_ids
# ---------------------------------------------------------------------------

def test_extract_deleted_kb_ids_int_form():
    task = {
        "knowledge_ambiguity": [
            {"term": "x", "deleted_knowledge": 7},
            {"term": "y", "deleted_knowledge": 12},
        ],
    }
    assert extract_deleted_kb_ids(task) == {7, 12}


def test_extract_deleted_kb_ids_list_form():
    task = {
        "knowledge_ambiguity": [
            {"term": "x", "deleted_knowledge": [3, 4]},
            {"term": "y", "deleted_knowledge": 9},
        ],
    }
    assert extract_deleted_kb_ids(task) == {3, 4, 9}


def test_extract_deleted_kb_ids_missing_or_empty():
    assert extract_deleted_kb_ids({}) == set()
    assert extract_deleted_kb_ids({"knowledge_ambiguity": []}) == set()
    assert extract_deleted_kb_ids({"knowledge_ambiguity": None}) == set()
    assert extract_deleted_kb_ids({
        "knowledge_ambiguity": [{"term": "x", "deleted_knowledge": None}],
    }) == set()


# ---------------------------------------------------------------------------
# build_task_variant_storage — fixture
# ---------------------------------------------------------------------------

DB_NAME = "tinydb"


async def _seed_canonical(canonical_root: Path) -> None:
    """Write a 3-model canonical YAMLStorage with mixed meta.kb_id coverage.

    - ``alpha``: model-level ``meta.kb_id=1`` → deletion of 1 drops the model.
    - ``beta``: column with ``kb_id=2``, measure with ``kb_id=3``,
      aggregation with ``kb_id=4``, plus an unmarked column.
    - ``gamma``: ``meta.kb_ids=[5,6]`` on the model → deletion of either drops it.
    """
    storage = YAMLStorage(base_dir=str(canonical_root / DB_NAME))
    await storage.save_datasource(
        DatasourceConfig(
            name=DB_NAME,
            type="sqlite",
            connection_string=f"sqlite:///{DB_NAME}.db",
        )
    )
    await storage.save_model(
        SlayerModel(
            name="alpha",
            data_source=DB_NAME,
            sql_table="alpha",
            columns=[Column(name="id", primary_key=True)],
            meta={"kb_id": 1},
        )
    )
    await storage.save_model(
        SlayerModel(
            name="beta",
            data_source=DB_NAME,
            sql_table="beta",
            columns=[
                Column(name="id", primary_key=True),
                Column(name="amount", meta={"kb_id": 2}),
                Column(name="plain"),
            ],
            measures=[
                ModelMeasure(name="total", formula="amount:sum", meta={"kb_id": 3}),
                ModelMeasure(name="rows", formula="*:count"),
            ],
            aggregations=[
                Aggregation(
                    name="weighted_amt",
                    formula="SUM({sql} * {weight}) / NULLIF(SUM({weight}), 0)",
                    params=[AggregationParam(name="weight", sql="amount")],
                    meta={"kb_id": 4},
                ),
            ],
        )
    )
    await storage.save_model(
        SlayerModel(
            name="gamma",
            data_source=DB_NAME,
            sql_table="gamma",
            columns=[Column(name="id", primary_key=True)],
            meta={"kb_ids": [5, 6]},
        )
    )


@pytest.fixture
async def canonical_root(tmp_path: Path) -> Path:
    root = tmp_path / "canonical"
    root.mkdir()
    await _seed_canonical(root)
    return root


# ---------------------------------------------------------------------------
# build_task_variant_storage — behaviors
# ---------------------------------------------------------------------------

async def test_two_tasks_get_isolated_copies(
    canonical_root: Path, tmp_path: Path
):
    """Concurrent tasks on the same DB must not share storage. Each task's
    `work_dir` produces an independent on-disk copy; mutating one (via the
    SLayer storage API) leaves the other untouched."""
    work_a = tmp_path / "task_a"
    work_b = tmp_path / "task_b"
    work_a.mkdir()
    work_b.mkdir()

    out_a = await build_task_variant_storage(
        canonical_storage_root=canonical_root, db_name=DB_NAME,
        deleted_kb_ids=set(), work_dir=work_a,
    )
    out_b = await build_task_variant_storage(
        canonical_storage_root=canonical_root, db_name=DB_NAME,
        deleted_kb_ids=set(), work_dir=work_b,
    )
    assert out_a != out_b
    assert out_a.exists() and out_b.exists()

    # Mutate task A's copy: drop a model. Task B's copy + the canonical
    # reference must be unaffected.
    storage_a = YAMLStorage(base_dir=str(out_a))
    await storage_a.delete_model("alpha")

    a_after = sorted(await storage_a.list_models())
    b_after = sorted(await YAMLStorage(base_dir=str(out_b)).list_models())
    canonical_after = sorted(
        await YAMLStorage(base_dir=str(canonical_root / DB_NAME)).list_models()
    )
    assert "alpha" not in a_after
    assert "alpha" in b_after
    assert "alpha" in canonical_after


async def test_no_deletions_still_materialises_per_task_copy(
    canonical_root: Path, tmp_path: Path
):
    """Even with empty `deleted_kb_ids`, the function must materialise a
    fresh per-task copy under `work_dir`. This isolation lets each task's
    SLayer MCP server safely write back type-refinement metadata without
    mutating the committed `slayer_models/` reference, and confines any
    agent `create_model` / `edit_model` calls to the scratch dir."""
    work = tmp_path / "work"
    work.mkdir()
    out = await build_task_variant_storage(
        canonical_storage_root=canonical_root,
        db_name=DB_NAME,
        deleted_kb_ids=set(),
        work_dir=work,
    )
    # Output points at the per-task copy, not the canonical path.
    assert out == work / DB_NAME
    assert (work / DB_NAME).exists()

    # The copy contains every model from the canonical store.
    src = YAMLStorage(base_dir=str(canonical_root / DB_NAME))
    dst = YAMLStorage(base_dir=str(out))
    canonical_names = sorted(await src.list_models())
    variant_names = sorted(await dst.list_models())
    assert canonical_names == variant_names

    # And the datasource carries through.
    ds = await dst.get_datasource(DB_NAME)
    assert ds is not None and ds.name == DB_NAME


async def test_deletion_drops_model_by_kb_id(canonical_root: Path, tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    out = await build_task_variant_storage(
        canonical_storage_root=canonical_root,
        db_name=DB_NAME,
        deleted_kb_ids={1},
        work_dir=work,
    )
    variant = YAMLStorage(base_dir=str(out))
    names = await variant.list_models()
    assert "alpha" not in names
    assert {"beta", "gamma"} <= set(names)
    # Datasource is preserved.
    ds = await variant.get_datasource(DB_NAME)
    assert ds is not None and ds.name == DB_NAME


async def test_deletion_drops_model_by_kb_ids_list(
    canonical_root: Path, tmp_path: Path
):
    work = tmp_path / "work"
    work.mkdir()
    out = await build_task_variant_storage(
        canonical_storage_root=canonical_root,
        db_name=DB_NAME,
        deleted_kb_ids={6},  # gamma has kb_ids=[5,6] — match on either
        work_dir=work,
    )
    variant = YAMLStorage(base_dir=str(out))
    names = await variant.list_models()
    assert "gamma" not in names
    assert "alpha" in names
    assert "beta" in names


async def test_deletion_drops_column_measure_aggregation(
    canonical_root: Path, tmp_path: Path
):
    work = tmp_path / "work"
    work.mkdir()
    out = await build_task_variant_storage(
        canonical_storage_root=canonical_root,
        db_name=DB_NAME,
        deleted_kb_ids={2, 3, 4},
        work_dir=work,
    )
    variant = YAMLStorage(base_dir=str(out))
    beta = await variant.get_model("beta")
    assert beta is not None
    # The unmarked column + the PK column survive; "amount" was kb_id=2.
    col_names = {c.name for c in beta.columns}
    assert col_names == {"id", "plain"}
    # Only the unmarked measure survives; "total" was kb_id=3.
    assert {m.name for m in beta.measures} == {"rows"}
    # The custom aggregation was kb_id=4.
    assert beta.aggregations == []


async def test_unmarked_model_is_returned_unchanged_object(
    canonical_root: Path, tmp_path: Path
):
    """A model with no meta-matching entities should serialize identically."""
    work = tmp_path / "work"
    work.mkdir()
    out = await build_task_variant_storage(
        canonical_storage_root=canonical_root,
        db_name=DB_NAME,
        deleted_kb_ids={2},  # touches only beta.amount; alpha + gamma untouched
        work_dir=work,
    )
    variant = YAMLStorage(base_dir=str(out))
    src = YAMLStorage(base_dir=str(canonical_root / DB_NAME))
    alpha_v = await variant.get_model("alpha")
    alpha_s = await src.get_model("alpha")
    assert alpha_v is not None and alpha_s is not None
    assert alpha_v.model_dump() == alpha_s.model_dump()
