"""Types shared by every agentic CLI backend."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from any_to_bench.schemas.usage import Effort

DEFAULT_TIMEOUT_S = 3600.0


class AgenticError(RuntimeError):
    """An agentic CLI is missing, failed, or timed out."""


def resolve_timeout(explicit: float | None, *env_names: str) -> float:
    """An explicit timeout, else the first env var that parses, else the default.

    Backends pass their own variable first and the shared one second, so a
    per-backend override wins without losing the fleet-wide knob.
    """
    if explicit is not None:
        return explicit
    for name in env_names:
        try:
            return float(os.environ[name])
        except (KeyError, ValueError):
            continue
    return DEFAULT_TIMEOUT_S


@dataclass
class AgentUsage:
    """Duck-types pydantic-ai RunUsage so UsageTracker.add() accepts it."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    details: dict[str, int] = field(default_factory=dict)


@dataclass
class AgentRunResult:
    session_id: str | None
    final_message: str
    usage: AgentUsage
    events: list[dict[str, Any]]


@dataclass
class FixLoopOutcome:
    problems: list[str]  # remaining after the last round; empty = success
    round_counts: list[int]  # problems found after each round
    rounds_run: int
    final_message: str


@dataclass(frozen=True)
class AgenticBackend:
    """One agentic CLI, selected by a model-string prefix.

    runner_name is resolved as a module global in ``agentic.runner`` at call
    time rather than bound here: the whole offline test suite works by
    monkeypatching that global, and an early-bound reference would escape it.
    """

    name: str
    prefix: str
    runner_name: str
    binary: str
    install_hint: str
    effort_map: Mapping[Effort, str]
    usage_accounting: Literal["per_turn", "cumulative_session"]


@dataclass(frozen=True)
class AgenticModel:
    """A parsed agentic model string: which backend, and the CLI's own model name."""

    backend: AgenticBackend
    cli_model: str
