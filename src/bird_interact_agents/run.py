"""CLI entry point for running BIRD-Interact evaluations."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from bird_interact_agents.harness import (
    calculate_budget,
    execute_submit_action,
    load_db_data_if_needed,
    load_tasks,
    SampleStatus,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


async def run_oracle_task(task_data: dict, data_path_base: str) -> dict:
    """Submit ground-truth SQL directly — no LLM, validates eval pipeline."""
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

    return {
        "task_id": instance_id,
        "instance_id": instance_id,
        "database": db_name,
        "phase1_passed": p1,
        "phase2_passed": p2,
        "total_reward": reward if reward is not None else 0.0,
        "trajectory": [],
        "error": None,
    }


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
) -> dict:
    """Run full evaluation across all tasks."""
    tasks = load_tasks(data_path, limit)
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

        agent = ClaudeSDKAgent(slayer_storage_root=slayer_storage_root)

        async def run_one(td: dict) -> dict:
            budget = calculate_budget(td, patience)
            return await agent.run_task(
                td, data_dir, budget, query_mode,
                eval_mode=mode,
                user_sim_model=user_sim_model,
            )
    elif framework == "pydantic_ai":
        from bird_interact_agents.agents.pydantic_ai.agent import PydanticAIAgent

        agent_pa = PydanticAIAgent(
            slayer_storage_root=slayer_storage_root,
            model="anthropic:claude-sonnet-4-5",
        )

        async def run_one(td: dict) -> dict:
            budget = calculate_budget(td, patience)
            return await agent_pa.run_task(
                td, data_dir, budget, query_mode,
                eval_mode=mode,
                user_sim_model=user_sim_model,
            )
    elif framework == "mcp_agent":
        from bird_interact_agents.agents.mcp_agent.agent import McpAgentAgent

        agent_mcp = McpAgentAgent(slayer_storage_root=slayer_storage_root)

        async def run_one(td: dict) -> dict:
            budget = calculate_budget(td, patience)
            return await agent_mcp.run_task(
                td, data_dir, budget, query_mode,
                eval_mode=mode,
                user_sim_model=user_sim_model,
            )
    else:
        raise ValueError(f"Unknown framework: {framework}")

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
            try:
                r = await run_one(td)
            except Exception as e:
                logger.error("Error on %s: %s", instance_id, e)
                r = {
                    "task_id": instance_id,
                    "instance_id": instance_id,
                    "database": td.get("selected_database", ""),
                    "phase1_passed": False,
                    "phase2_passed": False,
                    "total_reward": 0.0,
                    "trajectory": [],
                    "error": str(e),
                }
            results.append(r)
            total_reward += r.get("total_reward", 0)
            if r.get("phase1_passed"):
                p1_count += 1
            if r.get("phase2_passed"):
                p2_count += 1

    await asyncio.gather(*[_run_with_sem(i, td) for i, td in enumerate(tasks)])

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BIRD-Interact benchmark runner with pluggable agents"
    )
    parser.add_argument(
        "--framework",
        choices=["claude_sdk", "pydantic_ai", "mcp_agent"],
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
        "--user-sim-model",
        default="anthropic/claude-haiku-4-5-20251001",
        help="LiteLLM model for user simulator",
    )
    parser.add_argument(
        "--slayer-storage-root",
        default="./slayer_storage",
        help="Root dir of per-DB SLayer model stores (only used in --query-mode slayer)",
    )
    args = parser.parse_args()

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
        )
    )


if __name__ == "__main__":
    main()
