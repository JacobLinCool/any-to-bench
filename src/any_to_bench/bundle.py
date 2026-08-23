"""Exam bundle: the on-disk artifact produced by ingest and consumed by solve/grade."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel, Field, ValidationError

from any_to_bench import tool_version as _tool_version
from any_to_bench.schemas.answers import AnswerSheet, generate_answer_schema
from any_to_bench.schemas.exam import Exam, QuestionType
from any_to_bench.schemas.grading import (
    ChoiceRule,
    FillBlankRule,
    GradingSpec,
    JudgeRule,
    MatchingRule,
    PerOptionRule,
    TrueFalseRule,
)
from any_to_bench.schemas.resources import ResourceFile
from any_to_bench.schemas.usage import UsageSummary

EXAM_FILE = "exam.json"
ANSWER_SCHEMA_FILE = "answer_schema.json"
GRADING_FILE = "grading.json"
MANIFEST_FILE = "manifest.json"
ASSETS_DIR = "assets"


class SourceFile(BaseModel):
    path: str = Field(description="Original path as given to ingest")
    sha256: str


class BundleManifest(BaseModel):
    schema_version: str = "1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tool_version: str = Field(default_factory=_tool_version)
    ingest_model: str | None = None
    sources: list[SourceFile] = Field(default_factory=list)
    resources: list[ResourceFile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    usage: UsageSummary | None = None


@dataclass
class ExamBundle:
    root: Path
    exam: Exam
    grading: GradingSpec
    answer_schema: dict[str, Any]
    manifest: BundleManifest

    @classmethod
    def load(cls, root: Path | str) -> ExamBundle:
        root = Path(root)
        from any_to_bench.util import read_json

        exam = Exam.model_validate(read_json(root / EXAM_FILE))
        grading = GradingSpec.model_validate(read_json(root / GRADING_FILE))
        answer_schema = read_json(root / ANSWER_SCHEMA_FILE)
        manifest_path = root / MANIFEST_FILE
        manifest = (
            BundleManifest.model_validate(read_json(manifest_path))
            if manifest_path.exists()
            else BundleManifest()
        )
        return cls(
            root=root, exam=exam, grading=grading, answer_schema=answer_schema, manifest=manifest
        )

    def save(self) -> None:
        from any_to_bench.util import write_json

        self.root.mkdir(parents=True, exist_ok=True)
        write_json(self.root / EXAM_FILE, self.exam)
        write_json(self.root / GRADING_FILE, self.grading)
        write_json(self.root / ANSWER_SCHEMA_FILE, self.answer_schema)
        write_json(self.root / MANIFEST_FILE, self.manifest)

    def asset_path(self, asset: str) -> Path:
        return self.root / asset

    def read_asset(self, asset: str) -> bytes:
        return self.asset_path(asset).read_bytes()

    @property
    def has_resources(self) -> bool:
        return bool(self.manifest.resources)

    def validate_answer_sheet(
        self, sheet: AnswerSheet, allow_missing: Iterable[str] = ()
    ) -> list[str]:
        """Validate a filled answer sheet against the bundle's answer schema.

        allow_missing drops those question ids from `required` for this check
        only — a taker that was never asked a question has not violated the
        schema. The stored answer_schema.json is untouched, which matters
        because validate_bundle compares it byte-for-byte against a freshly
        generated one, and every published bundle carries the strict version.
        """
        schema = self.answer_schema
        if missing := set(allow_missing):
            schema = copy.deepcopy(schema)
            answers = schema["properties"]["answers"]
            answers["required"] = [q for q in answers["required"] if q not in missing]
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(sheet.model_dump(mode="json")), key=str)
        return [
            f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors
        ]


_RULE_KIND_FOR_TYPE: dict[QuestionType, type | tuple[type, ...]] = {
    QuestionType.single_choice: ChoiceRule,
    QuestionType.multiple_choice: (ChoiceRule, PerOptionRule),
    QuestionType.true_false: TrueFalseRule,
    QuestionType.fill_in_blank: FillBlankRule,
    QuestionType.matching: MatchingRule,
    QuestionType.short_answer: JudgeRule,
    QuestionType.essay: JudgeRule,
    QuestionType.drawing: JudgeRule,
}


def validate_bundle(root: Path | str) -> list[str]:
    """Full consistency check of a bundle. Returns a list of problems (empty = valid)."""
    root = Path(root)
    problems: list[str] = []

    for name in (EXAM_FILE, GRADING_FILE, ANSWER_SCHEMA_FILE):
        if not (root / name).exists():
            problems.append(f"missing file: {name}")
    if problems:
        return problems

    try:
        bundle = ExamBundle.load(root)
    except (ValidationError, ValueError) as e:
        return [f"failed to parse bundle: {e}"]

    exam, grading = bundle.exam, bundle.grading
    leaves = exam.leaf_map()

    if grading.exam_id != exam.exam_id:
        problems.append(f"grading exam_id {grading.exam_id!r} != exam exam_id {exam.exam_id!r}")

    for qid in leaves:
        if qid not in grading.questions:
            problems.append(f"question {qid} has no grading entry")
    for qid in grading.questions:
        if qid not in leaves:
            problems.append(f"grading entry {qid} has no matching question")

    for qid, qg in grading.questions.items():
        q = leaves.get(qid)
        if q is None:
            continue
        rule = qg.rule
        expected = _RULE_KIND_FOR_TYPE[q.type]
        # Open-ended question types must use a judge rule; fixed-answer types may
        # legitimately fall back to a judge rule when no answer key was found.
        if not isinstance(rule, expected) and not isinstance(rule, JudgeRule):
            problems.append(
                f"question {qid}: rule kind {rule.kind!r} does not fit type {q.type.value!r}"
            )
            continue
        if isinstance(rule, ChoiceRule | PerOptionRule) and q.options is not None:
            option_ids = {o.id for o in q.options}
            for oid in rule.correct:
                if oid not in option_ids:
                    problems.append(f"question {qid}: correct option {oid!r} not in options")
        if isinstance(rule, FillBlankRule) and q.blanks is not None:
            blank_ids = {b.id for b in q.blanks}
            if set(rule.blanks) != blank_ids:
                problems.append(
                    f"question {qid}: rule blanks {sorted(rule.blanks)} != "
                    f"question blanks {sorted(blank_ids)}"
                )
        if isinstance(rule, MatchingRule) and q.matching is not None:
            left_ids = {i.id for i in q.matching.left}
            right_ids = {i.id for i in q.matching.right}
            for left, right in rule.correct_pairs.items():
                if left not in left_ids:
                    problems.append(f"question {qid}: pair left {left!r} not in matching items")
                if right not in right_ids:
                    problems.append(f"question {qid}: pair right {right!r} not in matching items")
        if isinstance(rule, JudgeRule):
            for asset in rule.reference_assets:
                if not (root / asset).exists():
                    problems.append(f"question {qid}: missing reference asset {asset}")

    def check_blocks(owner: str, blocks: list) -> None:
        for block in blocks:
            if getattr(block, "type", None) == "image" and not (root / block.asset).exists():
                problems.append(f"{owner}: missing image asset {block.asset}")

    for section in exam.sections:
        check_blocks(f"section {section.id}", section.instructions)
        for q in section.questions:
            stack = [q]
            while stack:
                cur = stack.pop()
                check_blocks(f"question {cur.id}", cur.prompt)
                for option in cur.options or []:
                    check_blocks(f"question {cur.id} option {option.id}", option.content)
                if cur.matching:
                    for item in cur.matching.left + cur.matching.right:
                        check_blocks(f"question {cur.id} match item {item.id}", item.content)
                stack.extend(cur.children)

    from any_to_bench.resources import validate_resource_tree

    problems.extend(validate_resource_tree(root, bundle.manifest.resources))

    expected_schema = generate_answer_schema(exam, allow_citations=bundle.has_resources)
    if bundle.answer_schema != expected_schema:
        problems.append("answer_schema.json is stale (does not match the exam); re-run ingest")
    try:
        jsonschema.Draft202012Validator.check_schema(bundle.answer_schema)
    except jsonschema.SchemaError as e:
        problems.append(f"answer_schema.json is not a valid JSON Schema: {e.message}")

    return problems
