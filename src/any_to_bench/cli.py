"""any-to-bench command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from any_to_bench.schemas.usage import Effort, UsageSummary

app = typer.Typer(
    name="any-to-bench",
    help="Convert any exam materials into a machine-gradable benchmark.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


@app.callback()
def _load_env() -> None:
    """Load provider API keys from a .env file (never overriding real env vars)."""
    load_dotenv()


DEFAULT_MODEL = "openai:gpt-5.6-sol"

EffortOption = Annotated[
    Effort | None,
    typer.Option(
        help="Reasoning effort (OpenAI: reasoning.effort; Google: thinking_level; "
        "codex: model_reasoning_effort). Default: provider default."
    ),
]


def _echo_usage(usage: UsageSummary | None) -> None:
    if usage is not None:
        typer.echo(usage.format_line())


@app.command()
def ingest(
    inputs: Annotated[
        list[Path],
        typer.Argument(exists=True, readable=True, help="Exam materials: photos and/or PDFs"),
    ],
    output: Annotated[Path, typer.Option("--output", "-o", help="Bundle output directory")],
    model: Annotated[
        str,
        typer.Option(
            help="Extraction model, e.g. openai:gpt-5.6-terra, or codex:gpt-5.6-sol "
            "for agentic mode (runs the Codex CLI)"
        ),
    ] = DEFAULT_MODEL,
    effort: EffortOption = None,
    full_page_figures: Annotated[
        bool, typer.Option(help="Attach full page images instead of cropping figures")
    ] = False,
) -> None:
    """Turn exam materials (papers, keys, solutions, rubrics) into an exam bundle."""
    from any_to_bench.ingest.pipeline import run_ingest

    bundle = run_ingest(
        inputs, output, model=model, full_page_figures=full_page_figures, effort=effort
    )
    typer.echo(f"Bundle written to {bundle.root}")
    _echo_usage(bundle.manifest.usage)
    if bundle.manifest.warnings:
        typer.echo(f"{len(bundle.manifest.warnings)} warning(s) — see manifest.json:")
        for warning in bundle.manifest.warnings:
            typer.echo(f"  - {warning}", err=True)


@app.command()
def solve(
    bundle_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Exam bundle")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Where to write answers.json")],
    model: Annotated[
        str,
        typer.Option(
            help="Taker model, e.g. google:gemini-3.7-flash, or codex:gpt-5.6-sol "
            "for agentic mode (runs the Codex CLI)"
        ),
    ] = DEFAULT_MODEL,
    effort: EffortOption = None,
) -> None:
    """Have an LLM take the exam, producing an answer sheet."""
    from any_to_bench.bundle import ExamBundle
    from any_to_bench.solve.runner import run_solve
    from any_to_bench.util import write_json

    bundle = ExamBundle.load(bundle_dir)
    sheet = run_solve(bundle, model=model, effort=effort)
    errors = bundle.validate_answer_sheet(sheet)
    write_json(output, sheet)
    typer.echo(f"Answer sheet written to {output}")
    _echo_usage(sheet.usage)
    if errors:
        typer.echo("Answer sheet does NOT fully satisfy the answer schema:", err=True)
        for error in errors:
            typer.echo(f"  - {error}", err=True)
        raise typer.Exit(code=1)


@app.command()
def grade(
    bundle_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Exam bundle")],
    answers: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="answers.json")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Where to write report.json")],
    judge_model: Annotated[
        list[str] | None,
        typer.Option(
            help="Override judge model(s) from grading.json; repeatable. "
            "codex:* models judge agentically via the Codex CLI"
        ),
    ] = None,
    effort: EffortOption = None,
) -> None:
    """Grade a filled answer sheet: deterministic rules + LLM judges."""
    from any_to_bench.bundle import ExamBundle
    from any_to_bench.grade.aggregate import run_grade
    from any_to_bench.schemas.answers import AnswerSheet
    from any_to_bench.util import read_json, write_json

    bundle = ExamBundle.load(bundle_dir)
    sheet = AnswerSheet.model_validate(read_json(answers))
    report = run_grade(bundle, sheet, judge_models=judge_model or None, effort=effort)
    write_json(output, report)
    typer.echo(
        f"Score: {report.total_awarded:g}/{report.total_max:g} ({report.percentage:.1f}%) "
        f"-> {output}"
    )
    _echo_usage(report.usage)
    for warning in report.warnings:
        typer.echo(f"  warning: {warning}", err=True)


@app.command()
def bench(
    bundle_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Exam bundle")],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Directory for bench artifacts")
    ],
    model: Annotated[
        list[str],
        typer.Option(help="Taker model(s) to benchmark; repeatable (codex:* runs agentically)"),
    ],
    judge_model: Annotated[
        list[str] | None,
        typer.Option(
            help="Judge model(s) for open-ended questions; repeatable. "
            "Prefer models different from the takers"
        ),
    ] = None,
    effort: EffortOption = None,
) -> None:
    """Benchmark multiple taker models on one bundle and compare the results."""
    from any_to_bench.bench import BENCH_FILE, format_table, run_bench
    from any_to_bench.bundle import ExamBundle

    bundle = ExamBundle.load(bundle_dir)
    report = run_bench(
        bundle, model, output, judge_models=judge_model or None, effort=effort
    )
    typer.echo(format_table(report))
    typer.echo(f"Bench report written to {output / BENCH_FILE}")
    for warning in report.warnings:
        typer.echo(f"  warning: {warning}", err=True)
    if report.rows and all(row.status != "ok" for row in report.rows):
        raise typer.Exit(code=1)


@app.command()
def validate(
    bundle_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Exam bundle")],
) -> None:
    """Check an exam bundle for internal consistency."""
    from any_to_bench.bundle import validate_bundle

    problems = validate_bundle(bundle_dir)
    if problems:
        typer.echo(f"Bundle {bundle_dir} has {len(problems)} problem(s):", err=True)
        for problem in problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Bundle {bundle_dir} is valid.")


if __name__ == "__main__":
    app()
