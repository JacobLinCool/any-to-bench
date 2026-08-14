"""Offline CLI end-to-end: validate -> solve -> grade, no network."""

import json

from typer.testing import CliRunner

import any_to_bench.agentic.runner as agentic_runner
import any_to_bench.solve.runner as runner_module
from any_to_bench.cli import app
from any_to_bench.util import write_json
from tests.conftest import FakeCodex, build_tiny_bundle, fake_build_agent, imperfect_sheet
from tests.test_agentic_solve import write_valid
from tests.test_solve_offline import PERFECT_OUTPUTS

runner = CliRunner()


def test_validate_ok(tmp_path):
    bundle = build_tiny_bundle(tmp_path / "bundle")
    result = runner.invoke(app, ["validate", str(bundle.root)])
    assert result.exit_code == 0, result.output
    assert "is valid" in result.output


def test_validate_broken_bundle_fails(tmp_path):
    bundle = build_tiny_bundle(tmp_path / "bundle")
    (bundle.root / "assets" / "q1-fig1.png").unlink()
    result = runner.invoke(app, ["validate", str(bundle.root)])
    assert result.exit_code == 1
    assert "missing image asset" in result.output


def test_grade_deterministic_cli(tmp_path):
    bundle = build_tiny_bundle(tmp_path / "bundle")
    answers_path = tmp_path / "answers.json"
    write_json(answers_path, imperfect_sheet())
    report_path = tmp_path / "report.json"

    result = runner.invoke(
        app, ["grade", str(bundle.root), str(answers_path), "-o", str(report_path)]
    )
    assert result.exit_code == 0, result.output
    assert "3.5/17" in result.output

    report = json.loads(report_path.read_text())
    assert report["total_awarded"] == 3.5
    assert report["total_max"] == 17.0
    assert report["results"]["q2"]["awarded"] == 1.5


def test_solve_then_grade_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    bundle = build_tiny_bundle(tmp_path / "bundle")
    answers_path = tmp_path / "answers.json"

    result = runner.invoke(
        app,
        ["solve", str(bundle.root), "--model", "test:solver", "-o", str(answers_path)],
    )
    assert result.exit_code == 0, result.output
    sheet = json.loads(answers_path.read_text())
    assert sheet["taker"] == "test:solver"
    assert sheet["answers"]["q1"]["selected"] == "B"

    # Deterministic part of the perfect solve grades to 10/17
    # (judge questions error out offline; they score 0 without a judge model).
    report_path = tmp_path / "report.json"
    grade_result = runner.invoke(
        app, ["grade", str(bundle.root), str(answers_path), "-o", str(report_path)]
    )
    assert grade_result.exit_code == 0, grade_result.output
    report = json.loads(report_path.read_text())
    deterministic = {"q1": 2.0, "q2": 3.0, "q3": 1.0, "q4": 2.0, "q5": 2.0}
    for qid, expected in deterministic.items():
        assert report["results"][qid]["awarded"] == expected


def test_agentic_solve_cli_same_interface(tmp_path, monkeypatch):
    """A codex: model string is the ONLY change; commands and outputs are identical."""
    monkeypatch.setattr(agentic_runner, "run_codex", FakeCodex([write_valid]))
    bundle = build_tiny_bundle(tmp_path / "bundle")
    answers_path = tmp_path / "answers.json"

    result = runner.invoke(
        app,
        ["solve", str(bundle.root), "--model", "codex:test", "-o", str(answers_path)],
    )
    assert result.exit_code == 0, result.output
    assert "Tokens:" in result.output
    sheet = json.loads(answers_path.read_text())
    assert sheet["taker"] == "codex:test"
    assert sheet["answers"]["q1"]["selected"] == "B"

    report_path = tmp_path / "report.json"
    grade_result = runner.invoke(
        app, ["grade", str(bundle.root), str(answers_path), "-o", str(report_path)]
    )
    assert grade_result.exit_code == 0, grade_result.output
    report = json.loads(report_path.read_text())
    assert report["results"]["q1"]["awarded"] == 2.0
