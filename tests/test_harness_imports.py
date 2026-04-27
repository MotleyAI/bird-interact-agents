"""Verify the BIRD-Interact harness imports and basic helpers work."""

from bird_interact_agents.config import settings


def test_harness_imports():
    """All harness re-exports import successfully."""
    from bird_interact_agents.harness import (
        execute_env_action,
        execute_submit_action,
        load_db_data_if_needed,
        SampleStatus,
        build_user_encoder_prompt,
        build_user_decoder_prompt,
        parse_encoder_response,
        calculate_budget,
        load_tasks,
    )
    assert callable(execute_env_action)
    assert callable(execute_submit_action)
    assert callable(load_db_data_if_needed)
    assert SampleStatus is not None


def test_load_tasks():
    """Loading mini_interact.jsonl produces task dicts with the expected fields."""
    from bird_interact_agents.harness import load_tasks

    tasks = load_tasks(settings.data_path, limit=3)
    assert len(tasks) == 3
    for t in tasks:
        assert "instance_id" in t
        assert "amb_user_query" in t
        assert "selected_database" in t
        assert "sol_sql" in t
        assert isinstance(t["sol_sql"], list)
        assert len(t["sol_sql"]) > 0  # GT was merged in


def test_calculate_budget():
    """Budget formula: 6 + 2*ambiguities + 2*patience."""
    from bird_interact_agents.harness import calculate_budget, load_tasks

    tasks = load_tasks(settings.data_path, limit=1)
    budget = calculate_budget(tasks[0], patience=3)
    assert isinstance(budget, (int, float))
    assert budget >= 12  # 6 + 0 + 6 minimum
