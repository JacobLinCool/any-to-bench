"""Text normalization and comparison for fill-in-blank grading."""

from __future__ import annotations

import math
import re
import unicodedata

from any_to_bench.schemas.grading import Normalization

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str, rules: Normalization) -> str:
    if rules.unicode_nfkc:
        text = unicodedata.normalize("NFKC", text)
    if rules.strip:
        text = text.strip()
    if rules.collapse_whitespace:
        text = _WHITESPACE_RE.sub(" ", text)
    if rules.case_insensitive:
        text = text.casefold()
    return text


def _parse_number(text: str) -> float | None:
    text = text.strip().replace(",", "")
    # Accept simple fractions like "3/4"
    if re.fullmatch(r"[+-]?\d+(\.\d+)?/\d+(\.\d+)?", text):
        num, den = text.split("/")
        try:
            return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(text)
    except ValueError:
        return None


def texts_match(candidate: str, accepted: str, rules: Normalization) -> bool:
    """True if candidate matches accepted under the normalization rules."""
    if normalize_text(candidate, rules) == normalize_text(accepted, rules):
        return True
    if rules.numeric_tolerance is not None:
        a = _parse_number(candidate)
        b = _parse_number(accepted)
        if a is not None and b is not None:
            if rules.numeric_relative:
                return math.isclose(a, b, rel_tol=rules.numeric_tolerance)
            return math.isclose(a, b, abs_tol=rules.numeric_tolerance)
    return False
