"""Offline CLI end-to-end: validate -> solve -> grade, no network."""

import json

import pytest
from PIL import Image
from typer.testing import CliRunner

import any_to_bench.agentic.runner as agentic_runner
import any_to_bench.ingest.pipeline as pipeline_module
import any_to_bench.solve.runner as runner_module
from any_to_bench.cli import app
from any_to_bench.schemas.extraction import ExtractionChunk, GradingExtraction, MaterialInventory
from any_to_bench.util import write_json
from tests.conftest import FakeAgenticRun, build_tiny_bundle, fake_build_agent, imperfect_sheet
from tests.test_agentic_solve import write_valid
from tests.test_ingest_pipeline import ANSWER_KEY, EXTRACTION, INVENTORY
from tests.test_solve_offline import PERFECT_OUTPUTS

runner = CliRunner()


def test_ingest_help_distinguishes_resources_from_exam_materials():
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0, result.output
    assert "--resources" in result.output
    assert "Public resource" in result.output and "corpus directory" in result.output


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


def test_resource_backed_cli_ingest_solve_grade_bench_smoke(tmp_path, monkeypatch):
    exam_pdf = tmp_path / "exam.pdf"
    pages = [Image.new("RGB", (200, 280), color) for color in ("white", "ivory")]
    pages[0].save(exam_pdf, format="PDF", save_all=True, append_images=pages[1:])
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "facts.txt").write_text("the answer is 42", encoding="utf-8")
    (corpus / "paper.pdf").write_bytes(b"%PDF-1.4\nASCII\n")
    monkeypatch.setattr(
        pipeline_module,
        "build_agent",
        fake_build_agent(
            {
                MaterialInventory: INVENTORY,
                ExtractionChunk: EXTRACTION,
                GradingExtraction: ANSWER_KEY,
            }
        ),
    )
    bundle = tmp_path / "bundle"
    ingest = runner.invoke(
        app,
        [
            "ingest",
            str(exam_pdf),
            "--resources",
            str(corpus),
            "-o",
            str(bundle),
            "--model",
            "test:ingest",
        ],
    )
    assert ingest.exit_code == 0, ingest.output

    outputs = dict(PERFECT_OUTPUTS)
    outputs[runner_module.SolveBlanks] = runner_module.SolveBlanks(
        entries=[runner_module.SolveBlankEntry(blank_id="b1", text="42")]
    )
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(outputs))
    answers = tmp_path / "answers.json"
    solve = runner.invoke(app, ["solve", str(bundle), "--model", "test:solver", "-o", str(answers)])
    assert solve.exit_code == 0, solve.output
    assert "Resources: 1/2 files" in solve.output

    report_path = tmp_path / "report.json"
    grade = runner.invoke(app, ["grade", str(bundle), str(answers), "-o", str(report_path)])
    assert grade.exit_code == 0, grade.output
    assert "Citations: 0 submitted" in grade.output

    bench_dir = tmp_path / "bench"
    bench = runner.invoke(
        app,
        ["bench", str(bundle), "--model", "test:solver", "-o", str(bench_dir)],
    )
    assert bench.exit_code == 0, bench.output
    bench_json = json.loads((bench_dir / "bench.json").read_text(encoding="utf-8"))
    assert bench_json["rows"][0]["resource_access"]["exposed_files"] == 1
    assert bench_json["rows"][0]["citations"]["path_valid_percentage"] is None


@pytest.mark.parametrize(
    ("model", "runner_name"),
    [("codex:test", "run_codex"), ("agy:gemini-test", "run_agy")],
)
def test_agentic_solve_cli_same_interface(tmp_path, monkeypatch, model, runner_name):
    """An agentic model string is the only CLI change; outputs stay identical."""
    monkeypatch.setattr(agentic_runner, runner_name, FakeAgenticRun([write_valid]))
    bundle = build_tiny_bundle(tmp_path / "bundle")
    answers_path = tmp_path / "answers.json"

    result = runner.invoke(
        app,
        ["solve", str(bundle.root), "--model", model, "-o", str(answers_path)],
    )
    assert result.exit_code == 0, result.output
    assert "Tokens:" in result.output
    sheet = json.loads(answers_path.read_text())
    assert sheet["taker"] == model
    assert sheet["answers"]["q1"]["selected"] == "B"

    report_path = tmp_path / "report.json"
    grade_result = runner.invoke(
        app, ["grade", str(bundle.root), str(answers_path), "-o", str(report_path)]
    )
    assert grade_result.exit_code == 0, grade_result.output
    report = json.loads(report_path.read_text())
    assert report["results"]["q1"]["awarded"] == 2.0
