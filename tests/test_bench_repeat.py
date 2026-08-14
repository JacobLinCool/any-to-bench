"""bench --repeat: variance across runs, and what survives an interruption."""

import json
import statistics

import pytest
from typer.testing import CliRunner

import any_to_bench.bench as bench_module
import any_to_bench.solve.runner as runner_module
from any_to_bench.bench import format_table, run_bench, summarize_models
from any_to_bench.cli import app
from any_to_bench.schemas.bench import BenchRow
from any_to_bench.solve.runner import SolveChoice
from tests.conftest import fake_build_agent
from tests.test_solve_offline import PERFECT_OUTPUTS

cli = CliRunner()


def alternating_outputs(choices):
    """PERFECT_OUTPUTS, but the single-choice answer differs run to run.

    q1 is the exam's only single_choice question, so this callable fires exactly
    once per run and each repeat gets the next option in turn.
    """
    it = iter(choices)
    outputs = dict(PERFECT_OUTPUTS)
    outputs[SolveChoice] = lambda parts: SolveChoice(selected=next(it))
    return outputs


def test_repeat_produces_one_row_per_run(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))

    report = run_bench(tiny_bundle, ["test:solver"], tmp_path / "out", repeat=3)

    assert report.repeat == 3
    assert [r.run_index for r in report.rows] == [1, 2, 3]
    assert [r.slug for r in report.rows] == ["test-solver", "test-solver-2", "test-solver-3"]
    summary = report.summaries[0]
    assert summary.runs == summary.ok_runs == 3
    assert summary.awarded_mean == 10.0
    assert summary.awarded_std == 0.0  # deterministic fake: no variance
    assert summary.percentage_std == 0.0


def test_repeat_is_repeat_major(tiny_bundle, tmp_path, monkeypatch):
    """Interrupted after one pass you have every model sampled once, not half of them thrice."""
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))

    report = run_bench(tiny_bundle, ["test:a", "test:b"], tmp_path / "out", repeat=2)

    assert [(r.model, r.run_index) for r in report.rows] == [
        ("test:a", 1),
        ("test:b", 1),
        ("test:a", 2),
        ("test:b", 2),
    ]


def test_repeat_reports_variance(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner_module, "build_agent", fake_build_agent(alternating_outputs(["B", "A"]))
    )

    report = run_bench(tiny_bundle, ["test:solver"], tmp_path / "out", repeat=2)

    summary = report.summaries[0]
    # q1 is worth 2 points: right once, wrong once.
    assert sorted(summary.awarded) == [8.0, 10.0]
    assert summary.awarded_mean == 9.0
    assert summary.awarded_std == pytest.approx(statistics.stdev([10.0, 8.0]))


def test_single_run_reports_no_std(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))

    report = run_bench(tiny_bundle, ["test:solver"], tmp_path / "out")

    summary = report.summaries[0]
    assert summary.ok_runs == 1
    assert summary.awarded_mean == 10.0
    assert summary.awarded_std is None  # stdev is undefined for one sample


def test_summaries_survive_an_interrupted_run(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    real_run_solve = bench_module.run_solve
    calls = {"n": 0}

    def flaky(bundle, model, effort=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("provider down")
        return real_run_solve(bundle, model, effort=effort, **kwargs)

    monkeypatch.setattr(bench_module, "run_solve", flaky)
    out = tmp_path / "out"

    report = run_bench(tiny_bundle, ["test:solver"], out, repeat=4)

    on_disk = json.loads((out / "bench.json").read_text())
    assert len(on_disk["rows"]) == 4
    assert on_disk["summaries"][0]["runs"] == 4
    assert on_disk["summaries"][0]["ok_runs"] == 3  # the aggregate reflects only what worked
    assert report.summaries[0].awarded_std == 0.0


def test_duplicate_models_merge_into_one_summary(tiny_bundle, tmp_path, monkeypatch):
    """`--model X --model X --repeat 2` is four samples of X, as the docs have it."""
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))

    report = run_bench(tiny_bundle, ["test:solver", "test:solver"], tmp_path / "out", repeat=2)

    assert len(report.rows) == 4
    assert len(report.summaries) == 1
    assert report.summaries[0].runs == 4


def test_repeat_table_shows_mean_and_spread(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner_module, "build_agent", fake_build_agent(alternating_outputs(["B", "A"]))
    )

    report = run_bench(tiny_bundle, ["test:solver"], tmp_path / "out", repeat=2)
    table = format_table(report)

    assert "| runs |" in table
    assert "2/2" in table
    assert "±" in table


def test_single_run_table_is_the_familiar_one(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))

    report = run_bench(tiny_bundle, ["test:solver"], tmp_path / "out")
    table = format_table(report)

    assert "| runs |" not in table
    assert "| test:solver | 10/17 | 58.8% | 17/17 | 5/5 |" in table


def test_summarize_models_is_pure():
    rows = [
        BenchRow(model="m", slug="m", run_index=1, awarded=4.0, covered_percentage=40.0),
        BenchRow(model="m", slug="m-2", run_index=2, awarded=6.0, covered_percentage=60.0),
        BenchRow(model="m", slug="m-3", run_index=3, status="solve_error", error="boom"),
    ]

    summary = summarize_models(rows, ["m"])[0]

    assert summary.runs == 3
    assert summary.ok_runs == 2
    assert summary.awarded_mean == 5.0
    assert summary.percentage_mean == 50.0
    assert summary.awarded_std == pytest.approx(statistics.stdev([4.0, 6.0]))


def test_cli_rejects_zero_repeat(tiny_bundle, tmp_path):
    result = cli.invoke(
        app,
        [
            "bench",
            str(tiny_bundle.root),
            "-o",
            str(tmp_path / "o"),
            "--model",
            "x",
            "--repeat",
            "0",
        ],
    )

    assert result.exit_code == 2
