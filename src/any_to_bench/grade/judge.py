"""LLM-judge grading for open-ended questions (short answer, essay, drawing)."""

from __future__ import annotations

import math
import statistics
from typing import Any

from any_to_bench.agentic.runner import parse_agentic_model
from any_to_bench.bundle import ExamBundle
from any_to_bench.llm import UsageTracker, build_agent
from any_to_bench.schemas.answers import (
    AnswerSheet,
    AnswerValue,
    DrawingAnswer,
    FillInBlankAnswer,
    MatchingAnswer,
    MultipleChoiceAnswer,
    SingleChoiceAnswer,
    TextAnswer,
    TrueFalseAnswer,
)
from any_to_bench.schemas.grading import JudgeRule, QuestionGrading, RubricCriterion
from any_to_bench.schemas.report import (
    CriterionScore,
    JudgeAgreement,
    JudgeVerdict,
    QuestionResult,
)
from any_to_bench.schemas.usage import Effort
from any_to_bench.solve.render import Part, asset_content, leaf_context, render_question_parts

JUDGE_INSTRUCTIONS = (
    "You are an experienced, impartial exam grader. Grade the student's answer to the "
    "question below. Base your judgment only on the question, the scoring materials "
    "provided (rubric, reference answer, grading instructions), and the student's "
    "answer. Be strict but fair: award points the answer earns, no more. When a rubric "
    "is given, score every criterion at exactly one of its defined point levels and "
    "give a short rationale per criterion. Set total_points to the sum of your "
    "criterion scores (or your holistic score if no rubric is given)."
)


def _rubric_text(rubric: list[RubricCriterion]) -> str:
    lines = ["Scoring rubric (score each criterion at exactly one defined level):"]
    for criterion in rubric:
        lines.append(f"- Criterion '{criterion.id}': {criterion.description}")
        for level in criterion.levels:
            lines.append(f"    - {level.points:g} points: {level.descriptor}")
    return "\n".join(lines)


def _answer_to_text(answer: AnswerValue) -> str:
    """Textual form of a non-open-ended answer, for judge-fallback grading."""
    if isinstance(answer, SingleChoiceAnswer):
        return f"The student selected option: {answer.selected}"
    if isinstance(answer, MultipleChoiceAnswer):
        return f"The student selected options: {', '.join(answer.selected) or '(none)'}"
    if isinstance(answer, TrueFalseAnswer):
        return f"The student answered: {'true' if answer.value else 'false'}"
    if isinstance(answer, FillInBlankAnswer):
        filled = "; ".join(f"{k} = {v!r}" for k, v in answer.blanks.items())
        return f"The student filled the blanks: {filled or '(empty)'}"
    if isinstance(answer, MatchingAnswer):
        pairs = "; ".join(f"{k} -> {v}" for k, v in answer.pairs.items())
        return f"The student matched: {pairs or '(empty)'}"
    raise TypeError(f"unexpected answer type {answer.type}")


def build_judge_parts(
    bundle: ExamBundle,
    question_id: str,
    rule: JudgeRule,
    max_points: float,
    answer: AnswerValue,
) -> list[Part]:
    exam = bundle.exam
    section = exam.section_of(question_id)
    leaf = exam.leaf_map()[question_id]
    context: list = []
    if section is not None:
        for top in section.questions:
            if any(child.id == question_id for child in top.iter_leaves()):
                context = leaf_context(top, question_id)
                break

    parts: list[Part] = []
    if rule.include_question_images:
        parts.extend(render_question_parts(bundle, leaf, section, context))
    else:
        parts.append(f"### Question {leaf.number or leaf.id} ({leaf.points:g} points)")
        rendered = render_question_parts(bundle, leaf, section, context)
        parts.extend(p for p in rendered if isinstance(p, str))

    parts.append(f"Maximum points for this question: {max_points:g}.")
    if rule.judge_instructions:
        parts.append(f"Official grading instructions:\n{rule.judge_instructions}")
    if rule.rubric:
        parts.append(_rubric_text(rule.rubric))
    if rule.reference_answer:
        parts.append(f"Reference answer / model solution:\n{rule.reference_answer}")
    for asset in rule.reference_assets:
        if bundle.asset_path(asset).exists():
            parts.append("[Reference figure]")
            parts.append(asset_content(bundle, asset))

    parts.append("--- Student's answer ---")
    if isinstance(answer, TextAnswer):
        parts.append(answer.text)
    elif isinstance(answer, DrawingAnswer):
        parts.append(f"(Drawing, described by the student) {answer.description}")
        if answer.image_asset:
            path = bundle.asset_path(answer.image_asset)
            if path.exists():
                parts.append(asset_content(bundle, answer.image_asset))
    else:
        parts.append(_answer_to_text(answer))
    return parts


def snap_verdict(
    verdict: JudgeVerdict,
    rule: JudgeRule,
    max_points: float,
    min_points: float,
    warnings: list[str],
    question_id: str,
    judge_model: str,
) -> tuple[JudgeVerdict, dict[str, Any]]:
    """Force a verdict onto the rubric's defined levels and recompute the total.

    Returns the snapped verdict and a record of what the judge actually said
    before snapping. Snapping is a real part of how this tool makes grading
    reproducible — two judges saying 1.7 and 2.3 both become 2.0 — which means
    any measurement of judge agreement taken after it partly measures our own
    rounding. Keeping the raw figures lets that contribution be subtracted out
    instead of quietly counted as the models agreeing.
    """
    raw: dict[str, Any] = {
        "total": verdict.total_points,
        "criteria": {c.criterion_id: c.points for c in verdict.criteria},
    }
    if not rule.rubric:
        total = max(min_points, min(max_points, verdict.total_points))
        if total != verdict.total_points:
            warnings.append(
                f"question {question_id}: judge {judge_model} total {verdict.total_points} "
                f"clamped to {total}"
            )
        raw["changed"] = total != verdict.total_points
        return (
            JudgeVerdict(
                criteria=verdict.criteria,
                total_points=total,
                overall_rationale=verdict.overall_rationale,
            ),
            raw,
        )

    by_id = {c.criterion_id: c for c in verdict.criteria}
    snapped: list[CriterionScore] = []
    for criterion in rule.rubric:
        score = by_id.get(criterion.id)
        if score is None:
            warnings.append(
                f"question {question_id}: judge {judge_model} omitted criterion "
                f"{criterion.id!r}; scored 0"
            )
            lowest = min(level.points for level in criterion.levels)
            snapped.append(
                CriterionScore(
                    criterion_id=criterion.id,
                    points=min(lowest, 0.0),
                    rationale="(criterion not scored by judge)",
                )
            )
            continue
        levels = [level.points for level in criterion.levels]
        nearest = min(levels, key=lambda p: abs(p - score.points))
        if nearest != score.points:
            warnings.append(
                f"question {question_id}: judge {judge_model} gave {score.points} for "
                f"{criterion.id!r}; snapped to level {nearest}"
            )
        snapped.append(
            CriterionScore(criterion_id=criterion.id, points=nearest, rationale=score.rationale)
        )
    for extra in verdict.criteria:
        if all(extra.criterion_id != c.id for c in rule.rubric):
            warnings.append(
                f"question {question_id}: judge {judge_model} scored unknown criterion "
                f"{extra.criterion_id!r}; ignored"
            )
    total = max(min_points, min(max_points, sum(c.points for c in snapped)))
    raw["criteria_sum"] = sum(c.points for c in verdict.criteria)
    raw["changed"] = (
        any(raw["criteria"].get(c.criterion_id) != c.points for c in snapped)
        or total != verdict.total_points
    )
    return (
        JudgeVerdict(
            criteria=snapped, total_points=total, overall_rationale=verdict.overall_rationale
        ),
        raw,
    )


def judge_one(
    bundle: ExamBundle,
    question_id: str,
    grading: QuestionGrading,
    answer: AnswerValue,
    judge_model: str,
    warnings: list[str],
    tracker: UsageTracker,
    effort: Effort | str | None = None,
) -> tuple[JudgeVerdict, dict[str, Any]]:
    rule = grading.rule
    assert isinstance(rule, JudgeRule)
    parts = build_judge_parts(bundle, question_id, rule, grading.max_points, answer)
    agent = build_agent(judge_model, JudgeVerdict, JUDGE_INSTRUCTIONS, effort=effort)
    result = agent.run_sync(parts)
    tracker.add(f"judge:{judge_model}", result.usage)
    verdict = result.output

    if rule.rubric:
        expected_ids = {c.id for c in rule.rubric}
        got_ids = {c.criterion_id for c in verdict.criteria}
        if got_ids != expected_ids:
            retry_parts: list[Part] = [
                *parts,
                "Your previous verdict did not score the rubric criteria "
                f"{sorted(expected_ids)} exactly. Score each of them at one of its "
                "defined point levels.",
            ]
            retry_result = agent.run_sync(retry_parts)
            tracker.add(f"judge:{judge_model}", retry_result.usage)
            verdict = retry_result.output

    return snap_verdict(
        verdict, rule, grading.max_points, grading.min_points, warnings, question_id, judge_model
    )


def run_judges(
    bundle: ExamBundle,
    sheet: AnswerSheet,
    judge_rules: dict[str, QuestionGrading],
    models: list[str],
    aggregation: str,
    warnings: list[str],
    tracker: UsageTracker,
    effort: Effort | str | None = None,
) -> dict[str, tuple[float, list[JudgeVerdict], dict[str, Any]]]:
    """Judge every open-ended answered question with every judge model.

    Direct-LLM judges run one call per question; agentic (codex:) judges run
    one batch workspace session per model, collected up front.
    """
    results: dict[str, tuple[float, list[JudgeVerdict], dict[str, Any]]] = {}
    if not judge_rules:
        return results

    agentic_verdicts: dict[str, dict[str, JudgeVerdict]] = {}
    agentic_raw: dict[str, dict[str, dict[str, Any]]] = {}
    for judge_model in models:
        if parse_agentic_model(judge_model) is None:
            continue
        from any_to_bench.agentic.judge import agentic_judge

        raw_out: dict[str, dict[str, Any]] = {}
        agentic_raw[judge_model] = raw_out
        try:
            agentic_verdicts[judge_model] = agentic_judge(
                bundle, sheet, judge_rules, judge_model, warnings, tracker, effort, raw_out
            )
        except Exception as e:  # noqa: BLE001 — a failing judge must not sink the run
            warnings.append(f"judge {judge_model} failed: {e}")
            agentic_verdicts[judge_model] = {}

    for question_id, grading in judge_rules.items():
        answer = sheet.answers[question_id]
        # Kept as pairs, not two lists: judges drop out on failure, so anything
        # zipping a verdict list against the requested model list mis-attributes.
        scored: list[tuple[str, JudgeVerdict, dict[str, Any]]] = []
        for judge_model in models:
            if judge_model in agentic_verdicts:
                verdict = agentic_verdicts[judge_model].get(question_id)
                if verdict is not None:  # missing ones were already warned about
                    scored.append(
                        (judge_model, verdict, agentic_raw[judge_model].get(question_id, {}))
                    )
                continue
            try:
                verdict, raw = judge_one(
                    bundle, question_id, grading, answer, judge_model, warnings, tracker, effort
                )
                scored.append((judge_model, verdict, raw))
            except Exception as e:  # noqa: BLE001 — a failing judge must not sink the run
                warnings.append(f"question {question_id}: judge {judge_model} failed: {e}")
        if not scored:
            results[question_id] = (
                0.0,
                [],
                {"error": "all judges failed", "requested_judge_models": models},
            )
            continue

        scoring_models = [m for m, _, _ in scored]
        verdicts = [v for _, v, _ in scored]
        raw_records = [r for _, _, r in scored]
        totals = [v.total_points for v in verdicts]
        if aggregation == "median":
            awarded = statistics.median(totals)
        elif aggregation == "min":
            awarded = min(totals)
        elif aggregation == "max":
            awarded = max(totals)
        else:
            awarded = statistics.fmean(totals)
        results[question_id] = (
            awarded,
            verdicts,
            {
                # Only the judges that actually scored, positionally matching
                # `verdicts` and `totals` by construction.
                "judge_models": scoring_models,
                "requested_judge_models": models,
                "aggregation": aggregation,
                "totals": totals,
                # What each judge said before its scores were snapped onto the
                # rubric's levels, positionally matching `judge_models`. Agreement
                # measured after snapping partly measures the snapping.
                "raw_totals": [r.get("total") for r in raw_records],
                "snap_changed": [bool(r.get("changed")) for r in raw_records],
                "agreement": _question_agreement(totals, grading.max_points),
                "raw_agreement": _question_agreement(
                    [r["total"] for r in raw_records if r.get("total") is not None],
                    grading.max_points,
                )
                if all(r.get("total") is not None for r in raw_records)
                else None,
            },
        )
    return results


def _question_agreement(totals: list[float], max_points: float) -> dict[str, Any]:
    """How far apart the judges landed on one question."""
    spread = max(totals) - min(totals)
    return {
        "judge_count": len(totals),
        "spread": spread,
        "stdev": statistics.stdev(totals) if len(totals) >= 2 else 0.0,
        "normalized_spread": spread / max_points if max_points else 0.0,
        "unanimous": math.isclose(spread, 0.0, abs_tol=1e-9),
    }


def summarize_judge_agreement(
    results: dict[str, QuestionResult], requested_models: list[str]
) -> JudgeAgreement | None:
    """Roll per-question agreement up into one report-level summary.

    Pure over the finished results so it is testable without a judge run, and so
    `run_judges` keeps its return type.
    """
    judged = [r for r in results.values() if r.judge_verdicts]
    if not judged:
        return None

    spreads: list[float] = []
    normalized: list[float] = []
    disagreed = 0
    multi = 0
    by_judge: dict[str, list[float]] = {}
    for result in judged:
        agreement = result.detail.get("agreement") or {}
        for model, verdict in zip(
            result.detail.get("judge_models") or [], result.judge_verdicts, strict=False
        ):
            by_judge.setdefault(model, []).append(verdict.total_points)
        if len(result.judge_verdicts) < 2:
            continue
        multi += 1
        spreads.append(agreement.get("spread", 0.0))
        normalized.append(agreement.get("normalized_spread", 0.0))
        if not agreement.get("unanimous", True):
            disagreed += 1

    return JudgeAgreement(
        requested_judge_models=list(requested_models),
        judged_questions=len(judged),
        multi_judge_questions=multi,
        disagreed_questions=disagreed,
        mean_spread=statistics.fmean(spreads) if spreads else 0.0,
        max_spread=max(spreads) if spreads else 0.0,
        mean_normalized_spread=statistics.fmean(normalized) if normalized else 0.0,
        per_judge_mean={m: statistics.fmean(v) for m, v in sorted(by_judge.items())},
    )
