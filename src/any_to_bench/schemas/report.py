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
        default_factory=list, description="Raw verdicts, one per judge model"
    )


class SectionTotal(BaseModel):
    awarded: float
    max_points: float


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
    usage: UsageSummary | None = Field(
        default=None, description="Token usage spent by LLM judges, if any"
    )
