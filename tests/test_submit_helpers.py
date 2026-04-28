"""Shared submit/ask/env-action helpers — one authoritative implementation
that every framework adapter calls into."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeState(SimpleNamespace):
    """Mimics the shared shape of TaskState/TaskDeps/_ctx — only the
    fields the helpers touch."""

    def __init__(self, **kw):
        defaults = dict(
            status=SimpleNamespace(original_data={"selected_database": "fake_db"}),
            data_path_base="/tmp/ignored",
            user_sim_model="anthropic/claude-haiku-4-5-20251001",
            user_sim_prompt_version="v2",
            slayer_storage_dir="",
            result=None,
        )
        defaults.update(kw)
        super().__init__(**defaults)


def test_submit_raw_sql_records_submitted_sql_on_state(monkeypatch):
    from bird_interact_agents.agents import _submit

    monkeypatch.setattr(
        _submit, "execute_submit_action",
        lambda sql, status, dpb: ("ok", 1.0, True, False, True),
    )

    state = _FakeState()
    out = _submit.submit_raw_sql(state, "SELECT 1")

    assert "ok" in out
    assert state.result == {
        "phase1_passed": True,
        "phase2_passed": False,
        "total_reward": 1.0,
        "finished": True,
        "submitted_sql": "SELECT 1",
        "submitted_query": None,
    }


def test_submit_slayer_query_records_both_sql_and_dsl(monkeypatch):
    from bird_interact_agents.agents import _submit

    monkeypatch.setattr(
        _submit, "execute_submit_action",
        lambda sql, status, dpb: (f"obs of {sql}", 1.0, True, True, True),
    )

    fake_client = SimpleNamespace(sql_sync=lambda d: f"-- generated\nSELECT * FROM {d['models'][0]}")
    state = _FakeState()

    out = _submit.submit_slayer_query(
        state,
        query_json='{"models": ["m"]}',
        slayer_client_factory=lambda s: fake_client,
    )

    assert "Generated SQL" in out
    assert state.result["submitted_sql"].startswith("-- generated")
    assert state.result["submitted_query"] == '{"models": ["m"]}'
    assert state.result["phase1_passed"] is True
    assert state.result["phase2_passed"] is True


def test_submit_slayer_query_returns_error_on_bad_json():
    from bird_interact_agents.agents import _submit

    state = _FakeState()
    out = _submit.submit_slayer_query(
        state,
        query_json="{not json",
        slayer_client_factory=lambda s: pytest.fail("must not be called"),
    )
    assert "Invalid JSON" in out
    assert state.result is None


def test_submit_slayer_query_returns_error_on_render_failure():
    from bird_interact_agents.agents import _submit

    class _BoomClient:
        def sql_sync(self, _):
            raise RuntimeError("boom")

    state = _FakeState()
    out = _submit.submit_slayer_query(
        state,
        query_json='{"models": []}',
        slayer_client_factory=lambda s: _BoomClient(),
    )
    assert "Could not generate SQL" in out
    assert state.result is None


def test_run_env_action_renders_template_and_calls_executor(monkeypatch):
    from bird_interact_agents.agents import _submit
    from bird_interact_agents.agents._tool_specs import BIRD_INTERACT_TOOLS

    seen = {}

    def fake_execute(action, status, dpb):
        seen["action"] = action
        seen["dpb"] = dpb
        return ("schema goes here", None)

    monkeypatch.setattr(_submit, "execute_env_action", fake_execute)

    state = _FakeState()
    spec = next(t for t in BIRD_INTERACT_TOOLS if t.name == "get_column_meaning")
    out = _submit.run_env_action(state, spec, table_name="t1", column_name="c1")

    assert out == "schema goes here"
    assert seen["action"] == "get_column_meaning('t1', 'c1')"
    assert seen["dpb"] == "/tmp/ignored"


@pytest.mark.asyncio
async def test_ask_user_impl_records_user_sim_usage(monkeypatch):
    from bird_interact_agents.agents import _submit
    from bird_interact_agents import usage as usage_mod

    fake_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="<s>resp</s>"))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3),
    )

    async def fake_acompletion(**_):
        return fake_resp

    import litellm
    monkeypatch.setattr(usage_mod, "_acompletion", fake_acompletion)
    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(usage_mod, "_cost_per_token", lambda **_: (0.0, 0.0))

    monkeypatch.setattr(_submit, "build_user_encoder_prompt", lambda *a, **kw: "enc")
    monkeypatch.setattr(_submit, "build_user_decoder_prompt", lambda *a, **kw: "dec")
    monkeypatch.setattr(
        _submit, "parse_encoder_response",
        lambda raw: {"action_type": "answer", "encoded_data": "x"},
    )
    monkeypatch.setattr(_submit, "_schema_cache", {"fake_db": "CREATE TABLE foo;"})

    state = _FakeState(usage=usage_mod.TokenUsage())
    out = await _submit.ask_user_impl(state, "what?")

    assert out == "resp"
    assert state.usage.n_calls == 2
    assert all(row.scope == "user_sim" for row in state.usage.breakdown)
