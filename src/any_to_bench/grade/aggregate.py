"""Grade a filled answer sheet against a bundle and build the report."""

from __future__ import annotations

from datetime import UTC, datetime

from any_to_bench.bundle import ExamBundle
from any_to_bench.grade.deterministic import AnswerTypeMismatch, grade_deterministic
from any_to_bench.llm import UsageTracker
from any_to_bench.schemas.answers import AnswerSheet
from any_to_bench.schemas.grading import JudgeRule
from any_to_bench.schemas.report import GradeReport, QuestionResult, SectionTotal
from any_to_bench.schemas.usage import Effort


def run_grade(
    bundle: ExamBundle,
    sheet: AnswerSheet,
    judge_models: list[str] | None = None,
    effort: Effort | str | None = None,
) -> GradeReport:
    exam, grading = bundle.exam, bundle.grading
    warnings: list[str] = []
    tracker = UsageTracker()
    if sheet.exam_id != exam.exam_id:
        warnings.append(
            f"answer sheet exam_id {sheet.exam_id!r} != bundle exam_id {exam.exam_id!r}"
        )

    leaves = exam.leaf_map()
    results: dict[str, QuestionResult] = {}

    judge_rules = {
        qid: qg
        for qid, qg in grading.questions.items()
        if isinstance(qg.rule, JudgeRule) and sheet.answers.get(qid) is not None
    }
    judge_verdicts = {}
    if judge_rules:
        from any_to_bench.grade.judge import run_judges

        judge_verdicts = run_judges(
            bundle,
            sheet,
            judge_rules,
            models=judge_models or grading.judge.models,
            aggregation=grading.judge.aggregation,
            warnings=warnings,
            tracker=tracker,
            effort=effort,
        )

    for qid, qg in grading.questions.items():
        question = leaves.get(qid)
        answer = sheet.answers.get(qid)
        if question is None:
            warnings.append(f"grading entry {qid} has no matching question; skipped")
            continue

        if answer is None:
            results[qid] = QuestionResult(
                question_id=qid,
                mode="unanswered",
                max_points=qg.max_points,
                awarded=0.0,
                detail={"reason": "no answer submitted"},
            )
            continue

        if isinstance(qg.rule, JudgeRule):
            outcome = judge_verdicts.get(qid)
            if outcome is None:
                results[qid] = QuestionResult(
                    question_id=qid,
                    mode="error",
                    max_points=qg.max_points,
                    awarded=0.0,
                    detail={"error": "no judge verdict produced"},
                )
            else:
                awarded, verdicts, detail = outcome
                results[qid] = QuestionResult(
                    question_id=qid,
                    mode="judge" if verdicts else "error",
                    max_points=qg.max_points,
                    awarded=awarded,
                    detail=detail,
                    judge_verdicts=verdicts,
                )
            continue

        try:
            awarded, detail = grade_deterministic(qg.rule, qg.max_points, qg.min_points, answer)
            results[qid] = QuestionResult(
                question_id=qid,
                mode="deterministic",
                max_points=qg.max_points,
                awarded=awarded,
                detail=detail,
            )
        except AnswerTypeMismatch as e:
            results[qid] = QuestionResult(
                question_id=qid,
                mode="error",
                max_points=qg.max_points,
                awarded=0.0,
                detail={"error": str(e)},
            )
            warnings.append(f"question {qid}: {e}")

    for qid in sheet.answers:
        if qid not in grading.questions:
            warnings.append(f"answer for unknown question {qid} ignored")

    section_totals: dict[str, SectionTotal] = {}
    for section in exam.sections:
        leaf_ids = [
            leaf.id for question in section.questions for leaf in question.iter_leaves()
        ]
        section_totals[section.id] = SectionTotal(
            awarded=sum(results[qid].awarded for qid in leaf_ids if qid in results),
            max_points=sum(results[qid].max_points for qid in leaf_ids if qid in results),
        )

    total_awarded = sum(r.awarded for r in results.values())
    total_max = sum(r.max_points for r in results.values())
    return GradeReport(
        exam_id=exam.exam_id,
        taker=sheet.taker,
        graded_at=datetime.now(UTC),
        results=results,
        section_totals=section_totals,
        total_awarded=total_awarded,
        total_max=total_max,
        percentage=(100.0 * total_awarded / total_max) if total_max else 0.0,
        warnings=warnings,
        usage=tracker.summary(),
    )
