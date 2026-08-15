"""Deterministic graders for every fixed-answer question type."""

import pytest

from any_to_bench.grade.deterministic import (
    AnswerTypeMismatch,
    grade_choice,
    grade_deterministic,
    grade_fill_in_blank,
    grade_matching,
    grade_true_false,
)
from any_to_bench.schemas.answers import (
    FillInBlankAnswer,
    MatchingAnswer,
    MultipleChoiceAnswer,
    SingleChoiceAnswer,
    TextAnswer,
    TrueFalseAnswer,
)
from any_to_bench.schemas.grading import (
    BlankSpec,
    ChoiceRule,
    FillBlankRule,
    MatchingRule,
    Normalization,
    TrueFalseRule,
)


class TestChoice:
    def test_single_correct(self):
        rule = ChoiceRule(correct=["B"])
        awarded, _ = grade_choice(rule, 2.0, 0.0, SingleChoiceAnswer(selected="B"))
        assert awarded == 2.0

    def test_single_wrong(self):
        rule = ChoiceRule(correct=["B"])
        awarded, _ = grade_choice(rule, 2.0, 0.0, SingleChoiceAnswer(selected="A"))
        assert awarded == 0.0

    def test_single_choice_accepts_any_listed_option(self):
        """An amended key ("B or C both accepted") must pay out on either."""
        rule = ChoiceRule(correct=["B", "C"])

        assert grade_choice(rule, 2.0, 0.0, SingleChoiceAnswer(selected="B"))[0] == 2.0
        assert grade_choice(rule, 2.0, 0.0, SingleChoiceAnswer(selected="C"))[0] == 2.0
        assert grade_choice(rule, 2.0, 0.0, SingleChoiceAnswer(selected="A"))[0] == 0.0

    def test_single_choice_voided_question_pays_every_option(self):
        """A defective question voided into 送分: every option earns full marks."""
        rule = ChoiceRule(correct=["A", "B", "C", "D"])

        for option in ("A", "B", "C", "D"):
            assert grade_choice(rule, 2.0, 0.0, SingleChoiceAnswer(selected=option))[0] == 2.0

    def test_multiple_choice_still_needs_the_exact_set(self):
        """The accept-list reading is single_choice only; multi-select is unchanged."""
        rule = ChoiceRule(correct=["A", "C"])

        assert grade_choice(rule, 3.0, 0.0, MultipleChoiceAnswer(selected=["A", "C"]))[0] == 3.0
        assert grade_choice(rule, 3.0, 0.0, MultipleChoiceAnswer(selected=["A"]))[0] == 0.0

    def test_single_negative_marking(self):
        rule = ChoiceRule(correct=["B"], negative_marking=-0.5)
        awarded, detail = grade_choice(rule, 2.0, -0.5, SingleChoiceAnswer(selected="A"))
        assert awarded == -0.5
        assert detail["negative_marking"] is True

    def test_multi_exact(self):
        rule = ChoiceRule(correct=["A", "C"], partial_credit=True)
        awarded, _ = grade_choice(rule, 3.0, 0.0, MultipleChoiceAnswer(selected=["C", "A"]))
        assert awarded == 3.0

    def test_multi_partial(self):
        rule = ChoiceRule(correct=["A", "C"], partial_credit=True)
        awarded, _ = grade_choice(rule, 3.0, 0.0, MultipleChoiceAnswer(selected=["A"]))
        assert awarded == 1.5

    def test_multi_no_partial_credit(self):
        rule = ChoiceRule(correct=["A", "C"])
        awarded, _ = grade_choice(rule, 3.0, 0.0, MultipleChoiceAnswer(selected=["A"]))
        assert awarded == 0.0

    def test_multi_wrong_selection_penalty(self):
        rule = ChoiceRule(correct=["A", "C"], partial_credit=True, wrong_selection_penalty=1.0)
        awarded, _ = grade_choice(rule, 4.0, 0.0, MultipleChoiceAnswer(selected=["A", "B"]))
        assert awarded == 1.0  # 4*1/2 - 1

    def test_penalty_clamped_at_floor(self):
        rule = ChoiceRule(correct=["A", "C"], partial_credit=True, wrong_selection_penalty=5.0)
        awarded, _ = grade_choice(rule, 4.0, 0.0, MultipleChoiceAnswer(selected=["A", "B"]))
        assert awarded == 0.0

    def test_type_mismatch(self):
        with pytest.raises(AnswerTypeMismatch):
            grade_choice(ChoiceRule(correct=["A"]), 1.0, 0.0, TextAnswer(text="A"))


class TestTrueFalse:
    def test_correct(self):
        rule = TrueFalseRule(correct=True)
        awarded, _ = grade_true_false(rule, 1.0, 0.0, TrueFalseAnswer(value=True))
        assert awarded == 1.0

    def test_wrong(self):
        rule = TrueFalseRule(correct=True)
        awarded, _ = grade_true_false(rule, 1.0, 0.0, TrueFalseAnswer(value=False))
        assert awarded == 0.0

    def test_negative_marking(self):
        rule = TrueFalseRule(correct=True, negative_marking=-1.0)
        awarded, _ = grade_true_false(rule, 1.0, -1.0, TrueFalseAnswer(value=False))
        assert awarded == -1.0


class TestFillInBlank:
    RULE = FillBlankRule(
        blanks={
            "b1": BlankSpec(accepted=["Paris"]),
            "b2": BlankSpec(accepted=["3.14", "pi"]),
        },
        normalization=Normalization(numeric_tolerance=0.01),
    )

    def test_all_correct_with_normalization(self):
        answer = FillInBlankAnswer(blanks={"b1": "  PARIS ", "b2": "3.1416"})
        awarded, _ = grade_fill_in_blank(self.RULE, 2.0, 0.0, answer)
        assert awarded == 2.0

    def test_half_correct(self):
        answer = FillInBlankAnswer(blanks={"b1": "London", "b2": "pi"})
        awarded, detail = grade_fill_in_blank(self.RULE, 2.0, 0.0, answer)
        assert awarded == 1.0
        assert detail["blanks"]["b1"]["matched"] is False
        assert detail["blanks"]["b2"]["matched"] is True

    def test_missing_blank_counts_as_wrong(self):
        answer = FillInBlankAnswer(blanks={"b1": "Paris"})
        awarded, _ = grade_fill_in_blank(self.RULE, 2.0, 0.0, answer)
        assert awarded == 1.0

    def test_weights(self):
        rule = FillBlankRule(
            blanks={
                "b1": BlankSpec(accepted=["x"], weight=3.0),
                "b2": BlankSpec(accepted=["y"], weight=1.0),
            }
        )
        answer = FillInBlankAnswer(blanks={"b1": "x", "b2": "nope"})
        awarded, _ = grade_fill_in_blank(rule, 4.0, 0.0, answer)
        assert awarded == 3.0

    def test_all_or_nothing(self):
        rule = self.RULE.model_copy(update={"all_or_nothing": True})
        answer = FillInBlankAnswer(blanks={"b1": "Paris", "b2": "wrong"})
        awarded, _ = grade_fill_in_blank(rule, 2.0, 0.0, answer)
        assert awarded == 0.0


class TestMatching:
    RULE = MatchingRule(correct_pairs={"L1": "R2", "L2": "R1"})

    def test_all_correct(self):
        answer = MatchingAnswer(pairs={"L1": "R2", "L2": "R1"})
        awarded, _ = grade_matching(self.RULE, 2.0, 0.0, answer)
        assert awarded == 2.0

    def test_half_correct(self):
        answer = MatchingAnswer(pairs={"L1": "R2", "L2": "R3"})
        awarded, _ = grade_matching(self.RULE, 2.0, 0.0, answer)
        assert awarded == 1.0

    def test_wrong_pair_penalty(self):
        rule = MatchingRule(correct_pairs={"L1": "R2", "L2": "R1"}, wrong_pair_penalty=0.5)
        answer = MatchingAnswer(pairs={"L1": "R2", "L2": "R3"})
        awarded, _ = grade_matching(rule, 2.0, 0.0, answer)
        assert awarded == 0.5

    def test_unanswered_pair_not_penalized(self):
        rule = MatchingRule(correct_pairs={"L1": "R2", "L2": "R1"}, wrong_pair_penalty=0.5)
        answer = MatchingAnswer(pairs={"L1": "R2"})
        awarded, _ = grade_matching(rule, 2.0, 0.0, answer)
        assert awarded == 1.0

    def test_all_or_nothing(self):
        rule = MatchingRule(correct_pairs={"L1": "R2", "L2": "R1"}, all_or_nothing=True)
        answer = MatchingAnswer(pairs={"L1": "R2", "L2": "R3"})
        awarded, _ = grade_matching(rule, 2.0, 0.0, answer)
        assert awarded == 0.0


def test_dispatch():
    awarded, _ = grade_deterministic(
        ChoiceRule(correct=["A"]), 1.0, 0.0, SingleChoiceAnswer(selected="A")
    )
    assert awarded == 1.0
