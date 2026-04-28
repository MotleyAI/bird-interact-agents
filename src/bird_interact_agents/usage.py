"""Token-usage accumulator for benchmark runs.

Each `TokenUsage` records totals across many LLM calls plus a per-(scope,
model) breakdown. Cost is computed at `add_call` time via
`litellm.cost_per_token`, so callers always see a numeric cost — unpriced
models silently record 0.

Wire it through the per-task `deps`/state object, then `merge()` per-task
accumulators in `run.py` to produce the eval-level total.
"""

from __future__ import annotations

import logging
from typing import Any

import litellm
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Indirection seams so tests can monkey-patch without touching litellm.
_acompletion = litellm.acompletion


def _cost_per_token(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> tuple[float, float]:
    """Return (prompt_cost_usd, completion_cost_usd) for this call.

    Wraps `litellm.cost_per_token`, which returns the same tuple for any
    provider it has pricing for. Raises if the model is unknown — callers
    must handle that.
    """
    return litellm.cost_per_token(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


_warned_unpriced: set[str] = set()


def _safe_cost(
    *, model: str, prompt_tokens: int, completion_tokens: int,
) -> tuple[float, float]:
    try:
        return _cost_per_token(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    except Exception as e:
        if model not in _warned_unpriced:
            _warned_unpriced.add(model)
            logger.warning(
                "No litellm price entry for model %r (%s); "
                "recording cost_usd=0 for this run.",
                model, e,
            )
        return 0.0, 0.0


class CallCost(BaseModel):
    """Per-(scope, model) aggregate.

    `name` is the canonical "{scope}::{model}" key used for merging.
    """

    name: str
    scope: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    n_calls: int = 0
    cost_usd: float = 0.0


class TokenUsage(BaseModel):
    """Cumulative token + cost accumulator across many LLM calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    n_calls: int = 0
    cost_usd: float = 0.0
    agent_cost_usd: float = 0.0
    user_sim_cost_usd: float = 0.0
    partial: bool = False  # set when a framework can't expose all usage
    breakdown: list[CallCost] = Field(default_factory=list)

    def _row_for(self, *, scope: str, model: str) -> CallCost:
        name = f"{scope}::{model}"
        for row in self.breakdown:
            if row.name == name:
                return row
        row = CallCost(name=name, scope=scope, model=model)
        self.breakdown.append(row)
        return row

    def add_call(
        self,
        *,
        scope: str,
        model: str,
        prompt: int,
        completion: int,
        reasoning: int = 0,
        cache_read: int = 0,
    ) -> None:
        prompt_cost, completion_cost = _safe_cost(
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
        )
        cost = prompt_cost + completion_cost

        row = self._row_for(scope=scope, model=model)
        row.prompt_tokens += prompt
        row.completion_tokens += completion
        row.reasoning_tokens += reasoning
        row.cache_read_tokens += cache_read
        row.n_calls += 1
        row.cost_usd += cost

        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.reasoning_tokens += reasoning
        self.cache_read_tokens += cache_read
        self.n_calls += 1
        self.cost_usd += cost
        if scope == "agent":
            self.agent_cost_usd += cost
        elif scope == "user_sim":
            self.user_sim_cost_usd += cost

    def merge(self, other: "TokenUsage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.reasoning_tokens += other.reasoning_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.n_calls += other.n_calls
        self.cost_usd += other.cost_usd
        self.agent_cost_usd += other.agent_cost_usd
        self.user_sim_cost_usd += other.user_sim_cost_usd
        self.partial = self.partial or other.partial

        for incoming in other.breakdown:
            existing = next(
                (r for r in self.breakdown if r.name == incoming.name), None,
            )
            if existing is None:
                self.breakdown.append(incoming.model_copy(deep=True))
            else:
                existing.prompt_tokens += incoming.prompt_tokens
                existing.completion_tokens += incoming.completion_tokens
                existing.reasoning_tokens += incoming.reasoning_tokens
                existing.cache_read_tokens += incoming.cache_read_tokens
                existing.n_calls += incoming.n_calls
                existing.cost_usd += incoming.cost_usd


async def acompletion_tracked(
    accum: TokenUsage,
    *,
    scope: str,
    model: str,
    **kwargs: Any,
):
    """Drop-in replacement for `litellm.acompletion` that records usage.

    Returns the raw response object (so callers can read `.choices[0]`,
    `.usage`, etc. as before).
    """
    response = await _acompletion(model=model, **kwargs)
    usage_obj = getattr(response, "usage", None)
    if usage_obj is not None:
        prompt = getattr(usage_obj, "prompt_tokens", 0) or 0
        completion = getattr(usage_obj, "completion_tokens", 0) or 0
        reasoning = getattr(usage_obj, "reasoning_tokens", 0) or 0
        cache_read = getattr(usage_obj, "cache_read_input_tokens", 0) or 0
        accum.add_call(
            scope=scope,
            model=model,
            prompt=prompt,
            completion=completion,
            reasoning=reasoning,
            cache_read=cache_read,
        )
    return response
