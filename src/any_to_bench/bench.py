"""Benchmark matrix: run N taker models over one bundle and compare them."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from pathlib import Path

from any_to_bench import tool_version
from any_to_bench.agentic.runner import parse_agentic_model
from any_to_bench.bundle import ExamBundle
from any_to_bench.grade.aggregate import run_grade
from any_to_bench.modality import parse_capabilities
from any_to_bench.schemas.bench import BenchReport, BenchRow
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
) -> BenchReport:
    """Solve + grade the bundle with every model; write per-model artifacts and
    an incrementally-updated bench.json into out_dir. One failing model never
    sinks the matrix.

    text_only_models names takers that cannot consume images; their rows skip
    the questions that need them and score over the rest, with coverage shown
    so a subset score is never mistaken for a full-exam one."""
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
    for model in models:
        row = BenchRow(model=model, slug=_unique_slug(model, used_slugs))
        report.rows.append(row)
        capabilities = parse_capabilities(model in text_only)
        skipped: list[str] = []

        start = time.monotonic()
        try:
            sheet = run_solve(
                bundle, model, effort=effort, capabilities=capabilities, skipped=skipped
            )
        except Exception as e:  # noqa: BLE001 — one broken model must not sink the matrix
            row.status, row.error = "solve_error", str(e)
            write_json(out_dir / BENCH_FILE, report)
            continue
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
            write_json(out_dir / BENCH_FILE, report)
            continue
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
        write_json(out_dir / BENCH_FILE, report)

    covered = {row.covered_max for row in report.rows if row.status == "ok"}
    if len(covered) > 1:
        report.warnings.append(
            "takers were asked different subsets of the exam; read the 'cov' column before "
            "comparing scores — the percentages have different denominators"
        )

    report.finished_at = datetime.now(UTC)
    write_json(out_dir / BENCH_FILE, report)
    return report


def format_table(report: BenchReport) -> str:
    """The bench results as a Markdown comparison table."""
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


def _judge_delta(row: BenchRow) -> str:
    """Judge disagreement as disagreed/comparable, or – when nothing is comparable."""
    if not row.multi_judge_questions:
        return "–"
    return f"{row.judge_disagreements}/{row.multi_judge_questions}"
