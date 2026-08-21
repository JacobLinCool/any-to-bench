"""Offline Claude Code backend: argv shape, session handling, usage, dispatch."""

import json
import uuid
from types import SimpleNamespace

import pytest

import any_to_bench.agentic.claude as claude_module
import any_to_bench.agentic.runner as runner_module
from any_to_bench.agentic.claude import claude_effort, run_claude, summarize_result
from any_to_bench.agentic.runner import (
    CLAUDE,
    CODEX,
    AgenticError,
    parse_agentic,
    parse_agentic_model,
    run_fix_loop,
)
from any_to_bench.grade.aggregate import run_grade
from any_to_bench.schemas.usage import Effort
from any_to_bench.solve.runner import run_solve
from tests.conftest import FakeAgenticRun, perfect_sheet
from tests.test_agentic_solve import write_valid

RESULT_OK = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 3,
        "result": "wrote the file",
        "session_id": "ignored-we-choose-our-own",
        "usage": {
            "input_tokens": 120,
            "output_tokens": 34,
            "cache_read_input_tokens": 900,
            "cache_creation_input_tokens": 45,
        },
    }
)


def _patch_subprocess(monkeypatch, calls, stdout=RESULT_OK, returncode=0, stderr=""):
    monkeypatch.setattr(claude_module.shutil, "which", lambda _: "/usr/bin/claude")

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    monkeypatch.setattr(claude_module.subprocess, "run", fake_run)


def _workspace(tmp_path, contract="CONTRACT BODY"):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text(contract, encoding="utf-8")
    return workspace


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_parse_agentic_recognizes_both_backends():
    assert parse_agentic("claude:opus").backend is CLAUDE
    assert parse_agentic("claude:opus").cli_model == "opus"
    assert parse_agentic("codex:gpt-test").backend is CODEX
    assert parse_agentic_model("claude:opus") == "opus"
    assert parse_agentic("claude:") is None
    # pydantic-ai's Anthropic provider prefix must stay a direct-LLM string.
    assert parse_agentic("anthropic:claude-fable-5") is None


@pytest.mark.parametrize(
    ("effort", "expected"),
    [
        (Effort.minimal, "low"),  # Claude Code has no `minimal` — collapse to its floor
        (Effort.low, "low"),
        (Effort.medium, "medium"),
        (Effort.high, "high"),
        (Effort.xhigh, "xhigh"),
        (Effort.max, "max"),
        (None, None),
    ],
)
def test_claude_effort_mapping(effort, expected):
    assert claude_effort(effort) == expected


def test_run_claude_initial_argv(tmp_path, monkeypatch):
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)
    workspace = _workspace(tmp_path)

    result = run_claude(workspace, "do the task", "opus", effort="max")

    argv = calls[0]["argv"]
    assert argv[:2] == ["/usr/bin/claude", "-p"]
    assert argv[-1] == "do the task"
    assert _flag(argv, "--model") == "opus"
    assert _flag(argv, "--output-format") == "json"
    assert _flag(argv, "--effort") == "max"
    assert "--safe-mode" in argv
    assert _flag(argv, "--setting-sources") == ""
    assert _flag(argv, "--add-dir") == str(workspace)
    assert _flag(argv, "--append-system-prompt") == "CONTRACT BODY"
    assert calls[0]["cwd"] == workspace
    # A session id we chose, so a resume can never target the wrong session.
    uuid.UUID(_flag(argv, "--session-id"))
    assert "--resume" not in argv
    assert result.session_id == _flag(argv, "--session-id")


def test_run_claude_is_confined(tmp_path, monkeypatch):
    """Security regression guard: exam materials are untrusted input."""
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)

    run_claude(_workspace(tmp_path), "task", "opus")

    argv = calls[0]["argv"]
    settings = json.loads(_flag(argv, "--settings"))
    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["failIfUnavailable"] is True
    assert settings["sandbox"]["network"]["allowedDomains"] == []
    assert settings["sandbox"]["filesystem"]["disabled"] is False
    # acceptEdits auto-approves edits but not Bash; Bash rides on the sandbox
    # being live, so losing the sandbox fails the run instead of unconfining it.
    assert _flag(argv, "--permission-mode") == "acceptEdits"
    assert "--dangerously-skip-permissions" not in argv
    assert "--allow-dangerously-skip-permissions" not in argv
    assert "bypassPermissions" not in argv


def test_run_claude_resume_argv(tmp_path, monkeypatch):
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)

    run_claude(_workspace(tmp_path), "fix it", "opus", resume_session_id="sess-abc")

    argv = calls[0]["argv"]
    assert _flag(argv, "--resume") == "sess-abc"
    assert "--session-id" not in argv


def test_run_claude_usage_and_final_message(tmp_path, monkeypatch):
    _patch_subprocess(monkeypatch, [])

    result = run_claude(_workspace(tmp_path), "task", "opus")

    assert result.final_message == "wrote the file"
    assert result.usage.requests == 3
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 34
    assert result.usage.cache_read_tokens == 900
    assert result.usage.cache_write_tokens == 45
    # Anthropic reports no reasoning-token count; record zero rather than guess.
    assert result.usage.details == {}


def test_run_claude_missing_contract_omits_system_prompt(tmp_path, monkeypatch):
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    run_claude(workspace, "task", "opus")

    assert "--append-system-prompt" not in calls[0]["argv"]


def test_run_claude_stream_json_fallback(tmp_path, monkeypatch):
    stream = '{"type":"system"}\n' + RESULT_OK + "\n"
    _patch_subprocess(monkeypatch, [], stdout=stream)

    result = run_claude(_workspace(tmp_path), "task", "opus")

    assert result.final_message == "wrote the file"


def test_run_claude_nonzero_exit_raises(tmp_path, monkeypatch):
    _patch_subprocess(monkeypatch, [], returncode=1, stderr="boom")

    with pytest.raises(AgenticError, match="boom"):
        run_claude(_workspace(tmp_path), "task", "opus")


def test_run_claude_nonzero_exit_keeps_what_stdout_said(tmp_path, monkeypatch):
    """A refused session says why on stdout and nothing on stderr, so an error
    built from the exit code alone is indistinguishable from a bad prompt."""
    payload = json.dumps({"type": "result", "is_error": True, "result": "usage limit reached"})
    _patch_subprocess(monkeypatch, [], returncode=1, stdout=payload, stderr="")

    with pytest.raises(AgenticError, match="usage limit reached"):
        run_claude(_workspace(tmp_path), "task", "opus")


def test_run_claude_nonzero_exit_keeps_unparseable_stdout(tmp_path, monkeypatch):
    _patch_subprocess(monkeypatch, [], returncode=1, stdout="not json at all", stderr="")

    with pytest.raises(AgenticError, match="not json at all"):
        run_claude(_workspace(tmp_path), "task", "opus")


def test_run_claude_is_error_raises(tmp_path, monkeypatch):
    payload = json.dumps(
        {"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "gave up"}
    )
    _patch_subprocess(monkeypatch, [], stdout=payload)

    with pytest.raises(AgenticError, match="error_max_turns"):
        run_claude(_workspace(tmp_path), "task", "opus")


def test_run_claude_unparseable_stdout_raises(tmp_path, monkeypatch):
    _patch_subprocess(monkeypatch, [], stdout="not json at all")

    with pytest.raises(AgenticError, match="no parseable result"):
        run_claude(_workspace(tmp_path), "task", "opus")


def test_codex_runner_is_still_a_module_global():
    """The whole offline suite rests on this indirection staying late-bound."""
    assert runner_module._resolve_runner(CODEX) is runner_module.run_codex
    assert runner_module._resolve_runner(CLAUDE) is runner_module.run_claude


def test_fix_loop_dispatches_to_the_named_backend(tmp_path, monkeypatch):
    fake = FakeAgenticRun([None])

    def explode(*args, **kwargs):
        raise AssertionError("codex must not run for a claude: model")

    monkeypatch.setattr(runner_module, "run_claude", fake)
    monkeypatch.setattr(runner_module, "run_codex", explode)

    outcome = run_fix_loop(
        tmp_path, "task", "opus", lambda: [], on_usage=lambda u: None, backend=CLAUDE
    )

    assert outcome.rounds_run == 1
    assert fake.calls[0]["cli_model"] == "opus"


def test_agentic_solve_via_claude(tiny_bundle, monkeypatch):
    fake = FakeAgenticRun([write_valid])
    monkeypatch.setattr(runner_module, "run_claude", fake)

    sheet = run_solve(tiny_bundle, "claude:opus")

    assert sheet.taker == "claude:opus"
    assert tiny_bundle.validate_answer_sheet(sheet) == []
    assert set(sheet.usage.phases) == {"agentic:solve"}
    assert fake.calls[0]["cli_model"] == "opus"


def test_claude_judge_phase_name(tiny_bundle, monkeypatch):
    verdicts = {
        "q6.a": {"criteria": [], "total_points": 2.0, "overall_rationale": "ok"},
        "q6.b": {
            "criteria": [
                {"criterion_id": "content", "points": 2.0, "rationale": "ok"},
                {"criterion_id": "clarity", "points": 1.0, "rationale": "ok"},
            ],
            "total_points": 3.0,
            "overall_rationale": "ok",
        },
        "q7": {"criteria": [], "total_points": 2.0, "overall_rationale": "ok"},
    }

    def write_verdicts(workspace):
        from any_to_bench.util import write_json

        write_json(workspace / "output" / "verdicts.json", {"verdicts": verdicts})

    monkeypatch.setattr(runner_module, "run_claude", FakeAgenticRun([write_verdicts]))

    report = run_grade(tiny_bundle, perfect_sheet(), judge_models=["claude:opus"])

    assert set(report.usage.phases) == {"judge:claude:opus"}


def test_summarize_result_tolerates_missing_usage():
    usage = summarize_result({"type": "result"})

    assert usage.requests == 1
    assert usage.input_tokens == 0
