"""Single construction point for LLM agents (pydantic-ai).

Everything that talks to a model goes through build_agent(), so tests can
monkeypatch this module (or use Agent.override) to stay fully offline, and a
provider escape hatch stays a one-file change.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput, PromptedOutput

from any_to_bench.schemas.usage import Effort, PhaseUsage, UsageSummary

OutputMode = Literal["native", "prompted", "tool"]

# Google's ThinkingLevel has no xhigh/max — collapse to its ceiling.
_GOOGLE_THINKING_LEVEL: dict[Effort, str] = {
    Effort.minimal: "MINIMAL",
    Effort.low: "LOW",
    Effort.medium: "MEDIUM",
    Effort.high: "HIGH",
    Effort.xhigh: "HIGH",
    Effort.max: "HIGH",
}


def resolve_model_settings(model: str, effort: Effort | str | None) -> dict[str, Any] | None:
    """Provider-specific model settings for a generic effort level (None = provider default)."""
    if effort is None:
        return None
    effort = Effort(effort)
    provider = model.split(":", 1)[0]
    if provider == "openai":
        return {"openai_reasoning_effort": effort.value}
    if provider == "google":
        return {"google_thinking_config": {"thinking_level": _GOOGLE_THINKING_LEVEL[effort]}}
    return None


def build_agent[T: BaseModel](
    model: str,
    output_type: type[T],
    instructions: str,
    output_mode: OutputMode = "native",
    retries: int = 2,
    effort: Effort | str | None = None,
) -> Agent[None, T]:
    """Build an agent that returns a validated instance of output_type.

    model: a pydantic-ai model string, e.g. 'openai:gpt-5.6-terra' or
    'google:gemini-3.7-flash'. output_mode 'native' uses the provider's
    structured-output API; 'prompted'/'tool' are fallbacks for providers or
    schemas that reject native mode. effort tunes reasoning depth; None keeps
    the provider default (OpenAI: medium, Google: dynamic HIGH).
    """
    if output_mode == "native":
        output = NativeOutput(output_type)
    elif output_mode == "prompted":
        output = PromptedOutput(output_type)
    else:
        output = output_type
    return Agent(
        model,
        output_type=output,
        instructions=instructions,
        retries=retries,
        model_settings=resolve_model_settings(model, effort),
    )


class UsageTracker:
    """Accumulates pydantic-ai RunUsage across calls, grouped by phase."""

    def __init__(self) -> None:
        self._phases: dict[str, PhaseUsage] = {}

    def add(self, phase: str, run_usage: Any) -> None:
        """Record one run's usage. Accepts any object shaped like RunUsage."""
        details = getattr(run_usage, "details", None) or {}
        increment = PhaseUsage(
            requests=getattr(run_usage, "requests", 0) or 0,
            input_tokens=getattr(run_usage, "input_tokens", 0) or 0,
            output_tokens=getattr(run_usage, "output_tokens", 0) or 0,
            reasoning_tokens=details.get("reasoning_tokens", 0) + details.get("thoughts_tokens", 0),
            cache_read_tokens=getattr(run_usage, "cache_read_tokens", 0) or 0,
            cache_write_tokens=getattr(run_usage, "cache_write_tokens", 0) or 0,
        )
        current = self._phases.get(phase, PhaseUsage())
        self._phases[phase] = current.merged(increment)

    def summary(self) -> UsageSummary | None:
        """The accumulated usage, or None if no calls were recorded."""
        if not self._phases:
            return None
        total = PhaseUsage()
        for phase_usage in self._phases.values():
            total = total.merged(phase_usage)
        return UsageSummary(total=total, phases=dict(self._phases))
