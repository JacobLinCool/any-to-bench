"""Deterministic citation authenticity checks; never part of the score."""

from __future__ import annotations

from any_to_bench.bundle import ExamBundle
from any_to_bench.schemas.answers import AnswerSheet
from any_to_bench.schemas.resources import CitationCheck, CitationSummary


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def check_citations(
    bundle: ExamBundle, sheet: AnswerSheet
) -> tuple[dict[str, list[CitationCheck]], CitationSummary]:
    resources = {entry.path: entry for entry in bundle.manifest.resources}
    checks: dict[str, list[CitationCheck]] = {}
    summary = CitationSummary()
    for question_id, answer in sheet.answers.items():
        question_checks: list[CitationCheck] = []
        for index, citation in enumerate(answer.citations or []):
            summary.submitted += 1
            resource = resources.get(citation.path)
            if resource is None:
                status = "missing_resource"
                summary.missing_resources += 1
            elif not resource.text:
                status = "unverifiable_binary"
                summary.valid_paths += 1
                summary.unverifiable_binary += 1
            else:
                summary.valid_paths += 1
                source = (bundle.root / resource.path).read_text(encoding="utf-8")
                if _normalize_newlines(citation.excerpt) in _normalize_newlines(source):
                    status = "verified"
                    summary.verified += 1
                else:
                    status = "quote_mismatch"
                    summary.quote_mismatches += 1
            question_checks.append(
                CitationCheck(
                    question_id=question_id,
                    citation_index=index,
                    path=citation.path,
                    status=status,
                )
            )
        checks[question_id] = question_checks
    return checks, summary
