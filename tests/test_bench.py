"""Bench matrix: offline, faking the LLM layer per repo convention."""

import json

from typer.testing import CliRunner

import any_to_bench.bench as bench_module
import any_to_bench.solve.runner as runner_module
from any_to_bench.bench import format_table, run_bench
from any_to_bench.cli import app
from tests.conftest import fake_build_agent
from tests.test_solve_offline import PERFECT_OUTPUTS

runner = CliRunner()


def test_bench_matrix_happy_path(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    out = tmp_path / "bench"

    # The same model twice = variance run; slugs must not collide.
    report = run_bench(tiny_bundle, ["test:solver", "test:solver"], out)

    assert [row.slug for row in report.rows] == ["test-solver", "test-solver-2"]
    for row in report.rows:
        assert row.status == "ok"
        # Perfect deterministic part: 10/17; judge questions error offline (no judge).
        assert row.awarded == 10.0
        assert row.max_points == 17.0
        assert row.deterministic_full_credit == 5
        assert row.deterministic_total == 5
        assert row.error_count == 3  # q6.a, q6.b, q7: judges unreachable offline
        assert row.schema_error_count == 0
        assert (out / row.answers_path).exists()
        assert (out / row.report_path).exists()
        assert row.solve_usage is not None

    on_disk = json.loads((out / "bench.json").read_text())
    assert on_disk["exam_id"] == "tiny-exam"
    assert on_disk["judge_questions"] == 3
    assert len(on_disk["rows"]) == 2
    assert on_disk["finished_at"] is not None

    table = format_table(report)
    assert "| test:solver | 10/17 | 58.8% | 17/17 | 5/5 |" in table


def test_bench_isolates_a_failing_model(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    real_run_solve = bench_module.run_solve

    def flaky_run_solve(bundle, model, effort=None, **kwargs):
        if model == "test:broken":
            raise RuntimeError("provider down")
        return real_run_solve(bundle, model, effort=effort, **kwargs)

    monkeypatch.setattr(bench_module, "run_solve", flaky_run_solve)
    report = run_bench(tiny_bundle, ["test:broken", "test:solver"], tmp_path / "bench")

    broken, good = report.rows
    assert broken.status == "solve_error"
    assert "provider down" in broken.error
    assert broken.awarded is None
    assert good.status == "ok" and good.awarded == 10.0
    table = format_table(report)
    assert "| test:broken | solve_error |" in table


def test_bench_warns_on_self_judging(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    report = run_bench(
        tiny_bundle, ["test:solver"], tmp_path / "bench", judge_models=["test:solver"]
    )
    assert any("self-judging" in w for w in report.warnings)
    assert report.judge_models == ["test:solver"]


def test_bench_cli(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    out = tmp_path / "bench"
    result = runner.invoke(
        app,
        ["bench", str(tiny_bundle.root), "-o", str(out), "--model", "test:solver"],
    )
    assert result.exit_code == 0, result.output
    assert "| model |" in result.output
    assert (out / "bench.json").exists()


def test_bench_cli_exits_1_when_all_fail(tiny_bundle, tmp_path, monkeypatch):
    def explode(bundle, model, effort=None, **kwargs):
        raise RuntimeError("no provider")

    monkeypatch.setattr(bench_module, "run_solve", explode)
    result = runner.invoke(
        app,
        [
            "bench",
            str(tiny_bundle.root),
            "-o",
            str(tmp_path / "bench"),
            "--model",
            "test:a",
        ],
    )
    assert result.exit_code == 1
