"""Chunk merging and question-number normalization."""

from any_to_bench.ingest.merge import merge_chunks, normalize_number
from any_to_bench.schemas.content import TextBlock
from any_to_bench.schemas.exam import QuestionType
from any_to_bench.schemas.extraction import (
    ExtractedQuestion,
    ExtractionChunk,
)


def _q(number: str) -> ExtractedQuestion:
    return ExtractedQuestion(
        number=number,
        question_type=QuestionType.short_answer,
        blocks=[TextBlock(markdown=f"question {number}")],
        points=1.0,
        options=None,
        blanks=None,
        matching=None,
        children=None,
    )


class TestNormalizeNumber:
    def test_equivalent_forms(self):
        assert normalize_number("1.") == normalize_number("1)") == normalize_number("Q1")
        assert normalize_number("2.(a)") == normalize_number("2 (a)") == "2a"
        assert normalize_number("第 3 題") == normalize_number("3.")

    def test_distinct_numbers_stay_distinct(self):
        assert normalize_number("1.") != normalize_number("11.")
        assert normalize_number("2a") != normalize_number("2b")


def test_merge_dedupes_overlap():
    chunks = [
        ExtractionChunk(continues_previous=False, questions=[_q("1."), _q("2."), _q("3.")]),
        # Overlapping page re-extracted question 3; new questions 4 and 5.
        ExtractionChunk(continues_previous=True, questions=[_q("3."), _q("4."), _q("5.")]),
    ]
    merged = merge_chunks(chunks)
    assert [q.number for q in merged] == ["1.", "2.", "3.", "4.", "5."]
    # The first extraction of q3 wins.
    assert merged[2].blocks[0].markdown == "question 3."


def test_merge_empty_chunks():
    assert merge_chunks([ExtractionChunk(continues_previous=False, questions=[])]) == []
