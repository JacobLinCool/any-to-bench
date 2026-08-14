"""Offline grading: deterministic end-to-end plus judge with faked agents."""

import pytest

import any_to_bench.grade.judge as judge_module
from any_to_bench.grade.aggregate import run_grade
from any_to_bench.schemas.report import CriterionScore, JudgeVerdict
from tests.conftest import fake_build_agent, imperfect_sheet, perfect_sheet


def test_deterministic_only_grading_needs_no_model(tiny_bundle):
    report = run_grade(tiny_bundle, imperfect_sheet())
    assert report.usage is None  # zero LLM calls
    assert report.results["q1"].awarded == 0.0
    assert report.results["q2"].awarded == 1.5
    assert report.results["q3"].awarded == 0.0
    assert report.results["q4"].awarded == 1.0
    assert report.results["q5"].awarded == 1.0
    for qid in ("q6.a", "q6.b", "q7"):
        assert report.results[qid].mode == "unanswered"
    assert report.total_awarded == 3.5
    assert report.total_max == 17.0
    assert report.section_totals["s1"].awarded == 3.5
    assert report.percentage == pytest.approx(100 * 3.5 / 17)


def test_judge_grading_with_fake_judges(tiny_bundle, monkeypatch):
    verdict = JudgeVerdict(
        criteria=[
            CriterionScore(criterion_id="content", points=1.8, rationale="mostly right"),
            CriterionScore(criterion_id="clarity", points=1.0, rationale="clear"),
        ],
        total_points=2.8,
        overall_rationale="good",
    )
    monkeypatch.setattr(
        judge_module, "build_agent", fake_build_agent({JudgeVerdict: verdict})
    )

    report = run_grade(tiny_bundle, perfect_sheet())
    # Deterministic part is perfect: 2+3+1+2+2 = 10
    for qid, expected in (("q1", 2.0), ("q2", 3.0), ("q3", 1.0), ("q4", 2.0), ("q5", 2.0)):
        assert report.results[qid].awarded == expected

    # q6.b has a rubric: content 1.8 snaps to level 2.0, clarity stays 1.0 -> 3.0
    q6b = report.results["q6.b"]
    assert q6b.mode == "judge"
    assert q6b.awarded == 3.0
    assert any("snapped" in w for w in report.warnings)

    # Holistic questions (q6.a max 2.0, q7 max 2.0): total 2.8 clamps to 2.0
    assert report.results["q6.a"].awarded == 2.0
    assert report.results["q7"].awarded == 2.0
    assert report.total_awarded == 10 + 3.0 + 2.0 + 2.0


def test_multi_judge_aggregation(tiny_bundle, monkeypatch):
    totals = iter([1.0, 2.0, 1.0, 2.0, 1.0, 2.0])  # alternating per judge call

    def produce(parts):
        return JudgeVerdict(criteria=[], total_points=next(totals), overall_rationale="ok")

    monkeypatch.setattr(
        judge_module, "build_agent", fake_build_agent({JudgeVerdict: produce})
    )

    sheet = perfect_sheet()
    # Keep only holistic judge questions to make expectations simple.
    sheet.answers = {
        qid: ans for qid, ans in sheet.answers.items() if qid in ("q6.a", "q7")
    }
    report = run_grade(tiny_bundle, sheet, judge_models=["test:a", "test:b"])
    assert report.results["q6.a"].awarded == 1.5  # mean(1.0, 2.0)
    assert report.results["q6.a"].detail["totals"] == [1.0, 2.0]
    assert len(report.results["q6.a"].judge_verdicts) == 2
    # 2 questions x 2 judges = 4 calls, tracked per judge model.
    assert report.usage is not None
    assert set(report.usage.phases) == {"judge:test:a", "judge:test:b"}
    assert report.usage.total.requests == 4


def test_failing_judge_does_not_sink_run(tiny_bundle, monkeypatch):
    def explode(parts):
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        judge_module, "build_agent", fake_build_agent({JudgeVerdict: explode})
    )
    sheet = perfect_sheet()
    report = run_grade(tiny_bundle, sheet)
    assert report.results["q6.a"].mode == "error"
    assert any("failed" in w for w in report.warnings)
    # Deterministic questions still graded.
    assert report.results["q1"].awarded == 2.0


def test_answer_type_mismatch_is_error_not_crash(tiny_bundle):
    sheet = imperfect_sheet()
    # Swap q1's answer for a text answer (bypassing schema validation).
    from any_to_bench.schemas.answers import TextAnswer

    sheet.answers["q1"] = TextAnswer(text="B")
    report = run_grade(tiny_bundle, sheet)
    assert report.results["q1"].mode == "error"
    assert report.results["q1"].awarded == 0.0
