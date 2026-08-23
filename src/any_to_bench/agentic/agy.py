"""Antigravity CLI subprocess runner."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from any_to_bench.agentic.types import AgenticError, AgentRunResult, AgentUsage, resolve_timeout
from any_to_bench.schemas.usage import Effort

MIN_AGY_VERSION = (1, 1, 17)
PROCESS_EXIT_GRACE_S = 10.0
SETTINGS_DOC_URL = "https://antigravity.google/docs/cli/settings/"
_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")

AGY_EFFORT: dict[Effort, str] = {
    Effort.minimal: "low",
    Effort.low: "low",
    Effort.medium: "medium",
    Effort.high: "high",
    Effort.xhigh: "high",
    Effort.max: "high",
}


def agy_effort(effort: Effort | str | None) -> str | None:
    """Map provider-neutral effort to AGY's low/medium/high range."""
    if effort is None:
        return None
    return AGY_EFFORT[Effort(effort)]


def _settings_path() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli" / "settings.json"


def _validate_safe_settings() -> None:
    """Require a fail-closed global profile without persistent allow rules."""
    path = _settings_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise AgenticError(
            f"agy requires a safe settings profile at {path}; set toolPermission to "
            f"'proceed-in-sandbox'. See {SETTINGS_DOC_URL}"
        ) from e
    except OSError as e:
        raise AgenticError(f"cannot read agy settings at {path}: {e}") from e

    try:
        settings: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AgenticError(f"agy settings at {path} are not valid JSON: {e}") from e
    if not isinstance(settings, dict):
        raise AgenticError(f"agy settings at {path} must contain a JSON object")
    if settings.get("toolPermission") != "proceed-in-sandbox":
        raise AgenticError(
            "agy requires toolPermission='proceed-in-sandbox'; refusing an unattended run. "
            f"See {SETTINGS_DOC_URL}"
        )
    if "allowNonWorkspaceAccess" in settings and settings["allowNonWorkspaceAccess"] is not False:
        raise AgenticError("agy requires allowNonWorkspaceAccess=false")

    permissions = settings.get("permissions", {})
    if not isinstance(permissions, dict):
        raise AgenticError("agy settings permissions must be a JSON object")
    allow = permissions.get("allow", [])
    if not isinstance(allow, list):
        raise AgenticError("agy settings permissions.allow must be a JSON array")
    if allow:
        raise AgenticError(
            "agy settings permissions.allow must be empty for benchmark runs; "
            "persistent grants can escape the intended workspace boundary"
        )


def _validate_version(agy: str, timeout_s: float) -> None:
    try:
        proc = subprocess.run(
            [agy, "--version"],
            capture_output=True,
            text=True,
            timeout=min(timeout_s, 10.0),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as e:
        raise AgenticError("agy --version timed out") from e
    except OSError as e:
        raise AgenticError(f"failed to inspect agy version: {e}") from e

    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
    if proc.returncode != 0:
        raise AgenticError(
            f"agy --version exited with code {proc.returncode}"
            + (f": {output[-2000:]}" if output else "")
        )
    match = _VERSION_RE.search(output)
    if match is None:
        raise AgenticError(f"could not parse agy version from {output!r}")
    version = tuple(int(part) for part in match.groups())
    if version < MIN_AGY_VERSION:
        required = ".".join(str(part) for part in MIN_AGY_VERSION)
        found = ".".join(str(part) for part in version)
        raise AgenticError(f"agy version {required} or newer is required; found {found}")


def _parse_stream(stdout: str) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Parse one strict AGY stream: one init, updates, then one result."""
    events: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(stdout.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            event: Any = json.loads(line)
        except json.JSONDecodeError as e:
            raise AgenticError(f"agy emitted invalid JSON on stdout line {line_no}: {e}") from e
        if not isinstance(event, dict):
            raise AgenticError(f"agy stdout line {line_no} is not a JSON object")
        event_name = event.get("event")
        if event_name not in {"init", "step_update", "result"}:
            raise AgenticError(f"agy emitted unsupported event {event_name!r}")
        payload = event.get(event_name)
        if not isinstance(payload, dict):
            raise AgenticError(f"agy {event_name!r} event has no object payload")
        events.append(event)

    init_events = [event["init"] for event in events if event["event"] == "init"]
    result_events = [event["result"] for event in events if event["event"] == "result"]
    if len(init_events) != 1:
        raise AgenticError(f"agy emitted {len(init_events)} init events; expected exactly one")
    if len(result_events) != 1:
        raise AgenticError(f"agy emitted {len(result_events)} result events; expected exactly one")
    if events[0]["event"] != "init" or events[-1]["event"] != "result":
        raise AgenticError("agy stream must begin with init and end with result")
    return events, init_events[0], result_events[0]


def _conversation_id(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise AgenticError(f"agy {where} has no valid conversation_id")
    try:
        uuid.UUID(value)
    except ValueError as e:
        raise AgenticError(f"agy {where} has invalid conversation_id {value!r}") from e
    return value


def _nonnegative_int(payload: dict[str, Any], key: str, where: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AgenticError(f"agy {where}.{key} must be a non-negative integer")
    return value


def _summarize_usage(result: dict[str, Any]) -> AgentUsage:
    requests = _nonnegative_int(result, "num_turns", "result")
    if requests == 0:
        raise AgenticError("agy result.num_turns must be greater than zero")
    raw = result.get("usage")
    if not isinstance(raw, dict):
        raise AgenticError("agy result.usage must be a JSON object")
    input_tokens = _nonnegative_int(raw, "input_tokens", "result.usage")
    output_tokens = _nonnegative_int(raw, "output_tokens", "result.usage")
    thinking_tokens = _nonnegative_int(raw, "thinking_tokens", "result.usage")
    cache_read_tokens = _nonnegative_int(raw, "cache_read_tokens", "result.usage")
    _nonnegative_int(raw, "total_tokens", "result.usage")
    details = {"reasoning_tokens": thinking_tokens} if thinking_tokens else {}
    return AgentUsage(
        requests=requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=0,
        details=details,
    )


def _stderr_suffix(stderr: str) -> str:
    tail = stderr[-2000:].strip()
    return f"\nstderr: {tail}" if tail else ""


def _failure_detail(stdout: str) -> str:
    """Extract the terminal AGY error without treating failed output as success."""
    for line in reversed(stdout.splitlines()):
        try:
            event: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("event") != "result":
            continue
        result = event.get("result")
        if isinstance(result, dict):
            detail = result.get("error") or result.get("response") or result.get("status")
            if detail:
                return str(detail)[:2000]
    return stdout[-2000:].strip()


def run_agy(
    workspace: Path,
    prompt: str,
    cli_model: str,
    effort: Effort | str | None = None,
    resume_session_id: str | None = None,
    timeout_s: float | None = None,
) -> AgentRunResult:
    """Run one sandboxed AGY headless turn over the workspace."""
    agy = shutil.which("agy")
    if agy is None:
        raise AgenticError(
            "agy CLI not found on PATH; install and authenticate Antigravity CLI. "
            "See https://antigravity.google/docs/cli/install/"
        )
    timeout_s = resolve_timeout(
        timeout_s, "ANY_TO_BENCH_AGY_TIMEOUT", "ANY_TO_BENCH_AGENTIC_TIMEOUT"
    )
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise AgenticError("agy timeout must be greater than zero")
    if resume_session_id is not None:
        _conversation_id(resume_session_id, "resume request")
    _validate_safe_settings()
    _validate_version(agy, timeout_s)

    print_timeout_s = max(1, int(timeout_s - PROCESS_EXIT_GRACE_S))
    argv = [
        agy,
        "-p",
        prompt,
        "--model",
        cli_model,
        "--output-format",
        "stream-json",
        "--mode",
        "accept-edits",
        "--sandbox",
        "--disable-slash-commands",
        "--print-timeout",
        f"{print_timeout_s}s",
    ]
    if resume_session_id is not None:
        argv += ["--conversation", resume_session_id]
    level = agy_effort(effort)
    if level is not None:
        argv += ["--effort", level]

    try:
        proc = subprocess.run(
            argv,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as e:
        raise AgenticError(f"agy timed out after {timeout_s:.0f}s") from e
    except OSError as e:
        raise AgenticError(f"failed to run agy: {e}") from e

    if proc.returncode != 0:
        detail = _failure_detail(proc.stdout)
        raise AgenticError(
            f"agy exited with code {proc.returncode}"
            + (f": {detail}" if detail else "")
            + _stderr_suffix(proc.stderr)
        )
    try:
        events, init, result = _parse_stream(proc.stdout)
        init_session_id = _conversation_id(
            events[0].get("conversation_id"),
            "init event",
        )
        result_session_id = _conversation_id(result.get("conversation_id"), "result")
        if init_session_id != result_session_id:
            raise AgenticError(
                f"agy conversation changed within one turn: {init_session_id!r} -> "
                f"{result_session_id!r}"
            )
        if resume_session_id is not None and result_session_id != resume_session_id:
            raise AgenticError(
                f"agy resumed the wrong conversation: expected {resume_session_id!r}, "
                f"got {result_session_id!r}"
            )
        for event in events:
            if event["event"] != "step_update":
                continue
            step_session_id = _conversation_id(
                event["step_update"].get("conversation_id"), "step_update"
            )
            if step_session_id != result_session_id:
                raise AgenticError("agy step_update belongs to a different conversation")
        if init.get("permission_mode") != "proceed-in-sandbox":
            raise AgenticError(
                "agy effective permission mode is not 'proceed-in-sandbox'; refusing result"
            )
        init_cwd = init.get("cwd")
        if not isinstance(init_cwd, str) or Path(init_cwd).resolve() != workspace.resolve():
            raise AgenticError(f"agy initialized in unexpected cwd {init_cwd!r}")
        if init.get("model") != cli_model:
            raise AgenticError(
                f"agy initialized unexpected model {init.get('model')!r}; expected {cli_model!r}"
            )
        if result.get("status") != "SUCCESS":
            detail = result.get("error") or result.get("response")
            raise AgenticError(
                f"agy turn failed ({result.get('status') or 'unknown status'})"
                + (f": {detail}" if detail else "")
            )
        final_message = result.get("response")
        if not isinstance(final_message, str):
            raise AgenticError("agy result.response must be a string")
        usage = _summarize_usage(result)
    except AgenticError as e:
        raise AgenticError(f"{e}" + _stderr_suffix(proc.stderr)) from e

    return AgentRunResult(
        session_id=result_session_id,
        final_message=final_message.strip(),
        usage=usage,
        events=events,
    )
