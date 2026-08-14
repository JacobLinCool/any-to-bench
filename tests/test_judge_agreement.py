"""Inter-judge agreement, and the attribution that makes it meaningful."""

import pytest

import any_to_bench.grade.judge as judge_module
from any_to_bench.grade.aggregate import run_grade
from any_to_bench.grade.judge import summarize_judge_agreement
from any_to_bench.schemas.report import JudgeVerdict, QuestionResult
from tests.conftest import fake_build_agent, perfect_sheet


def holistic_sheet():
    """perfect_sheet trimmed to the two holistic judge questions."""
    sheet = perfect_sheet()
    sheet.answers = {qid: a for qid, a in sheet.answers.items() if qid in ("q6.a", "q7")}
    return sheet


def verdict(points: float):
    def produce(parts):
        return JudgeVerdict(criteria=[], total_points=points, overall_rationale="ok")

    return produce


def test_attribution_survives_a_failing_judge(tiny_bundle, monkeypatch):
    """The regression test: judges drop out, so positions must not be assumed."""

    def explode(parts):
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        judge_module,
        "build_agent",
        fake_build_agent({}, by_model={"test:a": explode, "test:b": verdict(2.0)}),
    )

    report = run_grade(tiny_bundle, holistic_sheet(), judge_models=["test:a", "test:b"])

    result = report.results["q6.a"]
    assert result.detail["judge_models"] == ["test:b"]  # not ["test:a", "test:b"]
    assert result.detail["requested_judge_models"] == ["test:a", "test:b"]
    assert result.detail["totals"] == [2.0]
    assert len(result.judge_verdicts) == 1
    # The surviving judge's score is credited to the judge that produced it.
    assert report.judge_agreement.per_judge_mean == {"test:b": 2.0}


def test_all_judges_failing_records_the_request(tiny_bundle, monkeypatch):
    def explode(parts):
        raise RuntimeError("provider down")

    monkeypatch.setattr(judge_module, "build_agent", fake_build_agent({JudgeVerdict: explode}))

    report = run_grade(tiny_bundle, holistic_sheet(), judge_models=["test:a"])

    result = report.results["q6.a"]
    assert result.mode == "error"
    assert result.detail["requested_judge_models"] == ["test:a"]
    assert report.judge_agreement is None  # no verdicts anywhere


def test_agreement_metrics_when_judges_differ(tiny_bundle, monkeypatch):
    monkeypatch.setattr(
        judge_module,
        "build_agent",
        fake_build_agent({}, by_model={"test:a": verdict(1.0), "test:b": verdict(2.0)}),
    )

    report = run_grade(tiny_bundle, holistic_sheet(), judge_models=["test:a", "test:b"])

    agreement = report.results["q6.a"].detail["agreement"]
    assert agreement["judge_count"] == 2
    assert agreement["spread"] == 1.0
    assert agreement["stdev"] == pytest.approx(0.7071, rel=1e-3)
    assert agreement["normalized_spread"] == 0.5  # q6.a is worth 2 points
    assert agreement["unanimous"] is False

    summary = report.judge_agreement
    assert summary.requested_judge_models == ["test:a", "test:b"]
    assert summary.judged_questions == 2
    assert summary.multi_judge_questions == 2
    assert summary.disagreed_questions == 2
    assert summary.mean_spread == 1.0
    assert summary.max_spread == 1.0
    assert summary.per_judge_mean == {"test:a": 1.0, "test:b": 2.0}


def test_agreement_when_judges_are_unanimous(tiny_bundle, monkeypatch):
    monkeypatch.setattr(
        judge_module,
        "build_agent",
        fake_build_agent({}, by_model={"test:a": verdict(2.0), "test:b": verdict(2.0)}),
    )

    report = run_grade(tiny_bundle, holistic_sheet(), judge_models=["test:a", "test:b"])

    assert report.results["q6.a"].detail["agreement"]["unanimous"] is True
    assert report.judge_agreement.disagreed_questions == 0
    assert report.judge_agreement.mean_spread == 0.0


def test_single_judge_reports_no_spread(tiny_bundle, monkeypatch):
    monkeypatch.setattr(judge_module, "build_agent", fake_build_agent({JudgeVerdict: verdict(2.0)}))

    report = run_grade(tiny_bundle, holistic_sheet(), judge_models=["test:a"])

    summary = report.judge_agreement
    assert summary.judged_questions == 2
    assert summary.multi_judge_questions == 0  # nothing to compare against
    assert summary.mean_spread == 0.0
    assert summary.per_judge_mean == {"test:a": 2.0}


def test_agreement_is_none_without_judged_questions(tiny_bundle):
    from tests.conftest import imperfect_sheet

    report = run_grade(tiny_bundle, imperfect_sheet())

    assert report.judge_agreement is None


def test_bench_surfaces_disagreement(tiny_bundle, tmp_path, monkeypatch):
    import any_to_bench.solve.runner as solve_runner
    from any_to_bench.bench import format_table, run_bench
    from tests.test_solve_offline import PERFECT_OUTPUTS

    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    monkeypatch.setattr(
        judge_module,
        "build_agent",
        fake_build_agent({}, by_model={"test:a": verdict(1.0), "test:b": verdict(2.0)}),
    )

    report = run_bench(
        tiny_bundle, ["test:solver"], tmp_path / "out", judge_models=["test:a", "test:b"]
    )

    row = report.rows[0]
    assert row.multi_judge_questions == 3
    # Only the two holistic questions differ: on the rubric question both judges
    # omit every criterion, so snapping zero-fills them to the same total.
    assert row.judge_disagreements == 2
    assert row.judge_mean_spread > 0
    assert "| 2/3 |" in format_table(report)


def test_bench_warns_when_agreement_cannot_be_measured(tiny_bundle, tmp_path, monkeypatch):
    import any_to_bench.solve.runner as solve_runner
    from any_to_bench.bench import format_table, run_bench
    from tests.test_solve_offline import PERFECT_OUTPUTS

    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    monkeypatch.setattr(judge_module, "build_agent", fake_build_agent({JudgeVerdict: verdict(2.0)}))

    report = run_bench(tiny_bundle, ["test:solver"], tmp_path / "out", judge_models=["test:only"])

    assert any("single judge model" in w for w in report.warnings)
    assert "| – |" in format_table(report)  # nothing comparable, so no ratio is implied


def test_summarize_judge_agreement_is_pure():
    """Callable on finished results, with no judge run and no fakes."""
    results = {
        "q1": QuestionResult(
            question_id="q1",
            mode="judge",
            max_points=4.0,
            awarded=3.0,
            detail={
                "judge_models": ["a", "b"],
                "agreement": {"spread": 2.0, "normalized_spread": 0.5, "unanimous": False},
            },
            judge_verdicts=[
                JudgeVerdict(total_points=2.0, overall_rationale=""),
                JudgeVerdict(total_points=4.0, overall_rationale=""),
            ],
        ),
        "q2": QuestionResult(question_id="q2", mode="deterministic", max_points=1.0, awarded=1.0),
    }

    summary = summarize_judge_agreement(results, ["a", "b"])

    assert summary.judged_questions == 1
    assert summary.multi_judge_questions == 1
    assert summary.disagreed_questions == 1
    assert summary.mean_normalized_spread == 0.5
    assert summary.per_judge_mean == {"a": 2.0, "b": 4.0}
