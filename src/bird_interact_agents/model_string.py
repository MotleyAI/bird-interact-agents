"""Tiny helpers for routing LiteLLM-style model strings to each framework's
preferred form.

We use LiteLLM's slash-separated `provider/model_id` convention as the
canonical form across our CLI and configs, because LiteLLM already maintains
the provider catalogue (Cerebras, OpenRouter, Anthropic, Z.ai, Fireworks,
DeepInfra, ...). PydanticAI uses the same set of providers but spells them
with a colon (`provider:model_id`), and OpenRouter model ids contain
embedded slashes — so we only swap the FIRST slash when converting.
"""

from __future__ import annotations


def is_anthropic(model: str) -> bool:
    """`anthropic/claude-sonnet-4-5` -> True. Anything else -> False.

    Used to short-circuit the Claude-locked claude_sdk framework when the
    user has selected a non-Anthropic model.
    """
    return model.split("/", 1)[0] == "anthropic"


def to_pydantic_ai(model: str) -> str:
    """Convert a LiteLLM-style string to PydanticAI's `provider:model_id` form.

    Idempotent: an input already in PydanticAI form (provider contains a
    colon before the first slash) is returned unchanged. Otherwise only the
    first slash is swapped — OpenRouter model ids contain a slash themselves
    (e.g. `z-ai/glm-4.7-flash`).

        cerebras/zai-glm-4.7              -> cerebras:zai-glm-4.7
        openrouter/z-ai/glm-4.7-flash     -> openrouter:z-ai/glm-4.7-flash
        anthropic/claude-sonnet-4-5       -> anthropic:claude-sonnet-4-5
        openrouter:z-ai/glm-4.7-flash     -> openrouter:z-ai/glm-4.7-flash  (unchanged)
    """
    provider, sep, rest = model.partition("/")
    if not sep:
        return model
    if ":" in provider:
        return model
    return f"{provider}:{rest}"


def native_model_id(model: str) -> str:
    """Strip the provider prefix: `anthropic/claude-sonnet-4-5` -> `claude-sonnet-4-5`.

    Some framework-native classes (e.g. `agno.models.anthropic.Claude(id=...)`)
    expect the bare model id without a provider prefix.
    """
    _, sep, rest = model.partition("/")
    return rest if sep else model
