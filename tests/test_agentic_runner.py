"""Unit tests for the codex subprocess seam (no codex binary required)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import any_to_bench.agentic.runner as runner_module
from any_to_bench.agentic.runner import (
    AgenticError,
    codex_effort,
    parse_agentic_model,
    run_codex,
    run_fix_loop,
    summarize_events,
)
from any_to_bench.agentic.types import AgentRunResult, AgentUsage
from any_to_bench.schemas.usage import Effort
from tests.conftest import FakeAgenticRun


def test_parse_agentic_model():
    assert parse_agentic_model("codex:gpt-5.6-sol") == "gpt-5.6-sol"
    assert parse_agentic_model("openai:gpt-5.6-sol") is None
    with pytest.raises(ValueError, match="non-empty"):
        parse_agentic_model("codex:")
    assert parse_agentic_model("gpt-5.6-sol") is None


def test_codex_effort_mapping():
    assert codex_effort(None) is None
    assert codex_effort("minimal") == "minimal"
    assert codex_effort("low") == "low"
    assert codex_effort(Effort.medium) == "medium"
    assert codex_effort("high") == "high"
    assert codex_effort(Effort.xhigh) == "xhigh"
    assert codex_effort(Effort.max) == "xhigh"  # codex has no max level


def test_summarize_events():
    events = [
        {"type": "thread.started", "thread_id": "t-123"},
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 10,
                "reasoning_output_tokens": 3,
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 5}},
        {"type": "item.completed", "item": {}},
    ]
    session_id, usage = summarize_events(events)
    assert session_id == "t-123"
    assert usage.requests == 2
    assert usage.input_tokens == 150
    assert usage.output_tokens == 15
    assert usage.cache_read_tokens == 40
    assert usage.details == {"reasoning_tokens": 3}


def test_missing_binary_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module.shutil, "which", lambda _: None)
    with pytest.raises(AgenticError, match="not found"):
        run_codex(tmp_path, "hi", "gpt-test")


STDOUT_OK = "\n".join(
    [
        json.dumps({"type": "thread.started", "thread_id": "t-1"}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}}),
        "not json noise",
    ]
)


def _patch_subprocess(monkeypatch, calls, stdout=STDOUT_OK, returncode=0, stderr=""):
    monkeypatch.setattr(runner_module.shutil, "which", lambda _: "/usr/bin/codex")

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)


def test_run_codex_initial_argv(tmp_path, monkeypatch):
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = run_codex(workspace, "do the task", "gpt-test", effort="max")

    argv = calls[0]["argv"]
    assert argv[1] == "exec"
    assert "resume" not in argv
    i = argv.index("-C")
    assert argv[i + 1] == str(workspace)
    i = argv.index("-s")
    assert argv[i + 1] == "workspace-write"
    assert "--skip-git-repo-check" in argv
    i = argv.index("-m")
    assert argv[i + 1] == "gpt-test"
    assert "model_reasoning_effort=xhigh" in argv
    assert argv[-1] == "-"  # prompt is delivered on stdin
    assert calls[0]["input"] == "do the task"
    assert calls[0]["cwd"] == workspace
    assert result.session_id == "t-1"
    assert result.usage.input_tokens == 10


def test_run_codex_shuts_every_door_to_the_internet(tmp_path, monkeypatch):
    """Every paper in these corpora has its answer key published online, so a
    solver that can search is sitting an open-book exam against the marking
    scheme. Each of the three settings was observed to be necessary: the sandbox
    flag alone leaves the built-in search tool, and those two alone leave an
    escalation request that an `on-request` approval policy will grant."""
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    run_codex(workspace, "do the task", "gpt-test")
    argv = calls[0]["argv"]

    assert "sandbox_workspace_write.network_access=false" in argv
    assert 'web_search="disabled"' in argv
    assert 'approval_policy="never"' in argv


def test_run_codex_resume_keeps_the_doors_shut(tmp_path, monkeypatch):
    """A resumed turn re-sends them: -C and -s are inherited from the session
    record, but a config override is not."""
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    run_codex(workspace, "keep going", "gpt-test", resume_session_id="t-1")
    argv = calls[0]["argv"]

    assert "sandbox_workspace_write.network_access=false" in argv
    assert 'web_search="disabled"' in argv
    assert 'approval_policy="never"' in argv


def test_run_codex_runs_out_of_a_private_home(tmp_path, monkeypatch):
    """The operator's machine is not part of the exam. A session that reads
    ~/.codex/AGENTS.md and the skills under ~/.agents makes a score depend on
    whose laptop produced it."""
    real_home = tmp_path / "real-codex"
    real_home.mkdir()
    (real_home / "auth.json").write_text('{"token": "secret"}')
    (real_home / "AGENTS.md").write_text("operator instructions that must not travel")
    monkeypatch.setenv("CODEX_HOME", str(real_home))

    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)
    workspace = tmp_path / "run" / "workspace"
    workspace.mkdir(parents=True)

    run_codex(workspace, "do the task", "gpt-test")

    env = calls[0]["env"]
    home = Path(env["CODEX_HOME"])
    assert env["HOME"] == env["CODEX_HOME"]  # skills live under HOME, not CODEX_HOME
    assert home.parent == workspace.parent
    assert (home / "auth.json").read_text() == '{"token": "secret"}'
    assert not (home / "AGENTS.md").exists()


def test_run_codex_resume_keeps_the_same_home(tmp_path, monkeypatch):
    """`codex exec resume` finds a session by looking under CODEX_HOME, so a
    fresh home per invocation would lose the session the fix loop resumes."""
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)
    workspace = tmp_path / "run" / "workspace"
    workspace.mkdir(parents=True)

    run_codex(workspace, "first", "gpt-test")
    run_codex(workspace, "second", "gpt-test", resume_session_id="t-1")

    assert calls[0]["env"]["CODEX_HOME"] == calls[1]["env"]["CODEX_HOME"]


def test_run_codex_resume_argv(tmp_path, monkeypatch):
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    run_codex(workspace, "fix it", "gpt-test", resume_session_id="sess-9")

    argv = calls[0]["argv"]
    assert argv[1:4] == ["exec", "resume", "sess-9"]
    # resume inherits cwd/sandbox from the session record; it accepts neither flag
    assert "-C" not in argv
    assert "-s" not in argv
    assert "--skip-git-repo-check" in argv
    assert calls[0]["cwd"] == workspace


def test_run_codex_reads_last_message(tmp_path, monkeypatch):
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "control").mkdir()
    (tmp_path / "control" / "last_message.txt").write_text("all done\n")

    # the pre-existing file is cleared before the run, so this reads as empty
    result = run_codex(workspace, "task", "gpt-test")
    assert result.final_message == ""


def test_run_codex_nonzero_exit_raises(tmp_path, monkeypatch):
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls, returncode=2, stderr="boom")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(AgenticError, match="boom"):
        run_codex(workspace, "task", "gpt-test")


def test_run_codex_turn_failed_raises(tmp_path, monkeypatch):
    stdout = json.dumps({"type": "turn.failed", "message": "model refused"})
    calls: list[dict] = []
    _patch_subprocess(monkeypatch, calls, stdout=stdout)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(AgenticError, match="model refused"):
        run_codex(workspace, "task", "gpt-test")


def test_fix_loop_resumes_with_problems(tmp_path, monkeypatch):
    fake = FakeAgenticRun([None, None])
    monkeypatch.setattr(runner_module, "run_codex", fake)
    rounds = iter([["p1", "p2"], []])

    outcome = run_fix_loop(
        tmp_path, "the task", "gpt-test", lambda: next(rounds), on_usage=lambda u: None
    )

    assert outcome.problems == []
    assert outcome.rounds_run == 2
    assert outcome.round_counts == [2, 0]
    assert fake.calls[0]["prompt"] == "the task"
    assert fake.calls[0]["resume_session_id"] is None
    assert fake.calls[1]["resume_session_id"] == "sess-1"
    assert "p1" in fake.calls[1]["prompt"]
    assert "p2" in fake.calls[1]["prompt"]


def test_fix_loop_falls_back_to_fresh_exec(tmp_path, monkeypatch):
    calls: list[dict] = []

    def flaky(workspace, prompt, cli_model, effort=None, resume_session_id=None, timeout_s=None):
        calls.append({"prompt": prompt, "resume_session_id": resume_session_id})
        if resume_session_id is not None:
            raise AgenticError("resume broke")
        return AgentRunResult(
            session_id=f"s{len(calls)}", final_message="", usage=AgentUsage(), events=[]
        )

    monkeypatch.setattr(runner_module, "run_codex", flaky)
    rounds = iter([["bad thing"], []])

    outcome = run_fix_loop(tmp_path, "the task", "m", lambda: next(rounds), on_usage=lambda u: None)

    assert outcome.problems == []
    assert [c["resume_session_id"] for c in calls] == [None, "s1", None]
    assert "the task" in calls[2]["prompt"]
    assert "bad thing" in calls[2]["prompt"]


def test_fix_loop_exhaustion(tmp_path, monkeypatch):
    fake = FakeAgenticRun([])
    monkeypatch.setattr(runner_module, "run_codex", fake)

    outcome = run_fix_loop(
        tmp_path, "the task", "m", lambda: ["still broken"], on_usage=lambda u: None
    )

    assert outcome.problems == ["still broken"]
    assert outcome.rounds_run == 3
    assert len(fake.calls) == 3
