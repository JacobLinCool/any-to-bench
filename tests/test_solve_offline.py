"""Offline solve: faked agents answer every question type."""

import any_to_bench.solve.runner as runner_module
from any_to_bench.solve.runner import (
    SolveBlankEntry,
    SolveBlanks,
    SolveChoice,
    SolveDrawing,
    SolveMatching,
    SolveMultiChoice,
    SolvePair,
    SolveText,
    SolveTrueFalse,
    run_solve,
)
from tests.conftest import fake_build_agent

PERFECT_OUTPUTS = {
    SolveChoice: SolveChoice(selected="B"),
    SolveMultiChoice: SolveMultiChoice(selected=["A", "C"]),
    SolveTrueFalse: SolveTrueFalse(value=True),
    SolveBlanks: SolveBlanks(
        entries=[
            SolveBlankEntry(blank_id="b1", text="Paris"),
            SolveBlankEntry(blank_id="b2", text="3.14"),
        ]
    ),
    SolveMatching: SolveMatching(
        pairs=[SolvePair(left_id="L1", right_id="R2"), SolvePair(left_id="L2", right_id="R1")]
    ),
    SolveText: SolveText(text="Chlorophyll absorbs light; more light, faster rate."),
    SolveDrawing: SolveDrawing(description="An upward parabola through the origin."),
}


def test_solve_produces_valid_sheet(tiny_bundle, monkeypatch):
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    sheet = run_solve(tiny_bundle, model="test:solver")
    assert sheet.taker == "test:solver"
    assert set(sheet.answers) == {"q1", "q2", "q3", "q4", "q5", "q6.a", "q6.b", "q7"}
    assert tiny_bundle.validate_answer_sheet(sheet) == []
    assert sheet.answers["q4"].blanks == {"b1": "Paris", "b2": "3.14"}
    assert sheet.answers["q5"].pairs == {"L1": "R2", "L2": "R1"}
    # One fake call per question, each reporting 100 in / 10 out / 7 reasoning.
    assert sheet.usage is not None
    assert sheet.usage.total.requests == 8
    assert sheet.usage.total.input_tokens == 800
    assert sheet.usage.total.reasoning_tokens == 56
    assert set(sheet.usage.phases) == {"solve"}


def test_solve_retries_on_invalid_answer(tiny_bundle, monkeypatch):
    attempts = {"n": 0}

    def flaky_choice(parts):
        attempts["n"] += 1
        # First attempt returns an invalid option id; the retry corrects it.
        return SolveChoice(selected="Z" if attempts["n"] == 1 else "B")

    outputs = dict(PERFECT_OUTPUTS)
    outputs[SolveChoice] = flaky_choice
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(outputs))
    sheet = run_solve(tiny_bundle, model="test:solver")
    assert attempts["n"] == 2
    assert sheet.answers["q1"].selected == "B"
    assert tiny_bundle.validate_answer_sheet(sheet) == []


def test_question_parts_include_images_and_context(tiny_bundle, monkeypatch):
    from pydantic_ai import BinaryContent

    calls = []
    monkeypatch.setattr(
        runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS, calls=calls)
    )
    run_solve(tiny_bundle, model="test:solver")

    by_type = {output_type: agent for _, output_type, agent in calls}
    # q1's parts include the figure bytes.
    q1_parts = by_type[SolveChoice].calls[0]
    assert any(isinstance(p, BinaryContent) for p in q1_parts)
    # Sub-questions carry their composite parent's stimulus as context.
    text_parts = [p for p in by_type[SolveText].calls[0] if isinstance(p, str)]
    assert any("photosynthesis" in p for p in text_parts)
    assert any("Context for question" in p for p in text_parts)
