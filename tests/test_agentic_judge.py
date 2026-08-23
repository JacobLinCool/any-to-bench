"""Offline agentic judging: batch verdicts via a fake CLI runner."""

import any_to_bench.agentic.runner as runner_module
import any_to_bench.grade.judge as judge_module
from any_to_bench.agentic.judge import (
    agentic_judge,
    build_judge_tasks,
    generate_verdicts_schema,
)
from any_to_bench.agentic.runner import AgenticError
from any_to_bench.grade.aggregate import run_grade
from any_to_bench.llm import UsageTracker
from any_to_bench.schemas.report import JudgeVerdict
from any_to_bench.util import write_json
from tests.conftest import FakeAgenticRun, fake_build_agent, perfect_sheet

VALID_VERDICTS = {
    "verdicts": {
        "q6.a": {"criteria": [], "total_points": 2.0, "overall_rationale": "correct"},
        "q6.b": {
            "criteria": [
                {"criterion_id": "content", "points": 1.8, "rationale": "mostly right"},
                {"criterion_id": "clarity", "points": 1.0, "rationale": "clear"},
            ],
            "total_points": 2.8,
            "overall_rationale": "good",
        },
        "q7": {"criteria": [], "total_points": 2.0, "overall_rationale": "ok"},
    }
}


def judge_rules_of(bundle, qids=("q6.a", "q6.b", "q7")):
    return {qid: bundle.grading.questions[qid] for qid in qids}


def write_verdicts(payload):
    return lambda ws: write_json(ws / "output" / "verdicts.json", payload)


def test_verdicts_schema_shape(tiny_bundle):
    schema = generate_verdicts_schema(judge_rules_of(tiny_bundle))
    per_q = schema["properties"]["verdicts"]["properties"]
    rubric_criteria = per_q["q6.b"]["properties"]["criteria"]
    assert rubric_criteria["minItems"] == rubric_criteria["maxItems"] == 2
    assert rubric_criteria["items"]["properties"]["criterion_id"]["enum"] == [
        "content",
        "clarity",
    ]
    assert per_q["q6.a"]["properties"]["criteria"] == {"type": "array", "maxItems": 0}
    assert schema["properties"]["verdicts"]["required"] == ["q6.a", "q6.b", "q7"]


def test_build_judge_tasks(tiny_bundle):
    tasks = build_judge_tasks(tiny_bundle, perfect_sheet(), judge_rules_of(tiny_bundle))
    by_id = {t["question_id"]: t for t in tasks["tasks"]}
    assert set(by_id) == {"q6.a", "q6.b", "q7"}
    assert by_id["q6.b"]["rubric"][0]["id"] == "content"
    assert by_id["q6.b"]["max_points"] == 3.0
    # Composite parent context (the shared passage) is included in the rendering.
    assert "photosynthesis" in by_id["q6.a"]["question_text"]
    assert by_id["q7"]["student_answer_text"].startswith("(Drawing")
    assert by_id["q6.a"]["reference_answer"] == "Chlorophyll."


def test_agentic_judge_snaps_and_tracks_usage(tiny_bundle, monkeypatch):
    fake = FakeAgenticRun([write_verdicts(VALID_VERDICTS)])
    monkeypatch.setattr(runner_module, "run_codex", fake)
    warnings: list[str] = []
    tracker = UsageTracker()

    verdicts = agentic_judge(
        tiny_bundle,
        perfect_sheet(),
        judge_rules_of(tiny_bundle),
        "codex:test",
        warnings,
        tracker,
    )

    assert set(verdicts) == {"q6.a", "q6.b", "q7"}
    assert verdicts["q6.b"].total_points == 3.0  # 1.8 snapped up to level 2.0, + 1.0
    assert any("snapped" in w and "codex:test" in w for w in warnings)
    summary = tracker.summary()
    assert summary is not None
    assert set(summary.phases) == {"judge:codex:test"}
    assert fake.calls[0]["cli_model"] == "test"


def test_agentic_judge_fix_loop_on_criterion_set(tiny_bundle, monkeypatch):
    duplicated = {
        "verdicts": {
            **VALID_VERDICTS["verdicts"],
            "q6.b": {
                "criteria": [
                    {"criterion_id": "content", "points": 2.0, "rationale": "a"},
                    {"criterion_id": "content", "points": 1.0, "rationale": "b"},
                ],
                "total_points": 3.0,
                "overall_rationale": "dup",
            },
        }
    }
    fake = FakeAgenticRun([write_verdicts(duplicated), write_verdicts(VALID_VERDICTS)])
    monkeypatch.setattr(runner_module, "run_codex", fake)

    verdicts = agentic_judge(
        tiny_bundle,
        perfect_sheet(),
        judge_rules_of(tiny_bundle),
        "codex:test",
        [],
        UsageTracker(),
    )

    assert len(fake.calls) == 2
    assert "must score exactly" in fake.calls[1]["prompt"]
    assert verdicts["q6.b"].total_points == 3.0


def test_agentic_judge_salvages_partial_verdicts(tiny_bundle, monkeypatch):
    partial = {"verdicts": {k: v for k, v in VALID_VERDICTS["verdicts"].items() if k != "q7"}}
    fake = FakeAgenticRun([write_verdicts(partial)])
    monkeypatch.setattr(runner_module, "run_codex", fake)
    warnings: list[str] = []

    verdicts = agentic_judge(
        tiny_bundle,
        perfect_sheet(),
        judge_rules_of(tiny_bundle),
        "codex:test",
        warnings,
        UsageTracker(),
    )

    assert set(verdicts) == {"q6.a", "q6.b"}
    assert any("q7" in w for w in warnings)
    assert len(fake.calls) == 3  # exhausted the fix loop on the missing verdict


def test_mixed_codex_and_llm_judges(tiny_bundle, monkeypatch):
    codex_verdicts = {
        "verdicts": {
            "q6.a": {"criteria": [], "total_points": 2.0, "overall_rationale": "full"},
            "q7": {"criteria": [], "total_points": 2.0, "overall_rationale": "full"},
        }
    }
    monkeypatch.setattr(
        runner_module, "run_codex", FakeAgenticRun([write_verdicts(codex_verdicts)])
    )
    llm_verdict = JudgeVerdict(criteria=[], total_points=1.0, overall_rationale="meh")
    monkeypatch.setattr(judge_module, "build_agent", fake_build_agent({JudgeVerdict: llm_verdict}))

    sheet = perfect_sheet()
    sheet.answers = {qid: a for qid, a in sheet.answers.items() if qid in ("q6.a", "q7")}
    report = run_grade(tiny_bundle, sheet, judge_models=["codex:test", "test:llm"])

    # Verdict order follows the models list: codex first, then the LLM judge.
    assert report.results["q6.a"].detail["totals"] == [2.0, 1.0]
    assert report.results["q6.a"].awarded == 1.5  # mean
    assert len(report.results["q6.a"].judge_verdicts) == 2
    assert report.usage is not None
    assert set(report.usage.phases) == {"judge:codex:test", "judge:test:llm"}


def test_failing_codex_judge_does_not_sink_run(tiny_bundle, monkeypatch):
    def broken(*args, **kwargs):
        raise AgenticError("codex down")

    monkeypatch.setattr(runner_module, "run_codex", broken)
    llm_verdict = JudgeVerdict(criteria=[], total_points=1.0, overall_rationale="ok")
    monkeypatch.setattr(judge_module, "build_agent", fake_build_agent({JudgeVerdict: llm_verdict}))

    sheet = perfect_sheet()
    sheet.answers = {qid: a for qid, a in sheet.answers.items() if qid in ("q6.a", "q7")}
    report = run_grade(tiny_bundle, sheet, judge_models=["codex:test", "test:llm"])

    assert any("judge codex:test failed" in w for w in report.warnings)
    assert report.results["q6.a"].mode == "judge"  # the LLM judge still counted
    assert report.results["q6.a"].awarded == 1.0
