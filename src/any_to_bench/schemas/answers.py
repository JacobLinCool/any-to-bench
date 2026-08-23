"""Answer sheet models and the per-exam strict JSON Schema generator."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from any_to_bench.schemas.exam import Exam, Question, QuestionType
from any_to_bench.schemas.resources import Citation, ResourceAccess
from any_to_bench.schemas.usage import UsageSummary


class CitedAnswer(BaseModel):
    citations: list[Citation] | None = Field(
        default=None,
        description="Optional evidence from the bundle's public resource corpus",
        exclude_if=lambda value: value is None,
    )


class SingleChoiceAnswer(CitedAnswer):
    type: Literal["single_choice"] = "single_choice"
    selected: str = Field(description="The chosen option id")


class MultipleChoiceAnswer(CitedAnswer):
    type: Literal["multiple_choice"] = "multiple_choice"
    selected: list[str] = Field(description="All chosen option ids")


class TrueFalseAnswer(CitedAnswer):
    type: Literal["true_false"] = "true_false"
    value: bool


class FillInBlankAnswer(CitedAnswer):
    type: Literal["fill_in_blank"] = "fill_in_blank"
    blanks: dict[str, str] = Field(description="Blank id -> answer text")


class MatchingAnswer(CitedAnswer):
    type: Literal["matching"] = "matching"
    pairs: dict[str, str] = Field(description="Left item id -> right item id")


class TextAnswer(CitedAnswer):
    """Answer for short_answer and essay questions."""

    type: Literal["text"] = "text"
    text: str = Field(description="The answer in Markdown (math as LaTeX)")


class DrawingAnswer(CitedAnswer):
    type: Literal["drawing"] = "drawing"
    description: str = Field(
        description="Precise textual description of the drawing (shapes, labels, positions)"
    )
    image_asset: str | None = Field(
        default=None,
        description="Optional path (or data URI) of a rendered image of the drawing",
    )


AnswerValue = Annotated[
    SingleChoiceAnswer
    | MultipleChoiceAnswer
    | TrueFalseAnswer
    | FillInBlankAnswer
    | MatchingAnswer
    | TextAnswer
    | DrawingAnswer,
    Field(discriminator="type"),
]

ANSWER_MODEL_FOR_TYPE: dict[QuestionType, type[BaseModel]] = {
    QuestionType.single_choice: SingleChoiceAnswer,
    QuestionType.multiple_choice: MultipleChoiceAnswer,
    QuestionType.true_false: TrueFalseAnswer,
    QuestionType.fill_in_blank: FillInBlankAnswer,
    QuestionType.matching: MatchingAnswer,
    QuestionType.short_answer: TextAnswer,
    QuestionType.essay: TextAnswer,
    QuestionType.drawing: DrawingAnswer,
}


class AnswerSheet(BaseModel):
    exam_id: str
    taker: str | None = Field(default=None, description="Who answered, e.g. a model id")
    answers: dict[str, AnswerValue] = Field(description="Leaf question id -> answer")
    usage: UsageSummary | None = Field(
        default=None, description="Token usage spent producing this sheet, if known"
    )
    resource_access: ResourceAccess | None = Field(
        default=None,
        description="Public corpus actually exposed to this taker, if known",
        exclude_if=lambda value: value is None,
    )


def _allow_citations(schema: dict[str, Any], enabled: bool) -> dict[str, Any]:
    if enabled:
        schema["properties"]["citations"] = {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "excerpt": {"type": "string", "minLength": 1},
                },
                "required": ["path", "excerpt"],
                "additionalProperties": False,
            },
        }
    return schema


def _question_answer_schema(q: Question, allow_citations: bool = False) -> dict[str, Any]:
    """Strict JSON Schema for one question's answer, narrowed to its ids."""
    t = q.type
    if t is QuestionType.single_choice:
        assert q.options is not None
        return _allow_citations(
            {
                "type": "object",
                "properties": {
                    "type": {"const": "single_choice"},
                    "selected": {"enum": [o.id for o in q.options]},
                },
                "required": ["type", "selected"],
                "additionalProperties": False,
            },
            allow_citations,
        )
    if t is QuestionType.multiple_choice:
        assert q.options is not None
        return _allow_citations(
            {
                "type": "object",
                "properties": {
                    "type": {"const": "multiple_choice"},
                    "selected": {
                        "type": "array",
                        "items": {"enum": [o.id for o in q.options]},
                        "uniqueItems": True,
                    },
                },
                "required": ["type", "selected"],
                "additionalProperties": False,
            },
            allow_citations,
        )
    if t is QuestionType.true_false:
        return _allow_citations(
            {
                "type": "object",
                "properties": {
                    "type": {"const": "true_false"},
                    "value": {"type": "boolean"},
                },
                "required": ["type", "value"],
                "additionalProperties": False,
            },
            allow_citations,
        )
    if t is QuestionType.fill_in_blank:
        assert q.blanks is not None
        blank_ids = [b.id for b in q.blanks]
        return _allow_citations(
            {
                "type": "object",
                "properties": {
                    "type": {"const": "fill_in_blank"},
                    "blanks": {
                        "type": "object",
                        "properties": {bid: {"type": "string"} for bid in blank_ids},
                        "required": blank_ids,
                        "additionalProperties": False,
                    },
                },
                "required": ["type", "blanks"],
                "additionalProperties": False,
            },
            allow_citations,
        )
    if t is QuestionType.matching:
        assert q.matching is not None
        left_ids = [i.id for i in q.matching.left]
        right_ids = [i.id for i in q.matching.right]
        return _allow_citations(
            {
                "type": "object",
                "properties": {
                    "type": {"const": "matching"},
                    "pairs": {
                        "type": "object",
                        "properties": {lid: {"enum": right_ids} for lid in left_ids},
                        "required": left_ids,
                        "additionalProperties": False,
                    },
                },
                "required": ["type", "pairs"],
                "additionalProperties": False,
            },
            allow_citations,
        )
    if t in (QuestionType.short_answer, QuestionType.essay):
        return _allow_citations(
            {
                "type": "object",
                "properties": {
                    "type": {"const": "text"},
                    "text": {"type": "string"},
                },
                "required": ["type", "text"],
                "additionalProperties": False,
            },
            allow_citations,
        )
    if t is QuestionType.drawing:
        return _allow_citations(
            {
                "type": "object",
                "properties": {
                    "type": {"const": "drawing"},
                    "description": {"type": "string"},
                    "image_asset": {"type": ["string", "null"]},
                },
                "required": ["type", "description"],
                "additionalProperties": False,
            },
            allow_citations,
        )
    raise ValueError(f"question {q.id}: type {t} is not answerable")


def generate_answer_schema(exam: Exam, *, allow_citations: bool = False) -> dict[str, Any]:
    """Generate the strict JSON Schema an answer sheet for this exam must satisfy."""
    leaves = list(exam.iter_leaves())
    result = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"Answer sheet for {exam.title}",
        "type": "object",
        "properties": {
            "exam_id": {"const": exam.exam_id},
            "taker": {"type": ["string", "null"]},
            "usage": {"type": ["object", "null"]},
            "answers": {
                "type": "object",
                "properties": {q.id: _question_answer_schema(q, allow_citations) for q in leaves},
                "required": [q.id for q in leaves],
                "additionalProperties": False,
            },
        },
        "required": ["exam_id", "answers"],
        "additionalProperties": False,
    }
    if allow_citations:
        schema = {
            "type": ["object", "null"],
            "properties": {
                "mode": {"enum": ["all_files", "utf8_text_only", "unknown"]},
                "total_files": {"type": "integer", "minimum": 0},
                "total_bytes": {"type": "integer", "minimum": 0},
                "exposed_files": {"type": "integer", "minimum": 0},
                "exposed_bytes": {"type": "integer", "minimum": 0},
            },
            "required": [
                "mode",
                "total_files",
                "total_bytes",
                "exposed_files",
                "exposed_bytes",
            ],
            "additionalProperties": False,
        }
        result["properties"]["resource_access"] = schema
    return result
