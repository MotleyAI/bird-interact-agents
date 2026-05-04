#!/usr/bin/env python3
"""Verify every KB entry for a mini-interact DB is either encoded in the
exported SLayer YAML models or documented in the per-DB notes file.

Usage:
    python scripts/verify_kb_coverage.py --db <db>
    python scripts/verify_kb_coverage.py --all

Exit 0 only when every KB id for the DB is in **exactly one** of:

  - the *encoded* set: any ``meta.kb_id`` reachable through the YAML
    models in ``bird-interact-agents/slayer_models/<db>/`` (walks
    ``SlayerModel.meta``, every ``Column.meta``, ``ModelMeasure.meta``,
    and ``Aggregation.meta``).
  - the *documented* set: KB ids parsed from
    ``bird-interact-agents/slayer_models/_notes/<db>.md`` headers of the
    shape ``## KB <id> — …``.

An id appearing in neither set, or in both, fails the check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Iterable

from slayer.storage.yaml_storage import YAMLStorage

REPO_ROOT = Path(__file__).resolve().parent.parent
SLAYER_MODELS_DIR = REPO_ROOT / "slayer_models"
NOTES_DIR = SLAYER_MODELS_DIR / "_notes"
DEFAULT_MINI_INTERACT_ROOT = REPO_ROOT.parent / "mini-interact"

KB_HEADER_RE = re.compile(r"^## KB (\d+) — ", re.MULTILINE)


def _kb_path(mini_interact_root: Path, db: str) -> Path:
    return mini_interact_root / db / f"{db}_kb.jsonl"


def load_kb_ids(kb_path: Path) -> set[int]:
    ids: set[int] = set()
    with kb_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ids.add(int(json.loads(line)["id"]))
    return ids


def _meta_kb_id(meta: dict | None) -> int | None:
    if not meta:
        return None
    raw = meta.get("kb_id")
    if raw is None:
        return None
    return int(raw)


async def load_encoded_ids(db_dir: Path) -> set[int]:
    """Load every meta.kb_id reachable through the YAML storage at *db_dir*.

    *db_dir* is a YAMLStorage ``base_dir``: it contains ``models/`` and
    ``datasources/`` sub-directories, populated by the export step in
    the translate-mini-interact-kb skill.
    """
    storage = YAMLStorage(base_dir=str(db_dir))
    ids: set[int] = set()
    for name in await storage.list_models():
        model = await storage.get_model(name)
        if model is None:
            continue
        for owner in (model, *model.columns, *model.measures, *model.aggregations):
            kb_id = _meta_kb_id(getattr(owner, "meta", None))
            if kb_id is not None:
                ids.add(kb_id)
    return ids


def load_documented_ids(notes_path: Path) -> set[int]:
    if not notes_path.exists():
        return set()
    text = notes_path.read_text(encoding="utf-8")
    return {int(m.group(1)) for m in KB_HEADER_RE.finditer(text)}


def _knowledge_text(kb_path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    with kb_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out[int(row["id"])] = row.get("knowledge", "")
    return out


async def verify_one(db: str, mini_interact_root: Path) -> tuple[set[int], set[int], dict[int, str]]:
    """Return ``(unaccounted, overlap, knowledge)`` for the DB.

    ``knowledge`` maps KB id → its ``knowledge`` field, used for human
    readability when reporting offenders.
    """
    kb_path = _kb_path(mini_interact_root, db)
    db_dir = SLAYER_MODELS_DIR / db
    notes_path = NOTES_DIR / f"{db}.md"

    if not kb_path.exists():
        raise FileNotFoundError(f"KB file not found: {kb_path}")
    if not db_dir.is_dir():
        raise FileNotFoundError(f"slayer_models dir not found: {db_dir}")
    if not notes_path.exists():
        raise FileNotFoundError(
            f"Notes file not found: {notes_path}. Create it (empty body OK)."
        )

    all_ids = load_kb_ids(kb_path)
    encoded = await load_encoded_ids(db_dir)
    documented = load_documented_ids(notes_path)

    accounted = encoded | documented
    unaccounted = all_ids - accounted
    overlap = encoded & documented
    knowledge = _knowledge_text(kb_path)
    return unaccounted, overlap, knowledge


def _list_dbs() -> list[str]:
    if not SLAYER_MODELS_DIR.is_dir():
        return []
    return sorted(
        p.name
        for p in SLAYER_MODELS_DIR.iterdir()
        if p.is_dir() and p.name != "_notes"
    )


async def main_async(dbs: Iterable[str], mini_interact_root: Path) -> int:
    bad = False
    for db in dbs:
        unaccounted, overlap, knowledge = await verify_one(db, mini_interact_root)
        if not unaccounted and not overlap:
            print(f"[OK] {db}")
            continue
        bad = True
        if unaccounted:
            print(f"[FAIL] {db}: {len(unaccounted)} unaccounted KB id(s):")
            for kb_id in sorted(unaccounted):
                print(f"  - {kb_id}: {knowledge.get(kb_id, '')}")
        if overlap:
            print(
                f"[FAIL] {db}: {len(overlap)} KB id(s) both encoded and "
                f"documented (must pick one):"
            )
            for kb_id in sorted(overlap):
                print(f"  - {kb_id}: {knowledge.get(kb_id, '')}")
    return 1 if bad else 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Verify mini-interact KB coverage in exported SLayer YAML.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--db", help="Verify one DB by name (e.g. 'households').")
    g.add_argument(
        "--all",
        action="store_true",
        help="Verify every DB with a slayer_models/<db>/ folder.",
    )
    p.add_argument(
        "--mini-interact-root",
        default=str(DEFAULT_MINI_INTERACT_ROOT),
        help=(
            "Root of the mini-interact dataset checkout "
            f"(default: {DEFAULT_MINI_INTERACT_ROOT})."
        ),
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()
    dbs = _list_dbs() if args.all else [args.db]
    if args.all and not dbs:
        print(
            f"[ERROR] No DBs found under {SLAYER_MODELS_DIR}. "
            "Run the translate-mini-interact-kb skill on at least one DB first.",
            file=sys.stderr,
        )
        return 1
    return asyncio.run(main_async(dbs, Path(args.mini_interact_root).resolve()))


if __name__ == "__main__":
    sys.exit(main())
