"""Per-option judged multiple choice: schema, grader, validation, and ingestion."""

import pytest
from PIL import Image
from pydantic import ValidationError

import any_to_bench.ingest.pipeline as pipeline_module
from any_to_bench.bundle import validate_bundle
from any_to_bench.grade.deterministic import AnswerTypeMismatch, grade_per_option
from any_to_bench.ingest.pipeline import run_ingest
from any_to_bench.schemas.answers import MultipleChoiceAnswer, TextAnswer
from any_to_bench.schemas.extraction import (
    ExtractionChunk,
    GradingExtraction,
    MaterialInventory,
    PerOptionScoring,
)
from any_to_bench.schemas.grading import PerOptionRule
from tests.conftest import build_tiny_bundle, fake_build_agent
from tests.test_ingest_pipeline import ANSWER_KEY, EXTRACTION, INVENTORY

# GSAT-style: all correct -> full, wrong on 1 option -> 3/5, on 2 -> 1/5, more -> 0.
GSAT_RULE = PerOptionRule(correct=["A", "C", "E"], ratio_by_errors=[1.0, 0.6, 0.2])


def _grade(selected: list[str]) -> tuple[float, dict]:
    return grade_per_option(GSAT_RULE, 5.0, 0.0, MultipleChoiceAnswer(selected=selected))


def test_per_option_grading_table():
    assert _grade(["A", "C", "E"])[0] == 5.0  # k=0
    awarded, detail = _grade(["A", "C"])  # missed E: k=1
    assert awarded == pytest.approx(3.0)
    assert detail["errors"] == 1 and detail["ratio"] == 0.6
    assert _grade(["A", "C", "E", "B"])[0] == pytest.approx(3.0)  # extra B: k=1
    assert _grade(["A", "E", "B"])[0] == pytest.approx(1.0)  # diff {B,C}: k=2
    assert _grade(["A", "B"])[0] == 0.0  # diff {B,C,E}: k=3, beyond the table


def test_per_option_blank_scores_zero():
    awarded, detail = _grade([])
    assert awarded == 0.0
    assert detail["blank"] is True


def test_per_option_wrong_answer_type_raises():
    with pytest.raises(AnswerTypeMismatch):
        grade_per_option(GSAT_RULE, 5.0, 0.0, TextAnswer(text="A, C, E"))


def test_ratio_bounds_validated():
    with pytest.raises(ValidationError, match=r"\[0, 1\]"):
        PerOptionRule(correct=["A"], ratio_by_errors=[1.2])


def test_validate_bundle_accepts_per_option_on_multiple_choice(tmp_path):
    bundle = build_tiny_bundle(tmp_path / "bundle")
    q2 = bundle.grading.questions["q2"]
    q2.rule = PerOptionRule(correct=["A", "C"], ratio_by_errors=[1.0, 0.5])
    bundle.save()
    assert validate_bundle(bundle.root) == []


def test_validate_bundle_rejects_per_option_on_single_choice(tmp_path):
    bundle = build_tiny_bundle(tmp_path / "bundle")
    q1 = bundle.grading.questions["q1"]
    q1.rule = PerOptionRule(correct=["B"], ratio_by_errors=[1.0])
    bundle.save()
    problems = validate_bundle(bundle.root)
    assert any("q1" in p and "per_option" in p for p in problems)


def test_validate_bundle_checks_per_option_correct_ids(tmp_path):
    bundle = build_tiny_bundle(tmp_path / "bundle")
    q2 = bundle.grading.questions["q2"]
    q2.rule = PerOptionRule(correct=["A", "Z"], ratio_by_errors=[1.0, 0.5])
    bundle.save()
    problems = validate_bundle(bundle.root)
    assert any("'Z' not in options" in p for p in problems)


@pytest.fixture
def exam_pdf(tmp_path):
    pages = [Image.new("RGB", (400, 560), color) for color in ("white", "ivory")]
    path = tmp_path / "exam.pdf"
    pages[0].save(path, format="PDF", save_all=True, append_images=pages[1:])
    return path


def _multi_choice_extraction() -> ExtractionChunk:
    """The shared EXTRACTION with q1 turned into a multiple-choice question."""
    chunk = EXTRACTION.model_copy(deep=True)
    q1 = chunk.questions[0]
    q1.question_type = pipeline_module.QuestionType.multiple_choice
    return chunk


def test_ingest_builds_per_option_rule_when_scoring_stated(exam_pdf, tmp_path, monkeypatch):
    key = ANSWER_KEY.model_copy(deep=True)
    key.multi_choice_scoring = PerOptionScoring(ratio_by_errors=[1.0, 0.6, 0.2])
    monkeypatch.setattr(
        pipeline_module,
        "build_agent",
        fake_build_agent(
            {
                MaterialInventory: INVENTORY,
                ExtractionChunk: _multi_choice_extraction(),
                GradingExtraction: key,
            }
        ),
    )
    out = tmp_path / "bundle"
    bundle = run_ingest([exam_pdf], out, model="test:ingest")

    assert validate_bundle(out) == []
    rule = bundle.grading.questions["q1"].rule
    assert isinstance(rule, PerOptionRule)
    assert rule.correct == ["B"]
    assert rule.ratio_by_errors == [1.0, 0.6, 0.2]


def test_ingest_keeps_choice_rule_without_scoring(exam_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(
        pipeline_module,
        "build_agent",
        fake_build_agent(
            {
                MaterialInventory: INVENTORY,
                ExtractionChunk: _multi_choice_extraction(),
                GradingExtraction: ANSWER_KEY,
            }
        ),
    )
    out = tmp_path / "bundle"
    bundle = run_ingest([exam_pdf], out, model="test:ingest")
    rule = bundle.grading.questions["q1"].rule
    assert rule.kind == "choice"
    assert rule.partial_credit is True
