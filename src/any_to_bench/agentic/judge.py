"""Agentic judging: one codex batch session grades all open-ended answers."""

from __future__ import annotations

from typing import Any

import jsonschema
from pydantic import ValidationError

from any_to_bench.agentic.prompts import JUDGE_AGENTS_MD, JUDGE_TASK_PROMPT
from any_to_bench.agentic.runner import CodexError, parse_agentic_model, run_fix_loop
from any_to_bench.agentic.workspace import (
    cleanup_workspace,
    copy_assets,
    new_workspace,
    question_assets,
    write_agents_md,
)
from any_to_bench.bundle import ExamBundle
from any_to_bench.grade.judge import _answer_to_text, snap_verdict
from any_to_bench.llm import UsageTracker
from any_to_bench.schemas.answers import AnswerSheet, DrawingAnswer, TextAnswer
from any_to_bench.schemas.grading import JudgeRule, QuestionGrading
from any_to_bench.schemas.report import JudgeVerdict
from any_to_bench.schemas.usage import Effort
from any_to_bench.solve.render import leaf_context, render_question_parts
from any_to_bench.util import read_json, write_json


def generate_verdicts_schema(judge_rules: dict[str, QuestionGrading]) -> dict[str, Any]:
    """Strict JSON Schema for the batch verdicts file, narrowed per question."""
    per_question: dict[str, Any] = {}
    for qid, grading in judge_rules.items():
        rule = grading.rule
        assert isinstance(rule, JudgeRule)
        rubric_ids = [c.id for c in rule.rubric]
        if rubric_ids:
            criteria_schema: dict[str, Any] = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion_id": {"enum": rubric_ids},
                        "points": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["criterion_id", "points", "rationale"],
                    "additionalProperties": False,
                },
                "minItems": len(rubric_ids),
                "maxItems": len(rubric_ids),
            }
        else:
            criteria_schema = {"type": "array", "maxItems": 0}
        per_question[qid] = {
            "type": "object",
            "properties": {
                "criteria": criteria_schema,
                "total_points": {"type": "number"},
                "overall_rationale": {"type": "string"},
            },
            "required": ["criteria", "total_points", "overall_rationale"],
            "additionalProperties": False,
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Judge verdicts",
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "object",
                "properties": per_question,
                "required": list(per_question),
                "additionalProperties": False,
            }
        },
        "required": ["verdicts"],
        "additionalProperties": False,
    }


def _student_answer_text(answer: Any) -> str:
    if isinstance(answer, TextAnswer):
        return answer.text
    if isinstance(answer, DrawingAnswer):
        return f"(Drawing, described by the student) {answer.description}"
    return _answer_to_text(answer)


def build_judge_tasks(
    bundle: ExamBundle, sheet: AnswerSheet, judge_rules: dict[str, QuestionGrading]
) -> dict[str, Any]:
    """The tasks.json payload: everything a judge needs, per question."""
    exam = bundle.exam
    leaves = exam.leaf_map()
    tasks: list[dict[str, Any]] = []
    for qid, grading in judge_rules.items():
        rule = grading.rule
        assert isinstance(rule, JudgeRule)
        leaf = leaves[qid]
        section = exam.section_of(qid)
        context: list = []
        if section is not None:
            for top in section.questions:
                if any(child.id == qid for child in top.iter_leaves()):
                    context = leaf_context(top, qid)
                    break
        rendered = render_question_parts(bundle, leaf, section, context)
        answer = sheet.answers[qid]
        assets = sorted(question_assets(leaf))
        if isinstance(answer, DrawingAnswer) and answer.image_asset:
            assets.append(answer.image_asset)
        tasks.append(
            {
                "question_id": qid,
                "question_number": leaf.number,
                "max_points": grading.max_points,
                "min_points": grading.min_points,
                "question_text": "\n\n".join(p for p in rendered if isinstance(p, str)),
                "question_assets": assets,
                "rubric": [c.model_dump(mode="json") for c in rule.rubric],
                "reference_answer": rule.reference_answer,
                "reference_assets": rule.reference_assets,
                "judge_instructions": rule.judge_instructions,
                "student_answer": answer.model_dump(mode="json"),
                "student_answer_text": _student_answer_text(answer),
            }
        )
    return {"tasks": tasks}


def _verdict_problems(qid: str, grading: QuestionGrading, raw: Any) -> list[str]:
    """Problems with one question's raw verdict dict (empty = usable)."""
    if raw is None:
        return [f"verdicts must include question {qid}"]
    try:
        verdict = JudgeVerdict.model_validate(raw)
    except ValidationError as e:
        return [f"verdict for {qid} is invalid: {e}"]
    rule = grading.rule
    assert isinstance(rule, JudgeRule)
    expected = {c.id for c in rule.rubric}
    got = {c.criterion_id for c in verdict.criteria}
    if expected != got:
        return [
            f"verdict for {qid} must score exactly the rubric criteria "
            f"{sorted(expected)} (got {sorted(got)})"
        ]
    return []


def agentic_judge(
    bundle: ExamBundle,
    sheet: AnswerSheet,
    judge_rules: dict[str, QuestionGrading],
    judge_model: str,
    warnings: list[str],
    tracker: UsageTracker,
    effort: Effort | str | None = None,
) -> dict[str, JudgeVerdict]:
    cli_model = parse_agentic_model(judge_model)
    if cli_model is None:
        raise ValueError(f"not an agentic model string: {judge_model!r}")
    if not judge_rules:
        return {}

    workspace = new_workspace("judge")
    write_agents_md(workspace, JUDGE_AGENTS_MD)
    write_json(workspace / "tasks" / "tasks.json", build_judge_tasks(bundle, sheet, judge_rules))
    write_json(workspace / "exam" / "exam.json", bundle.exam)
    schema = generate_verdicts_schema(judge_rules)
    write_json(workspace / "schemas" / "verdicts.schema.json", schema)
    (workspace / "output").mkdir()

    assets: set[str] = set()
    for qid, grading in judge_rules.items():
        rule = grading.rule
        assert isinstance(rule, JudgeRule)
        assets.update(question_assets(bundle.exam.leaf_map()[qid]))
        assets.update(rule.reference_assets)
        answer = sheet.answers[qid]
        if isinstance(answer, DrawingAnswer) and answer.image_asset:
            assets.add(answer.image_asset)
    copy_assets(bundle.root, assets, workspace / "exam")

    latest: Any = None

    def oracle() -> list[str]:
        nonlocal latest
        path = workspace / "output" / "verdicts.json"
        if not path.exists():
            return ["missing file: output/verdicts.json"]
        try:
            data = read_json(path)
        except ValueError as e:
            return [f"output/verdicts.json is not valid JSON: {e}"]
        latest = data
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=str)
        problems = [
            f"output/verdicts.json {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: "
            f"{e.message}"
            for e in errors
        ]
        if problems:
            return problems
        for qid, grading in judge_rules.items():
            problems.extend(_verdict_problems(qid, grading, data["verdicts"].get(qid)))
        return problems

    try:
        outcome = run_fix_loop(
            workspace,
            JUDGE_TASK_PROMPT,
            cli_model,
            oracle,
            on_usage=lambda u: tracker.add(f"judge:{judge_model}", u),
            effort=effort,
        )
    except CodexError as e:
        raise CodexError(f"{e} (workspace kept at {workspace})") from e

    # Salvage per-question: on success everything passes; on exhaustion keep
    # whatever verdicts are individually valid and warn about the rest.
    raw_verdicts = latest.get("verdicts") if isinstance(latest, dict) else None
    raw_verdicts = raw_verdicts if isinstance(raw_verdicts, dict) else {}
    verdicts: dict[str, JudgeVerdict] = {}
    for qid, grading in judge_rules.items():
        raw = raw_verdicts.get(qid)
        problems = _verdict_problems(qid, grading, raw)
        if problems:
            warnings.append(f"question {qid}: judge {judge_model}: {problems[0]}")
            continue
        rule = grading.rule
        assert isinstance(rule, JudgeRule)
        verdicts[qid] = snap_verdict(
            JudgeVerdict.model_validate(raw),
            rule,
            grading.max_points,
            grading.min_points,
            warnings,
            qid,
            judge_model,
        )
    if not outcome.problems:
        cleanup_workspace(workspace)
    else:
        warnings.append(
            f"judge {judge_model}: {len(outcome.problems)} validation problem(s) remained "
            f"after {outcome.rounds_run} round(s); workspace kept at {workspace}"
        )
    return verdicts
