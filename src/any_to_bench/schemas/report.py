"""Grade report models. JudgeVerdict doubles as the judge agent's output type."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from any_to_bench.schemas.usage import UsageSummary


class CriterionScore(BaseModel):
    criterion_id: str
    points: float
    rationale: str


class JudgeVerdict(BaseModel):
    """One judge's assessment of one answer."""

    criteria: list[CriterionScore] = Field(
        default_factory=list, description="Per-criterion scores; empty for holistic judging"
    )
    total_points: float
    overall_rationale: str


class QuestionResult(BaseModel):
    question_id: str
    mode: Literal["deterministic", "judge", "unanswered", "error"]
    max_points: float
    awarded: float
    detail: dict[str, Any] = Field(
        default_factory=dict, description="Per-blank/per-pair breakdown or error info"
    )
    judge_verdicts: list[JudgeVerdict] = Field(
        default_factory=list,
        description="Raw verdicts, positionally matching detail['judge_models']",
    )


class SectionTotal(BaseModel):
    awarded: float
    max_points: float


class JudgeAgreement(BaseModel):
    """How much the judges disagreed — the available measure of judge reliability.

    A score built on unanimous judges and one built on judges who split are
    otherwise indistinguishable in the report.
    """

    requested_judge_models: list[str] = Field(default_factory=list)
    judged_questions: int = Field(default=0, description="Questions with >= 1 verdict")
    multi_judge_questions: int = Field(default=0, description="Questions with >= 2 verdicts")
    disagreed_questions: int = Field(
        default=0, description="Of the multi-judge ones, those where judges differed"
    )
    mean_spread: float = Field(default=0.0, description="Mean max-min gap, in points")
    max_spread: float = 0.0
    mean_normalized_spread: float = Field(
        default=0.0, description="Mean spread as a fraction of each question's max points"
    )
    per_judge_mean: dict[str, float] = Field(
        default_factory=dict, description="Judge -> mean points awarded; its leniency"
    )


class GradeReport(BaseModel):
    schema_version: str = "1"
    exam_id: str
    taker: str | None = None
    graded_at: datetime
    results: dict[str, QuestionResult]
    section_totals: dict[str, SectionTotal] = Field(default_factory=dict)
    total_awarded: float
    total_max: float
    percentage: float
    warnings: list[str] = Field(default_factory=list)
    judge_agreement: JudgeAgreement | None = Field(
        default=None, description="None when the exam has no judged questions"
    )
    usage: UsageSummary | None = Field(
        default=None, description="Token usage spent by LLM judges, if any"
    )
