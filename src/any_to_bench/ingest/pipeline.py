"""The ingestion pipeline: source pages -> exam bundle."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pydantic_ai import BinaryContent

from any_to_bench.agentic.runner import parse_agentic_model
from any_to_bench.bundle import BundleManifest, ExamBundle, validate_bundle
from any_to_bench.ingest.figures import FigureResolver
from any_to_bench.ingest.merge import (
    covered_numbers,
    find_gaps,
    insert_recovered,
    merge_chunks,
    normalize_number,
)
from any_to_bench.ingest.prompts import (
    ANSWERS_INSTRUCTIONS,
    EXTRACT_INSTRUCTIONS,
    INVENTORY_INSTRUCTIONS,
)
from any_to_bench.ingest.sources import SourcePage, prepare_sources
from any_to_bench.llm import UsageTracker, build_agent
from any_to_bench.schemas.answers import generate_answer_schema
from any_to_bench.schemas.content import ContentBlock, TextBlock
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
from any_to_bench.schemas.extraction import (
    ExtractedAnswerKey,
    ExtractedQuestion,
    ExtractedSubQuestion,
    ExtractionChunk,
    FigureRef,
    GradingExtraction,
    MaterialInventory,
    PerOptionScoring,
)
from any_to_bench.schemas.grading import (
    BlankSpec,
    ChoiceRule,
    FillBlankRule,
    GradingSpec,
    JudgeRule,
    MatchingRule,
    PerOptionRule,
    QuestionGrading,
    RubricCriterion,
    RubricLevel,
    TrueFalseRule,
)
from any_to_bench.schemas.usage import Effort
from any_to_bench.util import slugify

CHUNK_SIZE = 4
CHUNK_OVERLAP = 1
DEFAULT_POINTS = 1.0

Part = str | BinaryContent


INVENTORY_THUMBNAIL_SIDE = 1024


def _page_parts(pages: list[SourcePage], max_side: int | None = None) -> list[Part]:
    """Label + image per page. max_side downscales in-memory (used by the
    inventory pass, which sees every page at once — full resolution would blow
    the request payload limit on long exams and adds nothing to classification)."""
    parts: list[Part] = []
    for page in pages:
        parts.append(f"Page {page.index}:")
        data = page.png_path.read_bytes()
        if max_side is not None:
            import io

            from PIL import Image

            with Image.open(io.BytesIO(data)) as image:
                if max(image.size) > max_side:
                    image.thumbnail((max_side, max_side))
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    data = buffer.getvalue()
        parts.append(BinaryContent(data=data, media_type="image/png"))
    return parts


def _chunk_pages(pages: list[SourcePage]) -> list[list[SourcePage]]:
    if len(pages) <= CHUNK_SIZE:
        return [pages]
    chunks: list[list[SourcePage]] = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for start in range(0, len(pages), step):
        chunk = pages[start : start + CHUNK_SIZE]
        chunks.append(chunk)
        if start + CHUNK_SIZE >= len(pages):
            break
    return chunks


class _ExamBuilder:
    """Convert extracted questions into validated Exam questions."""

    def __init__(self, resolver: FigureResolver, warnings: list[str]) -> None:
        self.resolver = resolver
        self.warnings = warnings
        # leaf id -> candidate normalized printed-number keys, for answer matching
        self.leaf_keys: dict[str, list[str]] = {}

    def _blocks(self, blocks: list, owner: str) -> list[ContentBlock]:
        converted: list[ContentBlock] = []
        for block in blocks:
            if isinstance(block, FigureRef):
                converted.append(self.resolver.resolve(block, owner))
            else:
                converted.append(block)
        if not converted:
            converted.append(TextBlock(markdown=""))
        return converted

    def _coerce_type(
        self, extracted: ExtractedQuestion | ExtractedSubQuestion, qid: str
    ) -> QuestionType:
        t = extracted.question_type
        if t in (QuestionType.single_choice, QuestionType.multiple_choice) and (
            not extracted.options or len(extracted.options) < 2
        ):
            self.warnings.append(
                f"{qid}: {t.value} without usable options; treated as short_answer"
            )
            return QuestionType.short_answer
        if t is QuestionType.matching and extracted.matching is None:
            self.warnings.append(f"{qid}: matching without item lists; treated as short_answer")
            return QuestionType.short_answer
        if t is QuestionType.composite and not getattr(extracted, "children", None):
            self.warnings.append(f"{qid}: composite without children; treated as short_answer")
            return QuestionType.short_answer
        return t

    def _leaf_fields(
        self, extracted: ExtractedQuestion | ExtractedSubQuestion, qtype: QuestionType, qid: str
    ) -> dict:
        fields: dict = {"options": None, "blanks": None, "matching": None}
        if qtype in (QuestionType.single_choice, QuestionType.multiple_choice):
            assert extracted.options is not None
            fields["options"] = [
                Option(id=o.id, content=self._blocks(o.blocks, f"{qid}-opt{o.id}"))
                for o in extracted.options
            ]
        elif qtype is QuestionType.fill_in_blank:
            blanks = extracted.blanks or []
            if not blanks:
                self.warnings.append(f"{qid}: fill_in_blank without blanks; created blank 'b1'")
                fields["blanks"] = [Blank(id="b1", label=None)]
            else:
                fields["blanks"] = [Blank(id=b.id, label=b.label) for b in blanks]
        elif qtype is QuestionType.matching:
            assert extracted.matching is not None
            fields["matching"] = MatchingSpec(
                left=[
                    MatchItem(id=i.id, content=self._blocks(i.blocks, f"{qid}-{i.id}"))
                    for i in extracted.matching.left
                ],
                right=[
                    MatchItem(id=i.id, content=self._blocks(i.blocks, f"{qid}-{i.id}"))
                    for i in extracted.matching.right
                ],
            )
        return fields

    def _points(self, extracted: ExtractedQuestion | ExtractedSubQuestion, qid: str) -> float:
        if extracted.points is not None and extracted.points > 0:
            return extracted.points
        self.warnings.append(f"{qid}: no printed point value; defaulting to {DEFAULT_POINTS:g}")
        return DEFAULT_POINTS

    def build_question(self, extracted: ExtractedQuestion, index: int) -> Question:
        qid = f"q{index + 1}"
        qtype = self._coerce_type(extracted, qid)

        if qtype is QuestionType.composite:
            assert extracted.children
            children: list[Question] = []
            for child_index, child in enumerate(extracted.children):
                children.append(self.build_sub_question(child, extracted, qid, child_index))
            return Question(
                id=qid,
                number=extracted.number,
                type=qtype,
                prompt=self._blocks(extracted.blocks, qid),
                points=sum(c.points for c in children),
                children=children,
            )

        question = Question(
            id=qid,
            number=extracted.number,
            type=qtype,
            prompt=self._blocks(extracted.blocks, qid),
            points=self._points(extracted, qid),
            **self._leaf_fields(extracted, qtype, qid),
        )
        self.leaf_keys[qid] = [normalize_number(extracted.number)]
        return question

    def build_sub_question(
        self,
        child: ExtractedSubQuestion,
        parent: ExtractedQuestion,
        parent_id: str,
        child_index: int,
    ) -> Question:
        suffix = normalize_number(child.number) or str(child_index + 1)
        qid = f"{parent_id}.{suffix}"
        qtype = self._coerce_type(child, qid)
        if qtype is QuestionType.composite:  # sub-questions cannot nest further
            qtype = QuestionType.short_answer
        question = Question(
            id=qid,
            number=child.number,
            type=qtype,
            prompt=self._blocks(child.blocks, qid),
            points=self._points(child, qid),
            **self._leaf_fields(child, qtype, qid),
        )
        self.leaf_keys[qid] = [
            normalize_number(parent.number + child.number),
            normalize_number(child.number),
        ]
        return question


def _question_index_text(exam: Exam, leaf_keys: dict[str, list[str]]) -> str:
    lines = ["Question index (printed number | type | points | answer-field ids):"]
    printed: dict[str, str] = {}
    for section in exam.sections:
        for top in section.questions:
            for leaf in top.iter_leaves():
                if leaf.id == top.id:
                    number = leaf.number or leaf.id
                else:
                    number = f"{top.number or top.id}{leaf.number or ''}"
                printed[leaf.id] = number
    for section in exam.sections:
        for top in section.questions:
            for leaf in top.iter_leaves():
                extras = ""
                if leaf.options:
                    extras = " | options: " + ",".join(o.id for o in leaf.options)
                elif leaf.blanks:
                    extras = " | blanks: " + ",".join(
                        b.id + (f"({b.label})" if b.label else "") for b in leaf.blanks
                    )
                elif leaf.matching:
                    extras = (
                        " | left: " + ",".join(i.id for i in leaf.matching.left)
                        + " | right: " + ",".join(i.id for i in leaf.matching.right)
                    )
                lines.append(
                    f"- number: {printed[leaf.id]!r} | type: {leaf.type.value} | "
                    f"points: {leaf.points:g}{extras}"
                )
    return "\n".join(lines)


def _merge_key_entries(
    extractions: list[GradingExtraction],
) -> dict[str, ExtractedAnswerKey]:
    merged: dict[str, ExtractedAnswerKey] = {}
    for extraction in extractions:
        for entry in extraction.entries:
            key = normalize_number(entry.question_number)
            if key not in merged:
                merged[key] = entry
                continue
            existing = merged[key]
            update = {
                name: value
                for name, value in entry.model_dump().items()
                if value is not None and getattr(existing, name, None) is None
            }
            if update:
                merged[key] = existing.model_copy(update=update)
    return merged


def _judge_rule_from_key(
    entry: ExtractedAnswerKey | None,
    question: Question,
    resolver: FigureResolver,
    warnings: list[str],
) -> JudgeRule:
    if entry is None:
        return JudgeRule()
    reference_assets: list[str] = []
    for ref in entry.solution_figures or []:
        block = resolver.resolve(ref, f"{question.id}-sol")
        if block.type == "image":
            reference_assets.append(block.asset)

    rubric: list[RubricCriterion] = []
    instructions = entry.judge_instructions
    if entry.rubric:
        try:
            rubric = [
                RubricCriterion(
                    id=c.id,
                    description=c.description,
                    levels=[
                        RubricLevel(points=lv.points, descriptor=lv.descriptor)
                        for lv in c.levels
                    ],
                )
                for c in entry.rubric
            ]
            rubric_max = sum(c.max_points for c in rubric)
            if not math.isclose(rubric_max, question.points, abs_tol=1e-6):
                raise ValueError(
                    f"rubric max {rubric_max:g} != question points {question.points:g}"
                )
        except ValueError as e:
            warnings.append(
                f"{question.id}: rubric unusable as structured levels ({e}); "
                "folded into judge instructions"
            )
            prose = "\n".join(
                f"- {c.id}: {c.description} "
                + "; ".join(f"{lv.points:g} pts: {lv.descriptor}" for lv in c.levels)
                for c in entry.rubric
            )
            instructions = ((instructions + "\n\n") if instructions else "") + "Rubric:\n" + prose
            rubric = []

    return JudgeRule(
        reference_answer=entry.solution_text,
        reference_assets=reference_assets,
        rubric=rubric,
        judge_instructions=instructions,
    )


def _build_grading_entry(
    question: Question,
    entry: ExtractedAnswerKey | None,
    resolver: FigureResolver,
    warnings: list[str],
    multi_choice_scoring: PerOptionScoring | None = None,
) -> QuestionGrading:
    qid = question.id
    t = question.type
    judge_fallback = _judge_rule_from_key(entry, question, resolver, warnings)

    def fallback(reason: str) -> QuestionGrading:
        warnings.append(f"{qid}: {reason}; falling back to LLM-judge grading")
        return QuestionGrading(question_id=qid, max_points=question.points, rule=judge_fallback)

    if t in (QuestionType.short_answer, QuestionType.essay, QuestionType.drawing):
        if entry is None:
            warnings.append(f"{qid}: no reference material found; judge will grade holistically")
        return QuestionGrading(question_id=qid, max_points=question.points, rule=judge_fallback)

    if entry is None:
        return fallback("no answer key entry found")

    if t in (QuestionType.single_choice, QuestionType.multiple_choice):
        option_ids = {o.id for o in question.options or []}
        correct = [o for o in (entry.correct_options or []) if o in option_ids]
        dropped = [o for o in (entry.correct_options or []) if o not in option_ids]
        if dropped:
            warnings.append(f"{qid}: answer key options {dropped} not in question; dropped")
        if not correct:
            return fallback("answer key has no usable correct options")
        if t is QuestionType.single_choice and len(correct) > 1:
            warnings.append(f"{qid}: multiple correct options for single choice; keeping all")
        rule: ChoiceRule | PerOptionRule
        if t is QuestionType.multiple_choice and multi_choice_scoring is not None:
            try:
                rule = PerOptionRule(
                    correct=correct, ratio_by_errors=multi_choice_scoring.ratio_by_errors
                )
            except ValueError as e:
                warnings.append(f"{qid}: per-option scoring table unusable ({e}); "
                                "using partial credit")
                rule = ChoiceRule(correct=correct, partial_credit=True)
        else:
            rule = ChoiceRule(correct=correct, partial_credit=t is QuestionType.multiple_choice)
        return QuestionGrading(question_id=qid, max_points=question.points, rule=rule)

    if t is QuestionType.true_false:
        if entry.true_false is None:
            return fallback("answer key has no true/false value")
        return QuestionGrading(
            question_id=qid,
            max_points=question.points,
            rule=TrueFalseRule(correct=entry.true_false),
        )

    if t is QuestionType.fill_in_blank:
        blanks = question.blanks or []
        by_key: dict[str, list[str]] = {}
        for kv in entry.blank_answers or []:
            by_key[normalize_number(kv.key)] = kv.values
        specs: dict[str, BlankSpec] = {}
        unmatched = []
        for blank in blanks:
            candidates = [normalize_number(blank.id)]
            if blank.label:
                candidates.append(normalize_number(blank.label))
            accepted = next((by_key[c] for c in candidates if c in by_key and by_key[c]), None)
            if accepted is None:
                unmatched.append(blank.id)
            else:
                specs[blank.id] = BlankSpec(accepted=accepted)
        if unmatched and len(entry.blank_answers or []) == len(blanks):
            # Same count: assume the key lists blanks in reading order.
            warnings.append(f"{qid}: matched blank answers to blanks by position")
            specs = {
                blank.id: BlankSpec(accepted=kv.values)
                for blank, kv in zip(blanks, entry.blank_answers or [], strict=False)
                if kv.values
            }
            unmatched = [b.id for b in blanks if b.id not in specs]
        if unmatched:
            return fallback(f"no accepted answers for blank(s) {unmatched}")
        return QuestionGrading(
            question_id=qid,
            max_points=question.points,
            rule=FillBlankRule(blanks=specs),
        )

    if t is QuestionType.matching:
        assert question.matching is not None
        left_ids = {i.id for i in question.matching.left}
        right_ids = {i.id for i in question.matching.right}
        pairs = {
            p.left: p.right
            for p in (entry.matching_pairs or [])
            if p.left in left_ids and p.right in right_ids
        }
        dropped_count = len(entry.matching_pairs or []) - len(pairs)
        if dropped_count:
            warnings.append(f"{qid}: {dropped_count} answer-key pair(s) had unknown ids; dropped")
        if not pairs:
            return fallback("answer key has no usable matching pairs")
        return QuestionGrading(
            question_id=qid,
            max_points=question.points,
            rule=MatchingRule(correct_pairs=pairs),
        )

    return fallback(f"unhandled question type {t.value}")


def _run_label(run: range) -> str:
    return str(run.start) if len(run) == 1 else f"{run.start}-{run.stop - 1}"


def _gap_pages(
    run: range,
    chunk_results: list[tuple[list[SourcePage], ExtractionChunk]],
    question_pages: list[SourcePage],
) -> list[SourcePage]:
    """Pages that must contain the missing run: every chunk whose OUTPUT covers a
    bracketing number (chunks know their pages; outputs don't carry page info)."""
    below, above = run.start - 1, run.stop
    pages: dict[int, SourcePage] = {}
    matched_below = matched_above = False
    for chunk_pages, output in chunk_results:
        covered: set[int] = set()
        for question in output.questions:
            covered |= covered_numbers(question)
        if below in covered:
            matched_below = True
            pages.update({p.index: p for p in chunk_pages})
        if above in covered:
            matched_above = True
            pages.update({p.index: p for p in chunk_pages})
    if matched_below and not matched_above:
        # Trailing gap (e.g. expected_last beyond everything extracted): search
        # from the below-bracket chunk to the end of the question pages.
        first = min(pages)
        pages.update({p.index: p for p in question_pages if p.index >= first})
    elif not matched_below and not matched_above:
        pages.update({p.index: p for p in question_pages})  # safety net
    return [pages[i] for i in sorted(pages)]


def _repair_gaps(
    extracted_questions: list[ExtractedQuestion],
    chunk_results: list[tuple[list[SourcePage], ExtractionChunk]],
    question_pages: list[SourcePage],
    extract_agent: Any,
    base_context: str,
    tracker: UsageTracker,
    warnings: list[str],
    expected_last: int | None,
) -> list[ExtractedQuestion]:
    runs, skip_reason = find_gaps(extracted_questions, expected_last)
    if skip_reason:
        warnings.append(skip_reason)
        return extracted_questions
    if not runs:
        return extracted_questions

    missing_count = sum(len(run) for run in runs)
    if missing_count > max(10, len(extracted_questions) // 5) or len(runs) > 5:
        warnings.append(
            f"{missing_count} question number(s) missing across {len(runs)} run(s); "
            "too many to repair automatically (likely a misread number)"
        )
        return extracted_questions

    seen = {normalize_number(q.number) for q in extracted_questions}
    recovered: list[ExtractedQuestion] = []
    for run in runs:
        pages = _gap_pages(run, chunk_results, question_pages)
        prompt = (
            f"{base_context} A previous extraction pass MISSED the question(s) with "
            f"printed number(s) {_run_label(run)}. Extract ONLY those missing "
            "questions from these pages. Do not re-extract neighboring questions "
            "that are already extracted. Set continues_previous to false."
        )
        result = extract_agent.run_sync([prompt, *_page_parts(pages)])
        tracker.add("extract-repair", result.usage)
        found: list[ExtractedQuestion] = []
        for question in result.output.questions:
            key = normalize_number(question.number)
            if key in seen or not (covered_numbers(question) & set(run)):
                continue
            seen.add(key)
            found.append(question)
        recovered.extend(found)
        page_span = f"{pages[0].index}-{pages[-1].index}" if pages else "none"
        warnings.append(
            f"question(s) {_run_label(run)} missed by chunked extraction; "
            f"re-extracted {len(found)} question(s) from page(s) {page_span}"
        )
    if recovered:
        extracted_questions = insert_recovered(extracted_questions, recovered)

    still_missing, _ = find_gaps(extracted_questions, expected_last)
    for run in still_missing:
        warnings.append(f"question(s) {_run_label(run)} still missing after re-extraction")
    return extracted_questions


def run_ingest(
    inputs: list[Path],
    output_dir: Path,
    model: str,
    full_page_figures: bool = False,
    effort: Effort | str | None = None,
) -> ExamBundle:
    if parse_agentic_model(model) is not None:
        from any_to_bench.agentic.ingest import agentic_ingest

        return agentic_ingest(inputs, output_dir, model, full_page_figures, effort)
    output_dir = Path(output_dir)
    warnings: list[str] = []
    tracker = UsageTracker()

    pages, sources = prepare_sources([Path(p) for p in inputs], output_dir)

    # Pass 1: inventory
    inventory_agent = build_agent(model, MaterialInventory, INVENTORY_INSTRUCTIONS, effort=effort)
    inventory_result = inventory_agent.run_sync(
        _page_parts(pages, max_side=INVENTORY_THUMBNAIL_SIDE)
    )
    tracker.add("inventory", inventory_result.usage)
    inventory = inventory_result.output

    roles = {c.page_index: c.role for c in inventory.pages}
    for page in pages:
        if page.index not in roles:
            warnings.append(f"page {page.index} was not classified; treating as 'questions'")
            roles[page.index] = "questions"

    question_pages = [p for p in pages if roles[p.index] == "questions"]
    key_pages = [p for p in pages if roles[p.index] in ("answer_key", "solutions", "rubric")]
    if not question_pages:
        warnings.append("no pages classified as questions; using all pages")
        question_pages = pages

    # Pass 2: question extraction, chunked with overlap
    extract_agent = build_agent(model, ExtractionChunk, EXTRACT_INSTRUCTIONS, effort=effort)
    base_context = f"Exam: {inventory.title} (language: {inventory.language})."
    chunk_results: list[tuple[list[SourcePage], ExtractionChunk]] = []
    for chunk_pages in _chunk_pages(question_pages):
        context = base_context
        if chunk_results and chunk_results[-1][1].questions:
            context += (
                " Questions up to printed number "
                f"{chunk_results[-1][1].questions[-1].number!r} are already extracted."
            )
        chunk_result = extract_agent.run_sync([context, *_page_parts(chunk_pages)])
        tracker.add("extract", chunk_result.usage)
        chunk_results.append((chunk_pages, chunk_result.output))
    extracted_questions = merge_chunks([output for _, output in chunk_results])
    if not extracted_questions:
        raise ValueError("extraction produced no questions")

    # Pass 2.5: one targeted repair round for question numbers lost at chunk
    # boundaries (the dominant real-world extraction failure).
    extracted_questions = _repair_gaps(
        extracted_questions,
        chunk_results,
        question_pages,
        extract_agent,
        base_context,
        tracker,
        warnings,
        inventory.last_question_number,
    )

    # Pass 3: build the exam (figures are cropped as blocks are converted)
    resolver = FigureResolver(output_dir, pages, full_page_figures=full_page_figures)
    builder = _ExamBuilder(resolver, warnings)
    questions = [builder.build_question(q, i) for i, q in enumerate(extracted_questions)]
    exam_id = slugify(inventory.title)
    exam = Exam(
        exam_id=exam_id,
        title=inventory.title,
        subject=inventory.subject,
        language=inventory.language,
        total_points=sum(q.points for q in questions),
        sections=[Section(id="s1", title=None, questions=questions)],
    )

    # Pass 4: answers / rubric extraction. Cover pages ride along because the
    # exam-wide scoring rules (e.g. per-option multiple-choice marking) are
    # usually printed in the general instructions.
    key_entries: dict[str, ExtractedAnswerKey] = {}
    multi_choice_scoring = None
    if key_pages:
        cover_pages = [p for p in pages if roles[p.index] == "cover"]
        answer_pages = sorted(cover_pages + key_pages, key=lambda p: p.index)
        answers_agent = build_agent(model, GradingExtraction, ANSWERS_INSTRUCTIONS, effort=effort)
        index_text = _question_index_text(exam, builder.leaf_keys)
        extractions: list[GradingExtraction] = []
        for chunk_pages in _chunk_pages(answer_pages):
            answers_result = answers_agent.run_sync([index_text, *_page_parts(chunk_pages)])
            tracker.add("answers", answers_result.usage)
            extractions.append(answers_result.output)
        key_entries = _merge_key_entries(extractions)
        multi_choice_scoring = next(
            (e.multi_choice_scoring for e in extractions if e.multi_choice_scoring), None
        )
    else:
        warnings.append("no answer key / solutions / rubric pages found")

    # Pass 5: grading spec
    grading_questions: dict[str, QuestionGrading] = {}
    for leaf in exam.iter_leaves():
        entry = next(
            (key_entries[k] for k in builder.leaf_keys.get(leaf.id, []) if k in key_entries),
            None,
        )
        grading_questions[leaf.id] = _build_grading_entry(
            leaf, entry, resolver, warnings, multi_choice_scoring
        )
    grading = GradingSpec(exam_id=exam_id, questions=grading_questions)

    warnings.extend(resolver.warnings)
    manifest = BundleManifest(
        ingest_model=model, sources=sources, warnings=warnings, usage=tracker.summary()
    )
    bundle = ExamBundle(
        root=output_dir,
        exam=exam,
        grading=grading,
        answer_schema=generate_answer_schema(exam),
        manifest=manifest,
    )
    bundle.save()

    problems = validate_bundle(output_dir)
    if problems:
        manifest.warnings.extend(f"validation: {p}" for p in problems)
        bundle.save()
    return bundle
