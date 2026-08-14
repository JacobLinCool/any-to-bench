"""Run an LLM over every leaf question of a bundle to produce an answer sheet.

The solver-facing output models avoid dynamic dict keys (provider-native
structured output rejects them in strict mode); results are converted to the
canonical AnswerValue shapes afterwards.
"""

from __future__ import annotations

import jsonschema
from pydantic import BaseModel, Field

from any_to_bench.agentic.runner import parse_agentic_model
from any_to_bench.bundle import ExamBundle
from any_to_bench.llm import UsageTracker, build_agent
from any_to_bench.modality import Modality, ModalityRequirement, exam_modalities
from any_to_bench.schemas.answers import (
    AnswerSheet,
    AnswerValue,
    DrawingAnswer,
    FillInBlankAnswer,
    MatchingAnswer,
    MultipleChoiceAnswer,
    SingleChoiceAnswer,
    TextAnswer,
)
from any_to_bench.schemas.exam import Question, QuestionType
from any_to_bench.schemas.usage import Effort
from any_to_bench.solve.render import Part, leaf_context, render_question_parts

SOLVER_INSTRUCTIONS = (
    "You are taking an exam. Read the question carefully, including any figures and "
    "tables, and answer to the best of your ability. Use ONLY the ids given in the "
    "question (option ids, blank ids, matching item ids). For open-ended questions, "
    "if the exam instructions or the question ask for working, a derivation, or "
    "justification, SHOW your full reasoning and calculations in the answer — the "
    "process is graded, not just the final result. Otherwise answer concisely "
    "without explanation."
)


class SolveChoice(BaseModel):
    selected: str = Field(description="The id of the chosen option")


class SolveMultiChoice(BaseModel):
    selected: list[str] = Field(description="The ids of ALL chosen options")


class SolveTrueFalse(BaseModel):
    value: bool


class SolveBlankEntry(BaseModel):
    blank_id: str
    text: str


class SolveBlanks(BaseModel):
    entries: list[SolveBlankEntry] = Field(description="One entry per blank id")


class SolvePair(BaseModel):
    left_id: str
    right_id: str


class SolveMatching(BaseModel):
    pairs: list[SolvePair] = Field(description="One pair per left item id")


class SolveText(BaseModel):
    text: str = Field(description="The answer in Markdown; math as LaTeX")


class SolveDrawing(BaseModel):
    description: str = Field(
        description="A precise textual description of the drawing: shapes, labels, positions"
    )


_SOLVER_MODEL_FOR_TYPE: dict[QuestionType, type[BaseModel]] = {
    QuestionType.single_choice: SolveChoice,
    QuestionType.multiple_choice: SolveMultiChoice,
    QuestionType.true_false: SolveTrueFalse,
    QuestionType.fill_in_blank: SolveBlanks,
    QuestionType.matching: SolveMatching,
    QuestionType.short_answer: SolveText,
    QuestionType.essay: SolveText,
    QuestionType.drawing: SolveDrawing,
}


def _to_answer_value(question: Question, output: BaseModel) -> AnswerValue:
    if isinstance(output, SolveChoice):
        return SingleChoiceAnswer(selected=output.selected)
    if isinstance(output, SolveMultiChoice):
        return MultipleChoiceAnswer(selected=output.selected)
    if isinstance(output, SolveTrueFalse):
        from any_to_bench.schemas.answers import TrueFalseAnswer

        return TrueFalseAnswer(value=output.value)
    if isinstance(output, SolveBlanks):
        return FillInBlankAnswer(blanks={e.blank_id: e.text for e in output.entries})
    if isinstance(output, SolveMatching):
        return MatchingAnswer(pairs={p.left_id: p.right_id for p in output.pairs})
    if isinstance(output, SolveText):
        return TextAnswer(text=output.text)
    if isinstance(output, SolveDrawing):
        return DrawingAnswer(description=output.description)
    raise TypeError(f"unexpected solver output for {question.id}: {type(output)}")


def solve_question(
    bundle: ExamBundle,
    question: Question,
    parts: list[Part],
    model: str,
    tracker: UsageTracker,
    effort: Effort | str | None = None,
) -> AnswerValue:
    """Solve one leaf question, retrying once if the answer violates its schema."""
    output_type = _SOLVER_MODEL_FOR_TYPE[question.type]
    agent = build_agent(model, output_type, SOLVER_INSTRUCTIONS, effort=effort)
    result = agent.run_sync(parts)
    tracker.add("solve", result.usage)
    answer = _to_answer_value(question, result.output)

    schema = bundle.answer_schema["properties"]["answers"]["properties"][question.id]
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(answer.model_dump(mode="json")))
    if errors:
        retry_parts: list[Part] = [
            *parts,
            "Your previous answer was invalid: "
            + "; ".join(e.message for e in errors[:5])
            + ". Answer again using only the ids defined in the question.",
        ]
        retry_result = agent.run_sync(retry_parts)
        tracker.add("solve", retry_result.usage)
        answer = _to_answer_value(question, retry_result.output)
    return answer


def run_solve(
    bundle: ExamBundle,
    model: str,
    effort: Effort | str | None = None,
    *,
    capabilities: frozenset[Modality] | None = None,
    skipped: list[str] | None = None,
) -> AnswerSheet:
    """Solve every leaf question the taker is equipped to attempt.

    capabilities declares what the taker can consume; None means assume it can
    consume anything, which is the historical behaviour. Questions demanding
    more are appended to `skipped` and left out of the sheet entirely, rather
    than answered badly or allowed to error the whole run — an out-parameter
    list, matching how warnings are already threaded through grading.
    """
    if parse_agentic_model(model) is not None:
        # Agentic takers read assets as files from their workspace, never as
        # inline content, so there is no modality to gate on.
        from any_to_bench.agentic.solve import agentic_solve

        return agentic_solve(bundle, model, effort=effort)
    tracker = UsageTracker()
    answers: dict[str, AnswerValue] = {}
    requirements = exam_modalities(bundle.exam) if capabilities is not None else {}
    for section in bundle.exam.sections:
        for top in section.questions:
            for leaf in top.iter_leaves():
                if capabilities is not None:
                    requirement = requirements.get(leaf.id, ModalityRequirement())
                    if requirement.missing_from(capabilities):
                        if skipped is not None:
                            skipped.append(leaf.id)
                        continue
                context = leaf_context(top, leaf.id)
                parts = render_question_parts(bundle, leaf, section, context)
                answers[leaf.id] = solve_question(bundle, leaf, parts, model, tracker, effort)
    return AnswerSheet(
        exam_id=bundle.exam.exam_id,
        taker=model,
        answers=answers,
        usage=tracker.summary(),
    )
