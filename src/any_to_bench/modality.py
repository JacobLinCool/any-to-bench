"""What each question demands of a taker, and what a taker can supply.

Modality is a property of the individual question, not of the bundle: a typical
exam mixes a handful of figure-bearing questions into many pure-text ones, and a
taker that cannot see images should still be able to sit the text-only subset
rather than losing the whole paper.

Requirements are derived from the exam structure rather than stored, so they are
always in step with the questions and need no migration for existing bundles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from any_to_bench.schemas.content import ContentBlock, ImageBlock
from any_to_bench.schemas.exam import Exam, Question
from any_to_bench.solve.render import leaf_context


class Modality(StrEnum):
    text = "text"
    image = "image"


ALL_MODALITIES = frozenset(Modality)
TEXT_ONLY = frozenset({Modality.text})


@dataclass
class ModalityRequirement:
    """What one leaf question needs, and where each demand came from.

    The provenance matters: an image in a section's instructions makes every
    question in that section unanswerable to a text-only taker, which is
    surprising enough to be worth naming rather than leaving the user to guess.
    """

    modalities: frozenset[Modality] = field(default_factory=lambda: TEXT_ONLY)
    sources: dict[str, list[str]] = field(default_factory=dict)

    def missing_from(self, capabilities: frozenset[Modality]) -> frozenset[Modality]:
        return frozenset(self.modalities - capabilities)


def block_modalities(blocks: list[ContentBlock]) -> set[Modality]:
    """The modalities a run of content blocks demands of whoever reads it."""
    found: set[Modality] = set()
    for block in blocks:
        if isinstance(block, ImageBlock):
            found.add(Modality.image)
        else:
            found.add(Modality.text)
    return found


def _accumulate(
    requirement: ModalityRequirement, blocks: list[ContentBlock], source: str
) -> ModalityRequirement:
    found = block_modalities(blocks)
    if not found:
        return requirement
    sources = dict(requirement.sources)
    for modality in found:
        if modality is Modality.text:
            continue  # every question is textual; only note what could exclude a taker
        entries = list(sources.get(modality.value, []))
        if source not in entries:
            entries.append(source)
        sources[modality.value] = entries
    return ModalityRequirement(
        modalities=requirement.modalities | frozenset(found), sources=sources
    )


def exam_modalities(exam: Exam) -> dict[str, ModalityRequirement]:
    """Per-leaf requirements, walking exactly what render_question_parts sends.

    Note this walks *upward* — a leaf inherits its section's instructions and its
    composite ancestors' shared stimulus. That is the opposite direction from
    agentic.workspace.question_assets, which descends into children to collect a
    question's own assets; the two are not interchangeable.
    """
    requirements: dict[str, ModalityRequirement] = {}
    for section in exam.sections:
        section_req = _accumulate(
            ModalityRequirement(), section.instructions, f"section:{section.id}"
        )
        for top in section.questions:
            for leaf in top.iter_leaves():
                requirement = section_req
                for parent in leaf_context(top, leaf.id):
                    requirement = _accumulate(requirement, parent.prompt, f"question:{parent.id}")
                requirements[leaf.id] = _leaf_requirement(requirement, leaf)
    return requirements


def _leaf_requirement(inherited: ModalityRequirement, leaf: Question) -> ModalityRequirement:
    source = f"question:{leaf.id}"
    requirement = _accumulate(inherited, leaf.prompt, source)
    for option in leaf.options or []:
        requirement = _accumulate(requirement, option.content, source)
    if leaf.matching:
        for item in leaf.matching.left + leaf.matching.right:
            requirement = _accumulate(requirement, item.content, source)
    return requirement


def parse_capabilities(text_only: bool) -> frozenset[Modality]:
    """A taker's declared modalities; undeclared means assume it can do everything."""
    return TEXT_ONLY if text_only else ALL_MODALITIES


def describe_missing(missing: frozenset[Modality]) -> list[str]:
    return sorted(m.value for m in missing)
