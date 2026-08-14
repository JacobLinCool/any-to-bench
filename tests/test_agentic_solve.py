"""Offline agentic solve: FakeCodex plants answers.json; the fix loop validates."""

import pytest

import any_to_bench.agentic.runner as runner_module
from any_to_bench.agentic.runner import CodexError
from any_to_bench.solve.runner import run_solve
from any_to_bench.util import write_json
from tests.conftest import FakeCodex, make_png

VALID_ANSWERS = {
    "exam_id": "tiny-exam",
    "answers": {
        "q1": {"type": "single_choice", "selected": "B"},
        "q2": {"type": "multiple_choice", "selected": ["A", "C"]},
        "q3": {"type": "true_false", "value": True},
        "q4": {"type": "fill_in_blank", "blanks": {"b1": "Paris", "b2": "3.14"}},
        "q5": {"type": "matching", "pairs": {"L1": "R2", "L2": "R1"}},
        "q6.a": {"type": "text", "text": "Chlorophyll."},
        "q6.b": {"type": "text", "text": "Rate increases with light, then plateaus."},
        "q7": {"type": "drawing", "description": "Upward parabola, vertex at the origin."},
    },
}


def write_valid(workspace):
    write_json(workspace / "output" / "answers.json", VALID_ANSWERS)


def test_agentic_solve_happy_path(tiny_bundle, monkeypatch):
    fake = FakeCodex([write_valid])
    monkeypatch.setattr(runner_module, "run_codex", fake)

    sheet = run_solve(tiny_bundle, "codex:test")

    assert sheet.taker == "codex:test"
    assert tiny_bundle.validate_answer_sheet(sheet) == []
    assert sheet.answers["q1"].selected == "B"
    assert sheet.usage is not None
    assert set(sheet.usage.phases) == {"agentic:solve"}
    assert sheet.usage.total.requests == 1
    assert sheet.usage.total.reasoning_tokens == 9
    assert len(fake.calls) == 1
    assert fake.calls[0]["cli_model"] == "test"


def test_solve_workspace_has_no_answer_leaks(tiny_bundle, monkeypatch):
    # Plant bundle files a solver must never see: provenance page renders (they
    # may show the answer key) alongside the always-present grading.json.
    make_png(tiny_bundle.root / "assets" / "pages" / "p0001.png")
    seen: dict = {}

    def snoop_and_write(workspace):
        seen["files"] = sorted(
            str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file()
        )
        write_valid(workspace)

    monkeypatch.setattr(runner_module, "run_codex", FakeCodex([snoop_and_write]))
    run_solve(tiny_bundle, "codex:test")

    files = seen["files"]
    assert "AGENTS.md" in files
    assert "exam/exam.json" in files
    assert "exam/assets/q1-fig1.png" in files  # referenced by q1's prompt
    assert "schemas/answer_schema.json" in files
    assert not any("grading" in f for f in files)
    assert not any("manifest" in f for f in files)
    assert not any("pages" in f for f in files)


def test_solve_fix_loop_feeds_schema_errors_back(tiny_bundle, monkeypatch):
    bad = {
        **VALID_ANSWERS,
        "answers": {
            **VALID_ANSWERS["answers"],
            "q1": {"type": "single_choice", "selected": "Z"},
        },
    }
    fake = FakeCodex([lambda ws: write_json(ws / "output" / "answers.json", bad), write_valid])
    monkeypatch.setattr(runner_module, "run_codex", fake)

    sheet = run_solve(tiny_bundle, "codex:test")

    assert tiny_bundle.validate_answer_sheet(sheet) == []
    assert len(fake.calls) == 2
    assert fake.calls[1]["resume_session_id"] == "sess-1"
    assert "'Z'" in fake.calls[1]["prompt"]  # the jsonschema enum error, verbatim
    assert sheet.usage.total.requests == 2


def test_solve_exhaustion_still_returns_parseable_sheet(tiny_bundle, monkeypatch):
    bad = {
        **VALID_ANSWERS,
        "answers": {
            **VALID_ANSWERS["answers"],
            "q1": {"type": "single_choice", "selected": "Z"},
        },
    }
    fake = FakeCodex([lambda ws: write_json(ws / "output" / "answers.json", bad)])
    monkeypatch.setattr(runner_module, "run_codex", fake)

    sheet = run_solve(tiny_bundle, "codex:test")

    # Residual schema errors surface through the CLI's exit-1 path, like LLM mode.
    assert tiny_bundle.validate_answer_sheet(sheet)
    assert len(fake.calls) == 3


def test_solve_unparseable_output_raises(tiny_bundle, monkeypatch):
    monkeypatch.setattr(runner_module, "run_codex", FakeCodex([]))
    with pytest.raises(CodexError, match="no parseable"):
        run_solve(tiny_bundle, "codex:test")
