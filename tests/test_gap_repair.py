"""Chunk-gap detection and repair: merge helpers + the pipeline repair pass."""

import pytest
from PIL import Image

import any_to_bench.ingest.pipeline as pipeline_module
from any_to_bench.bundle import validate_bundle
from any_to_bench.ingest.merge import covered_numbers, find_gaps, insert_recovered
from any_to_bench.ingest.pipeline import run_ingest
from any_to_bench.schemas.content import TextBlock
from any_to_bench.schemas.exam import QuestionType
from any_to_bench.schemas.extraction import (
    ExtractedOption,
    ExtractedQuestion,
    ExtractedSubQuestion,
    ExtractionChunk,
    MaterialInventory,
    PageClassification,
)
from tests.conftest import fake_build_agent


def q(number: str, children: list[str] | None = None) -> ExtractedQuestion:
    kids = [
        ExtractedSubQuestion(
            number=n,
            question_type=QuestionType.short_answer,
            blocks=[TextBlock(markdown="sub")],
            points=1.0,
            options=None,
            blanks=None,
            matching=None,
        )
        for n in (children or [])
    ]
    return ExtractedQuestion(
        number=number,
        question_type=QuestionType.composite if kids else QuestionType.short_answer,
        blocks=[TextBlock(markdown=f"question {number}")],
        points=None if kids else 1.0,
        options=None,
        blanks=None,
        matching=None,
        children=kids or None,
    )


def choice_q(number: str) -> ExtractedQuestion:
    return ExtractedQuestion(
        number=number,
        question_type=QuestionType.single_choice,
        blocks=[TextBlock(markdown=f"question {number}")],
        points=2.0,
        options=[
            ExtractedOption(id="A", blocks=[TextBlock(markdown="yes")]),
            ExtractedOption(id="B", blocks=[TextBlock(markdown="no")]),
        ],
        blanks=None,
        matching=None,
        children=None,
    )


class TestCoveredNumbers:
    def test_leading_int(self):
        assert covered_numbers(q("12.")) == {12}
        assert covered_numbers(q("第 3 題")) == {3}

    def test_range_number_covers_whole_span(self):
        assert covered_numbers(q("39～41")) == {39, 40, 41}
        assert covered_numbers(q("第39-41題為題組")) == {39, 40, 41}

    def test_numeric_children_are_covered(self):
        assert covered_numbers(q("題組", children=["40.", "41."])) == {40, 41}

    def test_letter_children_add_nothing(self):
        assert covered_numbers(q("5.", children=["(a)", "(b)"])) == {5}


class TestFindGaps:
    def test_no_gap(self):
        runs, reason = find_gaps([q("1."), q("2."), q("3.")])
        assert runs == [] and reason is None

    def test_interior_gap_grouped_into_runs(self):
        runs, _ = find_gaps([q("1."), q("4."), q("6.")])
        assert [list(r) for r in runs] == [[2, 3], [5]]

    def test_range_numbers_do_not_create_phantom_gaps(self):
        runs, _ = find_gaps([q("38."), q("39～41"), q("42.")])
        assert runs == []

    def test_non_monotonic_is_skipped_with_reason(self):
        runs, reason = find_gaps([q("1."), q("2."), q("1."), q("2.")])
        assert runs == []
        assert "not monotonic" in reason

    def test_expected_last_extends_the_search(self):
        runs, _ = find_gaps([q("1."), q("2.")], expected_last=4)
        assert [list(r) for r in runs] == [[3, 4]]

    def test_too_few_numbers_is_silent(self):
        runs, reason = find_gaps([q("only")])
        assert runs == [] and reason is None


class TestInsertRecovered:
    def test_inserts_in_numeric_position(self):
        merged = insert_recovered([q("1."), q("3.")], [q("2.")])
        assert [x.number for x in merged] == ["1.", "2.", "3."]

    def test_inserts_at_head(self):
        merged = insert_recovered([q("2."), q("3.")], [q("1.")])
        assert [x.number for x in merged] == ["1.", "2.", "3."]

    def test_non_numeric_neighbors_stay_glued(self):
        merged = insert_recovered([q("1."), q("附註"), q("3.")], [q("2.")])
        assert [x.number for x in merged] == ["1.", "附註", "2.", "3."]

    def test_multiple_recovered_sorted(self):
        merged = insert_recovered([q("1."), q("5.")], [q("4."), q("2.")])
        assert [x.number for x in merged] == ["1.", "2.", "4.", "5."]


@pytest.fixture
def exam_pdf(tmp_path):
    pages = [Image.new("RGB", (400, 560), color) for color in ("white", "ivory")]
    path = tmp_path / "exam.pdf"
    pages[0].save(path, format="PDF", save_all=True, append_images=pages[1:])
    return path


INVENTORY = MaterialInventory(
    title="Gap Quiz",
    language="en",
    subject=None,
    last_question_number=None,
    pages=[
        PageClassification(page_index=0, role="questions", note=None),
        PageClassification(page_index=1, role="questions", note=None),
    ],
)


def test_pipeline_repairs_chunk_gap(exam_pdf, tmp_path, monkeypatch):
    # Two single-page chunks: page 0 yields q1, page 1 yields q3 — q2 fell in
    # the boundary. The repair call must recover it.
    monkeypatch.setattr(pipeline_module, "CHUNK_SIZE", 1)
    monkeypatch.setattr(pipeline_module, "CHUNK_OVERLAP", 0)

    chunk_outputs = iter(
        [
            ExtractionChunk(continues_previous=False, questions=[choice_q("1.")]),
            ExtractionChunk(continues_previous=False, questions=[choice_q("3.")]),
        ]
    )
    repair_calls: list[list] = []

    def produce(parts):
        if "MISSED the question(s)" in parts[0]:
            repair_calls.append(parts)
            return ExtractionChunk(continues_previous=False, questions=[choice_q("2.")])
        return next(chunk_outputs)

    monkeypatch.setattr(
        pipeline_module,
        "build_agent",
        fake_build_agent({MaterialInventory: INVENTORY, ExtractionChunk: produce}),
    )
    out = tmp_path / "bundle"
    bundle = run_ingest([exam_pdf], out, model="test:ingest")

    assert validate_bundle(out) == []
    assert [x.number for x in bundle.exam.iter_leaves()] == ["1.", "2.", "3."]
    assert [x.id for x in bundle.exam.iter_leaves()] == ["q1", "q2", "q3"]
    assert len(repair_calls) == 1
    assert "printed number(s) 2" in repair_calls[0][0]
    assert any("missed by chunked extraction" in w for w in bundle.manifest.warnings)
    assert "extract-repair" in bundle.manifest.usage.phases


def test_pipeline_repair_filters_disobedient_output(exam_pdf, tmp_path, monkeypatch):
    # The repair call re-extracts a bracketing question too; only q2 may enter.
    monkeypatch.setattr(pipeline_module, "CHUNK_SIZE", 1)
    monkeypatch.setattr(pipeline_module, "CHUNK_OVERLAP", 0)
    chunk_outputs = iter(
        [
            ExtractionChunk(continues_previous=False, questions=[choice_q("1.")]),
            ExtractionChunk(continues_previous=False, questions=[choice_q("3.")]),
        ]
    )

    def produce(parts):
        if "MISSED the question(s)" in parts[0]:
            return ExtractionChunk(
                continues_previous=False, questions=[choice_q("1."), choice_q("2.")]
            )
        return next(chunk_outputs)

    monkeypatch.setattr(
        pipeline_module,
        "build_agent",
        fake_build_agent({MaterialInventory: INVENTORY, ExtractionChunk: produce}),
    )
    bundle = run_ingest([exam_pdf], tmp_path / "bundle", model="test:ingest")
    assert [x.number for x in bundle.exam.iter_leaves()] == ["1.", "2.", "3."]


def test_repair_guardrail_skips_absurd_gaps(monkeypatch):
    # A misread "30." would imply 27 missing questions; repair must not fire.
    class Boom:
        def run_sync(self, parts):
            raise AssertionError("repair should have been skipped")

    warnings: list[str] = []
    from any_to_bench.ingest.pipeline import _repair_gaps
    from any_to_bench.llm import UsageTracker

    result = _repair_gaps(
        [q("1."), q("30.")],
        chunk_results=[],
        question_pages=[],
        extract_agent=Boom(),
        base_context="Exam: X.",
        tracker=UsageTracker(),
        warnings=warnings,
        expected_last=None,
    )
    assert [x.number for x in result] == ["1.", "30."]
    assert any("too many to repair" in w for w in warnings)


def test_pipeline_repair_still_missing_warns(exam_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_module, "CHUNK_SIZE", 1)
    monkeypatch.setattr(pipeline_module, "CHUNK_OVERLAP", 0)
    chunk_outputs = iter(
        [
            ExtractionChunk(continues_previous=False, questions=[choice_q("1.")]),
            ExtractionChunk(continues_previous=False, questions=[choice_q("3.")]),
        ]
    )

    def produce(parts):
        if "MISSED the question(s)" in parts[0]:
            return ExtractionChunk(continues_previous=False, questions=[])
        return next(chunk_outputs)

    monkeypatch.setattr(
        pipeline_module,
        "build_agent",
        fake_build_agent({MaterialInventory: INVENTORY, ExtractionChunk: produce}),
    )
    bundle = run_ingest([exam_pdf], tmp_path / "bundle", model="test:ingest")
    assert any("still missing after re-extraction" in w for w in bundle.manifest.warnings)
