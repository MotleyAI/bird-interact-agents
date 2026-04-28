"""Pick a stable instance_id slice from mini_interact.jsonl.

Used to lock the same set of tasks across all three runners (original,
raw, slayer) so their results are comparable.

Usage:
    python scripts/select_tasks.py \
        --data /path/to/mini_interact.jsonl \
        --limit 30 \
        --out instance_ids.txt
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Path to mini_interact.jsonl")
    parser.add_argument("--limit", type=int, default=30, help="Number of tasks to take")
    parser.add_argument(
        "--start", type=int, default=0, help="Start offset (0-based)"
    )
    parser.add_argument("--out", required=True, help="Where to write instance_ids.txt")
    args = parser.parse_args()

    ids: list[str] = []
    with open(args.data) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            if i < args.start:
                continue
            if len(ids) >= args.limit:
                break
            row = json.loads(line)
            ids.append(row["instance_id"])

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(ids) + "\n")
    print(f"Wrote {len(ids)} instance_ids to {args.out}")


if __name__ == "__main__":
    main()
