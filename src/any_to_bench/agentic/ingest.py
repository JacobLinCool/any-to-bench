"""Agentic ingest: a CLI agent digitizes raw exam materials into a bundle."""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

from any_to_bench.agentic.prompts import INGEST_AGENTS_MD, INGEST_TASK_PROMPT
from any_to_bench.agentic.runner import AgenticError, parse_agentic, run_fix_loop
from any_to_bench.agentic.workspace import (
    cleanup_workspace,
    collect_exam_assets,
    new_workspace,
    stage_inputs,
    write_agents_md,
)
from any_to_bench.bundle import (
    ANSWER_SCHEMA_FILE,
    ASSETS_DIR,
    EXAM_FILE,
    GRADING_FILE,
    BundleManifest,
    ExamBundle,
    SourceFile,
    validate_bundle,
)
from any_to_bench.llm import UsageTracker
from any_to_bench.resources import snapshot_resources
from any_to_bench.schemas.answers import generate_answer_schema
from any_to_bench.schemas.exam import Exam
from any_to_bench.schemas.grading import GradingSpec, JudgeRule
from any_to_bench.schemas.usage import Effort
from any_to_bench.util import read_json, sha256_file, write_json

PHASE = "agentic:ingest"
WARNINGS_FILE = "ingest_warnings.json"


def _unsafe_asset(asset: str) -> bool:
    p = PurePosixPath(asset)
    return p.is_absolute() or ".." in p.parts


def _asset_path_problems(staging: Path) -> list[str]:
    """Reject path-escaping asset strings; validate_bundle only checks existence."""
    try:
        bundle = ExamBundle.load(staging)
    except Exception:  # noqa: BLE001 — parse problems are already reported upstream
        return []
    problems = []
    referenced = {("exam", a) for a in collect_exam_assets(bundle.exam)}
    for qid, grading in bundle.grading.questions.items():
        if isinstance(grading.rule, JudgeRule):
            referenced.update((f"question {qid}", a) for a in grading.rule.reference_assets)
    for owner, asset in sorted(referenced):
        if _unsafe_asset(asset):
            problems.append(
                f"{owner}: asset path {asset!r} must be a relative path under assets/ "
                "(no absolute paths, no '..')"
            )
    return problems


def _bundle_problems(staging: Path) -> list[str]:
    """The fix-loop oracle: everything wrong with the agent's bundle/ so far."""
    if not (staging / EXAM_FILE).exists():
        return ["missing file: exam.json (write bundle/exam.json)"]
    try:
        exam = Exam.model_validate(read_json(staging / EXAM_FILE))
    except ValueError as e:
        return [f"exam.json is invalid: {e}"]
    # The agent never writes the answer schema; regenerate it every round so
    # validate_bundle's freshness check tracks the agent's current exam.json.
    write_json(staging / ANSWER_SCHEMA_FILE, generate_answer_schema(exam))
    problems = validate_bundle(staging)
    problems.extend(_asset_path_problems(staging))
    return problems


def agentic_ingest(
    inputs: list[Path],
    output_dir: Path,
    model: str,
    full_page_figures: bool = False,
    effort: Effort | str | None = None,
    *,
    resources: Path | None = None,
) -> ExamBundle:
    agentic_model = parse_agentic(model)
    if agentic_model is None:
        raise ValueError(f"not an agentic model string: {model!r}")
    output_dir = Path(output_dir)
    inputs = [Path(p) for p in inputs]
    warnings: list[str] = []
    if full_page_figures:
        warnings.append("agentic mode ignores --full-page-figures (the agent decides crops)")
    tracker = UsageTracker()
    sources = [SourceFile(path=str(p), sha256=sha256_file(p)) for p in inputs]
    resource_files = snapshot_resources(resources, output_dir) if resources is not None else []

    workspace = new_workspace("ingest")
    write_agents_md(workspace, INGEST_AGENTS_MD)
    stage_inputs(inputs, workspace)
    write_json(workspace / "schemas" / "exam.schema.json", Exam.model_json_schema())
    write_json(workspace / "schemas" / "grading.schema.json", GradingSpec.model_json_schema())
    staging = workspace / "bundle"
    staging.mkdir()

    try:
        outcome = run_fix_loop(
            workspace,
            INGEST_TASK_PROMPT,
            agentic_model.cli_model,
            lambda: _bundle_problems(staging),
            on_usage=lambda u: tracker.add(PHASE, u),
            effort=effort,
            backend=agentic_model.backend,
        )
    except AgenticError as e:
        raise AgenticError(f"{e} (workspace kept at {workspace})") from e

    for round_no, count in enumerate(outcome.round_counts, start=1):
        if count:
            warnings.append(f"agentic ingest round {round_no}: {count} validation problem(s)")
    if outcome.problems:
        raise AgenticError(
            f"agentic ingest failed validation after {outcome.rounds_run} round(s) "
            f"(workspace kept at {workspace}): " + "; ".join(outcome.problems[:10])
        )

    warn_file = staging / WARNINGS_FILE
    if warn_file.exists():
        try:
            data = read_json(warn_file)
            if isinstance(data, list):
                warnings.extend(str(w) for w in data)
            else:
                warnings.append(f"{WARNINGS_FILE} was not a JSON array; ignored")
        except ValueError:
            warnings.append(f"{WARNINGS_FILE} was not valid JSON; ignored")
        warn_file.unlink()

    exam = Exam.model_validate(read_json(staging / EXAM_FILE))
    grading = GradingSpec.model_validate(read_json(staging / GRADING_FILE))

    output_dir.mkdir(parents=True, exist_ok=True)
    assets_src = staging / ASSETS_DIR
    if assets_src.is_dir():
        shutil.copytree(assets_src, output_dir / ASSETS_DIR, dirs_exist_ok=True)

    manifest = BundleManifest(
        ingest_model=model,
        sources=sources,
        resources=resource_files,
        warnings=warnings,
        usage=tracker.summary(),
    )
    bundle = ExamBundle(
        root=output_dir,
        exam=exam,
        grading=grading,
        answer_schema=generate_answer_schema(exam, allow_citations=bool(resource_files)),
        manifest=manifest,
    )
    bundle.save()

    problems = validate_bundle(output_dir)
    if problems:
        manifest.warnings.extend(f"validation: {p}" for p in problems)
        bundle.save()
    cleanup_workspace(workspace)
    return bundle
