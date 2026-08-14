"""Deterministic graders: pure functions from (rule, answer) to (awarded, detail).

Semantics:
- An exact/complete correct answer earns max_points.
- Penalties clamp into [min_points, max_points], except negative_marking, which
  is an explicit wrong-answer score and is applied as-is (capped at max_points).
"""

from __future__ import annotations

from typing import Any

from any_to_bench.grade.normalize import texts_match
from any_to_bench.schemas.answers import (
    AnswerValue,
    FillInBlankAnswer,
    MatchingAnswer,
    MultipleChoiceAnswer,
    SingleChoiceAnswer,
    TrueFalseAnswer,
)
from any_to_bench.schemas.grading import (
    ChoiceRule,
    FillBlankRule,
    MatchingRule,
    PerOptionRule,
    TrueFalseRule,
)


class AnswerTypeMismatch(Exception):
    """The submitted answer's type does not fit the grading rule."""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def grade_choice(
    rule: ChoiceRule, max_points: float, min_points: float, answer: AnswerValue
) -> tuple[float, dict[str, Any]]:
    if isinstance(answer, SingleChoiceAnswer):
        selected = {answer.selected}
    elif isinstance(answer, MultipleChoiceAnswer):
        selected = set(answer.selected)
    else:
        raise AnswerTypeMismatch(f"expected a choice answer, got {answer.type}")

    correct = set(rule.correct)
    hits = selected & correct
    wrong = selected - correct
    detail: dict[str, Any] = {
        "selected": sorted(selected),
        "correct": sorted(correct),
        "hits": sorted(hits),
        "wrong": sorted(wrong),
    }

    if selected == correct:
        return max_points, detail

    if not hits and rule.negative_marking is not None:
        detail["negative_marking"] = True
        return min(rule.negative_marking, max_points), detail

    if rule.partial_credit:
        awarded = max_points * len(hits) / len(correct)
        awarded -= rule.wrong_selection_penalty * len(wrong)
        return _clamp(awarded, min_points, max_points), detail

    return _clamp(0.0, min_points, max_points), detail


def grade_per_option(
    rule: PerOptionRule, max_points: float, min_points: float, answer: AnswerValue
) -> tuple[float, dict[str, Any]]:
    if isinstance(answer, MultipleChoiceAnswer):
        selected = set(answer.selected)
    elif isinstance(answer, SingleChoiceAnswer):
        selected = {answer.selected}
    else:
        raise AnswerTypeMismatch(f"expected a choice answer, got {answer.type}")

    correct = set(rule.correct)
    errors = len(selected ^ correct)
    detail: dict[str, Any] = {
        "selected": sorted(selected),
        "correct": sorted(correct),
        "errors": errors,
    }
    if not selected:
        detail["blank"] = True
        return _clamp(0.0, min_points, max_points), detail
    ratio = rule.ratio_by_errors[errors] if errors < len(rule.ratio_by_errors) else 0.0
    detail["ratio"] = ratio
    return _clamp(ratio * max_points, min_points, max_points), detail


def grade_true_false(
    rule: TrueFalseRule, max_points: float, min_points: float, answer: AnswerValue
) -> tuple[float, dict[str, Any]]:
    if not isinstance(answer, TrueFalseAnswer):
        raise AnswerTypeMismatch(f"expected a true/false answer, got {answer.type}")
    detail: dict[str, Any] = {"value": answer.value, "correct": rule.correct}
    if answer.value == rule.correct:
        return max_points, detail
    if rule.negative_marking is not None:
        detail["negative_marking"] = True
        return min(rule.negative_marking, max_points), detail
    return _clamp(0.0, min_points, max_points), detail


def grade_fill_in_blank(
    rule: FillBlankRule, max_points: float, min_points: float, answer: AnswerValue
) -> tuple[float, dict[str, Any]]:
    if not isinstance(answer, FillInBlankAnswer):
        raise AnswerTypeMismatch(f"expected a fill-in-blank answer, got {answer.type}")

    total_weight = sum(spec.weight for spec in rule.blanks.values())
    matched_weight = 0.0
    per_blank: dict[str, Any] = {}
    for blank_id, spec in rule.blanks.items():
        candidate = answer.blanks.get(blank_id, "")
        matched = any(
            texts_match(candidate, accepted, rule.normalization) for accepted in spec.accepted
        )
        per_blank[blank_id] = {"answer": candidate, "matched": matched}
        if matched:
            matched_weight += spec.weight

    detail = {"blanks": per_blank}
    if rule.all_or_nothing:
        awarded = max_points if matched_weight == total_weight else 0.0
    else:
        awarded = max_points * matched_weight / total_weight if total_weight else 0.0
    return _clamp(awarded, min_points, max_points), detail


def grade_matching(
    rule: MatchingRule, max_points: float, min_points: float, answer: AnswerValue
) -> tuple[float, dict[str, Any]]:
    if not isinstance(answer, MatchingAnswer):
        raise AnswerTypeMismatch(f"expected a matching answer, got {answer.type}")

    per_pair: dict[str, Any] = {}
    correct_count = 0
    wrong_count = 0
    for left, expected_right in rule.correct_pairs.items():
        given = answer.pairs.get(left)
        ok = given == expected_right
        per_pair[left] = {"answer": given, "expected": expected_right, "matched": ok}
        if ok:
            correct_count += 1
        elif given is not None:
            wrong_count += 1

    total = len(rule.correct_pairs)
    detail = {"pairs": per_pair}
    if rule.all_or_nothing:
        awarded = max_points if correct_count == total else 0.0
    else:
        awarded = max_points * correct_count / total if total else 0.0
        awarded -= rule.wrong_pair_penalty * wrong_count
    return _clamp(awarded, min_points, max_points), detail


def grade_deterministic(
    rule: ChoiceRule | PerOptionRule | TrueFalseRule | FillBlankRule | MatchingRule,
    max_points: float,
    min_points: float,
    answer: AnswerValue,
) -> tuple[float, dict[str, Any]]:
    """Dispatch to the grader for this rule kind."""
    if isinstance(rule, ChoiceRule):
        return grade_choice(rule, max_points, min_points, answer)
    if isinstance(rule, PerOptionRule):
        return grade_per_option(rule, max_points, min_points, answer)
    if isinstance(rule, TrueFalseRule):
        return grade_true_false(rule, max_points, min_points, answer)
    if isinstance(rule, FillBlankRule):
        return grade_fill_in_blank(rule, max_points, min_points, answer)
    return grade_matching(rule, max_points, min_points, answer)
