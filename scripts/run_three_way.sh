#!/usr/bin/env bash
# Run all three benchmark versions (original BIRD-Interact harness, our raw
# flavor, our slayer flavor) on the same task subset and emit a comparison.
#
# Versions are run sequentially by default (less rate-limit risk, cleaner
# logs); pass --parallel to run them concurrently with `&` + `wait`.
#
# Required env: BIRD_BIRD_INTERACT_ROOT, ANTHROPIC_API_KEY.

set -euo pipefail

# ---- Defaults ----------------------------------------------------------------
MODE="a-interact"
LIMIT=10
CONCURRENCY=3
FRAMEWORK="pydantic_ai"
AGENT_MODEL="anthropic/claude-sonnet-4-5"
USER_SIM_MODEL="anthropic/claude-haiku-4-5-20251001"
OUTPUT_DIR=""
PARALLEL=false
STRICT=false

usage() {
  cat <<EOF
Usage: $0 [options]
  --mode {a-interact,c-interact}    (default: a-interact)
  --limit N                         (default: 10)
  --concurrency K                   (default: 3)
  --output-dir DIR                  (default: results/3way_<timestamp>)
  --framework {claude_sdk,pydantic_ai,smolagents,agno,mcp_agent}
                                    (default: pydantic_ai — claude_sdk
                                    cannot run from inside another
                                    Claude Code session due to stdio
                                    contention with the spawned `claude`
                                    subprocess)
  --agent-model MODEL               LiteLLM-style PROVIDER/MODEL_ID
                                    (default: anthropic/claude-sonnet-4-5).
                                    Examples: cerebras/zai-glm-4.7,
                                    openrouter/z-ai/glm-4.7-flash,
                                    fireworks_ai/glm-4p7. The matching
                                    API-key env var must be set.
  --user-sim-model MODEL            (default: anthropic/claude-haiku-4-5-20251001)
  --parallel                        Run the three versions concurrently
  --strict / --no-strict            Force every tool definition to carry
                                    strict=True (default: --no-strict).
                                    Only honoured by pydantic_ai/smolagents/agno;
                                    claude_sdk ignores; mcp_agent errors out.
  -h | --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --framework) FRAMEWORK="$2"; shift 2 ;;
    --agent-model) AGENT_MODEL="$2"; shift 2 ;;
    --user-sim-model) USER_SIM_MODEL="$2"; shift 2 ;;
    --parallel) PARALLEL=true; shift ;;
    --strict) STRICT=true; shift ;;
    --no-strict) STRICT=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

# ---- Env validation ----------------------------------------------------------
: "${BIRD_BIRD_INTERACT_ROOT:?Set BIRD_BIRD_INTERACT_ROOT to the BIRD-Interact clone}"

# Check the API key for whichever provider the agent + user-sim models use.
# (LiteLLM resolves the env var name from the prefix.)
provider_env() {
  case "${1%%/*}" in
    anthropic)    echo ANTHROPIC_API_KEY ;;
    cerebras)     echo CEREBRAS_API_KEY ;;
    openrouter)   echo OPENROUTER_API_KEY ;;
    fireworks_ai) echo FIREWORKS_API_KEY ;;
    zhipu)        echo ZHIPU_API_KEY ;;
    *)            echo "" ;;
  esac
}
for m in "$AGENT_MODEL" "$USER_SIM_MODEL"; do
  env_var="$(provider_env "$m")"
  if [[ -n "$env_var" && -z "${!env_var:-}" ]]; then
    echo "Error: $env_var is not set (needed for model '$m')." >&2
    exit 1
  fi
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="results/3way_$(date +%Y%m%d_%H%M%S)"
fi
mkdir -p "$OUTPUT_DIR"
# Resolve to absolute so subprocesses that cd elsewhere still find it.
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

# Default data + db paths come from .env via bird_interact_agents.config.
# Resolve them from the env vars that pydantic-settings looks at.
DATA_PATH="${BIRD_DATA_PATH:?Set BIRD_DATA_PATH to mini_interact.jsonl}"
DB_PATH="${BIRD_DB_PATH:?Set BIRD_DB_PATH to mini-interact dir with SQLite DBs}"

# ---- Step 1: lock task subset ------------------------------------------------
IDS_FILE="$OUTPUT_DIR/instance_ids.txt"
uv run python scripts/select_tasks.py \
  --data "$DATA_PATH" --limit "$LIMIT" --out "$IDS_FILE"
echo "Selected $(wc -l < "$IDS_FILE") tasks (logged in $IDS_FILE)"

# ---- Step 2: ensure SLayer storage exists ------------------------------------
if [[ ! -d slayer_storage ]] || [[ -z "$(ls -A slayer_storage 2>/dev/null)" ]]; then
  echo "slayer_storage not found — running ingest..."
  uv run python scripts/ingest_slayer_models.py \
    --db-path "$DB_PATH" --storage-root ./slayer_storage
fi

# ---- Step 3: run each version ------------------------------------------------
# We invoke the upstream batch_run_bird_interact.main directly rather than its
# bash wrapper: the wrapper had a bug where --agent_models was assigned to a
# variable the loop never read (we patched it upstream too, but bypassing the
# wrapper means fewer moving parts and uses our uv-managed venv consistently).
run_original() {
  local out_dir="$OUTPUT_DIR/original"
  mkdir -p "$out_dir"
  echo "[original] Running upstream main.py via uv run..."
  uv run python -m batch_run_bird_interact.main \
    --data_path "$DATA_PATH" \
    --output_path "$out_dir/results.jsonl" \
    --agent_model "$AGENT_MODEL" \
    --user_model "$USER_SIM_MODEL" \
    --user_sim_mode encoder_decoder \
    --user_sim_prompt_version v2 \
    --user_patience_budget 6 \
    --max_turns 60 \
    --num_threads "$CONCURRENCY" \
    --limit "$LIMIT" \
    --mini_interact \
    --log_file "$out_dir/experiment.log" \
    --log_level WARNING \
    > "$out_dir/run.log" 2>&1 || echo "[original] returned non-zero — see $out_dir/run.log"
}

run_ours() {
  local query_mode="$1"
  local out_dir="$OUTPUT_DIR/$query_mode"
  mkdir -p "$out_dir"
  echo "[$query_mode] Running bird-interact (--framework $FRAMEWORK --query-mode $query_mode --mode $MODE)..."
  uv run python -m bird_interact_agents.run \
    --framework "$FRAMEWORK" \
    --mode "$MODE" \
    --query-mode "$query_mode" \
    --data "$DATA_PATH" \
    --db-path "$DB_PATH" \
    --output "$out_dir/eval.json" \
    --concurrency "$CONCURRENCY" \
    --filter-ids "$IDS_FILE" \
    --agent-model "$AGENT_MODEL" \
    --user-sim-model "$USER_SIM_MODEL" \
    $($STRICT && echo "--strict" || echo "--no-strict") \
    > "$out_dir/run.log" 2>&1 || echo "[$query_mode] returned non-zero — see $out_dir/run.log"
}

if $PARALLEL; then
  run_original &
  run_ours raw &
  run_ours slayer &
  wait
else
  run_original
  run_ours raw
  run_ours slayer
fi

# ---- Step 4: compare ---------------------------------------------------------
echo
uv run python scripts/compare_results.py "$OUTPUT_DIR"
