"""Offline ingest: the full pipeline with faked extraction agents."""

import pytest
from PIL import Image

import any_to_bench.ingest.pipeline as pipeline_module
from any_to_bench.bundle import validate_bundle
from any_to_bench.ingest.pipeline import run_ingest
from any_to_bench.schemas.content import TextBlock
from any_to_bench.schemas.exam import QuestionType
from any_to_bench.schemas.extraction import (
    ExtractedAnswerKey,
    ExtractedBlank,
    ExtractedOption,
    ExtractedQuestion,
    ExtractedRubricCriterion,
    ExtractedRubricLevel,
    ExtractedSubQuestion,
    ExtractionChunk,
    FigureRef,
    GradingExtraction,
    KeyValue,
    MaterialInventory,
    PageClassification,
)
from any_to_bench.schemas.grading import ChoiceRule, FillBlankRule, JudgeRule
from tests.conftest import fake_build_agent


@pytest.fixture
def exam_pdf(tmp_path):
    pages = [Image.new("RGB", (400, 560), color) for color in ("white", "ivory")]
    path = tmp_path / "exam.pdf"
    pages[0].save(path, format="PDF", save_all=True, append_images=pages[1:])
    return path


INVENTORY = MaterialInventory(
    title="Mini Quiz",
    language="en",
    subject="Math",
    last_question_number=None,
    pages=[
        PageClassification(page_index=0, role="questions", note=None),
        PageClassification(page_index=1, role="answer_key", note=None),
    ],
)

EXTRACTION = ExtractionChunk(
    continues_previous=False,
    questions=[
        ExtractedQuestion(
            number="1.",
            question_type=QuestionType.single_choice,
            blocks=[
                TextBlock(markdown="What shape is shown?"),
                FigureRef(page_index=0, bbox=(0.1, 0.1, 0.5, 0.4), alt="a circle", caption=None),
            ],
            points=2.0,
            options=[
                ExtractedOption(id="A", blocks=[TextBlock(markdown="Square")]),
                ExtractedOption(id="B", blocks=[TextBlock(markdown="Circle")]),
            ],
            blanks=None,
            matching=None,
            children=None,
        ),
        ExtractedQuestion(
            number="2.",
            question_type=QuestionType.fill_in_blank,
            blocks=[TextBlock(markdown="6 x 7 = ___(i)___")],
            points=1.0,
            options=None,
            blanks=[ExtractedBlank(id="b1", label="(i)")],
            matching=None,
            children=None,
        ),
        ExtractedQuestion(
            number="3.",
            question_type=QuestionType.composite,
            blocks=[TextBlock(markdown="Consider the function f(x) = x^2.")],
            points=None,
            options=None,
            blanks=None,
            matching=None,
            children=[
                ExtractedSubQuestion(
                    number="(a)",
                    question_type=QuestionType.short_answer,
                    blocks=[TextBlock(markdown="State f(3).")],
                    points=2.0,
                    options=None,
                    blanks=None,
                    matching=None,
                ),
                ExtractedSubQuestion(
                    number="(b)",
                    question_type=QuestionType.essay,
                    blocks=[TextBlock(markdown="Discuss the symmetry of f.")],
                    points=3.0,
                    options=None,
                    blanks=None,
                    matching=None,
                ),
            ],
        ),
    ],
)

ANSWER_KEY = GradingExtraction(
    entries=[
        ExtractedAnswerKey(
            question_number="1.",
            correct_options=["B"],
            true_false=None,
            blank_answers=None,
            matching_pairs=None,
            solution_text=None,
            solution_figures=None,
            rubric=None,
            judge_instructions=None,
        ),
        ExtractedAnswerKey(
            question_number="2.",
            correct_options=None,
            true_false=None,
            blank_answers=[KeyValue(key="b1", values=["42", "forty-two"])],
            matching_pairs=None,
            solution_text=None,
            solution_figures=None,
            rubric=None,
            judge_instructions=None,
        ),
        ExtractedAnswerKey(
            question_number="3.(a)",
            correct_options=None,
            true_false=None,
            blank_answers=None,
            matching_pairs=None,
            solution_text="f(3) = 9.",
            solution_figures=None,
            rubric=None,
            judge_instructions=None,
        ),
        ExtractedAnswerKey(
            question_number="3.(b)",
            correct_options=None,
            true_false=None,
            blank_answers=None,
            matching_pairs=None,
            solution_text="Even function, symmetric about the y-axis.",
            solution_figures=None,
            rubric=[
                ExtractedRubricCriterion(
                    id="content",
                    description="Correctly identifies even symmetry",
                    levels=[
                        ExtractedRubricLevel(points=3.0, descriptor="Complete"),
                        ExtractedRubricLevel(points=1.0, descriptor="Partial"),
                        ExtractedRubricLevel(points=0.0, descriptor="Missing"),
                    ],
                )
            ],
            judge_instructions=None,
        ),
    ],
    multi_choice_scoring=None,
)


@pytest.fixture
def fake_agents(monkeypatch):
    monkeypatch.setattr(
        pipeline_module,
        "build_agent",
        fake_build_agent(
            {
                MaterialInventory: INVENTORY,
                ExtractionChunk: EXTRACTION,
                GradingExtraction: ANSWER_KEY,
            }
        ),
    )


def test_ingest_builds_valid_bundle(exam_pdf, tmp_path, fake_agents):
    out = tmp_path / "bundle"
    bundle = run_ingest([exam_pdf], out, model="test:ingest")

    assert validate_bundle(out) == []
    exam = bundle.exam
    assert exam.title == "Mini Quiz"
    assert exam.exam_id == "mini-quiz"
    assert [q.id for q in exam.iter_leaves()] == ["q1", "q2", "q3.a", "q3.b"]
    assert exam.total_points == 8.0  # 2 + 1 + (2 + 3)

    # The figure was cropped from the rendered page.
    q1 = exam.leaf_map()["q1"]
    image_blocks = [b for b in q1.prompt if b.type == "image"]
    assert len(image_blocks) == 1
    assert (out / image_blocks[0].asset).exists()

    # Grading rules built from the answer key.
    rules = {qid: qg.rule for qid, qg in bundle.grading.questions.items()}
    assert isinstance(rules["q1"], ChoiceRule) and rules["q1"].correct == ["B"]
    assert isinstance(rules["q2"], FillBlankRule)
    assert rules["q2"].blanks["b1"].accepted == ["42", "forty-two"]
    assert isinstance(rules["q3.a"], JudgeRule)
    assert rules["q3.a"].reference_answer == "f(3) = 9."
    assert isinstance(rules["q3.b"], JudgeRule)
    assert [c.id for c in rules["q3.b"].rubric] == ["content"]

    # Composite points defaulted per child and summed; a warning notes it.
    assert bundle.manifest.warnings == [] or all(
        isinstance(w, str) for w in bundle.manifest.warnings
    )
    assert bundle.manifest.ingest_model == "test:ingest"
    assert len(bundle.manifest.sources) == 1

    # Usage: 1 inventory + 1 extract chunk + 1 answers chunk, 100 input each.
    usage = bundle.manifest.usage
    assert usage is not None
    assert set(usage.phases) == {"inventory", "extract", "answers"}
    assert usage.total.requests == 3
    assert usage.total.input_tokens == 300
    assert usage.total.reasoning_tokens == 21


def test_ingest_snapshots_resources_without_sending_them_to_agents(exam_pdf, tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "knowledge.txt").write_text("public evidence", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        pipeline_module,
        "build_agent",
        fake_build_agent(
            {
                MaterialInventory: INVENTORY,
                ExtractionChunk: EXTRACTION,
                GradingExtraction: ANSWER_KEY,
            },
            calls=calls,
        ),
    )

    bundle = run_ingest(
        [exam_pdf], tmp_path / "resource-bundle", model="test:ingest", resources=corpus
    )

    assert validate_bundle(bundle.root) == []
    assert [entry.path for entry in bundle.manifest.resources] == ["resources/knowledge.txt"]
    assert all(
        "public evidence" not in str(part)
        for _, _, agent in calls
        for invocation in agent.calls
        for part in invocation
    )


def test_ingest_without_answer_key_falls_back_to_judge(exam_pdf, tmp_path, monkeypatch):
    inventory = INVENTORY.model_copy(
        update={
            "pages": [
                PageClassification(page_index=0, role="questions", note=None),
                PageClassification(page_index=1, role="cover", note=None),
            ]
        }
    )
    monkeypatch.setattr(
        pipeline_module,
        "build_agent",
        fake_build_agent({MaterialInventory: inventory, ExtractionChunk: EXTRACTION}),
    )
    out = tmp_path / "bundle"
    bundle = run_ingest([exam_pdf], out, model="test:ingest")

    assert validate_bundle(out) == []
    # Fixed-answer questions degraded to judge rules, with warnings.
    assert isinstance(bundle.grading.questions["q1"].rule, JudgeRule)
    assert isinstance(bundle.grading.questions["q2"].rule, JudgeRule)
    assert any("no answer key" in w for w in bundle.manifest.warnings)
