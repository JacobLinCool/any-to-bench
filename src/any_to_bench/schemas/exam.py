"""The structured exam paper."""

from __future__ import annotations

import math
from collections.abc import Iterator
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from any_to_bench.schemas.content import ContentBlock


class QuestionType(StrEnum):
    single_choice = "single_choice"
    multiple_choice = "multiple_choice"
    true_false = "true_false"
    fill_in_blank = "fill_in_blank"
    matching = "matching"
    short_answer = "short_answer"
    essay = "essay"
    drawing = "drawing"
    composite = "composite"  # container: prompt is a shared stimulus, answers live in children


CHOICE_TYPES = {QuestionType.single_choice, QuestionType.multiple_choice}


class Option(BaseModel):
    id: str = Field(description="Option identifier as printed, e.g. 'A'")
    content: list[ContentBlock]


class Blank(BaseModel):
    id: str = Field(description="Blank identifier, e.g. 'b1'")
    label: str | None = Field(default=None, description="Printed label, e.g. '(i)'")


class MatchItem(BaseModel):
    id: str
    content: list[ContentBlock]


class MatchingSpec(BaseModel):
    left: list[MatchItem]
    right: list[MatchItem] = Field(description="May be longer than left (distractors)")

    @model_validator(mode="after")
    def _unique_ids(self) -> MatchingSpec:
        for side, items in (("left", self.left), ("right", self.right)):
            ids = [i.id for i in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {side} item ids in matching spec")
        return self


class Question(BaseModel):
    id: str = Field(description="Globally unique, stable id, e.g. 'q1', 'q2.a'")
    number: str | None = Field(default=None, description="Display label as printed, e.g. '1.'")
    type: QuestionType
    prompt: list[ContentBlock]
    points: float = Field(ge=0)
    options: list[Option] | None = None
    blanks: list[Blank] | None = None
    matching: MatchingSpec | None = None
    children: list[Question] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_type_invariants(self) -> Question:
        t = self.type
        if t in CHOICE_TYPES:
            if not self.options or len(self.options) < 2:
                raise ValueError(f"question {self.id}: {t.value} requires at least 2 options")
            ids = [o.id for o in self.options]
            if len(ids) != len(set(ids)):
                raise ValueError(f"question {self.id}: duplicate option ids")
        elif self.options:
            raise ValueError(f"question {self.id}: options only allowed on choice questions")

        if t is QuestionType.fill_in_blank:
            if not self.blanks:
                raise ValueError(f"question {self.id}: fill_in_blank requires blanks")
            ids = [b.id for b in self.blanks]
            if len(ids) != len(set(ids)):
                raise ValueError(f"question {self.id}: duplicate blank ids")
        elif self.blanks:
            raise ValueError(f"question {self.id}: blanks only allowed on fill_in_blank questions")

        if t is QuestionType.matching:
            if self.matching is None:
                raise ValueError(f"question {self.id}: matching requires a matching spec")
        elif self.matching is not None:
            raise ValueError(
                f"question {self.id}: matching spec only allowed on matching questions"
            )

        if t is QuestionType.composite:
            if not self.children:
                raise ValueError(f"question {self.id}: composite requires children")
            child_sum = sum(c.points for c in self.children)
            if not math.isclose(child_sum, self.points, abs_tol=1e-6):
                raise ValueError(
                    f"question {self.id}: composite points {self.points} != "
                    f"sum of children {child_sum}"
                )
        elif self.children:
            raise ValueError(f"question {self.id}: only composite questions may have children")
        return self

    def iter_leaves(self) -> Iterator[Question]:
        """Yield answerable (non-composite) questions, depth-first."""
        if self.type is QuestionType.composite:
            for child in self.children:
                yield from child.iter_leaves()
        else:
            yield self


class Section(BaseModel):
    id: str
    title: str | None = None
    instructions: list[ContentBlock] = Field(default_factory=list)
    questions: list[Question]


class Exam(BaseModel):
    schema_version: str = "1"
    exam_id: str
    title: str
    subject: str | None = None
    language: str = "en"
    description: str | None = None
    total_points: float = Field(ge=0)
    sections: list[Section]
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_exam(self) -> Exam:
        seen: set[str] = set()

        def walk(q: Question) -> None:
            if q.id in seen:
                raise ValueError(f"duplicate question id: {q.id}")
            seen.add(q.id)
            for child in q.children:
                walk(child)

        for section in self.sections:
            for q in section.questions:
                walk(q)

        leaf_sum = sum(q.points for q in self.iter_leaves())
        if not math.isclose(leaf_sum, self.total_points, abs_tol=1e-6):
            raise ValueError(
                f"total_points {self.total_points} != sum of leaf question points {leaf_sum}"
            )
        return self

    def iter_leaves(self) -> Iterator[Question]:
        for section in self.sections:
            for q in section.questions:
                yield from q.iter_leaves()

    def leaf_map(self) -> dict[str, Question]:
        return {q.id: q for q in self.iter_leaves()}

    def section_of(self, question_id: str) -> Section | None:
        for section in self.sections:
            for q in section.questions:
                if any(leaf.id == question_id for leaf in q.iter_leaves()):
                    return section
        return None
