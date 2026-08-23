"""Offline Antigravity backend tests: protocol, safety, accounting, and routing."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

import any_to_bench.agentic.agy as agy_module
import any_to_bench.agentic.runner as runner_module
from any_to_bench.agentic.agy import agy_effort, run_agy
from any_to_bench.agentic.runner import AGY, CLAUDE, CODEX, parse_agentic, run_fix_loop
from any_to_bench.agentic.types import AgenticError, AgentRunResult, AgentUsage
from any_to_bench.grade.aggregate import run_grade
from any_to_bench.ingest.pipeline import run_ingest
from any_to_bench.schemas.usage import Effort
from any_to_bench.solve.runner import run_solve
from tests.conftest import FakeAgenticRun, perfect_sheet
from tests.test_agentic_ingest import _source, _write_bundle
from tests.test_agentic_judge import VALID_VERDICTS, write_verdicts
from tests.test_agentic_solve import write_valid

SESSION_ID = "055a398f-db14-4c5f-abbb-1bf03f8120a7"
OTHER_SESSION_ID = "155a398f-db14-4c5f-abbb-1bf03f8120a7"


def _safe_settings(tmp_path, payload=None):
    path = tmp_path / "settings.json"
    if payload is None:
        payload = {
            "toolPermission": "proceed-in-sandbox",
            "allowNonWorkspaceAccess": False,
            "permissions": {"allow": []},
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _stream(
    workspace,
    *,
    session_id=SESSION_ID,
    model="gemini-test",
    permission_mode="proceed-in-sandbox",
    status="SUCCESS",
    response="wrote the file",
    usage=None,
):
    if usage is None:
        usage = {
            "input_tokens": 120,
            "output_tokens": 34,
            "thinking_tokens": 8,
            "cache_read_tokens": 90,
            "total_tokens": 162,
        }
    events = [
        {
            "event": "init",
            "conversation_id": session_id,
            "init": {
                "cwd": str(workspace),
                "tools": ["run_command", "write_to_file"],
                "permission_mode": permission_mode,
                "model": model,
            },
        },
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": session_id,
                "step_index": 0,
                "state": "DONE",
                "step_type": "user_input",
            },
        },
        {
            "event": "result",
            "result": {
                "conversation_id": session_id,
                "status": status,
                "response": response,
                "num_turns": 2,
                "usage": usage,
            },
        },
    ]
    return "\n".join(json.dumps(event) for event in events)


def _patch_runtime(
    monkeypatch,
    tmp_path,
    calls,
    *,
    stdout=None,
    stderr="",
    returncode=0,
    version="1.1.19",
):
    settings_path = _safe_settings(tmp_path)
    monkeypatch.setattr(agy_module, "_settings_path", lambda: settings_path)
    monkeypatch.setattr(agy_module.shutil, "which", lambda _: "/usr/bin/agy")

    def fake_run(argv, **kwargs):
        if argv == ["/usr/bin/agy", "--version"]:
            return SimpleNamespace(stdout=version, stderr="", returncode=0)
        calls.append({"argv": argv, **kwargs})
        return SimpleNamespace(stdout=stdout or "", stderr=stderr, returncode=returncode)

    monkeypatch.setattr(agy_module.subprocess, "run", fake_run)


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_parse_agentic_recognizes_all_three_backends():
    assert parse_agentic("codex:gpt-test").backend is CODEX
    assert parse_agentic("claude:opus").backend is CLAUDE
    parsed = parse_agentic("agy:gemini-3.7-flash-high")
    assert parsed.backend is AGY
    assert parsed.cli_model == "gemini-3.7-flash-high"
    with pytest.raises(ValueError, match="non-empty"):
        parse_agentic("agy:")
    with pytest.raises(ValueError, match="non-empty"):
        parse_agentic("agy:   ")
    assert parse_agentic("google:gemini-3.7-flash") is None
    assert parse_agentic("anthropic:claude-opus") is None


@pytest.mark.parametrize(
    ("effort", "expected"),
    [
        (Effort.minimal, "low"),
        (Effort.low, "low"),
        (Effort.medium, "medium"),
        (Effort.high, "high"),
        (Effort.xhigh, "high"),
        (Effort.max, "high"),
        (None, None),
    ],
)
def test_agy_effort_mapping(effort, expected):
    assert agy_effort(effort) == expected


def test_run_agy_initial_argv_and_usage(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    calls = []
    _patch_runtime(
        monkeypatch,
        tmp_path,
        calls,
        stdout=_stream(workspace),
    )

    result = run_agy(workspace, "do the task", "gemini-test", effort="max", timeout_s=100)

    argv = calls[0]["argv"]
    assert argv[:3] == ["/usr/bin/agy", "-p", "do the task"]
    assert _flag(argv, "--model") == "gemini-test"
    assert _flag(argv, "--output-format") == "stream-json"
    assert _flag(argv, "--mode") == "accept-edits"
    assert _flag(argv, "--effort") == "high"
    assert _flag(argv, "--print-timeout") == "90s"
    assert "--sandbox" in argv
    assert "--disable-slash-commands" in argv
    assert "--conversation" not in argv
    assert "--continue" not in argv
    assert "--dangerously-skip-permissions" not in argv
    assert calls[0]["cwd"] == workspace
    assert calls[0]["timeout"] == 100
    assert calls[0]["stdin"] is subprocess.DEVNULL
    assert result.session_id == SESSION_ID
    assert result.final_message == "wrote the file"
    assert result.usage == AgentUsage(
        requests=2,
        input_tokens=120,
        output_tokens=34,
        cache_read_tokens=90,
        cache_write_tokens=0,
        details={"reasoning_tokens": 8},
    )
    assert [event["event"] for event in result.events] == ["init", "step_update", "result"]


def test_run_agy_resumes_exact_conversation(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    calls = []
    _patch_runtime(monkeypatch, tmp_path, calls, stdout=_stream(workspace))

    result = run_agy(
        workspace,
        "fix it",
        "gemini-test",
        resume_session_id=SESSION_ID,
    )

    assert _flag(calls[0]["argv"], "--conversation") == SESSION_ID
    assert "--continue" not in calls[0]["argv"]
    assert result.session_id == SESSION_ID


def test_run_agy_uses_backend_timeout_env(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    calls = []
    _patch_runtime(monkeypatch, tmp_path, calls, stdout=_stream(workspace))
    monkeypatch.setenv("ANY_TO_BENCH_AGENTIC_TIMEOUT", "80")
    monkeypatch.setenv("ANY_TO_BENCH_AGY_TIMEOUT", "45")

    run_agy(workspace, "task", "gemini-test")

    assert calls[0]["timeout"] == 45
    assert _flag(calls[0]["argv"], "--print-timeout") == "35s"


def test_run_agy_missing_binary_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(agy_module.shutil, "which", lambda _: None)
    with pytest.raises(AgenticError, match="not found"):
        run_agy(tmp_path, "task", "gemini-test")


@pytest.mark.parametrize("version", ["1.1.16", "not-a-version"])
def test_run_agy_rejects_unsupported_version(tmp_path, monkeypatch, version):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _patch_runtime(monkeypatch, tmp_path, [], version=version)
    with pytest.raises(AgenticError, match="version"):
        run_agy(workspace, "task", "gemini-test")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "toolPermission"),
        ({"toolPermission": "always-proceed"}, "toolPermission"),
        (
            {
                "toolPermission": "proceed-in-sandbox",
                "allowNonWorkspaceAccess": True,
            },
            "allowNonWorkspaceAccess",
        ),
        (
            {
                "toolPermission": "proceed-in-sandbox",
                "allowNonWorkspaceAccess": 0,
            },
            "allowNonWorkspaceAccess",
        ),
        (
            {
                "toolPermission": "proceed-in-sandbox",
                "permissions": {"allow": ["unsandboxed(*)"]},
            },
            "must be empty",
        ),
    ],
)
def test_agy_rejects_unsafe_settings(tmp_path, monkeypatch, payload, message):
    path = _safe_settings(tmp_path, payload)
    monkeypatch.setattr(agy_module, "_settings_path", lambda: path)
    with pytest.raises(AgenticError, match=message):
        agy_module._validate_safe_settings()


def test_agy_rejects_missing_or_invalid_settings(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(agy_module, "_settings_path", lambda: missing)
    with pytest.raises(AgenticError, match="safe settings profile"):
        agy_module._validate_safe_settings()

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(agy_module, "_settings_path", lambda: invalid)
    with pytest.raises(AgenticError, match="not valid JSON"):
        agy_module._validate_safe_settings()


def test_run_agy_rejects_wrong_effective_permission(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _patch_runtime(
        monkeypatch,
        tmp_path,
        [],
        stdout=_stream(workspace, permission_mode="always-proceed"),
        stderr="permission mismatch",
    )
    with pytest.raises(AgenticError, match="stderr: permission mismatch"):
        run_agy(workspace, "task", "gemini-test")


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json",
        json.dumps(
            {
                "event": "init",
                "conversation_id": SESSION_ID,
                "init": {},
            }
        ),
        json.dumps({"event": "future_event", "future_event": {}}),
    ],
)
def test_run_agy_rejects_malformed_stream(tmp_path, monkeypatch, stdout):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _patch_runtime(monkeypatch, tmp_path, [], stdout=stdout, stderr="diagnostic")
    with pytest.raises(AgenticError, match="stderr: diagnostic"):
        run_agy(workspace, "task", "gemini-test")


def test_run_agy_rejects_failed_result(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _patch_runtime(
        monkeypatch,
        tmp_path,
        [],
        stdout=_stream(workspace, status="ERROR", response="permission denied"),
    )
    with pytest.raises(AgenticError, match="ERROR.*permission denied"):
        run_agy(workspace, "task", "gemini-test")


def test_run_agy_nonzero_exit_keeps_stderr(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _patch_runtime(monkeypatch, tmp_path, [], returncode=2, stderr="authentication required")
    with pytest.raises(AgenticError, match="authentication required"):
        run_agy(workspace, "task", "gemini-test")


def test_run_agy_nonzero_exit_keeps_result_error(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _patch_runtime(
        monkeypatch,
        tmp_path,
        [],
        stdout=_stream(workspace, status="ERROR", response="quota exhausted"),
        returncode=1,
    )
    with pytest.raises(AgenticError, match="quota exhausted"):
        run_agy(workspace, "task", "gemini-test")


def test_run_agy_rejects_invalid_resume_id_before_subprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(agy_module.shutil, "which", lambda _: "/usr/bin/agy")
    with pytest.raises(AgenticError, match="resume request"):
        run_agy(
            tmp_path,
            "task",
            "gemini-test",
            resume_session_id="not-a-uuid",
        )


def test_run_agy_timeout_raises(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings_path = _safe_settings(tmp_path)
    monkeypatch.setattr(agy_module, "_settings_path", lambda: settings_path)
    monkeypatch.setattr(agy_module.shutil, "which", lambda _: "/usr/bin/agy")

    def fake_run(argv, **kwargs):
        if argv[-1] == "--version":
            return SimpleNamespace(stdout="1.1.19", stderr="", returncode=0)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(agy_module.subprocess, "run", fake_run)
    with pytest.raises(AgenticError, match="timed out after 12s"):
        run_agy(workspace, "task", "gemini-test", timeout_s=12)


def test_run_agy_rejects_conversation_mismatch(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _patch_runtime(
        monkeypatch,
        tmp_path,
        [],
        stdout=_stream(workspace, session_id=OTHER_SESSION_ID),
    )
    with pytest.raises(AgenticError, match="wrong conversation"):
        run_agy(
            workspace,
            "task",
            "gemini-test",
            resume_session_id=SESSION_ID,
        )


def _result(session_id, requests, input_tokens, output_tokens, thinking_tokens):
    return AgentRunResult(
        session_id=session_id,
        final_message="done",
        usage=AgentUsage(
            requests=requests,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=0,
            details={"reasoning_tokens": thinking_tokens},
        ),
        events=[],
    )


def test_fix_loop_records_only_cumulative_usage_delta(tmp_path, monkeypatch):
    results = iter(
        [
            _result(SESSION_ID, 1, 100, 20, 5),
            _result(SESSION_ID, 2, 160, 32, 9),
        ]
    )
    monkeypatch.setattr(runner_module, "run_agy", lambda *args, **kwargs: next(results))
    problems = iter([["fix this"], []])
    recorded = []

    run_fix_loop(
        tmp_path,
        "task",
        "gemini-test",
        lambda: next(problems),
        recorded.append,
        backend=AGY,
    )

    assert [usage.requests for usage in recorded] == [1, 1]
    assert [usage.input_tokens for usage in recorded] == [100, 60]
    assert [usage.output_tokens for usage in recorded] == [20, 12]
    assert [usage.details for usage in recorded] == [
        {"reasoning_tokens": 5},
        {"reasoning_tokens": 4},
    ]


def test_fix_loop_resets_cumulative_baseline_after_fresh_retry(tmp_path, monkeypatch):
    calls = 0

    def flaky(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _result(SESSION_ID, 1, 100, 20, 5)
        if calls == 2:
            raise AgenticError("resume failed")
        return _result(OTHER_SESSION_ID, 1, 80, 10, 3)

    monkeypatch.setattr(runner_module, "run_agy", flaky)
    problems = iter([["fix this"], []])
    recorded = []

    run_fix_loop(
        tmp_path,
        "task",
        "gemini-test",
        lambda: next(problems),
        recorded.append,
        backend=AGY,
    )

    assert calls == 3
    assert [usage.input_tokens for usage in recorded] == [100, 80]


def test_fix_loop_rejects_cumulative_usage_regression(tmp_path, monkeypatch):
    results = iter(
        [
            _result(SESSION_ID, 1, 100, 20, 5),
            _result(SESSION_ID, 2, 90, 22, 6),
        ]
    )
    monkeypatch.setattr(runner_module, "run_agy", lambda *args, **kwargs: next(results))
    problems = iter([["fix this"], []])

    with pytest.raises(AgenticError, match="regressed for input_tokens"):
        run_fix_loop(
            tmp_path,
            "task",
            "gemini-test",
            lambda: next(problems),
            lambda usage: None,
            backend=AGY,
        )


def test_agy_ingest_routes_through_shared_backend(tmp_path, monkeypatch):
    fake = FakeAgenticRun([_write_bundle])
    monkeypatch.setattr(runner_module, "run_agy", fake)

    bundle = run_ingest(
        [_source(tmp_path)],
        tmp_path / "bundle",
        model="agy:gemini-test",
    )

    assert bundle.manifest.ingest_model == "agy:gemini-test"
    assert fake.calls[0]["cli_model"] == "gemini-test"


def test_agy_solve_routes_through_shared_backend(tiny_bundle, monkeypatch):
    fake = FakeAgenticRun([write_valid])
    monkeypatch.setattr(runner_module, "run_agy", fake)

    sheet = run_solve(tiny_bundle, "agy:gemini-test")

    assert sheet.taker == "agy:gemini-test"
    assert tiny_bundle.validate_answer_sheet(sheet) == []
    assert fake.calls[0]["cli_model"] == "gemini-test"


def test_agy_judge_routes_through_shared_backend(tiny_bundle, monkeypatch):
    fake = FakeAgenticRun([write_verdicts(VALID_VERDICTS)])
    monkeypatch.setattr(runner_module, "run_agy", fake)

    report = run_grade(
        tiny_bundle,
        perfect_sheet(),
        judge_models=["agy:gemini-test"],
    )

    assert report.usage is not None
    assert set(report.usage.phases) == {"judge:agy:gemini-test"}
    assert fake.calls[0]["cli_model"] == "gemini-test"
