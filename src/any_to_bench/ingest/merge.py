"""Programmatic merge of chunked extraction results."""

from __future__ import annotations

import re

from any_to_bench.schemas.extraction import ExtractedQuestion, ExtractionChunk


def normalize_number(number: str) -> str:
    """Normalize a printed question number for matching: '1.' == '1)' == 'Q1'."""
    text = number.strip().lower()
    text = re.sub(r"^(q|question|第)\s*", "", text)
    text = re.sub(r"[\s.。()（）\[\]]+", "", text)
    text = re.sub(r"(題|题|问|問)$", "", text)
    return text or number.strip().lower()


def merge_chunks(chunks: list[ExtractionChunk]) -> list[ExtractedQuestion]:
    """Stitch chunk outputs into one ordered, de-duplicated question list.

    Chunks are produced from page windows with one page of overlap, so the same
    question can be extracted twice — the first extraction wins (it saw the
    question's beginning). `continues_previous` marks chunks whose first pages
    only continue an already-extracted question.
    """
    merged: list[ExtractedQuestion] = []
    seen: set[str] = set()
    for chunk in chunks:
        for question in chunk.questions:
            key = normalize_number(question.number)
            if key in seen:
                continue
            seen.add(key)
            merged.append(question)
    return merged


_RANGE_RE = re.compile(r"(\d+)\s*[-–~～至到]\s*(\d+)")


def leading_int(number: str) -> int | None:
    """The leading integer of a printed question number, if any."""
    match = re.match(r"\d+", normalize_number(number))
    return int(match.group()) if match else None


def covered_numbers(question: ExtractedQuestion) -> set[int]:
    """Every integer question number this question accounts for.

    Group questions print ranges ("第39～41題為題組") and composite children can
    carry the real numbers — all of those must count as present, or gap
    detection would re-extract them as phantom duplicates.
    """
    covered: set[int] = set()
    for lo, hi in _RANGE_RE.findall(question.number):
        lo_i, hi_i = int(lo), int(hi)
        if lo_i <= hi_i <= lo_i + 100:
            covered.update(range(lo_i, hi_i + 1))
    lead = leading_int(question.number)
    if lead is not None:
        covered.add(lead)
    for child in getattr(question, "children", None) or []:
        lead = leading_int(child.number)
        if lead is not None:
            covered.add(lead)
    return covered


def find_gaps(
    questions: list[ExtractedQuestion], expected_last: int | None = None
) -> tuple[list[range], str | None]:
    """Runs of missing question numbers, or (empty, reason) when detection is unsafe.

    Detection only makes sense for a strictly increasing top-level numbering; a
    per-section restart makes gaps meaningless (and merge already conflated the
    duplicate numbers). expected_last extends the search past the largest seen
    number, catching questions lost at the very end.
    """
    leads = [lead for q in questions if (lead := leading_int(q.number)) is not None]
    if len(set(leads)) < 2:
        return [], None
    if any(a >= b for a, b in zip(leads, leads[1:], strict=False)):
        return [], "question numbering is not monotonic; gap repair skipped"

    covered: set[int] = set()
    for question in questions:
        covered |= covered_numbers(question)
    low, high = min(covered), max(covered)
    if expected_last is not None and high < expected_last <= high + 50:
        high = expected_last

    runs: list[range] = []
    for n in range(low, high + 1):
        if n in covered:
            continue
        if runs and runs[-1].stop == n:
            runs[-1] = range(runs[-1].start, n + 1)
        else:
            runs.append(range(n, n + 1))
    return runs, None


def insert_recovered(
    merged: list[ExtractedQuestion], recovered: list[ExtractedQuestion]
) -> list[ExtractedQuestion]:
    """Insert recovered questions into numeric position within the merged list.

    Each goes after the last question with a smaller leading number; questions
    with non-numeric numbers stay glued to their preceding numbered neighbor.
    """
    result = list(merged)
    for question in sorted(recovered, key=lambda q: leading_int(q.number) or 0):
        lead = leading_int(question.number)
        pos = 0
        for i, existing in enumerate(result):
            existing_lead = leading_int(existing.number)
            if lead is not None and existing_lead is not None and existing_lead < lead:
                pos = i + 1
        while 0 < pos < len(result) and leading_int(result[pos].number) is None:
            pos += 1
        result.insert(pos, question)
    return result
