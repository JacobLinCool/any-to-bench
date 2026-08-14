"""AGENTS.md templates and task prompts for the agentic (codex) backend.

Codex automatically reads AGENTS.md at the working root, so the standing
contract lives there and the per-run prompt stays short.
"""

from __future__ import annotations

INGEST_AGENTS_MD = """\
# Task: digitize exam materials into a machine-gradable bundle

You are given the raw materials of ONE exam (question booklet, answer key,
solutions, scoring guidelines — PDFs and/or photos) under `input/`. Produce an
"exam bundle" under `bundle/`. Your output is validated by a machine; if
validation fails you will receive the exact list of problems and must fix the
files under `bundle/` in place.

## Deliverables

1. `bundle/exam.json` — the structured exam. MUST validate against
   `schemas/exam.schema.json`.
2. `bundle/grading.json` — the grading spec. MUST validate against
   `schemas/grading.schema.json`.
3. `bundle/assets/...` — every image file referenced from the JSON above.
4. Optional `bundle/ingest_warnings.json` — a JSON array of strings noting
   anything ambiguous, missing, or assumed (e.g. "points not printed;
   defaulted to 1").

Do NOT write `bundle/answer_schema.json` or `bundle/manifest.json` — they are
generated for you.

## Reading the inputs

The inputs are raw files. Render or convert them with local tools so you can
actually LOOK at every page (e.g. render PDF pages to PNG at ~200 DPI; on
macOS `sips` or `qlmanage -t` work, or python3 if a PDF library is available).
Work inside the workspace; there is no network access. Go page by page and
extract EVERY question — completeness is the top priority.

## exam.json rules

- Transcribe text VERBATIM as Markdown; math as LaTeX ($...$ inline,
  $$...$$ display). Preserve the original language exactly.
- Content blocks: `{"type": "text", "markdown": ...}`,
  `{"type": "image", "asset": ..., "alt": ...}` (optional `caption`),
  `{"type": "table", "header": [...], "rows": [[...]]}`. Tables become table
  blocks, never images of tables.
- Every figure/diagram/graph needed to answer becomes an image block. Create
  the image file yourself under `bundle/assets/` (crop it out of a page
  render, or use a full-page render if cropping is impractical) and write a
  detailed `alt` describing its content. Asset paths are bundle-root-relative
  like `assets/q03-fig1.png` — never absolute, never containing `..`.
- Question ids: `q1`, `q2`, ... in document order; sub-questions of a
  composite: `q6.a`, `q6.b`, ... Ids must be globally unique.
- Question types: single_choice, multiple_choice, true_false, fill_in_blank,
  matching, short_answer (a few words/lines), essay (extended response),
  drawing (the answer is a drawing/graph), composite (shared stimulus with
  sub-questions in `children`).
- Choice options keep their printed ids (A, B, ...). Fill-in-blank: blanks
  `b1`, `b2`, ... in reading order. Matching: left ids `L1`..., right ids
  `R1`... (right may include distractors).
- Composite questions: shared stimulus in `prompt`, sub-questions in
  `children`; the composite's `points` MUST equal the sum of its children's.
- `points`: the printed point value. If not printed, use 1.0 and record a
  warning. `total_points` MUST equal the sum of all leaf question points.

## grading.json rules

- `exam_id` MUST equal exam.json's `exam_id`.
- Exactly one entry per leaf (answerable, non-composite) question, keyed by
  its question id, with `question_id` equal to the key and `max_points` equal
  to the question's points.
- Rule kinds by question type:
  - single_choice / multiple_choice → `"choice"` (`correct` option ids must
    exist on the question; for multiple_choice set `partial_credit` true
    unless the materials say all-or-nothing)
  - multiple_choice, when the exam's general instructions define per-option
    scoring (each option judged independently, score determined by how many
    options were judged wrongly) → `"per_option"`: copy the printed table into
    `ratio_by_errors` as ratios, e.g. "all correct: full points; wrong on 1
    option: 3/5; wrong on 2: 1/5; otherwise 0" → `[1.0, 0.6, 0.2]` (beyond the
    table and blank answers score 0 automatically)
  - true_false → `"true_false"`
  - fill_in_blank → `"fill_in_blank"` (`blanks` must have EXACTLY the
    question's blank ids; list ALL accepted variants per blank)
  - matching → `"matching"` (`correct_pairs` left/right ids must exist)
  - short_answer / essay / drawing → `"judge"`
- If the materials provide no answer for a fixed-answer question, fall back
  to a `"judge"` rule and record a warning.
- `"judge"` rules: `reference_answer` = the model solution (Markdown);
  `rubric` = scoring criteria with point levels when the materials include
  scoring guidelines (the sum of the criteria's maximum levels MUST equal
  `max_points`); `judge_instructions` = grading guidance prose;
  `reference_assets` = solution figures (files you create under
  `bundle/assets/`).
- Do not invent answers that are not in the materials.
"""

SOLVE_AGENTS_MD = """\
# Task: take an exam

You are taking an exam. The structured exam is `exam/exam.json`; the figures
and tables it references are image files under `exam/assets/` — open and LOOK
at every image a question references before answering it. Write your answers
to `output/answers.json`. Your output is validated against
`schemas/answer_schema.json`; that schema is authoritative (exact question
ids, exact answer shapes). If validation fails you will receive the exact
list of problems and must fix `output/answers.json` in place.

## Output format

```json
{"exam_id": "<the exam_id from exam/exam.json>",
 "answers": {"<question id>": <answer>, ...}}
```

Answer shapes by question type:

- single_choice: `{"type": "single_choice", "selected": "<option id>"}`
- multiple_choice: `{"type": "multiple_choice", "selected": ["<option id>", ...]}`
  — list ALL correct options
- true_false: `{"type": "true_false", "value": true}`
- fill_in_blank: `{"type": "fill_in_blank", "blanks": {"<blank id>": "<text>", ...}}` — every blank
- matching: `{"type": "matching", "pairs": {"<left id>": "<right id>", ...}}` — every left id
- short_answer / essay: `{"type": "text", "text": "<Markdown; math as LaTeX>"}`
- drawing: `{"type": "drawing", "description": "<precise textual description>"}`

## Rules

- Answer EVERY leaf question, to the best of your ability.
- Use ONLY the ids defined in the exam (option ids, blank ids, matching ids).
- For open-ended questions, if the exam instructions or the question ask for
  working, a derivation, or justification, SHOW your full reasoning and
  calculations in the answer — the process is graded, not just the final
  result. Otherwise answer concisely without explanation.
- Drawing questions: describe every shape, label, and axis and their relative
  positions precisely, so a grader could reproduce the drawing.
"""

JUDGE_AGENTS_MD = """\
# Task: grade student answers

You are an experienced, impartial exam grader. Grade the student's answer to
each question. Base your judgment only on the question, the scoring materials
provided (rubric, reference answer, grading instructions), and the student's
answer. Be strict but fair: award the points the answer earns, no more.

The grading tasks are in `tasks/tasks.json`: one entry per question with the
question text, max/min points, rubric, reference answer, official grading
instructions, and the student's answer. The full exam is in `exam/exam.json`
and referenced figures are image files under `exam/assets/` — open and LOOK
at them whenever a question, reference solution, or student answer involves
one.

Write `output/verdicts.json`, validating against
`schemas/verdicts.schema.json`:

```json
{"verdicts": {"<question id>": {
    "criteria": [{"criterion_id": "...", "points": 0, "rationale": "..."}],
    "total_points": 0,
    "overall_rationale": "..."}}}
```

- Grade EVERY task.
- Questions with a rubric: score EVERY criterion at exactly one of its
  defined point levels, with a short rationale each; `total_points` = the sum
  of your criterion points.
- Questions without a rubric: `criteria` MUST be `[]`; `total_points` = your
  holistic score, between the task's min_points and max_points.

If validation fails you will receive the exact list of problems and must fix
`output/verdicts.json` in place.
"""

INGEST_TASK_PROMPT = (
    "Digitize the exam materials under input/ into a bundle under bundle/, following "
    "AGENTS.md exactly. Inspect every page of every input file before extracting; "
    "extract every question."
)

SOLVE_TASK_PROMPT = (
    "Take the exam in exam/exam.json and write output/answers.json, following AGENTS.md exactly."
)

JUDGE_TASK_PROMPT = (
    "Grade every task in tasks/tasks.json and write output/verdicts.json, following "
    "AGENTS.md exactly."
)


def format_problems(problems: list[str], limit: int = 50) -> str:
    """The fix-round prompt: the validator's problem list, verbatim."""
    lines = [f"Your output did not pass validation. Problems ({len(problems)} total):"]
    lines.extend(f"- {p}" for p in problems[:limit])
    if len(problems) > limit:
        lines.append(f"... and {len(problems) - limit} more.")
    lines.append(
        "Fix your deliverable files in place so ALL problems are resolved, then stop. "
        "Do not modify anything outside your deliverable files."
    )
    return "\n".join(lines)
