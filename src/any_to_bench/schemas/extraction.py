"""LLM-facing intermediate models used during ingestion.

These are never written to the bundle. Design constraints for provider-native
structured output (OpenAI json_schema strict mode, Gemini response_schema):
no dynamic dict keys (use key/value item lists instead) and bounded nesting
(one level of sub-questions).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from any_to_bench.schemas.content import TableBlock, TextBlock
from any_to_bench.schemas.exam import QuestionType

PageRole = Literal["questions", "answer_key", "solutions", "rubric", "cover", "other"]


class PageClassification(BaseModel):
    page_index: int = Field(description="0-based index of the page as presented")
    role: PageRole
    note: str | None = Field(description="Anything notable about this page, else null")


class MaterialInventory(BaseModel):
    """Result of the inventory pass over all source pages."""

    title: str = Field(description="Exam title as printed (or a sensible description)")
    language: str = Field(description="BCP-47 language tag of the exam, e.g. 'zh-TW'")
    subject: str | None = Field(description="Subject, e.g. 'Physics', else null")
    last_question_number: int | None = Field(
        description=(
            "The highest printed question number in the exam, when the materials "
            "state it clearly (cover/instruction pages often print 'questions 1 "
            "to N'); null if unsure"
        )
    )
    pages: list[PageClassification]


class FigureRef(BaseModel):
    """A figure on a source page, located by a normalized bounding box."""

    type: Literal["figure"] = "figure"
    page_index: int = Field(description="0-based index of the page the figure is on")
    bbox: tuple[float, float, float, float] = Field(
        description="Normalized (x0, y0, x1, y1) with 0,0 at the top-left of the page"
    )
    alt: str = Field(description="Detailed description of the figure's content")
    caption: str | None = Field(description="Printed caption, else null")


ExtractedBlock = Annotated[TextBlock | TableBlock | FigureRef, Field(discriminator="type")]


class ExtractedOption(BaseModel):
    id: str = Field(description="Option label as printed, e.g. 'A'")
    blocks: list[ExtractedBlock]


class ExtractedBlank(BaseModel):
    id: str = Field(description="Assign 'b1', 'b2', ... in reading order")
    label: str | None = Field(description="Printed label like '(i)', else null")


class ExtractedMatchItem(BaseModel):
    id: str = Field(description="Assign 'L1'.. for left items, 'R1'.. for right items")
    blocks: list[ExtractedBlock]


class ExtractedMatching(BaseModel):
    left: list[ExtractedMatchItem]
    right: list[ExtractedMatchItem]


class ExtractedSubQuestion(BaseModel):
    """A sub-question of a composite question (no further nesting)."""

    number: str = Field(description="Printed label, e.g. '(a)'")
    question_type: QuestionType
    blocks: list[ExtractedBlock]
    points: float | None = Field(description="Printed point value, else null")
    options: list[ExtractedOption] | None
    blanks: list[ExtractedBlank] | None
    matching: ExtractedMatching | None


class ExtractedQuestion(BaseModel):
    number: str = Field(description="Printed question number, e.g. '1.'")
    question_type: QuestionType
    blocks: list[ExtractedBlock] = Field(description="The question prompt, verbatim")
    points: float | None = Field(description="Printed point value, else null")
    options: list[ExtractedOption] | None
    blanks: list[ExtractedBlank] | None
    matching: ExtractedMatching | None
    children: list[ExtractedSubQuestion] | None = Field(
        description="Sub-questions when question_type is 'composite', else null"
    )


class ExtractionChunk(BaseModel):
    """Questions extracted from one chunk of pages."""

    continues_previous: bool = Field(
        description="True if the first question here continues one cut off in the previous chunk"
    )
    questions: list[ExtractedQuestion]


class KeyValue(BaseModel):
    key: str
    values: list[str] = Field(description="Accepted answers for this key")


class PairKey(BaseModel):
    left: str
    right: str


class ExtractedRubricLevel(BaseModel):
    points: float
    descriptor: str


class ExtractedRubricCriterion(BaseModel):
    id: str = Field(description="Short slug, e.g. 'thesis', 'evidence'")
    description: str
    levels: list[ExtractedRubricLevel]


class ExtractedAnswerKey(BaseModel):
    """Answer/solution/rubric info for one question, matched by printed number."""

    question_number: str = Field(
        description="Printed number this key belongs to, e.g. '1.' or '2.(a)'"
    )
    correct_options: list[str] | None = Field(
        description="Correct option ids for choice questions, else null"
    )
    true_false: bool | None = Field(description="Correct value for true/false questions, else null")
    blank_answers: list[KeyValue] | None = Field(
        description="For fill-in-blank: blank id/label -> accepted answers, else null"
    )
    matching_pairs: list[PairKey] | None = Field(
        description="For matching: correct left->right pairs, else null"
    )
    solution_text: str | None = Field(
        description="Worked solution or reference answer (Markdown), else null"
    )
    solution_figures: list[FigureRef] | None = Field(
        description="Figures in the solution, else null"
    )
    rubric: list[ExtractedRubricCriterion] | None = Field(
        description="Scoring rubric for open-ended questions, else null"
    )
    judge_instructions: str | None = Field(
        description="Scoring guidance prose for graders, else null"
    )


class PerOptionScoring(BaseModel):
    """An exam-wide per-option scoring rule for multiple-choice questions."""

    ratio_by_errors: list[float] = Field(
        description=(
            "Score ratio indexed by the number of wrongly judged options, copied "
            "from the printed rule; e.g. 'all correct: full points; wrong on 1 "
            "option: 3/5; wrong on 2: 1/5; more or blank: 0' -> [1.0, 0.6, 0.2]"
        )
    )


class GradingExtraction(BaseModel):
    """Result of one answers/rubric extraction call."""

    entries: list[ExtractedAnswerKey]
    multi_choice_scoring: PerOptionScoring | None = Field(
        description=(
            "If the exam's general instructions define per-option scoring for "
            "multiple-choice questions (each option judged independently, score "
            "determined by how many options were judged wrongly), the ratio "
            "table; else null"
        )
    )
