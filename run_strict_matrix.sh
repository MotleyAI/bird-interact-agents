#!/usr/bin/env bash
set +e
cd /home/james/Dropbox/SLayer/bird-interact-agents

export BIRD_BIRD_INTERACT_ROOT=/home/james/Dropbox/SLayer/BIRD-Interact
DATA=/home/james/Dropbox/SLayer/mini-interact/mini_interact.jsonl
DB=/home/james/Dropbox/SLayer/mini-interact

for fw in pydantic_ai smolagents agno mcp_agent claude_sdk; do
  for strict in "--strict" "--no-strict"; do
    label=${strict#--}
    out=results/strict_matrix/${fw}_${label}
    mkdir -p "$out"
    echo "=== $fw $strict ==="
    uv run python -m bird_interact_agents.run \
      --framework "$fw" --query-mode raw --mode a-interact \
      --agent-model cerebras/zai-glm-4.7 \
      --user-sim-model cerebras/zai-glm-4.7 \
      --limit 1 --concurrency 1 \
      $strict \
      --data "$DATA" --db-path "$DB" \
      --output "$out/eval.json" \
      >"$out/run.log" 2>&1
    echo "exit=$?"
  done
done
echo "=== DONE ==="
