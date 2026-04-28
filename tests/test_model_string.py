"""Invariants for the LiteLLM <-> PydanticAI model-string helpers."""

from bird_interact_agents.model_string import (
    is_anthropic,
    native_model_id,
    to_pydantic_ai,
)


def test_is_anthropic_true_for_anthropic_prefix():
    assert is_anthropic("anthropic/claude-sonnet-4-5") is True
    assert is_anthropic("anthropic/claude-haiku-4-5-20251001") is True


def test_is_anthropic_false_for_other_providers():
    assert is_anthropic("cerebras/zai-glm-4.7") is False
    assert is_anthropic("openrouter/z-ai/glm-4.7-flash") is False
    assert is_anthropic("fireworks_ai/glm-4p7") is False
    # Bare ids (legacy, no prefix) — definitely not anthropic
    assert is_anthropic("claude-sonnet-4-5") is False


def test_to_pydantic_ai_simple_provider():
    assert to_pydantic_ai("cerebras/zai-glm-4.7") == "cerebras:zai-glm-4.7"
    assert to_pydantic_ai("anthropic/claude-sonnet-4-5") == "anthropic:claude-sonnet-4-5"


def test_to_pydantic_ai_only_first_slash_for_openrouter():
    """OpenRouter model ids contain a slash (`z-ai/glm-4.7-flash`); the
    swap must only touch the first slash so the model id stays intact."""
    assert (
        to_pydantic_ai("openrouter/z-ai/glm-4.7-flash")
        == "openrouter:z-ai/glm-4.7-flash"
    )


def test_to_pydantic_ai_passes_through_unprefixed():
    """Bare ids without a slash are returned unchanged so PydanticAI's own
    inference can pick a provider for them."""
    assert to_pydantic_ai("claude-sonnet-4-5") == "claude-sonnet-4-5"


def test_to_pydantic_ai_idempotent_for_colonized_openrouter():
    """Already-colonized OpenRouter ids must not be mangled into
    `openrouter:z-ai:glm-4.7-flash` — that broke PydanticAI lookups when
    callers pre-converted the string before handing it to the adapter."""
    assert (
        to_pydantic_ai("openrouter:z-ai/glm-4.7-flash")
        == "openrouter:z-ai/glm-4.7-flash"
    )


def test_to_pydantic_ai_idempotent_for_colonized_simple():
    """Colon form without a slash also survives a redundant conversion."""
    assert to_pydantic_ai("anthropic:claude-sonnet-4-5") == "anthropic:claude-sonnet-4-5"


def test_native_model_id_strips_prefix():
    assert native_model_id("anthropic/claude-sonnet-4-5") == "claude-sonnet-4-5"
    assert native_model_id("cerebras/zai-glm-4.7") == "zai-glm-4.7"
    # Multiple slashes — only the first is the provider boundary
    assert native_model_id("openrouter/z-ai/glm-4.7-flash") == "z-ai/glm-4.7-flash"
    # Bare id, no prefix -> unchanged
    assert native_model_id("claude-sonnet-4-5") == "claude-sonnet-4-5"
