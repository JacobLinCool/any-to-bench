"""Per-question modality requirements and taker gating."""

from pydantic_ai import BinaryContent

import any_to_bench.grade.judge as judge_module
import any_to_bench.solve.runner as solve_runner
from any_to_bench.bench import format_table, run_bench
from any_to_bench.grade.aggregate import run_grade
from any_to_bench.modality import (
    ALL_MODALITIES,
    TEXT_ONLY,
    Modality,
    exam_modalities,
    parse_capabilities,
)
from any_to_bench.schemas.content import ImageBlock
from any_to_bench.schemas.report import JudgeVerdict
from tests.conftest import build_tiny_bundle, fake_build_agent
from tests.test_solve_offline import PERFECT_OUTPUTS


def modalities_of(exam, qid):
    return exam_modalities(exam)[qid].modalities


def test_leaf_requirements_of_the_tiny_exam(tiny_bundle):
    requirements = exam_modalities(tiny_bundle.exam)

    # q1 carries a figure; every other leaf is pure text.
    assert requirements["q1"].modalities == ALL_MODALITIES
    assert requirements["q1"].sources == {"image": ["question:q1"]}
    for qid in ("q2", "q3", "q4", "q5", "q6.a", "q6.b", "q7"):
        assert requirements[qid].modalities == TEXT_ONLY
        assert requirements[qid].sources == {}


def test_section_instruction_image_excludes_the_whole_section(tiny_bundle):
    """Surprising enough that the requirement records where it came from."""
    exam = tiny_bundle.exam.model_copy(deep=True)
    exam.sections[0].instructions.append(ImageBlock(asset="assets/banner.png", alt="a chart"))

    requirements = exam_modalities(exam)

    for qid in ("q2", "q6.a", "q7"):
        assert Modality.image in requirements[qid].modalities
        assert requirements[qid].sources["image"] == ["section:s1"]


def test_composite_stimulus_image_propagates_to_children(tiny_bundle):
    exam = tiny_bundle.exam.model_copy(deep=True)
    composite = next(q for q in exam.sections[0].questions if q.id == "q6")
    composite.prompt.append(ImageBlock(asset="assets/passage.png", alt="a diagram"))

    requirements = exam_modalities(exam)

    for qid in ("q6.a", "q6.b"):
        assert Modality.image in requirements[qid].modalities
        assert requirements[qid].sources["image"] == ["question:q6"]
    assert requirements["q7"].modalities == TEXT_ONLY  # a sibling is unaffected


def test_solve_skips_questions_beyond_the_taker(tiny_bundle, monkeypatch):
    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    skipped: list[str] = []

    sheet = solve_runner.run_solve(
        tiny_bundle, "test:solver", capabilities=TEXT_ONLY, skipped=skipped
    )

    assert skipped == ["q1"]
    assert "q1" not in sheet.answers
    # The stored schema still demands every question, so the relaxation is what
    # makes a subset sheet valid — and it is scoped to the ids actually skipped.
    assert tiny_bundle.validate_answer_sheet(sheet, allow_missing=skipped) == []
    assert tiny_bundle.validate_answer_sheet(sheet) != []


def test_text_only_taker_is_never_sent_image_bytes(tiny_bundle, monkeypatch):
    calls: list = []
    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS, calls=calls))

    solve_runner.run_solve(tiny_bundle, "test:solver", capabilities=TEXT_ONLY, skipped=[])

    sent = [part for _, _, agent in calls for parts in agent.calls for part in parts]
    assert sent  # the text questions really were attempted
    assert not any(isinstance(part, BinaryContent) for part in sent)


def test_capable_taker_still_gets_everything(tiny_bundle, monkeypatch):
    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    skipped: list[str] = []

    sheet = solve_runner.run_solve(
        tiny_bundle, "test:solver", capabilities=ALL_MODALITIES, skipped=skipped
    )

    assert skipped == []
    assert len(sheet.answers) == 8


def test_agentic_taker_is_never_gated(tiny_bundle, monkeypatch):
    """Agentic takers open assets as files, so a modality filter is meaningless."""
    import any_to_bench.agentic.runner as runner_module
    from tests.conftest import FakeAgenticRun
    from tests.test_agentic_solve import write_valid

    monkeypatch.setattr(runner_module, "run_codex", FakeAgenticRun([write_valid]))
    skipped: list[str] = []

    sheet = solve_runner.run_solve(
        tiny_bundle, "codex:test", capabilities=TEXT_ONLY, skipped=skipped
    )

    assert skipped == []
    assert len(sheet.answers) == 8


def test_grade_marks_skipped_and_reports_coverage(tiny_bundle, monkeypatch):
    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    monkeypatch.setattr(
        judge_module,
        "build_agent",
        fake_build_agent({JudgeVerdict: JudgeVerdict(total_points=0.0, overall_rationale="x")}),
    )
    skipped: list[str] = []
    sheet = solve_runner.run_solve(
        tiny_bundle, "test:solver", capabilities=TEXT_ONLY, skipped=skipped
    )

    report = run_grade(tiny_bundle, sheet, capabilities=TEXT_ONLY)

    assert report.results["q1"].mode == "skipped"
    assert report.results["q1"].detail["missing_modalities"] == ["image"]
    assert report.results["q1"].detail["modality_sources"] == {"image": ["question:q1"]}
    assert report.total_max == 17.0  # the exam is still worth what it is worth
    assert report.skipped_count == 1
    assert report.skipped_points == 2.0
    assert report.covered_max == 15.0
    assert any("skipped" in w for w in report.warnings)


def test_grade_without_capabilities_still_calls_it_unanswered(tiny_bundle, monkeypatch):
    """No declaration means no behaviour change for anyone."""
    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    skipped: list[str] = []
    sheet = solve_runner.run_solve(
        tiny_bundle, "test:solver", capabilities=TEXT_ONLY, skipped=skipped
    )

    report = run_grade(tiny_bundle, sheet)

    assert report.results["q1"].mode == "unanswered"
    assert report.skipped_count == 0
    assert report.covered_max == report.total_max


def test_answering_beyond_declared_modalities_is_still_graded(tiny_bundle, monkeypatch):
    """A taker that answered anyway is graded on what it produced."""
    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    sheet = solve_runner.run_solve(tiny_bundle, "test:solver")  # answers everything

    report = run_grade(tiny_bundle, sheet, capabilities=TEXT_ONLY)

    assert report.results["q1"].mode == "deterministic"
    assert report.skipped_count == 0


def test_parse_capabilities():
    assert parse_capabilities(text_only=True) == TEXT_ONLY
    assert parse_capabilities(text_only=False) == ALL_MODALITIES


def test_bench_warns_when_takers_cover_different_subsets(tmp_path, monkeypatch):
    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    monkeypatch.setattr(
        judge_module,
        "build_agent",
        fake_build_agent({JudgeVerdict: JudgeVerdict(total_points=0.0, overall_rationale="x")}),
    )
    bundle = build_tiny_bundle(tmp_path / "bundle")

    report = run_bench(
        bundle,
        ["test:blind", "test:seeing"],
        tmp_path / "out",
        text_only_models=["test:blind"],
    )

    blind, seeing = report.rows
    assert blind.skipped_count == 1
    assert blind.covered_max == 15.0
    assert seeing.covered_max == 17.0
    assert any("different subsets" in w for w in report.warnings)
    table = format_table(report)
    assert "| 15/17 |" in table  # coverage is visible next to the score
    assert "| 17/17 |" in table


def test_bench_warns_on_an_unmatched_text_only_declaration(tiny_bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(solve_runner, "build_agent", fake_build_agent(PERFECT_OUTPUTS))

    report = run_bench(
        tiny_bundle, ["test:solver"], tmp_path / "out", text_only_models=["test:typo"]
    )

    assert any("matches no --model" in w for w in report.warnings)


def test_bench_warns_that_agentic_declaration_is_ignored(tiny_bundle, tmp_path, monkeypatch):
    import any_to_bench.agentic.runner as runner_module
    from tests.conftest import FakeAgenticRun
    from tests.test_agentic_solve import write_valid

    monkeypatch.setattr(runner_module, "run_codex", FakeAgenticRun([write_valid]))

    report = run_bench(
        tiny_bundle, ["codex:test"], tmp_path / "out", text_only_models=["codex:test"]
    )

    assert any("is agentic" in w for w in report.warnings)
    assert report.rows[0].skipped_count == 0
