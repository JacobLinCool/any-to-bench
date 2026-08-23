"""Published evaluation results: what a leaderboard is built from.

Three grains, because they are read by three different consumers:

- `ResultsIndex` — one headline row per entry plus a catalog of the papers.
  The web leaderboard fetches this first and can draw its whole table from it.
- `ResultsEntry` — one row per paper for one taker configuration. Fetched lazily,
  only for the entries a visitor selected.
- the per-question parquet (built in `results.py`) — never read by the browser;
  it exists so the results are browsable on the Hub and reusable elsewhere.

A paper is keyed by its **source subset name**, never by `exam_id`: the two
disagree in 6 of the 21 published 115 papers (`ast-115-history` carries
`exam_id: ceec-115-history`), and only the subset name joins back to the exam
repo the score was earned against.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from any_to_bench.schemas.grading import GradingSpec
from any_to_bench.schemas.report import GradeReport
from any_to_bench.schemas.usage import PhaseUsage

RuleClass = Literal["deterministic", "judge"]
RULE_CLASSES: tuple[RuleClass, ...] = ("deterministic", "judge")


def _round(value: float, places: int = 6) -> float:
    """Float noise out of published JSON: 69.60000000000001 is not a score."""
    return round(value, places)


class PointBucket(BaseModel):
    """One rule class of one paper, for one taker.

    `max_points` is a property of the bundle and is the same for every taker;
    `covered_max` is the honest denominator once questions the taker could not
    attempt are taken out.
    """

    questions: int = 0
    max_points: float = 0.0
    skipped_points: float = 0.0
    covered_max: float = 0.0
    awarded: float = 0.0
    # Outcome counters are means over a paper's runs, so they are floats: with
    # --repeat 3 a question can go full credit twice and miss once.
    full_credit: float = 0.0
    unanswered: float = 0.0
    errored: float = 0.0
    skipped: float = 0.0

    @property
    def percentage(self) -> float | None:
        """None, not zero, when nothing was asked — a paper with no judged
        questions has not scored 0% on its judged half."""
        if self.covered_max <= 0:
            return None
        return 100.0 * self.awarded / self.covered_max


class RetrievalMetrics(BaseModel):
    """Resource exposure and optional citation evidence, averaged per run."""

    total_files: int = 0
    total_bytes: int = 0
    exposed_files: float = 0.0
    exposed_bytes: float = 0.0
    citations_submitted: float = 0.0
    citation_valid_paths: float = 0.0
    citations_verified: float = 0.0
    citation_quote_mismatches: float = 0.0
    citation_missing_resources: float = 0.0
    citation_unverifiable_binary: float = 0.0


class PaperResult(BaseModel):
    """One taker configuration's outcome on one paper, averaged over its runs."""

    subset: str = Field(description="Subset name in the source exam repo; the join key")
    exam_id: str = Field(description="Provenance only — see the module docstring")
    title: str
    subject: str | None = None
    language: str = "und"
    total_points: float = Field(description="exam.total_points, for a cross-check")
    judge_models: list[str] = Field(
        default_factory=list, description="Per paper: bundles do differ in their judges"
    )
    runs: int = 0
    ok_runs: int = 0
    failed: list[str] = Field(default_factory=list, description="status of each non-ok run")
    deterministic: PointBucket = Field(default_factory=PointBucket)
    judge: PointBucket = Field(default_factory=PointBucket)
    awarded_samples: list[float] = Field(
        default_factory=list, description="Total awarded per ok run; the raw spread"
    )
    det_awarded_samples: list[float] = Field(default_factory=list)
    schema_errors: float = 0.0
    multi_judge_questions: float = 0.0
    judge_disagreements: float = 0.0
    judge_mean_spread: float | None = None
    solve_secs: float | None = None
    grade_secs: float | None = None
    solve_usage: PhaseUsage = Field(default_factory=PhaseUsage, description="Mean per run")
    grade_usage: PhaseUsage | None = Field(
        default=None, description="None when nothing was judged — not the same as zero cost"
    )
    classification: Literal["rule-kind", "mode-fallback"] = "rule-kind"
    warnings: list[str] = Field(default_factory=list)
    retrieval: RetrievalMetrics | None = None

    @property
    def awarded(self) -> float:
        return self.deterministic.awarded + self.judge.awarded

    @property
    def covered_max(self) -> float:
        return self.deterministic.covered_max + self.judge.covered_max


class TakerIdentity(BaseModel):
    """What sat the exam. One entry is exactly one of these."""

    model: str
    effort: str | None = Field(
        default=None, description="None is 'provider default' — a configuration, not a level"
    )
    agentic: bool = Field(
        default=False,
        description="codex:/claude:/agy: — token counts approximate",
    )
    text_only: bool = False
    repeat: int = 1


class ResultsEntry(BaseModel):
    schema_version: str = "1"
    entry_id: str
    tool_version: str
    source_repo: str = Field(description="Exam dataset the papers were downloaded from")
    taker: TakerIdentity
    note: str | None = Field(
        default=None, description="Free text: concurrency, hardware — wall time needs it"
    )
    published_at: datetime
    first_run_at: datetime
    last_run_at: datetime
    papers: list[PaperResult] = Field(default_factory=list)


class PaperMeta(BaseModel):
    """A paper as the leaderboard's picker sees it: the union across entries."""

    subset: str
    source_repo: str
    title: str
    subject: str | None = None
    exam: str | None = Field(default=None, description="Leading segment: gsat / ast / cap")
    year: str | None = None
    total_points: float = 0.0
    deterministic_points: float = 0.0
    judge_points: float = 0.0
    questions: int = 0
    judge_questions: int = 0
    resource_files: int = 0
    resource_bytes: int = 0


class IndexEntry(BaseModel):
    """Headline numbers only. Per-paper rows live in `<entry_id>/entry.json`."""

    entry_id: str
    path: str
    model: str
    effort: str | None = None
    agentic: bool = False
    judge_models: list[str] = Field(default_factory=list, description="Union across its papers")
    tool_version: str
    repeat: int = 1
    published_at: datetime
    papers: list[str] = Field(default_factory=list)
    ok_papers: int = 0
    awarded: float = 0.0
    covered_max: float = 0.0
    percentage: float | None = None
    det_awarded: float = 0.0
    det_covered_max: float = 0.0
    det_percentage: float | None = None
    solve_input_tokens: int = 0
    solve_output_tokens: int = 0
    solve_reasoning_tokens: int = 0
    solve_cache_read_tokens: int = 0
    grade_input_tokens: int = 0
    grade_output_tokens: int = 0
    solve_secs: float = 0.0
    grade_secs: float = 0.0
    any_mode_fallback: bool = False
    resource_files: int = 0
    resource_bytes: int = 0
    resource_exposed_files: float = 0.0
    resource_exposed_bytes: float = 0.0
    citations_submitted: float = 0.0
    citation_valid_paths: float = 0.0
    citations_verified: float = 0.0
    citation_quote_mismatches: float = 0.0
    citation_missing_resources: float = 0.0
    citation_unverifiable_binary: float = 0.0
    note: str | None = None


class ResultsIndex(BaseModel):
    schema_version: str = "1"
    generated_at: datetime
    tool_version: str
    source_repos: list[str] = Field(default_factory=list)
    papers: list[PaperMeta] = Field(default_factory=list)
    entries: list[IndexEntry] = Field(default_factory=list)


def rule_kinds(grading: GradingSpec) -> dict[str, RuleClass]:
    """Question id -> which half of the score it belongs to."""
    return {
        qid: ("judge" if entry.rule.kind == "judge" else "deterministic")
        for qid, entry in grading.questions.items()
    }


def rule_kinds_from_modes(report: GradeReport) -> dict[str, RuleClass]:
    """Fallback for when the bundle is unavailable. Wrong whenever a judged
    question failed: `mode` records the outcome, so a judge question nobody could
    grade reads as 'error' and lands in the deterministic half. Only reachable
    behind --allow-mode-fallback, and the paper is stamped 'mode-fallback'.
    """
    return {
        qid: ("judge" if result.mode == "judge" else "deterministic")
        for qid, result in report.results.items()
    }


def classify_points(
    report: GradeReport, kinds: Mapping[str, RuleClass]
) -> dict[RuleClass, PointBucket]:
    """Split one grade report into its deterministic and judged halves.

    `kinds` must come from the grading spec (`rule_kinds`), not from
    `QuestionResult.mode`: mode is what happened, not how the question is
    graded. On the tiny fixture — 10 deterministic points and 7 judged — an
    offline run leaves all three judged questions at mode='error'; bucketing by
    mode reports 10/10 (100%) instead of 10/17 (58.8%).
    """
    buckets: dict[RuleClass, PointBucket] = {name: PointBucket() for name in RULE_CLASSES}
    for qid, result in report.results.items():
        bucket = buckets[kinds.get(qid, "deterministic")]
        bucket.questions += 1
        bucket.max_points += result.max_points
        bucket.awarded += result.awarded
        if result.mode == "skipped":
            bucket.skipped += 1
            bucket.skipped_points += result.max_points
        elif result.mode == "unanswered":
            bucket.unanswered += 1
        elif result.mode == "error":
            bucket.errored += 1
        if result.max_points > 0 and result.awarded >= result.max_points - 1e-9:
            bucket.full_credit += 1
    for bucket in buckets.values():
        bucket.max_points = _round(bucket.max_points)
        bucket.awarded = _round(bucket.awarded)
        bucket.skipped_points = _round(bucket.skipped_points)
        bucket.covered_max = _round(bucket.max_points - bucket.skipped_points)
    return buckets
