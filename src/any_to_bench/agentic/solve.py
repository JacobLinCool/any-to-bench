"""Agentic solve: a CLI agent takes the whole exam in one workspace session."""

from __future__ import annotations

from pydantic import ValidationError

from any_to_bench.agentic.prompts import SOLVE_AGENTS_MD, SOLVE_TASK_PROMPT
from any_to_bench.agentic.runner import AgenticError, parse_agentic, run_fix_loop
from any_to_bench.agentic.workspace import (
    cleanup_workspace,
    collect_exam_assets,
    copy_assets,
    new_workspace,
    write_agents_md,
)
from any_to_bench.bundle import ExamBundle
from any_to_bench.llm import UsageTracker
from any_to_bench.schemas.answers import AnswerSheet
from any_to_bench.schemas.usage import Effort
from any_to_bench.util import read_json, write_json

PHASE = "agentic:solve"


def agentic_solve(
    bundle: ExamBundle, model: str, effort: Effort | str | None = None
) -> AnswerSheet:
    agentic_model = parse_agentic(model)
    if agentic_model is None:
        raise ValueError(f"not an agentic model string: {model!r}")
    tracker = UsageTracker()

    workspace = new_workspace("solve")
    write_agents_md(workspace, SOLVE_AGENTS_MD)
    # Only the exam and the assets it references: the rest of the bundle
    # (grading, manifest, provenance pages) would leak the answer key.
    write_json(workspace / "exam" / "exam.json", bundle.exam)
    copy_assets(bundle.root, collect_exam_assets(bundle.exam), workspace / "exam")
    write_json(workspace / "schemas" / "answer_schema.json", bundle.answer_schema)
    (workspace / "output").mkdir()

    parsed: AnswerSheet | None = None

    def oracle() -> list[str]:
        nonlocal parsed
        path = workspace / "output" / "answers.json"
        if not path.exists():
            return ["missing file: output/answers.json"]
        try:
            data = read_json(path)
        except ValueError as e:
            return [f"output/answers.json is not valid JSON: {e}"]
        try:
            candidate = AnswerSheet.model_validate(data)
        except ValidationError as e:
            return [f"output/answers.json does not parse as an answer sheet: {e}"]
        sheet = AnswerSheet(exam_id=bundle.exam.exam_id, taker=model, answers=candidate.answers)
        parsed = sheet
        return bundle.validate_answer_sheet(sheet)

    try:
        outcome = run_fix_loop(
            workspace,
            SOLVE_TASK_PROMPT,
            agentic_model.cli_model,
            oracle,
            on_usage=lambda u: tracker.add(PHASE, u),
            effort=effort,
            backend=agentic_model.backend,
        )
    except AgenticError as e:
        raise AgenticError(f"{e} (workspace kept at {workspace})") from e

    if parsed is None:
        raise AgenticError(
            f"agentic solve produced no parseable answers.json in {outcome.rounds_run} "
            f"round(s) (workspace kept at {workspace}): " + "; ".join(outcome.problems[:5])
        )
    if not outcome.problems:
        cleanup_workspace(workspace)
    # Residual schema problems flow through the CLI's normal validate-and-exit-1
    # path, matching LLM-mode semantics.
    return AnswerSheet(
        exam_id=bundle.exam.exam_id,
        taker=model,
        answers=parsed.answers,
        usage=tracker.summary(),
    )
