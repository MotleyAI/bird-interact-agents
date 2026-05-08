"""CLI entry point for running BIRD-Interact evaluations."""

import argparse
import asyncio
import json
import logging
import statistics
import time
from pathlib import Path

from bird_interact_agents.harness import (
    calculate_budget,
    execute_submit_action,
    finalize_result_row,
    load_db_data_if_needed,
    load_tasks,
    SampleStatus,
)
from bird_interact_agents.results_db import (
    TaskResultRow,
    insert_run_metadata,
    insert_task_result,
    open_db,
)
from bird_interact_agents.usage import TokenUsage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


async def run_oracle_task(task_data: dict, data_path_base: str) -> dict:
    """Submit ground-truth SQL directly — no LLM, validates eval pipeline."""
    from bird_interact_agents.agents._submit import (
        capture_result_snapshot,
        classify_submission,
    )
    import json as _json

    instance_id = task_data["instance_id"]
    db_name = task_data["selected_database"]
    sol_sql = task_data.get("sol_sql", [])
    if isinstance(sol_sql, list) and sol_sql:
        sol_sql = sol_sql[0]
    elif isinstance(sol_sql, list):
        sol_sql = ""

    load_db_data_if_needed(db_name, data_path_base)
    status = SampleStatus(idx=0, original_data=task_data)

    observation, reward, p1, p2, finished = execute_submit_action(
        sol_sql, status, data_path_base
    )

    predicted = capture_result_snapshot(sol_sql, db_name, data_path_base)
    gold = capture_result_snapshot(sol_sql, db_name, data_path_base)
    return finalize_result_row(
        {
            "task_id": instance_id,
            "instance_id": instance_id,
            "database": db_name,
            "phase1_passed": p1,
            "phase2_passed": p2,
            "total_reward": reward if reward is not None else 0.0,
            "submitted_sql": sol_sql,
            "submitted_query": None,
            "trajectory": [],
            "error": None,
            "submission_status": classify_submission(
                p1=p1, p2=p2, observation=observation,
            ),
            "phase1_observation": observation,
            "phase2_observation": None,
            "predicted_result_json": (
                _json.dumps(predicted, default=str)
                if predicted is not None else None
            ),
            "gold_result_json": (
                _json.dumps(gold, default=str) if gold is not None else None
            ),
            "n_agent_turns": 0,
        },
        deleted_kb_ids=[],
        slayer_storage_dir="",
    )


async def run_evaluation(
    data_path: str,
    data_dir: str,
    output_path: str,
    mode: str,
    query_mode: str,
    framework: str,
    limit: int | None = None,
    concurrency: int = 3,
    patience: int = 3,
    user_sim_model: str = "anthropic/claude-haiku-4-5-20251001",
    slayer_storage_root: str | None = None,
    filter_ids: list[str] | None = None,
    agent_model: str = "anthropic/claude-sonnet-4-5",
    strict: bool = False,
) -> dict:
    """Run full evaluation across all tasks."""
    tasks = load_tasks(data_path, limit)
    if filter_ids:
        wanted = set(filter_ids)
        tasks = [t for t in tasks if t.get("instance_id") in wanted]
    logger.info(
        "%s/%s: Evaluating %d tasks (concurrency=%d)",
        mode, query_mode, len(tasks), concurrency,
    )

    # Select the task runner
    if mode == "oracle":
        async def run_one(td: dict) -> dict:
            return await run_oracle_task(td, data_dir)
    elif framework == "claude_sdk":
        from bird_interact_agents.agents.claude_sdk.agent import ClaudeSDKAgent

        if strict:
            logger.warning(
                "[claude_sdk] --strict is a no-op for Anthropic models; ignored."
            )
        agent = ClaudeSDKAgent(
            slayer_storage_root=slayer_storage_root, model=agent_model,
        )

        async def run_one(td: dict) -> dict:
            budget = calculate_budget(td, patience, mode=mode)
            return await agent.run_task(
                td, data_dir, budget, query_mode,
                eval_mode=mode,
                user_sim_model=user_sim_model,
            )
    elif framework == "pydantic_ai":
        from bird_interact_agents.agents.pydantic_ai.agent import PydanticAIAgent

        agent_pa = PydanticAIAgent(
            slayer_storage_root=slayer_storage_root,
            model=agent_model,
            strict=strict,
        )

        async def run_one(td: dict) -> dict:
            budget = calculate_budget(td, patience, mode=mode)
            return await agent_pa.run_task(
                td, data_dir, budget, query_mode,
                eval_mode=mode,
                user_sim_model=user_sim_model,
            )
    elif framework == "mcp_agent":
        from bird_interact_agents.agents.mcp_agent.agent import McpAgentAgent

        agent_mcp = McpAgentAgent(
            slayer_storage_root=slayer_storage_root, model=agent_model,
            strict=strict,
        )

        async def run_one(td: dict) -> dict:
            budget = calculate_budget(td, patience, mode=mode)
            return await agent_mcp.run_task(
                td, data_dir, budget, query_mode,
                eval_mode=mode,
                user_sim_model=user_sim_model,
            )
    elif framework == "agno":
        from bird_interact_agents.agents.agno.agent import AgnoAgent

        agent_agno = AgnoAgent(
            slayer_storage_root=slayer_storage_root, model_id=agent_model,
            strict=strict,
        )

        async def run_one(td: dict) -> dict:
            budget = calculate_budget(td, patience, mode=mode)
            return await agent_agno.run_task(
                td, data_dir, budget, query_mode,
                eval_mode=mode,
                user_sim_model=user_sim_model,
            )
    elif framework == "smolagents":
        from bird_interact_agents.agents.smolagents.agent import SmolagentsAgent

        agent_sa = SmolagentsAgent(
            slayer_storage_root=slayer_storage_root, model_id=agent_model,
            strict=strict,
        )

        async def run_one(td: dict) -> dict:
            budget = calculate_budget(td, patience, mode=mode)
            return await agent_sa.run_task(
                td, data_dir, budget, query_mode,
                eval_mode=mode,
                user_sim_model=user_sim_model,
            )
    else:
        raise ValueError(f"Unknown framework: {framework}")

    # Open the per-run results.db (lives next to eval.json) and write
    # the run-metadata header before any task starts.
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "results.db"
    db_conn = open_db(db_path)
    run_id = output_dir.name or "default"
    insert_run_metadata(
        db_conn,
        run_id=run_id,
        agent_model=agent_model,
        user_sim_model=user_sim_model,
        framework=framework,
        mode=mode,
        started_at=time.time(),
    )

    def _persist(td: dict, r: dict, started_at: float) -> None:
        """Insert one task result into the DB. Called immediately after
        each task — both successes and failures — so a mid-run crash
        never throws away completed-task data."""
        usage_blob = r.get("usage")
        usage_json = json.dumps(usage_blob) if usage_blob is not None else "{}"
        sol = td.get("sol_sql")
        if isinstance(sol, list) and sol:
            ground_truth = sol[0]
        elif isinstance(sol, str):
            ground_truth = sol
        else:
            ground_truth = None
        n_turns = r.get("n_agent_turns")
        stats_blob = r.get("tool_call_stats")
        tool_call_stats_json = (
            json.dumps(stats_blob) if stats_blob is not None else None
        )
        insert_task_result(db_conn, TaskResultRow(
            run_id=run_id,
            framework=framework,
            mode=mode,
            query_mode=query_mode,
            instance_id=str(r.get("instance_id") or td.get("instance_id") or ""),
            database=str(r.get("database") or td.get("selected_database") or ""),
            started_at=started_at,
            duration_s=float(r.get("duration_s") or 0.0),
            phase1_passed=bool(r.get("phase1_passed")),
            phase2_passed=bool(r.get("phase2_passed")),
            total_reward=float(r.get("total_reward") or 0.0),
            submitted_sql=r.get("submitted_sql"),
            submitted_query=r.get("submitted_query"),
            ground_truth_sql=r.get("ground_truth_sql") or ground_truth,
            error=r.get("error"),
            usage_json=usage_json,
            user_query=td.get("amb_user_query"),
            submission_status=str(
                r.get("submission_status") or "never_submitted"
            ),
            phase1_observation=r.get("phase1_observation"),
            phase2_observation=r.get("phase2_observation"),
            predicted_result_json=r.get("predicted_result_json"),
            gold_result_json=r.get("gold_result_json"),
            n_agent_turns=int(n_turns) if isinstance(n_turns, int) else None,
            tool_call_stats_json=tool_call_stats_json,
        ))

    # Run tasks with concurrency limiter
    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    total_reward = 0.0
    p1_count = 0
    p2_count = 0

    async def _run_with_sem(i: int, td: dict) -> None:
        nonlocal total_reward, p1_count, p2_count
        async with semaphore:
            instance_id = td["instance_id"]
            logger.info("Task %d/%d: %s", i + 1, len(tasks), instance_id)
            started_at = time.time()
            t_start = time.perf_counter()
            try:
                r = await run_one(td)
            except Exception as e:
                logger.error("Error on %s: %s", instance_id, e)
                r = finalize_result_row(
                    {
                        "task_id": instance_id,
                        "instance_id": instance_id,
                        "database": td.get("selected_database", ""),
                        "phase1_passed": False,
                        "phase2_passed": False,
                        "total_reward": 0.0,
                        "trajectory": [],
                        "error": str(e),
                    },
                    deleted_kb_ids=[],
                    slayer_storage_dir="",
                )
            r["duration_s"] = time.perf_counter() - t_start
            _persist(td, r, started_at)
            results.append(r)
            total_reward += r.get("total_reward", 0)
            if r.get("phase1_passed"):
                p1_count += 1
            if r.get("phase2_passed"):
                p2_count += 1

    try:
        await asyncio.gather(*[_run_with_sem(i, td) for i, td in enumerate(tasks)])
    finally:
        db_conn.close()

    # Sum per-task usage blocks into a top-level total. Any task missing
    # `usage` (e.g. oracle pre-instrumentation) is skipped without error.
    total_usage = TokenUsage()
    for r in results:
        u_blob = r.get("usage")
        if u_blob is not None:
            total_usage.merge(TokenUsage.model_validate(u_blob))

    durations = [float(r.get("duration_s") or 0.0) for r in results]
    timing = {
        "total_duration_s": sum(durations),
        "avg_duration_s": (sum(durations) / len(durations)) if durations else 0.0,
        "p50_duration_s": statistics.median(durations) if durations else 0.0,
        "max_duration_s": max(durations) if durations else 0.0,
    }

    # Build metrics
    n = len(tasks)
    metrics = {
        "mode": mode,
        "query_mode": query_mode,
        "framework": framework,
        "total_tasks": n,
        "phase1_count": p1_count,
        "phase1_rate": p1_count / n if n else 0,
        "phase2_count": p2_count,
        "phase2_rate": p2_count / n if n else 0,
        "total_reward": total_reward,
        "average_reward": total_reward / n if n else 0,
        "total_usage": total_usage.model_dump(),
        **timing,
        "results": results,
    }

    # Save
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    logger.info(
        "Done. Tasks: %d, P1: %d/%d (%.1f%%), Avg Reward: %.4f",
        n, p1_count, n, (p1_count / n * 100) if n else 0,
        (total_reward / n) if n else 0,
    )
    return metrics


def _apply_price_overrides(path: str) -> None:
    """Merge a JSON price-overrides file into litellm's built-in pricing
    table. Entries are `{"name": str, "input_per_m": float, "output_per_m": float}`.

    Per-million → per-token conversion happens here.
    """
    import litellm

    with open(path) as f:
        entries = json.load(f)

    for e in entries:
        litellm.model_cost[e["name"]] = {
            "input_cost_per_token": float(e["input_per_m"]) / 1_000_000,
            "output_cost_per_token": float(e["output_per_m"]) / 1_000_000,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BIRD-Interact benchmark runner with pluggable agents"
    )
    parser.add_argument(
        "--framework",
        choices=["claude_sdk", "pydantic_ai", "mcp_agent", "agno", "smolagents"],
        default="claude_sdk",
        help="Agent framework to use",
    )
    parser.add_argument(
        "--mode",
        choices=["a-interact", "c-interact", "oracle"],
        default="a-interact",
        help="Evaluation mode",
    )
    parser.add_argument(
        "--query-mode",
        choices=["slayer", "raw"],
        default="raw",
        help="Query mode: slayer (semantic layer) or raw (direct SQL)",
    )
    parser.add_argument(
        "--data", required=True, help="Path to mini_interact.jsonl"
    )
    parser.add_argument(
        "--db-path", required=True, help="Path to mini-interact/ with SQLite DBs"
    )
    parser.add_argument(
        "--output", default="results/eval.json", help="Output JSON path"
    )
    parser.add_argument("--limit", type=int, default=None, help="Max tasks to run")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--patience", type=int, default=3, help="User patience budget")
    parser.add_argument(
        "--agent-model",
        default="anthropic/claude-sonnet-4-5",
        help=(
            "LiteLLM-style PROVIDER/MODEL_ID for the system agent. "
            "Examples: cerebras/zai-glm-4.7, openrouter/z-ai/glm-4.7-flash, "
            "anthropic/claude-sonnet-4-5, fireworks_ai/glm-4p7. The matching "
            "API-key env var (CEREBRAS_API_KEY, OPENROUTER_API_KEY, "
            "ANTHROPIC_API_KEY, FIREWORKS_API_KEY) must be set. The "
            "claude_sdk framework is locked to Anthropic and will skip "
            "with a warning if given a non-Anthropic model."
        ),
    )
    parser.add_argument(
        "--user-sim-model",
        default="anthropic/claude-haiku-4-5-20251001",
        help="LiteLLM model for user simulator",
    )
    parser.add_argument(
        "--slayer-storage-root",
        default="./slayer_storage",
        help="Root dir of per-DB SLayer model stores (only used in --query-mode slayer)",
    )
    parser.add_argument(
        "--filter-ids",
        default=None,
        help=(
            "Path to a text file with one instance_id per line; only tasks "
            "with these IDs are evaluated. Use to align with the original "
            "harness in 3-way comparison runs."
        ),
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Force every tool definition to carry strict=True (OpenAI "
            "strict structured-output mode). Default False matches the "
            "non-strict, non-constrained-decoding behaviour of all "
            "frameworks. claude_sdk silently ignores the flag (Anthropic "
            "has no tool-level strict). mcp_agent doesn't expose a hook "
            "for it and exits with a clear error when --strict is given."
        ),
    )
    parser.add_argument(
        "--price-overrides",
        default=None,
        help=(
            "Optional JSON file with price overrides merged into litellm's "
            "built-in pricing table. Format: a list of "
            '{"name": "<model>", "input_per_m": <float>, '
            '"output_per_m": <float>} entries.'
        ),
    )
    args = parser.parse_args()

    if args.price_overrides:
        _apply_price_overrides(args.price_overrides)

    filter_ids: list[str] | None = None
    if args.filter_ids:
        with open(args.filter_ids) as f:
            filter_ids = [line.strip() for line in f if line.strip()]

    asyncio.run(
        run_evaluation(
            data_path=args.data,
            data_dir=args.db_path,
            output_path=args.output,
            mode=args.mode,
            query_mode=args.query_mode,
            framework=args.framework,
            limit=args.limit,
            concurrency=args.concurrency,
            patience=args.patience,
            user_sim_model=args.user_sim_model,
            slayer_storage_root=args.slayer_storage_root,
            filter_ids=filter_ids,
            agent_model=args.agent_model,
            strict=args.strict,
        )
    )


if __name__ == "__main__":
    main()
