"""Exam/content model validators."""

import pytest
from pydantic import ValidationError

from any_to_bench.schemas.content import TableBlock, TextBlock, content_to_markdown
from any_to_bench.schemas.exam import (
    Exam,
    Option,
    Question,
    QuestionType,
    Section,
)
from tests.conftest import build_tiny_exam


def _text(md):
    return [TextBlock(markdown=md)]


def _choice(qid: str, points: float = 1.0) -> Question:
    return Question(
        id=qid,
        type=QuestionType.single_choice,
        prompt=_text("pick"),
        points=points,
        options=[Option(id="A", content=_text("a")), Option(id="B", content=_text("b"))],
    )


def test_tiny_exam_is_valid():
    exam = build_tiny_exam()
    assert exam.total_points == 17.0
    assert [q.id for q in exam.iter_leaves()] == [
        "q1", "q2", "q3", "q4", "q5", "q6.a", "q6.b", "q7",
    ]


def test_choice_requires_options():
    with pytest.raises(ValidationError, match="requires at least 2 options"):
        Question(id="x", type=QuestionType.single_choice, prompt=_text("p"), points=1.0)


def test_options_forbidden_on_non_choice():
    with pytest.raises(ValidationError, match="options only allowed"):
        Question(
            id="x",
            type=QuestionType.essay,
            prompt=_text("p"),
            points=1.0,
            options=[Option(id="A", content=_text("a")), Option(id="B", content=_text("b"))],
        )


def test_fill_in_blank_requires_blanks():
    with pytest.raises(ValidationError, match="requires blanks"):
        Question(id="x", type=QuestionType.fill_in_blank, prompt=_text("p"), points=1.0)


def test_composite_points_must_sum():
    with pytest.raises(ValidationError, match="sum of children"):
        Question(
            id="x",
            type=QuestionType.composite,
            prompt=_text("p"),
            points=5.0,
            children=[_choice("x.a", 1.0), _choice("x.b", 1.0)],
        )


def test_duplicate_question_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate question id"):
        Exam(
            exam_id="e",
            title="t",
            total_points=2.0,
            sections=[Section(id="s", questions=[_choice("q1"), _choice("q1")])],
        )


def test_total_points_must_match_leaves():
    with pytest.raises(ValidationError, match="total_points"):
        Exam(
            exam_id="e",
            title="t",
            total_points=99.0,
            sections=[Section(id="s", questions=[_choice("q1")])],
        )


def test_content_to_markdown_renders_all_blocks():
    from any_to_bench.schemas.content import ImageBlock

    text = content_to_markdown(
        [
            TextBlock(markdown="Hello"),
            ImageBlock(asset="assets/x.png", alt="a chart", caption="Fig 1"),
            TableBlock(header=["a", "b"], rows=[["1", "2"]]),
        ]
    )
    assert "Hello" in text
    assert "[Figure: a chart] (Fig 1)" in text
    assert "| a | b |" in text
    assert "| 1 | 2 |" in text
