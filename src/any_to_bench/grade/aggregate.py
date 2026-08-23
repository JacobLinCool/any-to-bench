"""Grade a filled answer sheet against a bundle and build the report."""

from __future__ import annotations

from datetime import UTC, datetime

from any_to_bench.bundle import ExamBundle
from any_to_bench.grade.deterministic import AnswerTypeMismatch, grade_deterministic
from any_to_bench.llm import UsageTracker
from any_to_bench.modality import Modality, ModalityRequirement, describe_missing, exam_modalities
from any_to_bench.resources import resource_access
from any_to_bench.schemas.answers import AnswerSheet
from any_to_bench.schemas.grading import JudgeRule
from any_to_bench.schemas.report import GradeReport, QuestionResult, SectionTotal
from any_to_bench.schemas.usage import Effort


def run_grade(
    bundle: ExamBundle,
    sheet: AnswerSheet,
    judge_models: list[str] | None = None,
    effort: Effort | str | None = None,
    capabilities: frozenset[Modality] | None = None,
) -> GradeReport:
    """Grade a sheet. capabilities, when given, marks questions the taker was
    never equipped to attempt as skipped rather than as answered-wrong."""
    exam, grading = bundle.exam, bundle.grading
    requirements = exam_modalities(exam) if capabilities is not None else {}
    warnings: list[str] = []
    tracker = UsageTracker()
    if sheet.exam_id != exam.exam_id:
        warnings.append(
            f"answer sheet exam_id {sheet.exam_id!r} != bundle exam_id {exam.exam_id!r}"
        )

    leaves = exam.leaf_map()
    results: dict[str, QuestionResult] = {}

    citation_checks = {}
    citation_summary = None
    if bundle.has_resources:
        from any_to_bench.grade.citations import check_citations

        citation_checks, citation_summary = check_citations(bundle, sheet)

    judge_rules = {
        qid: qg
        for qid, qg in grading.questions.items()
        if isinstance(qg.rule, JudgeRule) and sheet.answers.get(qid) is not None
    }
    effective_judges = list(judge_models or grading.judge.models)
    if judge_rules:
        # bench runs these same checks up front; grade is used directly just as
        # often, and a self-judged score is exactly the one that looks fine.
        if sheet.taker in effective_judges:
            warnings.append(
                f"taker {sheet.taker} judged its own answers; self-judging tends to be "
                "optimistic — prefer a --judge-model different from the taker"
            )
        if len(effective_judges) < 2:
            warnings.append(
                "single judge model — inter-judge agreement cannot be measured; pass a "
                "second --judge-model to see how much of the score is judge-dependent"
            )
    judge_verdicts = {}
    if judge_rules:
        from any_to_bench.grade.judge import run_judges

        judge_verdicts = run_judges(
            bundle,
            sheet,
            judge_rules,
            models=effective_judges,
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

        if answer is None and capabilities is not None:
            # Only when the taker actually answered nothing: a taker that
            # attempted a question beyond its declared modalities is graded on
            # what it produced, not excused from it.
            missing = requirements.get(qid, ModalityRequirement()).missing_from(capabilities)
            if missing:
                results[qid] = QuestionResult(
                    question_id=qid,
                    mode="skipped",
                    max_points=qg.max_points,
                    awarded=0.0,
                    detail={
                        "reason": "taker lacks a modality this question requires",
                        "missing_modalities": describe_missing(missing),
                        "modality_sources": requirements[qid].sources,
                    },
                )
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

    for qid, result in results.items():
        result.citation_checks = citation_checks.get(qid, [])

    section_totals: dict[str, SectionTotal] = {}
    for section in exam.sections:
        leaf_ids = [leaf.id for question in section.questions for leaf in question.iter_leaves()]
        section_totals[section.id] = SectionTotal(
            awarded=sum(results[qid].awarded for qid in leaf_ids if qid in results),
            max_points=sum(results[qid].max_points for qid in leaf_ids if qid in results),
        )

    from any_to_bench.grade.judge import summarize_judge_agreement

    total_awarded = sum(r.awarded for r in results.values())
    total_max = sum(r.max_points for r in results.values())
    skipped = [r for r in results.values() if r.mode == "skipped"]
    skipped_points = sum(r.max_points for r in skipped)
    covered_max = total_max - skipped_points
    if skipped:
        warnings.append(
            f"{len(skipped)} question(s) worth {skipped_points:g} point(s) were skipped as "
            "beyond the taker's declared modalities; the score covers the rest"
        )
    reported_access = sheet.resource_access
    if reported_access is None and bundle.has_resources:
        reported_access = resource_access(bundle.manifest.resources, "unknown")
    return GradeReport(
        exam_id=exam.exam_id,
        taker=sheet.taker,
        graded_at=datetime.now(UTC),
        results=results,
        section_totals=section_totals,
        total_awarded=total_awarded,
        total_max=total_max,
        percentage=(100.0 * total_awarded / total_max) if total_max else 0.0,
        skipped_count=len(skipped),
        skipped_points=skipped_points,
        covered_max=covered_max,
        covered_percentage=(100.0 * total_awarded / covered_max) if covered_max else 0.0,
        warnings=warnings,
        judge_agreement=summarize_judge_agreement(results, effective_judges),
        usage=tracker.summary(),
        resource_access=reported_access,
        citations=citation_summary,
    )
