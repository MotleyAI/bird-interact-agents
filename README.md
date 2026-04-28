# bird-interact-agents

Pluggable agent benchmarks for [BIRD-Interact](https://github.com/bird-bench/BIRD-Interact) mini (300 SQLite tasks). Evaluates query generation via [SLayer](https://github.com/MotleyAI/slayer) semantic layer and raw SQL, across multiple agent frameworks.

See [ROADMAP.md](ROADMAP.md) for the multi-framework plan.

## Quick Start

### Prerequisites

1. Clone [BIRD-Interact](https://github.com/bird-bench/BIRD-Interact):
   ```bash
   git clone https://github.com/bird-bench/BIRD-Interact.git
   ```

2. Get the mini-interact dataset (SQLite DBs + metadata) from [HuggingFace](https://huggingface.co/datasets/birdsql/mini-interact) or use a local copy.

3. Set environment variables:
   ```bash
   export BIRD_BIRD_INTERACT_ROOT=/path/to/BIRD-Interact
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

### Install

```bash
pip install -e ".[claude-sdk,dev]"
```

### Run

```bash
# Validate eval pipeline (submits ground-truth SQL, no LLM)
bird-interact --mode oracle \
  --data /path/to/mini_interact.jsonl \
  --db-path /path/to/mini-interact/

# Run with Claude Agent SDK, raw SQL mode
bird-interact --framework claude_sdk --query-mode raw --mode a-interact \
  --data /path/to/mini_interact.jsonl \
  --db-path /path/to/mini-interact/ \
  --limit 10 --concurrency 3

# Run with SLayer mode (requires SLayer models to be ingested)
bird-interact --framework claude_sdk --query-mode slayer --mode a-interact \
  --data /path/to/mini_interact.jsonl \
  --db-path /path/to/mini-interact/
```

## 3-way comparison (original ↔ raw ↔ slayer)

`scripts/run_three_way.sh` runs the upstream BIRD-Interact harness, our raw-SQL flavour, and our SLayer flavour on the same `instance_id` slice and emits a side-by-side `comparison.json`.

Prerequisites:
```bash
export BIRD_BIRD_INTERACT_ROOT=/path/to/BIRD-Interact
export BIRD_DATA_PATH=/path/to/mini_interact.jsonl
export BIRD_DB_PATH=/path/to/mini-interact
export ANTHROPIC_API_KEY=sk-ant-...
uv sync --extra all --extra dev   # brings in the upstream harness via tool.uv.sources
```

Run:
```bash
bash scripts/run_three_way.sh --mode a-interact --limit 30 --concurrency 4
```

Defaults to `--framework pydantic_ai` because `claude_sdk` cannot run from inside an active Claude Code session (stdio collision with the spawned `claude` subprocess). `--parallel` runs the three versions concurrently. The output directory contains:

- `original/results.jsonl`, `raw/eval.json`, `slayer/eval.json` — raw per-version outputs
- `comparison.json` — `{summary: {<version>: {n, phase1_rate, phase2_rate, avg_reward, errors}}, per_task: {<id>: {<version>: ...}}}` for direct row-by-row comparison
- A Markdown table is also printed to stdout

## Query Modes

- **`raw`**: Agent gets direct DB tools (`execute_sql`, `get_schema`, `get_column_meaning`, etc.) and writes SQL.
- **`slayer`**: Agent uses SLayer MCP tools (`models_summary`, `inspect_model`, `query`). Doesn't know about SQL/SQLite.

## Agent Frameworks

| Framework | Status | Install extra |
|-----------|--------|--------------|
| Claude Agent SDK | Active | `claude-sdk` |
| PydanticAI | Planned | — |
| smolagents | Planned | — |
| Agno | Planned | — |
| mcp-agent | Planned | — |

## License

MIT
