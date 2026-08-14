"""Claude Code CLI subprocess runner.

Mirrors run_codex's signature exactly so run_fix_loop can drive either backend
and the offline test doubles stand in for both unchanged.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from any_to_bench.agentic.types import AgenticError, AgentRunResult, AgentUsage, resolve_timeout
from any_to_bench.schemas.usage import Effort

CONTRACT_FILE = "AGENTS.md"

# Claude Code's --effort has no `minimal` — collapse to its floor.
CLAUDE_EFFORT: dict[Effort, str] = {
    Effort.minimal: "low",
    Effort.low: "low",
    Effort.medium: "medium",
    Effort.high: "high",
    Effort.xhigh: "xhigh",
    Effort.max: "max",
}

# Reproduces the Codex path's posture: writes confined to the workspace, no network.
# Verified against claude 2.1.232 — a shell `curl` and a write to /tmp are both denied,
# while reads outside the workspace are NOT restricted (same as codex workspace-write;
# see the trust note in docs/agentic-mode.md).
#
# `acceptEdits` auto-approves file edits but NOT Bash; Bash is auto-approved only by
# autoAllowBashIfSandboxed, which fires only while the sandbox is actually active.
# So if the sandbox is unavailable the agent loses its shell and the run fails loudly
# instead of silently continuing unconfined. failIfUnavailable makes that explicit,
# which matters because `-p` silently ignores settings that fail validation.
HERMETIC_SETTINGS: dict[str, Any] = {
    "sandbox": {
        "enabled": True,
        "failIfUnavailable": True,
        "autoAllowBashIfSandboxed": True,
        "filesystem": {"disabled": False},
        "network": {"allowedDomains": []},
    },
    "permissions": {"defaultMode": "acceptEdits"},
}


def claude_effort(effort: Effort | str | None) -> str | None:
    """Map the generic effort level to Claude Code's --effort (None = CLI default)."""
    if effort is None:
        return None
    return CLAUDE_EFFORT[Effort(effort)]


def summarize_result(payload: dict[str, Any]) -> AgentUsage:
    """Extract token usage from a --output-format json result object.

    Scans tolerantly (missing keys count as zero) so minor CLI upgrades don't
    zero out accounting, mirroring the Codex event scanner.
    """
    raw = payload.get("usage")
    usage = AgentUsage(requests=int(payload.get("num_turns") or 1))
    if isinstance(raw, dict):
        usage.input_tokens = int(raw.get("input_tokens") or 0)
        usage.output_tokens = int(raw.get("output_tokens") or 0)
        usage.cache_read_tokens = int(raw.get("cache_read_input_tokens") or 0)
        usage.cache_write_tokens = int(raw.get("cache_creation_input_tokens") or 0)
    # Anthropic reports no separate reasoning-token count, so details stays empty
    # and UsageTracker correctly records zero rather than guessing.
    return usage


def _parse_result(stdout: str) -> dict[str, Any]:
    """The single result object, whether stdout is one document or a JSON stream."""
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("type") == "result":
            return candidate
    raise AgenticError(f"claude produced no parseable result object; stdout: {stdout[:500]!r}")


def run_claude(
    workspace: Path,
    prompt: str,
    cli_model: str,
    effort: Effort | str | None = None,
    resume_session_id: str | None = None,
    timeout_s: float | None = None,
) -> AgentRunResult:
    """Run one Claude Code turn (or a resumed turn) over the workspace.

    The workspace contract (AGENTS.md) is passed as --append-system-prompt rather
    than relied upon for auto-discovery, because --safe-mode turns discovery off.
    The file stays on disk, so prompts that tell the agent to follow AGENTS.md
    remain literally true.
    """
    claude = shutil.which("claude")
    if claude is None:
        raise AgenticError(
            "claude CLI not found on PATH; install it "
            "(npm install -g @anthropic-ai/claude-code) or use a direct-LLM model "
            "string such as 'openai:gpt-5.6-sol'"
        )
    timeout_s = resolve_timeout(
        timeout_s, "ANY_TO_BENCH_CLAUDE_TIMEOUT", "ANY_TO_BENCH_AGENTIC_TIMEOUT"
    )

    contract_path = workspace / CONTRACT_FILE
    contract = contract_path.read_text(encoding="utf-8") if contract_path.exists() else ""

    # Unlike codex, the session id is ours to choose, so there is nothing to scrape
    # back out of the output and a resume can never target the wrong session.
    session_id = resume_session_id or str(uuid.uuid4())

    argv = [
        claude,
        "-p",
        "--model",
        cli_model,
        "--output-format",
        "json",
        "--safe-mode",  # no CLAUDE.md/skills/plugins/hooks/MCP leaking into a benchmark
        "--setting-sources",
        "",  # ignore user/project/local settings.json
        "--settings",
        json.dumps(HERMETIC_SETTINGS),
        "--permission-mode",
        "acceptEdits",
        "--add-dir",
        str(workspace),
    ]
    if contract:
        argv += ["--append-system-prompt", contract]
    argv += ["--resume", session_id] if resume_session_id else ["--session-id", session_id]
    level = claude_effort(effort)
    if level is not None:
        argv += ["--effort", level]
    argv.append(prompt)

    try:
        proc = subprocess.run(
            argv,
            cwd=workspace,  # constant across rounds: sessions are keyed by project dir
            capture_output=True,
            text=True,
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as e:
        raise AgenticError(f"claude timed out after {timeout_s:.0f}s") from e
    except OSError as e:
        raise AgenticError(f"failed to run claude: {e}") from e

    if proc.returncode != 0:
        stderr_tail = proc.stderr[-2000:].strip()
        raise AgenticError(
            f"claude exited with code {proc.returncode}"
            + (f"\nstderr: {stderr_tail}" if stderr_tail else "")
        )

    payload = _parse_result(proc.stdout)
    final_message = str(payload.get("result") or "").strip()
    if payload.get("is_error") or payload.get("subtype") not in (None, "success"):
        raise AgenticError(
            f"claude turn failed ({payload.get('subtype') or 'error'})"
            + (f": {final_message}" if final_message else "")
        )
    return AgentRunResult(
        session_id=session_id,
        final_message=final_message,
        usage=summarize_result(payload),
        events=[payload],
    )
