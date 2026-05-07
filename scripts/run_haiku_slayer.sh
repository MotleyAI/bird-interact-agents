#!/usr/bin/env bash
# Reproducible single-DB benchmark run: pydantic_ai + slayer + Haiku 4.5
# on a-interact mode. Each invocation creates a timestamped output dir
# under results/, filters mini_interact.jsonl to one DB, and runs the
# bird-interact CLI with the canonical-only-info prompt set.
#
# Usage:
#   scripts/run_haiku_slayer.sh --db households --concurrency 5
#   scripts/run_haiku_slayer.sh --db credit --limit 3 --concurrency 1
#
# Required env: ANTHROPIC_API_KEY.
# Optional env: BIRD_BIRD_INTERACT_ROOT (default: sibling BIRD-Interact),
#               BIRD_DATA_PATH (default: ../mini-interact/mini_interact.jsonl),
#               BIRD_DB_PATH   (default: ../mini-interact).

set -euo pipefail

DB="households"
LIMIT_FLAG=""
CONCURRENCY=5
PATIENCE=3

usage() {
  cat <<EOF
Usage: $0 [--db NAME] [--limit N] [--concurrency K] [--patience P]
  --db NAME           target database (default: households)
  --limit N           cap on tasks to run from the filtered list
  --concurrency K     concurrent task workers (default: 5)
  --patience P        user_patience_budget (default: 3, matches canonical)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB="$2"; shift 2 ;;
    --limit) LIMIT_FLAG="--limit $2"; shift 2 ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --patience) PATIENCE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; usage; exit 1 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY before running.}"
: "${BIRD_BIRD_INTERACT_ROOT:=$REPO_ROOT/../BIRD-Interact}"
: "${BIRD_DATA_PATH:=$REPO_ROOT/../mini-interact/mini_interact.jsonl}"
: "${BIRD_DB_PATH:=$REPO_ROOT/../mini-interact}"
export BIRD_BIRD_INTERACT_ROOT

if [[ ! -f "$BIRD_DATA_PATH" ]]; then
  echo "Dataset jsonl not found: $BIRD_DATA_PATH" >&2; exit 1
fi
if [[ ! -d "$BIRD_DB_PATH" ]]; then
  echo "DB path not found: $BIRD_DB_PATH" >&2; exit 1
fi

TS=$(date +%Y%m%d-%H%M)
OUT="$REPO_ROOT/results/${TS}_pa_haiku_${DB}_slayer_a"
mkdir -p "$OUT"

# Filter the dataset to the chosen DB.
python3 - "$BIRD_DATA_PATH" "$DB" "$OUT/instance_ids.txt" <<'PY'
import json, sys
data, db, out = sys.argv[1], sys.argv[2], sys.argv[3]
n = 0
with open(data) as f, open(out, "w") as g:
    for line in f:
        if not line.strip():
            continue
        t = json.loads(line)
        if t.get("selected_database") == db:
            g.write(t["instance_id"] + "\n")
            n += 1
print(f"selected {n} tasks for db={db!r} -> {out}")
PY

if [[ ! -s "$OUT/instance_ids.txt" ]]; then
  echo "No tasks matched db=$DB; aborting." >&2; exit 1
fi

# Stash the invocation for replay.
{
  echo "DB=$DB"
  echo "LIMIT_FLAG=$LIMIT_FLAG"
  echo "CONCURRENCY=$CONCURRENCY"
  echo "PATIENCE=$PATIENCE"
  echo "BIRD_DATA_PATH=$BIRD_DATA_PATH"
  echo "BIRD_DB_PATH=$BIRD_DB_PATH"
  echo "BIRD_BIRD_INTERACT_ROOT=$BIRD_BIRD_INTERACT_ROOT"
  echo "AGENT_MODEL=anthropic/claude-haiku-4-5-20251001"
  echo "USER_SIM_MODEL=anthropic/claude-haiku-4-5-20251001"
  date -Iseconds
} > "$OUT/invocation.txt"

uv run bird-interact \
  --framework pydantic_ai \
  --query-mode slayer \
  --mode a-interact \
  --agent-model anthropic/claude-haiku-4-5-20251001 \
  --user-sim-model anthropic/claude-haiku-4-5-20251001 \
  --slayer-storage-root "$REPO_ROOT/slayer_storage" \
  --data "$BIRD_DATA_PATH" \
  --db-path "$BIRD_DB_PATH" \
  --filter-ids "$OUT/instance_ids.txt" \
  --concurrency "$CONCURRENCY" \
  --patience "$PATIENCE" \
  --output "$OUT/eval.json" \
  $LIMIT_FLAG \
  2>&1 | tee "$OUT/run.log"

echo
echo "Run complete. Output dir: $OUT"
echo "  - eval.json   (canonical metrics + per-task results dump)"
echo "  - results.db  (per-task SQLite with diagnostic columns)"
echo "  - run.log     (full stdout/stderr)"
echo "  - invocation.txt + instance_ids.txt (for replay)"
