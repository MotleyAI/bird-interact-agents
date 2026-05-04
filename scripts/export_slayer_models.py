#!/usr/bin/env python3
"""Export SLayer models for one mini-interact DB from the live SLayer
storage to ``bird-interact-agents/slayer_models/<db>/``.

Reads from the SLayer storage path the MCP server uses (default:
``~/.local/share/slayer``) and writes a YAMLStorage-shaped tree at
``bird-interact-agents/slayer_models/<db>/`` containing only the models
+ datasource for the named DB. The output tree is exactly what
``YAMLStorage(base_dir=…)`` expects, so the verifier (and any future
runner that loads the per-DB YAML) can pick it up directly.

Usage:
    python scripts/export_slayer_models.py --db <db>
    python scripts/export_slayer_models.py --db <db> --source <slayer_storage_path>

Idempotent: re-runs overwrite the destination directory.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

from slayer.storage.sqlite_storage import SQLiteStorage
from slayer.storage.yaml_storage import YAMLStorage

REPO_ROOT = Path(__file__).resolve().parent.parent
DEST_ROOT = REPO_ROOT / "slayer_models"
DEFAULT_SLAYER_STORAGE = Path(os.environ.get(
    "SLAYER_STORAGE",
    str(Path.home() / ".local" / "share" / "slayer"),
))


def _open_source(path: Path):
    """Open the right storage backend for *path*.

    YAMLStorage wraps a directory; SQLiteStorage wraps a .db / .sqlite
    file. Mirrors the precedence in ``slayer.cli._resolve_storage``.
    """
    if path.is_file() and path.suffix in (".db", ".sqlite"):
        return SQLiteStorage(db_path=str(path))
    return YAMLStorage(base_dir=str(path))


async def _export_async(db: str, source_path: Path) -> int:
    src = _open_source(source_path)
    dest_dir = DEST_ROOT / db

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = YAMLStorage(base_dir=str(dest_dir))

    ds = await src.get_datasource(db)
    if ds is None:
        print(
            f"[ERROR] Datasource '{db}' not found in {source_path}.",
            file=sys.stderr,
        )
        return 1
    await dest.save_datasource(ds)

    n_models = 0
    for name in await src.list_models():
        try:
            model = await src.get_model(name)
        except Exception as exc:
            # Other DBs may have v1-shape models (e.g. demo data with
            # dimension/measure name collisions) that fail v3 migration.
            # We only care about models whose data_source matches *db*;
            # log and skip the rest.
            print(
                f"  skip '{name}': {exc.__class__.__name__}: {exc}",
                file=sys.stderr,
            )
            continue
        if model is None or model.data_source != db:
            continue
        await dest.save_model(model)
        n_models += 1

    print(f"[OK] exported {n_models} model(s) for '{db}' to {dest_dir}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Export SLayer models for one mini-interact DB to slayer_models/<db>/.",
    )
    p.add_argument("--db", required=True, help="DB / datasource name (e.g. 'households').")
    p.add_argument(
        "--source",
        default=str(DEFAULT_SLAYER_STORAGE),
        help=(
            f"Path to the SLayer storage to read from "
            f"(default: {DEFAULT_SLAYER_STORAGE}). Override with $SLAYER_STORAGE."
        ),
    )
    args = p.parse_args()
    return asyncio.run(_export_async(args.db, Path(args.source).resolve()))


if __name__ == "__main__":
    sys.exit(main())
