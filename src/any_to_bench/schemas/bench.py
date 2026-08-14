"""Benchmark-matrix report models (bench.json)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from any_to_bench.schemas.usage import UsageSummary


class BenchRow(BaseModel):
    """One taker model's outcome over the bundle."""

    model: str
    slug: str
    run_index: int = Field(default=1, description="1-based repeat number for this model")
    status: Literal["ok", "solve_error", "grade_error"] = "ok"
    error: str | None = None
    awarded: float | None = None
    max_points: float | None = None
    percentage: float | None = Field(
        default=None, description="Over the whole exam, skipped questions included"
    )
    skipped_count: int | None = None
    skipped_points: float | None = None
    covered_max: float | None = Field(
        default=None, description="max_points minus what the taker could not attempt"
    )
    covered_percentage: float | None = Field(
        default=None, description="Over what the taker was actually asked; the headline score"
    )
    deterministic_full_credit: int | None = Field(
        default=None, description="Deterministic questions answered for full credit"
    )
    deterministic_total: int | None = Field(
        default=None, description="Questions with a non-judge grading rule (bundle property)"
    )
    judge_count: int | None = None
    multi_judge_questions: int | None = Field(
        default=None, description="Judged questions that got >= 2 verdicts"
    )
    judge_disagreements: int | None = Field(
        default=None, description="Of those, how many the judges scored differently"
    )
    judge_mean_spread: float | None = Field(
        default=None, description="Mean max-min gap between judges, in points"
    )
    error_count: int | None = None
    unanswered_count: int | None = None
    schema_error_count: int | None = None
    solve_usage: UsageSummary | None = None
    grade_usage: UsageSummary | None = None
    answers_path: str | None = Field(default=None, description="Relative to the bench out dir")
    report_path: str | None = Field(default=None, description="Relative to the bench out dir")
    solve_secs: float | None = None
    grade_secs: float | None = None


class BenchModelSummary(BaseModel):
    """One model across its repeat runs.

    A single run gives a score with unknown noise; the spread across repeats is
    what tells you whether a gap between two models is real.
    """

    model: str
    runs: int = Field(description="Invocations attempted")
    ok_runs: int = 0
    max_points: float | None = None
    awarded: list[float] = Field(default_factory=list, description="One per successful run")
    percentages: list[float] = Field(default_factory=list, description="Coverage-relative")
    awarded_mean: float | None = None
    awarded_std: float | None = Field(default=None, description="Sample stdev; None below 2 runs")
    percentage_mean: float | None = None
    percentage_std: float | None = None
    covered_max_mean: float | None = None
    deterministic_full_credit_mean: float | None = None
    judge_disagreements_mean: float | None = None
    solve_secs_mean: float | None = None
    grade_secs_mean: float | None = None
    input_tokens_mean: float = Field(default=0.0, description="Per run, not summed")
    output_tokens_mean: float = 0.0
    input_tokens_total: int = 0
    output_tokens_total: int = 0


class BenchReport(BaseModel):
    schema_version: str = "1"
    tool_version: str
    bundle_dir: str
    exam_id: str
    title: str
    total_points: float
    ingest_model: str | None = Field(
        default=None, description="Provenance: the model that ingested the bundle"
    )
    models: list[str]
    judge_models: list[str] = Field(description="Effective judge models used for every row")
    effort: str | None = None
    judge_questions: int
    repeat: int = Field(default=1, description="Runs per taker model")
    started_at: datetime
    finished_at: datetime | None = None
    rows: list[BenchRow] = Field(
        default_factory=list, description="One per taker invocation, flat across repeats"
    )
    summaries: list[BenchModelSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
