"""Benchmark matrix: run N taker models over one bundle and compare them."""

from __future__ import annotations

import math
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from any_to_bench import tool_version
from any_to_bench.agentic.runner import parse_agentic_model
from any_to_bench.bundle import ExamBundle
from any_to_bench.grade.aggregate import run_grade
from any_to_bench.modality import parse_capabilities
from any_to_bench.schemas.bench import BenchModelSummary, BenchReport, BenchRow
from any_to_bench.schemas.grading import JudgeRule
from any_to_bench.schemas.usage import Effort
from any_to_bench.solve.runner import run_solve
from any_to_bench.util import slugify, write_json

BENCH_FILE = "bench.json"


def _unique_slug(model: str, used: set[str]) -> str:
    slug = base = slugify(model)
    counter = 1
    while slug in used:
        counter += 1
        slug = f"{base}-{counter}"
    used.add(slug)
    return slug


def run_bench(
    bundle: ExamBundle,
    models: list[str],
    out_dir: Path,
    judge_models: list[str] | None = None,
    effort: Effort | str | None = None,
    text_only_models: list[str] | None = None,
    repeat: int = 1,
    concurrency: int = 1,
) -> BenchReport:
    """Solve + grade the bundle with every model; write per-model artifacts and
    an incrementally-updated bench.json into out_dir. One failing model never
    sinks the matrix.

    text_only_models names takers that cannot consume images; their rows skip
    the questions that need them and score over the rest, with coverage shown
    so a subset score is never mistaken for a full-exam one.

    repeat runs each taker that many times. A single run gives a score with
    unknown noise, which is the whole difficulty in reading a one-shot matrix.

    concurrency solves that many questions at once per taker. It does not touch
    agentic takers, which run one CLI over the whole paper."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    effective_judges = list(judge_models or bundle.grading.judge.models)
    deterministic_total = sum(
        1 for qg in bundle.grading.questions.values() if not isinstance(qg.rule, JudgeRule)
    )
    report = BenchReport(
        tool_version=tool_version(),
        bundle_dir=str(bundle.root),
        exam_id=bundle.exam.exam_id,
        title=bundle.exam.title,
        total_points=bundle.exam.total_points,
        ingest_model=bundle.manifest.ingest_model,
        models=list(models),
        judge_models=effective_judges,
        effort=str(effort) if effort is not None else None,
        judge_questions=len(bundle.grading.questions) - deterministic_total,
        repeat=repeat,
        started_at=datetime.now(UTC),
    )
    for model in models:
        if model in effective_judges:
            report.warnings.append(
                f"taker {model} is also a judge model; self-judging tends to be optimistic — "
                "prefer a different --judge-model"
            )
    if report.judge_questions and len(effective_judges) < 2:
        report.warnings.append(
            "single judge model — inter-judge agreement cannot be measured; pass a second "
            "--judge-model to see how much of the judged score is judge-dependent"
        )
    text_only = set(text_only_models or ())
    for model in sorted(text_only - set(models)):
        report.warnings.append(
            f"--text-only-model {model} matches no --model; the declaration had no effect"
        )
    for model in sorted(text_only & set(models)):
        if parse_agentic_model(model) is not None:
            report.warnings.append(
                f"--text-only-model {model} is agentic; agentic takers open assets as files, "
                "so the declaration is ignored"
            )

    used_slugs: set[str] = set()
    # Repeat-major: one sample of every model beats N samples of half of them if
    # the run is interrupted, and bench.json is written to be useful mid-run.
    for run_index in range(1, repeat + 1):
        for model in models:
            _run_one(
                bundle=bundle,
                model=model,
                run_index=run_index,
                report=report,
                out_dir=out_dir,
                used_slugs=used_slugs,
                capabilities=parse_capabilities(model in text_only),
                judge_models=judge_models,
                effort=effort,
                deterministic_total=deterministic_total,
                concurrency=concurrency,
            )

    covered = {row.covered_max for row in report.rows if row.status == "ok"}
    if len(covered) > 1:
        report.warnings.append(
            "takers were asked different subsets of the exam; read the 'cov' column before "
            "comparing scores — the percentages have different denominators"
        )

    report.finished_at = datetime.now(UTC)
    _flush(report, out_dir)
    return report


def _run_one(
    *,
    bundle: ExamBundle,
    model: str,
    run_index: int,
    report: BenchReport,
    out_dir: Path,
    used_slugs: set[str],
    capabilities: frozenset,
    judge_models: list[str] | None,
    effort: Effort | str | None,
    deterministic_total: int,
    concurrency: int = 1,
) -> None:
    """Solve + grade one taker once, flushing at every exit so a kill leaves usable state."""
    row = BenchRow(model=model, slug=_unique_slug(model, used_slugs), run_index=run_index)
    report.rows.append(row)
    skipped: list[str] = []

    start = time.monotonic()
    try:
        sheet = run_solve(
            bundle,
            model,
            effort=effort,
            capabilities=capabilities,
            skipped=skipped,
            concurrency=concurrency,
        )
    except Exception as e:  # noqa: BLE001 — one broken model must not sink the matrix
        row.status, row.error = "solve_error", str(e)
        _flush(report, out_dir)
        return
    row.solve_secs = round(time.monotonic() - start, 1)
    row.schema_error_count = len(bundle.validate_answer_sheet(sheet, allow_missing=skipped))
    row.answers_path = f"{row.slug}-answers.json"
    write_json(out_dir / row.answers_path, sheet)
    row.solve_usage = sheet.usage

    start = time.monotonic()
    try:
        grade_report = run_grade(
            bundle,
            sheet,
            judge_models=judge_models,
            effort=effort,
            capabilities=capabilities,
        )
    except Exception as e:  # noqa: BLE001
        row.status, row.error = "grade_error", str(e)
        _flush(report, out_dir)
        return
    row.grade_secs = round(time.monotonic() - start, 1)
    row.report_path = f"{row.slug}-report.json"
    write_json(out_dir / row.report_path, grade_report)
    row.grade_usage = grade_report.usage
    row.awarded = grade_report.total_awarded
    row.max_points = grade_report.total_max
    row.percentage = grade_report.percentage
    row.skipped_count = grade_report.skipped_count
    row.skipped_points = grade_report.skipped_points
    row.covered_max = grade_report.covered_max
    row.covered_percentage = grade_report.covered_percentage

    modes: dict[str, int] = {}
    full_credit = 0
    for result in grade_report.results.values():
        modes[result.mode] = modes.get(result.mode, 0) + 1
        if result.mode == "deterministic" and math.isclose(result.awarded, result.max_points):
            full_credit += 1
    row.deterministic_full_credit = full_credit
    row.deterministic_total = deterministic_total
    row.judge_count = modes.get("judge", 0)
    if (agreement := grade_report.judge_agreement) is not None:
        row.multi_judge_questions = agreement.multi_judge_questions
        row.judge_disagreements = agreement.disagreed_questions
        row.judge_mean_spread = round(agreement.mean_spread, 3)
    row.error_count = modes.get("error", 0)
    row.unanswered_count = modes.get("unanswered", 0)
    row.skipped_count = grade_report.skipped_count
    _flush(report, out_dir)


def _flush(report: BenchReport, out_dir: Path) -> None:
    """Recompute summaries and rewrite bench.json.

    Summaries are derived here rather than only at the end so an interrupted run
    still carries correct aggregates for the rows it did finish.
    """
    report.summaries = summarize_models(report.rows, report.models)
    write_json(out_dir / BENCH_FILE, report)


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _std(values: list[float]) -> float | None:
    """Sample stdev, or None below two runs — statistics.stdev raises there."""
    return statistics.stdev(values) if len(values) >= 2 else None


def summarize_models(rows: list[BenchRow], models: list[str]) -> list[BenchModelSummary]:
    """Aggregate rows per model. Pure, so it is testable without running a bench.

    Grouped by model string, so a model passed twice on the command line merges
    with its repeats into one summary — consistent with the long-standing
    "the same model twice is a variance run" behaviour.
    """
    summaries: list[BenchModelSummary] = []
    for model in dict.fromkeys(models):
        attempts = [r for r in rows if r.model == model]
        if not attempts:
            continue
        ok = [r for r in attempts if r.status == "ok"]
        awarded = [r.awarded for r in ok if r.awarded is not None]
        percentages = [r.covered_percentage for r in ok if r.covered_percentage is not None]
        tokens_in = [_row_tokens(r)[0] for r in ok]
        tokens_out = [_row_tokens(r)[1] for r in ok]
        summaries.append(
            BenchModelSummary(
                model=model,
                runs=len(attempts),
                ok_runs=len(ok),
                max_points=ok[0].max_points if ok else None,
                awarded=awarded,
                percentages=percentages,
                awarded_mean=_mean(awarded),
                awarded_std=_std(awarded),
                percentage_mean=_mean(percentages),
                percentage_std=_std(percentages),
                covered_max_mean=_mean([r.covered_max for r in ok if r.covered_max is not None]),
                deterministic_full_credit_mean=_mean(
                    [
                        r.deterministic_full_credit
                        for r in ok
                        if r.deterministic_full_credit is not None
                    ]
                ),
                judge_disagreements_mean=_mean(
                    [r.judge_disagreements for r in ok if r.judge_disagreements is not None]
                ),
                solve_secs_mean=_mean([r.solve_secs for r in ok if r.solve_secs is not None]),
                grade_secs_mean=_mean([r.grade_secs for r in ok if r.grade_secs is not None]),
                input_tokens_mean=_mean(tokens_in) or 0.0,
                output_tokens_mean=_mean(tokens_out) or 0.0,
                input_tokens_total=sum(tokens_in),
                output_tokens_total=sum(tokens_out),
            )
        )
    return summaries


def _row_tokens(row: BenchRow) -> tuple[int, int]:
    tokens_in = tokens_out = 0
    for usage in (row.solve_usage, row.grade_usage):
        if usage is not None:
            tokens_in += usage.total.input_tokens
            tokens_out += usage.total.output_tokens
    return tokens_in, tokens_out


def format_table(report: BenchReport) -> str:
    """The bench results as a Markdown comparison table.

    With repeats, one row per model showing mean ± std instead of one row per
    invocation — the per-run rows are still all in bench.json.
    """
    if report.repeat > 1:
        return _format_summary_table(report)
    lines = [
        "| model | score | % | cov | det full | judge | judge Δ | schema err "
        "| tokens in/out | time |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report.rows:
        if row.status != "ok":
            lines.append(f"| {row.model} | {row.status} |  |  |  |  |  |  |  |  |")
            continue
        tokens_in = tokens_out = 0
        for usage in (row.solve_usage, row.grade_usage):
            if usage is not None:
                tokens_in += usage.total.input_tokens
                tokens_out += usage.total.output_tokens
        secs = (row.solve_secs or 0.0) + (row.grade_secs or 0.0)
        covered_max = row.covered_max if row.covered_max is not None else row.max_points
        percentage = (
            row.covered_percentage if row.covered_percentage is not None else row.percentage
        )
        lines.append(
            f"| {row.model} | {row.awarded:g}/{covered_max:g} | {percentage:.1f}% "
            f"| {covered_max:g}/{row.max_points:g} "
            f"| {row.deterministic_full_credit}/{row.deterministic_total} "
            f"| {row.judge_count} | {_judge_delta(row)} | {row.schema_error_count} "
            f"| {tokens_in:,} / {tokens_out:,} | {secs:.0f}s |"
        )
    return "\n".join(lines)


def _pm(mean: float | None, std: float | None, suffix: str = "") -> str:
    """A mean with its spread, or just the mean when there is only one sample."""
    if mean is None:
        return "–"
    if std is None:
        return f"{mean:.3g}{suffix}"
    return f"{mean:.3g}{suffix} ± {std:.2g}"


def _format_summary_table(report: BenchReport) -> str:
    """One row per model across repeats. Token and time figures are per run."""
    lines = [
        "| model | runs | score | % | cov | det full | judge Δ | tokens in/out | time |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for summary in report.summaries:
        if not summary.ok_runs:
            lines.append(f"| {summary.model} | 0/{summary.runs} | failed |  |  |  |  |  |  |")
            continue
        max_points = summary.max_points or 0.0
        covered = summary.covered_max_mean if summary.covered_max_mean is not None else max_points
        secs = (summary.solve_secs_mean or 0.0) + (summary.grade_secs_mean or 0.0)
        lines.append(
            f"| {summary.model} | {summary.ok_runs}/{summary.runs} "
            f"| {_pm(summary.awarded_mean, summary.awarded_std)}/{covered:g} "
            f"| {_pm(summary.percentage_mean, summary.percentage_std, '%')} "
            f"| {covered:g}/{max_points:g} "
            f"| {_pm(summary.deterministic_full_credit_mean, None)}/"
            f"{report.rows[0].deterministic_total} "
            f"| {_pm(summary.judge_disagreements_mean, None)} "
            f"| {summary.input_tokens_mean:,.0f} / {summary.output_tokens_mean:,.0f} "
            f"| {secs:.0f}s |"
        )
    return "\n".join(lines)


def _judge_delta(row: BenchRow) -> str:
    """Judge disagreement as disagreed/comparable, or – when nothing is comparable."""
    if not row.multi_judge_questions:
        return "–"
    return f"{row.judge_disagreements}/{row.multi_judge_questions}"
