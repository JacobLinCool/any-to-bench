"""Render exam content into multimodal message parts (text + images).

Used by both the solver (the model taking the exam) and the judge (the model
grading an answer) so both see the question the same way.
"""

from __future__ import annotations

import mimetypes

from pydantic_ai import BinaryContent

from any_to_bench.bundle import ExamBundle
from any_to_bench.schemas.content import (
    ContentBlock,
    ImageBlock,
    TableBlock,
    TextBlock,
    table_to_markdown,
)
from any_to_bench.schemas.exam import Question, QuestionType, Section

Part = str | BinaryContent


def asset_content(bundle: ExamBundle, asset: str) -> BinaryContent:
    media_type = mimetypes.guess_type(asset)[0] or "image/png"
    return BinaryContent(data=bundle.read_asset(asset), media_type=media_type)


def blocks_to_parts(bundle: ExamBundle, blocks: list[ContentBlock]) -> list[Part]:
    parts: list[Part] = []
    figure_index = 0
    for block in blocks:
        if isinstance(block, TextBlock):
            parts.append(block.markdown)
        elif isinstance(block, ImageBlock):
            figure_index += 1
            label = f"[Figure {figure_index}: {block.alt}]"
            if block.caption:
                label += f" ({block.caption})"
            parts.append(label)
            path = bundle.asset_path(block.asset)
            if path.exists():
                parts.append(asset_content(bundle, block.asset))
        elif isinstance(block, TableBlock):
            parts.append(table_to_markdown(block))
    return parts


def _answer_format_note(question: Question) -> str:
    t = question.type
    if t is QuestionType.single_choice:
        return "Select exactly one option by its id."
    if t is QuestionType.multiple_choice:
        return "Select ALL correct options by their ids."
    if t is QuestionType.true_false:
        return "Answer true or false."
    if t is QuestionType.fill_in_blank:
        assert question.blanks is not None
        ids = ", ".join(b.id + (f" {b.label}" if b.label else "") for b in question.blanks)
        return f"Fill in every blank. Blank ids: {ids}."
    if t is QuestionType.matching:
        return "Match every left item id to exactly one right item id."
    if t is QuestionType.drawing:
        return (
            "This is a drawing question. Describe your drawing precisely: every shape, "
            "label, axis, and their relative positions, so a grader could reproduce it."
        )
    return (
        "Answer in Markdown; write math as LaTeX. If the question or the exam "
        "instructions require showing your work, include the full derivation or "
        "justification, not just the final answer."
    )


def render_question_parts(
    bundle: ExamBundle,
    question: Question,
    section: Section | None,
    context_questions: list[Question] | None = None,
) -> list[Part]:
    """Render one leaf question (with optional composite-parent context) as parts."""
    exam = bundle.exam
    parts: list[Part] = [f"# {exam.title}" + (f" ({exam.subject})" if exam.subject else "")]
    if section is not None:
        if section.title:
            parts.append(f"## {section.title}")
        parts.extend(blocks_to_parts(bundle, section.instructions))

    for parent in context_questions or []:
        parts.append(f"### Context for question {parent.number or parent.id}")
        parts.extend(blocks_to_parts(bundle, parent.prompt))

    header = f"### Question {question.number or question.id} ({question.points:g} points)"
    parts.append(header)
    parts.extend(blocks_to_parts(bundle, question.prompt))

    if question.options:
        parts.append("Options:")
        for option in question.options:
            parts.append(f"({option.id})")
            parts.extend(blocks_to_parts(bundle, option.content))
    if question.matching:
        parts.append("Left items:")
        for item in question.matching.left:
            parts.append(f"[{item.id}]")
            parts.extend(blocks_to_parts(bundle, item.content))
        parts.append("Right items:")
        for item in question.matching.right:
            parts.append(f"[{item.id}]")
            parts.extend(blocks_to_parts(bundle, item.content))

    parts.append(_answer_format_note(question))
    return parts


def leaf_context(question_tree: Question, leaf_id: str) -> list[Question]:
    """Composite ancestors of a leaf within one top-level question, outermost first."""

    def walk(q: Question, trail: list[Question]) -> list[Question] | None:
        if q.id == leaf_id:
            return trail
        for child in q.children:
            found = walk(child, [*trail, q])
            if found is not None:
                return found
        return None

    return walk(question_tree, []) or []
