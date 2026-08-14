"""Normalization and text matching for fill-in-blank grading."""

import pytest

from any_to_bench.grade.normalize import normalize_text, texts_match
from any_to_bench.schemas.grading import Normalization

DEFAULT = Normalization()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Hello  World ", "hello world"),
        ("ＦＵＬＬｗｉｄｔｈ", "fullwidth"),  # NFKC folds fullwidth forms
        ("Tab\tand\nnewline", "tab and newline"),
        ("MiXeD", "mixed"),
    ],
)
def test_normalize_text(raw, expected):
    assert normalize_text(raw, DEFAULT) == expected


def test_case_sensitive_mode():
    rules = Normalization(case_insensitive=False)
    assert normalize_text("ABC", rules) == "ABC"
    assert not texts_match("abc", "ABC", rules)


@pytest.mark.parametrize(
    ("candidate", "accepted", "matches"),
    [
        ("Paris", "paris", True),
        (" Paris ", "Paris", True),
        ("London", "Paris", False),
    ],
)
def test_texts_match_plain(candidate, accepted, matches):
    assert texts_match(candidate, accepted, DEFAULT) is matches


@pytest.mark.parametrize(
    ("candidate", "accepted", "tolerance", "matches"),
    [
        ("3.1416", "3.14", 0.01, True),
        ("3.16", "3.14", 0.01, False),
        ("1,000", "1000", 0.001, True),
        ("1/2", "0.5", 0.001, True),
        ("half", "0.5", 0.01, False),
    ],
)
def test_numeric_tolerance(candidate, accepted, tolerance, matches):
    rules = Normalization(numeric_tolerance=tolerance)
    assert texts_match(candidate, accepted, rules) is matches


def test_relative_tolerance():
    rules = Normalization(numeric_tolerance=0.05, numeric_relative=True)
    assert texts_match("105", "100", rules)
    assert not texts_match("110", "100", rules)
