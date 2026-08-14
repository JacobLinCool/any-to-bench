"""Grading spec: deterministic rules and LLM-judge rules."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class Normalization(BaseModel):
    """Text normalization applied before comparing fill-in-blank answers."""

    case_insensitive: bool = True
    strip: bool = True
    collapse_whitespace: bool = True
    unicode_nfkc: bool = True
    numeric_tolerance: float | None = Field(
        default=None,
        description="If both sides parse as numbers, accept within this tolerance",
    )
    numeric_relative: bool = Field(
        default=False, description="Interpret numeric_tolerance as a relative tolerance"
    )


class ChoiceRule(BaseModel):
    kind: Literal["choice"] = "choice"
    correct: list[str] = Field(min_length=1, description="Correct option ids")
    partial_credit: bool = Field(
        default=False, description="Multiple choice: award points * |sel∩correct|/|correct|"
    )
    wrong_selection_penalty: float = Field(
        default=0.0, ge=0, description="Points subtracted per wrong selected option"
    )
    negative_marking: float | None = Field(
        default=None,
        description="If set, a fully wrong answer scores this (typically negative)",
    )


class PerOptionRule(BaseModel):
    """Per-option judged multiple choice (e.g. Taiwan GSAT): every option is
    marked independently and the score is looked up by how many options were
    judged wrongly (selected but incorrect, or correct but missed)."""

    kind: Literal["per_option"] = "per_option"
    correct: list[str] = Field(min_length=1, description="Correct option ids")
    ratio_by_errors: list[float] = Field(
        min_length=1,
        description=(
            "Score ratio indexed by k = number of wrongly judged options, copied "
            "from the printed rule; e.g. [1.0, 0.6, 0.2] for full / 3-5ths / "
            "1-5th of the points. k beyond the last entry scores 0. A fully "
            "blank answer scores 0."
        ),
    )

    @model_validator(mode="after")
    def _check_ratios(self) -> PerOptionRule:
        for ratio in self.ratio_by_errors:
            if not 0.0 <= ratio <= 1.0:
                raise ValueError(f"ratio_by_errors values must be in [0, 1], got {ratio}")
        return self


class TrueFalseRule(BaseModel):
    kind: Literal["true_false"] = "true_false"
    correct: bool
    negative_marking: float | None = None


class BlankSpec(BaseModel):
    accepted: list[str] = Field(min_length=1, description="Accepted answers (post-normalization)")
    weight: float = Field(default=1.0, gt=0)


class FillBlankRule(BaseModel):
    kind: Literal["fill_in_blank"] = "fill_in_blank"
    blanks: dict[str, BlankSpec] = Field(description="Blank id -> spec")
    normalization: Normalization = Field(default_factory=Normalization)
    all_or_nothing: bool = False


class MatchingRule(BaseModel):
    kind: Literal["matching"] = "matching"
    correct_pairs: dict[str, str] = Field(description="Left item id -> correct right item id")
    all_or_nothing: bool = False
    wrong_pair_penalty: float = Field(default=0.0, ge=0)


class RubricLevel(BaseModel):
    points: float
    descriptor: str


class RubricCriterion(BaseModel):
    id: str
    description: str
    levels: list[RubricLevel] = Field(min_length=2)

    @model_validator(mode="after")
    def _sort_levels(self) -> RubricCriterion:
        self.levels = sorted(self.levels, key=lambda level: -level.points)
        return self

    @property
    def max_points(self) -> float:
        return max(level.points for level in self.levels)


class JudgeRule(BaseModel):
    kind: Literal["judge"] = "judge"
    reference_answer: str | None = Field(
        default=None, description="Model solution / expected answer (Markdown)"
    )
    reference_assets: list[str] = Field(
        default_factory=list, description="Bundle-relative paths of solution figures"
    )
    rubric: list[RubricCriterion] = Field(
        default_factory=list,
        description="Empty means holistic judging against reference + instructions",
    )
    judge_instructions: str | None = Field(
        default=None, description="Extracted from official scoring guidelines"
    )
    include_question_images: bool = True


GradingRule = Annotated[
    ChoiceRule | PerOptionRule | TrueFalseRule | FillBlankRule | MatchingRule | JudgeRule,
    Field(discriminator="kind"),
]


class QuestionGrading(BaseModel):
    question_id: str
    max_points: float = Field(ge=0)
    min_points: float = Field(default=0.0, description="Floor for negative marking")
    rule: GradingRule

    @model_validator(mode="after")
    def _check(self) -> QuestionGrading:
        if self.min_points > 0:
            raise ValueError(f"{self.question_id}: min_points must be <= 0")
        rule = self.rule
        if isinstance(rule, JudgeRule) and rule.rubric:
            rubric_max = sum(c.max_points for c in rule.rubric)
            if not math.isclose(rubric_max, self.max_points, abs_tol=1e-6):
                raise ValueError(
                    f"{self.question_id}: rubric max total {rubric_max} != "
                    f"max_points {self.max_points}"
                )
        return self


class JudgeConfig(BaseModel):
    models: list[str] = Field(
        default_factory=lambda: ["openai:gpt-5.6-sol"],
        min_length=1,
        description="Judge model strings, e.g. 'openai:gpt-5.6-sol', 'google:gemini-3.7-flash'",
    )
    aggregation: Literal["mean", "median", "min", "max"] = "mean"


class GradingSpec(BaseModel):
    schema_version: str = "1"
    exam_id: str
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    questions: dict[str, QuestionGrading] = Field(description="Leaf question id -> grading")

    @model_validator(mode="after")
    def _check_keys(self) -> GradingSpec:
        for qid, qg in self.questions.items():
            if qg.question_id != qid:
                raise ValueError(f"grading key {qid} != entry question_id {qg.question_id}")
        return self
