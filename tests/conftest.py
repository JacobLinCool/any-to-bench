"""Shared test fixtures. All tests run offline: model requests are forbidden."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pydantic_ai.models
import pytest
from PIL import Image

from any_to_bench.agentic.runner import CodexRunResult, CodexUsage
from any_to_bench.bundle import BundleManifest, ExamBundle
from any_to_bench.schemas.answers import (
    AnswerSheet,
    DrawingAnswer,
    FillInBlankAnswer,
    MatchingAnswer,
    MultipleChoiceAnswer,
    SingleChoiceAnswer,
    TextAnswer,
    TrueFalseAnswer,
    generate_answer_schema,
)
from any_to_bench.schemas.content import ImageBlock, TextBlock
from any_to_bench.schemas.exam import (
    Blank,
    Exam,
    MatchingSpec,
    MatchItem,
    Option,
    Question,
    QuestionType,
    Section,
)
from any_to_bench.schemas.grading import (
    BlankSpec,
    ChoiceRule,
    FillBlankRule,
    GradingSpec,
    JudgeConfig,
    JudgeRule,
    MatchingRule,
    Normalization,
    QuestionGrading,
    RubricCriterion,
    RubricLevel,
    TrueFalseRule,
)

pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


def _text(markdown: str) -> list:
    return [TextBlock(markdown=markdown)]


def make_png(path: Path, size: tuple[int, int] = (64, 48), color: str = "red") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")


def build_tiny_exam() -> Exam:
    """A 7-question exam covering every question type. Total 17 points."""
    return Exam(
        exam_id="tiny-exam",
        title="Tiny Exam",
        subject="Testing",
        language="en",
        total_points=17.0,
        sections=[
            Section(
                id="s1",
                title="All types",
                instructions=_text("Answer every question."),
                questions=[
                    Question(
                        id="q1",
                        number="1.",
                        type=QuestionType.single_choice,
                        prompt=[
                            TextBlock(markdown="What color is the figure?"),
                            ImageBlock(asset="assets/q1-fig1.png", alt="a solid red rectangle"),
                        ],
                        points=2.0,
                        options=[
                            Option(id="A", content=_text("Blue")),
                            Option(id="B", content=_text("Red")),
                            Option(id="C", content=_text("Green")),
                            Option(id="D", content=_text("Yellow")),
                        ],
                    ),
                    Question(
                        id="q2",
                        number="2.",
                        type=QuestionType.multiple_choice,
                        prompt=_text("Which are prime numbers?"),
                        points=3.0,
                        options=[
                            Option(id="A", content=_text("2")),
                            Option(id="B", content=_text("4")),
                            Option(id="C", content=_text("5")),
                            Option(id="D", content=_text("6")),
                        ],
                    ),
                    Question(
                        id="q3",
                        number="3.",
                        type=QuestionType.true_false,
                        prompt=_text("The earth orbits the sun."),
                        points=1.0,
                    ),
                    Question(
                        id="q4",
                        number="4.",
                        type=QuestionType.fill_in_blank,
                        prompt=_text("The capital of France is ___(i)___ and pi is ___(ii)___."),
                        points=2.0,
                        blanks=[
                            Blank(id="b1", label="(i)"),
                            Blank(id="b2", label="(ii)"),
                        ],
                    ),
                    Question(
                        id="q5",
                        number="5.",
                        type=QuestionType.matching,
                        prompt=_text("Match each country to its capital."),
                        points=2.0,
                        matching=MatchingSpec(
                            left=[
                                MatchItem(id="L1", content=_text("Japan")),
                                MatchItem(id="L2", content=_text("Italy")),
                            ],
                            right=[
                                MatchItem(id="R1", content=_text("Rome")),
                                MatchItem(id="R2", content=_text("Tokyo")),
                                MatchItem(id="R3", content=_text("Madrid")),
                            ],
                        ),
                    ),
                    Question(
                        id="q6",
                        number="6.",
                        type=QuestionType.composite,
                        prompt=_text("Read the following passage about photosynthesis."),
                        points=5.0,
                        children=[
                            Question(
                                id="q6.a",
                                number="(a)",
                                type=QuestionType.short_answer,
                                prompt=_text("Name the pigment that absorbs light."),
                                points=2.0,
                            ),
                            Question(
                                id="q6.b",
                                number="(b)",
                                type=QuestionType.essay,
                                prompt=_text("Explain how light intensity affects the rate."),
                                points=3.0,
                            ),
                        ],
                    ),
                    Question(
                        id="q7",
                        number="7.",
                        type=QuestionType.drawing,
                        prompt=_text("Sketch a graph of y = x^2 for -2 <= x <= 2."),
                        points=2.0,
                    ),
                ],
            )
        ],
    )


def build_tiny_grading() -> GradingSpec:
    return GradingSpec(
        exam_id="tiny-exam",
        judge=JudgeConfig(models=["test:judge"], aggregation="mean"),
        questions={
            "q1": QuestionGrading(
                question_id="q1", max_points=2.0, rule=ChoiceRule(correct=["B"])
            ),
            "q2": QuestionGrading(
                question_id="q2",
                max_points=3.0,
                rule=ChoiceRule(correct=["A", "C"], partial_credit=True),
            ),
            "q3": QuestionGrading(
                question_id="q3", max_points=1.0, rule=TrueFalseRule(correct=True)
            ),
            "q4": QuestionGrading(
                question_id="q4",
                max_points=2.0,
                rule=FillBlankRule(
                    blanks={
                        "b1": BlankSpec(accepted=["Paris"]),
                        "b2": BlankSpec(accepted=["3.14", "pi"]),
                    },
                    normalization=Normalization(numeric_tolerance=0.01),
                ),
            ),
            "q5": QuestionGrading(
                question_id="q5",
                max_points=2.0,
                rule=MatchingRule(correct_pairs={"L1": "R2", "L2": "R1"}),
            ),
            "q6.a": QuestionGrading(
                question_id="q6.a",
                max_points=2.0,
                rule=JudgeRule(reference_answer="Chlorophyll."),
            ),
            "q6.b": QuestionGrading(
                question_id="q6.b",
                max_points=3.0,
                rule=JudgeRule(
                    reference_answer="Rate increases with light intensity until a plateau.",
                    rubric=[
                        RubricCriterion(
                            id="content",
                            description="Scientific accuracy",
                            levels=[
                                RubricLevel(points=2.0, descriptor="Accurate and complete"),
                                RubricLevel(points=1.0, descriptor="Partially accurate"),
                                RubricLevel(points=0.0, descriptor="Inaccurate"),
                            ],
                        ),
                        RubricCriterion(
                            id="clarity",
                            description="Clear explanation",
                            levels=[
                                RubricLevel(points=1.0, descriptor="Clear"),
                                RubricLevel(points=0.0, descriptor="Unclear"),
                            ],
                        ),
                    ],
                ),
            ),
            "q7": QuestionGrading(
                question_id="q7",
                max_points=2.0,
                rule=JudgeRule(reference_answer="An upward parabola with vertex at the origin."),
            ),
        },
    )


def build_tiny_bundle(root: Path) -> ExamBundle:
    exam = build_tiny_exam()
    bundle = ExamBundle(
        root=root,
        exam=exam,
        grading=build_tiny_grading(),
        answer_schema=generate_answer_schema(exam),
        manifest=BundleManifest(),
    )
    make_png(root / "assets" / "q1-fig1.png")
    bundle.save()
    return bundle


def perfect_sheet() -> AnswerSheet:
    return AnswerSheet(
        exam_id="tiny-exam",
        taker="test-taker",
        answers={
            "q1": SingleChoiceAnswer(selected="B"),
            "q2": MultipleChoiceAnswer(selected=["A", "C"]),
            "q3": TrueFalseAnswer(value=True),
            "q4": FillInBlankAnswer(blanks={"b1": "  PARIS ", "b2": "3.1416"}),
            "q5": MatchingAnswer(pairs={"L1": "R2", "L2": "R1"}),
            "q6.a": TextAnswer(text="Chlorophyll."),
            "q6.b": TextAnswer(text="More light means a faster rate, up to a plateau."),
            "q7": DrawingAnswer(description="An upward parabola, vertex at origin."),
        },
    )


def imperfect_sheet() -> AnswerSheet:
    """Deterministic score: q1=0, q2=1.5, q3=0, q4=1.0, q5=1.0 -> 3.5. Rest unanswered."""
    return AnswerSheet(
        exam_id="tiny-exam",
        taker="test-taker",
        answers={
            "q1": SingleChoiceAnswer(selected="C"),
            "q2": MultipleChoiceAnswer(selected=["A"]),
            "q3": TrueFalseAnswer(value=False),
            "q4": FillInBlankAnswer(blanks={"b1": "Paris", "b2": "3.16"}),
            "q5": MatchingAnswer(pairs={"L1": "R2", "L2": "R3"}),
        },
    )


@pytest.fixture
def tiny_bundle(tmp_path: Path) -> ExamBundle:
    return build_tiny_bundle(tmp_path / "bundle")


# Every FakeCodex call reports this usage, so tests can assert accumulation.
FAKE_CODEX_USAGE = CodexUsage(
    requests=1,
    input_tokens=200,
    output_tokens=20,
    cache_read_tokens=50,
    cache_write_tokens=0,
    details={"reasoning_tokens": 9},
)


class FakeCodex:
    """Stands in for agentic.runner.run_codex; each round runs a writer(workspace).

    Rounds beyond the provided writers are no-ops (earlier files persist), so a
    single bad writer naturally exercises fix-loop exhaustion.
    """

    def __init__(self, rounds: list[Any]) -> None:
        self._rounds = list(rounds)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        workspace: Path,
        prompt: str,
        cli_model: str,
        effort: Any = None,
        resume_session_id: str | None = None,
        timeout_s: float | None = None,
    ) -> CodexRunResult:
        self.calls.append(
            {
                "workspace": workspace,
                "prompt": prompt,
                "cli_model": cli_model,
                "effort": effort,
                "resume_session_id": resume_session_id,
            }
        )
        if self._rounds:
            writer = self._rounds.pop(0)
            if writer is not None:
                writer(workspace)
        return CodexRunResult(
            session_id=f"sess-{len(self.calls)}",
            final_message="done",
            usage=FAKE_CODEX_USAGE,
            events=[],
        )


# Every FakeAgent call reports this usage, so tests can assert accumulation.
FAKE_CALL_USAGE = SimpleNamespace(
    requests=1,
    input_tokens=100,
    output_tokens=10,
    cache_read_tokens=20,
    cache_write_tokens=0,
    details={"reasoning_tokens": 7},
)


class FakeAgent:
    """Stands in for a pydantic_ai Agent; returns canned or computed outputs."""

    def __init__(self, produce: Any) -> None:
        self._produce = produce
        self.calls: list[list[Any]] = []

    def run_sync(self, parts: list[Any]) -> SimpleNamespace:
        self.calls.append(parts)
        output = self._produce(parts) if callable(self._produce) else self._produce
        return SimpleNamespace(output=output, usage=FAKE_CALL_USAGE)


def fake_build_agent(outputs_by_type: dict[type, Any], calls: list | None = None):
    """A build_agent replacement dispatching canned outputs on output_type."""

    def _build(model: str, output_type: type, instructions: str, **kwargs: Any) -> FakeAgent:
        produce = outputs_by_type[output_type]
        agent = FakeAgent(produce)
        if calls is not None:
            calls.append((model, output_type, agent))
        return agent

    return _build
