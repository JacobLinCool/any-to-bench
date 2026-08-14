"""Reasoning-effort levels and token-usage accounting models.

Kept dependency-light so the CLI can import it without pulling in pydantic-ai.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Effort(StrEnum):
    """Provider-agnostic reasoning effort.

    OpenAI: passed through as `reasoning.effort` (all levels supported on GPT-5.6).
    Google: mapped to `thinking_level` (MINIMAL/LOW/MEDIUM/HIGH; xhigh and max
    collapse to HIGH).
    """

    minimal = "minimal"
    low = "low"
    medium = "medium"
    high = "high"
    xhigh = "xhigh"
    max = "max"


class PhaseUsage(BaseModel):
    """Token usage accumulated over the model calls of one phase."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = Field(
        default=0, description="OpenAI reasoning tokens / Google thinking tokens"
    )
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def merged(self, other: PhaseUsage) -> PhaseUsage:
        return PhaseUsage(
            requests=self.requests + other.requests,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


class UsageSummary(BaseModel):
    total: PhaseUsage
    phases: dict[str, PhaseUsage] = Field(default_factory=dict)

    def format_line(self) -> str:
        t = self.total
        extras = []
        if t.reasoning_tokens:
            extras.append(f"reasoning {t.reasoning_tokens:,}")
        if t.cache_read_tokens:
            extras.append(f"cache read {t.cache_read_tokens:,}")
        if t.cache_write_tokens:
            # Priced above ordinary input tokens, so hiding it understates cost.
            extras.append(f"cache write {t.cache_write_tokens:,}")
        extra = f" ({', '.join(extras)})" if extras else ""
        return (
            f"Tokens: {t.input_tokens:,} in / {t.output_tokens:,} out{extra} "
            f"over {t.requests} request(s)"
        )
