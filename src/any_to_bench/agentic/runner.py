"""Agentic backend dispatch, fix loop, and the Codex CLI subprocess runner.

Everything that spawns an agentic CLI goes through a runner function that lives
as a module global *here* (run_codex, run_claude, run_agy), so tests can monkeypatch this
module to stay fully offline, mirroring how llm.build_agent is the single seam
for direct LLM calls. run_codex stays in this module rather than moving to a
sibling for symmetry with claude.py, because the Codex tests patch this module's
`shutil` and `subprocess` globals too.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

# These runners are imported to exist as module globals here, not to be called by
# name: _resolve_runner looks them up through globals(), which is also what lets
# tests swap them out. Hence the noqa — they are used, just not lexically.
from any_to_bench.agentic.agy import AGY_EFFORT, run_agy  # noqa: F401
from any_to_bench.agentic.claude import CLAUDE_EFFORT, run_claude  # noqa: F401
from any_to_bench.agentic.types import (
    AgenticBackend,
    AgenticError,
    AgenticModel,
    AgentRunResult,
    AgentUsage,
    FixLoopOutcome,
    resolve_timeout,
)
from any_to_bench.schemas.usage import Effort

MAX_FIX_ROUNDS = 3  # one initial run + up to two fix rounds

# Codex has no dedicated max level — collapse to its ceiling.
_CODEX_EFFORT: dict[Effort, str] = {
    Effort.minimal: "minimal",
    Effort.low: "low",
    Effort.medium: "medium",
    Effort.high: "high",
    Effort.xhigh: "xhigh",
    Effort.max: "xhigh",
}

CODEX = AgenticBackend(
    name="codex",
    prefix="codex:",
    runner_name="run_codex",
    binary="codex",
    install_hint="npm install -g @openai/codex",
    effort_map=_CODEX_EFFORT,
    usage_accounting="per_turn",
)
CLAUDE = AgenticBackend(
    name="claude",
    prefix="claude:",
    runner_name="run_claude",
    binary="claude",
    install_hint="npm install -g @anthropic-ai/claude-code",
    effort_map=CLAUDE_EFFORT,
    usage_accounting="per_turn",
)
AGY = AgenticBackend(
    name="agy",
    prefix="agy:",
    runner_name="run_agy",
    binary="agy",
    install_hint="https://antigravity.google/docs/cli/install/",
    effort_map=AGY_EFFORT,
    usage_accounting="cumulative_session",
)
BACKENDS: dict[str, AgenticBackend] = {b.prefix: b for b in (CODEX, CLAUDE, AGY)}


def parse_agentic(model: str) -> AgenticModel | None:
    """Parse a registered CLI prefix; return None for direct-LLM model strings."""
    for prefix, backend in BACKENDS.items():
        if model.startswith(prefix) and not model[len(prefix) :].strip():
            raise ValueError(f"agentic model {prefix!r} requires a non-empty CLI model name")
        if model.startswith(prefix):
            return AgenticModel(backend=backend, cli_model=model[len(prefix) :])
    return None


def parse_agentic_model(model: str) -> str | None:
    """The CLI-side model name for any agentic prefix; None for direct-LLM strings."""
    parsed = parse_agentic(model)
    return parsed.cli_model if parsed is not None else None


def _resolve_runner(backend: AgenticBackend) -> Callable[..., AgentRunResult]:
    """Look the backend's runner up as a module global, deliberately late.

    Binding the function object at registry-construction time would escape
    `monkeypatch.setattr(<this module>, "run_codex", fake)`, which is how the
    entire suite stays offline.
    """
    return globals()[backend.runner_name]


def codex_effort(effort: Effort | str | None) -> str | None:
    """Map the generic effort level to codex's model_reasoning_effort."""
    if effort is None:
        return None
    return CODEX.effort_map[Effort(effort)]


def summarize_events(events: list[dict[str, Any]]) -> tuple[str | None, AgentUsage]:
    """Extract the session id and total token usage from a --json event stream.

    Scans tolerantly (any event bearing a thread id / usage object counts) so
    minor codex CLI upgrades don't zero out accounting.
    """
    session_id: str | None = None
    usage = AgentUsage()
    for event in events:
        if session_id is None:
            candidate = event.get("thread_id") or (event.get("thread") or {}).get("id")
            if isinstance(candidate, str) and candidate:
                session_id = candidate
        u = event.get("usage") or (event.get("turn") or {}).get("usage")
        if isinstance(u, dict):
            usage.requests += 1
            usage.input_tokens += int(u.get("input_tokens") or 0)
            usage.output_tokens += int(u.get("output_tokens") or 0)
            usage.cache_read_tokens += int(u.get("cached_input_tokens") or 0)
            reasoning = int(u.get("reasoning_output_tokens") or 0)
            if reasoning:
                usage.details["reasoning_tokens"] = (
                    usage.details.get("reasoning_tokens", 0) + reasoning
                )
    return session_id, usage


def _parse_jsonl(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _private_codex_home(workspace: Path) -> Path:
    """A throwaway CODEX_HOME (and HOME) for one solve, holding only credentials.

    The operator's own machine would otherwise sit inside the exam room. A codex
    session loads `~/.codex/AGENTS.md`, `~/.codex/config.toml` and the skills
    under `~/.agents/skills` — observed, in an audited run, as the model reading
    a personal skill file and searching the disk for its notes. That makes a
    score depend on whose laptop produced it.

    Keyed on the run directory rather than the invocation: `codex exec resume`
    finds a session by looking under CODEX_HOME, and the fix loop resumes.
    """
    home = workspace.parent / "codex-home"
    if home.exists():
        return home
    home.mkdir(parents=True)
    source = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    auth = source / "auth.json"
    if auth.is_file():
        shutil.copy2(auth, home / "auth.json")  # env-var credentials need no file
    return home


# Three settings, because closing any two of them leaves the third open. Verified
# by probe, not by reading docs: with only the sandbox flag the model reaches the
# network through its built-in search tool, and with only those two it asks for
# escalated permissions and — under an `on-request` approval policy — gets them.
#
# The stake is the whole benchmark. Every paper in these corpora has its official
# answer key published online, so a solver that can search is sitting an open-book
# exam against the marking scheme.
HERMETIC_CONFIG = [
    # No network from the shell: curl and friends fail to resolve.
    "-c",
    "sandbox_workspace_write.network_access=false",
    # No server-side search tool, which the sandbox cannot reach.
    "-c",
    'web_search="disabled"',
    # No escalation out of either: the operator's own config may auto-approve.
    "-c",
    'approval_policy="never"',
]


def run_codex(
    workspace: Path,
    prompt: str,
    cli_model: str,
    effort: Effort | str | None = None,
    resume_session_id: str | None = None,
    timeout_s: float | None = None,
) -> AgentRunResult:
    """Run one codex exec (or exec resume) turn over the workspace.

    The initial run pins the working root and sandbox (-C, -s workspace-write);
    `codex exec resume` accepts neither flag and inherits both from the session
    record, with session lookup filtered by cwd — hence cwd=workspace always.
    """
    codex = shutil.which("codex")
    if codex is None:
        raise AgenticError(
            "codex CLI not found on PATH; install it (npm install -g @openai/codex) "
            "or use a direct-LLM model string such as 'openai:gpt-5.6-sol'"
        )
    timeout_s = resolve_timeout(
        timeout_s, "ANY_TO_BENCH_CODEX_TIMEOUT", "ANY_TO_BENCH_AGENTIC_TIMEOUT"
    )

    control = workspace.parent / "control"
    control.mkdir(parents=True, exist_ok=True)
    last_message = control / "last_message.txt"
    last_message.unlink(missing_ok=True)

    argv = [codex, "exec"]
    if resume_session_id is not None:
        argv += ["resume", resume_session_id]
    argv += ["--json", "--color", "never", "--skip-git-repo-check", "-m", cli_model]
    if resume_session_id is None:
        argv += ["-C", str(workspace), "-s", "workspace-write"]
    argv += HERMETIC_CONFIG
    level = codex_effort(effort)
    if level is not None:
        argv += ["-c", f"model_reasoning_effort={level}"]
    argv += ["-o", str(last_message), "-"]  # "-": read the prompt from stdin

    home = _private_codex_home(workspace)
    env = {**os.environ, "HOME": str(home), "CODEX_HOME": str(home)}

    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise AgenticError(f"codex timed out after {timeout_s:.0f}s") from e
    except OSError as e:
        raise AgenticError(f"failed to run codex: {e}") from e

    events = _parse_jsonl(proc.stdout)
    session_id, usage = summarize_events(events)

    failures = [e for e in events if e.get("type") in ("turn.failed", "error")]
    if proc.returncode != 0 or any(e.get("type") == "turn.failed" for e in failures):
        detail = "; ".join(
            str(e.get("message") or (e.get("error") or {}).get("message") or e)
            for e in failures[:3]
        )
        stderr_tail = proc.stderr[-2000:].strip()
        raise AgenticError(
            f"codex exited with code {proc.returncode}"
            + (f": {detail}" if detail else "")
            + (f"\nstderr: {stderr_tail}" if stderr_tail else "")
        )

    final_message = (
        last_message.read_text(encoding="utf-8").strip() if last_message.exists() else ""
    )
    return AgentRunResult(
        session_id=session_id, final_message=final_message, usage=usage, events=events
    )


def _usage_delta(current: AgentUsage, previous: AgentUsage) -> AgentUsage:
    """Return a cumulative-session increment, rejecting protocol regressions."""
    values: dict[str, int] = {}
    for field_name in (
        "requests",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        current_value = getattr(current, field_name)
        previous_value = getattr(previous, field_name)
        if current_value < previous_value:
            raise AgenticError(
                f"cumulative agent usage regressed for {field_name}: "
                f"{current_value} < {previous_value}"
            )
        values[field_name] = current_value - previous_value

    details: dict[str, int] = {}
    for key in current.details.keys() | previous.details.keys():
        current_value = current.details.get(key, 0)
        previous_value = previous.details.get(key, 0)
        if current_value < previous_value:
            raise AgenticError(
                f"cumulative agent usage regressed for details.{key}: "
                f"{current_value} < {previous_value}"
            )
        delta = current_value - previous_value
        if delta:
            details[key] = delta
    return AgentUsage(**values, details=details)


def run_fix_loop(
    workspace: Path,
    task_prompt: str,
    cli_model: str,
    oracle: Callable[[], list[str]],
    on_usage: Callable[[AgentUsage], None],
    effort: Effort | str | None = None,
    max_rounds: int = MAX_FIX_ROUNDS,
    *,
    backend: AgenticBackend = CODEX,
) -> FixLoopOutcome:
    """Run the agent, validate with oracle(), and feed problems back until clean.

    Round 1 sends task_prompt; later rounds resume the session with the problem
    list. If a resume invocation fails, the session is abandoned and retried
    once as a fresh run carrying the full context.

    The two `run(...)` calls below must keep their exact argument lists: the
    offline test doubles mirror them positionally, so a per-call kwarg here
    would break every agentic test at once. Backend-specific behaviour belongs
    inside the runner, not in this call.
    """
    from any_to_bench.agentic.prompts import format_problems

    run = _resolve_runner(backend)
    session_id: str | None = None
    cumulative_usage: AgentUsage | None = None
    problems: list[str] = []
    round_counts: list[int] = []
    final_message = ""
    rounds_run = 0
    for round_no in range(1, max_rounds + 1):
        rounds_run = round_no
        prompt = task_prompt if round_no == 1 else format_problems(problems)
        expected_session_id = session_id
        try:
            result = run(workspace, prompt, cli_model, effort=effort, resume_session_id=session_id)
        except AgenticError:
            if session_id is None:
                raise
            session_id = None  # dead session; retry statelessly with full context
            cumulative_usage = None
            expected_session_id = None
            prompt = f"{task_prompt}\n\n{format_problems(problems)}"
            result = run(workspace, prompt, cli_model, effort=effort)
        if expected_session_id is not None and result.session_id != expected_session_id:
            raise AgenticError(
                f"agentic session changed during resume: expected {expected_session_id!r}, "
                f"got {result.session_id!r}"
            )
        if backend.usage_accounting == "cumulative_session":
            if result.session_id is None:
                raise AgenticError(f"{backend.name} returned no session id for cumulative usage")
            increment = (
                result.usage
                if cumulative_usage is None
                else _usage_delta(result.usage, cumulative_usage)
            )
            on_usage(increment)
            cumulative_usage = result.usage
        else:
            on_usage(result.usage)
        session_id = result.session_id
        final_message = result.final_message
        problems = oracle()
        round_counts.append(len(problems))
        if not problems:
            break
    return FixLoopOutcome(
        problems=problems,
        round_counts=round_counts,
        rounds_run=rounds_run,
        final_message=final_message,
    )
