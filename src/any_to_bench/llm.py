"""Single construction point for LLM agents (pydantic-ai).

Everything that talks to a model goes through build_agent(), so tests can
monkeypatch this module (or use Agent.override) to stay fully offline, and a
provider escape hatch stays a one-file change.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput, PromptedOutput

from any_to_bench.schemas.usage import Effort, PhaseUsage, UsageSummary

OutputMode = Literal["native", "prompted", "tool"]

# pydantic-ai's provider name for what Google's docs still call Vertex AI. Same
# models as `google:`, reached with Google Cloud credentials instead of an API key.
GOOGLE_CLOUD = "google-cloud"

# Both Google providers take the same thinking config; Google's ThinkingLevel has
# no xhigh/max, so those collapse to its ceiling.
_GOOGLE_PROVIDERS = frozenset({"google", GOOGLE_CLOUD})
_GOOGLE_THINKING_LEVEL: dict[Effort, str] = {
    Effort.minimal: "MINIMAL",
    Effort.low: "LOW",
    Effort.medium: "MEDIUM",
    Effort.high: "HIGH",
    Effort.xhigh: "HIGH",
    Effort.max: "HIGH",
}


class ModelConfigError(RuntimeError):
    """A model string the environment cannot satisfy."""


def resolve_model_settings(model: str, effort: Effort | str | None) -> dict[str, Any] | None:
    """Provider-specific model settings for a generic effort level (None = provider default)."""
    if effort is None:
        return None
    effort = Effort(effort)
    provider = model.split(":", 1)[0]
    if provider == "openai":
        return {"openai_reasoning_effort": effort.value}
    if provider in _GOOGLE_PROVIDERS:
        return {"google_thinking_config": {"thinking_level": _GOOGLE_THINKING_LEVEL[effort]}}
    return None


def _service_account_project(path: str | None) -> str | None:
    """The project a service-account JSON names, or None if it names none.

    A service-account key file already carries `project_id`, so pointing
    GOOGLE_APPLICATION_CREDENTIALS at one is enough — GOOGLE_CLOUD_PROJECT is
    only needed to bill a different project than the key belongs to.
    """
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    project = data.get("project_id") if isinstance(data, dict) else None
    return project if isinstance(project, str) and project else None


# pydantic-ai defaults to us-central1, which carries the most models by count.
# That is the wrong axis for a benchmark harness: on a real project every current
# Gemini — 3.5, 3.6 and 3.7 flash — answered 404 there and resolved on `global`,
# where new models land first. GOOGLE_CLOUD_LOCATION still overrides, and a wrong
# region fails loudly with a 404 naming it.
DEFAULT_GOOGLE_CLOUD_LOCATION = "global"


def _google_cloud_provider(project: str, location: str) -> Any:
    """Seam: constructing this resolves Application Default Credentials."""
    from pydantic_ai.providers.google_cloud import GoogleCloudProvider

    return GoogleCloudProvider(project=project, location=location)


def resolve_model(model: str) -> Any:
    """A pydantic-ai model string, or a Model instance where inference is unsafe.

    `google-cloud:` is built here rather than left to pydantic-ai's provider
    inference, which falls back to API-key auth: with GOOGLE_API_KEY set — which
    it usually is, since that is what `google:` uses — a `google-cloud:` model
    would quietly run on Vertex AI Express Mode instead of the Google Cloud
    credentials the caller asked for, and nothing in the output would say so.
    Passing an explicit project shuts that path off.
    """
    provider, _, model_name = model.partition(":")
    if provider != GOOGLE_CLOUD or not model_name:
        return model

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or _service_account_project(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )
    if not project:
        raise ModelConfigError(
            f"{model} needs a Google Cloud project: point GOOGLE_APPLICATION_CREDENTIALS at a "
            "service-account JSON key (it names its own project), or set GOOGLE_CLOUD_PROJECT"
        )

    location = os.getenv("GOOGLE_CLOUD_LOCATION") or DEFAULT_GOOGLE_CLOUD_LOCATION

    from pydantic_ai.models.google import GoogleModel

    return GoogleModel(model_name, provider=_google_cloud_provider(project, location))


def build_agent[T: BaseModel](
    model: str,
    output_type: type[T],
    instructions: str,
    output_mode: OutputMode = "native",
    retries: int = 2,
    effort: Effort | str | None = None,
) -> Agent[None, T]:
    """Build an agent that returns a validated instance of output_type.

    model: a pydantic-ai model string, e.g. 'openai:gpt-5.6-terra',
    'google:gemini-3.7-flash', or 'google-cloud:gemini-3.7-flash' for the same
    Google models over Vertex AI. output_mode 'native' uses the provider's
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
        resolve_model(model),
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
