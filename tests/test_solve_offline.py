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


def test_concurrency_changes_nothing_but_wall_time(tiny_bundle, monkeypatch):
    """Same answers, same order, same usage — a thread pool is not a semantic change.

    Order matters beyond tidiness: the answer sheet is written to disk and
    published as a benchmark artifact, so questions resolving out of order would
    make two runs of the same taker differ byte-for-byte for no reason.
    """
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    serial = run_solve(tiny_bundle, model="test:solver")
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    parallel = run_solve(tiny_bundle, model="test:solver", concurrency=4)

    assert list(parallel.answers) == list(serial.answers)
    assert parallel.model_dump(mode="json", exclude={"usage"}) == serial.model_dump(
        mode="json", exclude={"usage"}
    )
    assert parallel.usage is not None and serial.usage is not None
    assert parallel.usage.total == serial.usage.total


def test_concurrent_usage_is_not_lost_to_a_race(tiny_bundle, monkeypatch):
    """The tracker is read-modify-write on a shared dict; without its lock a
    concurrent solve silently under-reports what the taker spent.

    The window is widened deliberately. Under CPython the real one is a couple
    of bytecodes wide and the GIL hides the bug almost every time — which is
    exactly why it would ship. Sleeping inside `merged` forces the interleave
    that a slower machine, a bigger paper, or a free-threaded build would find
    on its own; the test fails without the lock and passes with it.
    """
    import threading
    import time

    from any_to_bench.schemas.usage import PhaseUsage

    real_merged = PhaseUsage.merged

    def slow_merged(self, other):
        time.sleep(0.005)
        return real_merged(self, other)

    monkeypatch.setattr(PhaseUsage, "merged", slow_merged)

    barrier = threading.Barrier(8, timeout=5)

    def at_the_same_moment(output):
        def answer(parts):
            barrier.wait()  # every worker enters tracker.add together
            return output

        return answer

    outputs = {k: at_the_same_moment(v) for k, v in PERFECT_OUTPUTS.items()}
    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(outputs))
    sheet = run_solve(tiny_bundle, model="test:solver", concurrency=8)

    assert sheet.usage is not None
    assert sheet.usage.total.requests == 8
    assert sheet.usage.total.input_tokens == 800
