# The exam bundle

`ingest` turns the materials of one exam into a self-contained **exam bundle**
directory — the unit that `validate`, `solve`, and `grade` operate on.

| File | What it is |
|---|---|
| `exam.json` | The structured exam paper (questions, figures, tables, points) |
| `answer_schema.json` | A strict JSON Schema an answer sheet must satisfy — hand it to any LLM harness |
| `grading.json` | How to grade each question: deterministic rules or LLM-judge rubrics |
| `assets/` | Rendered source pages and cropped question/solution figures |
| `manifest.json` | Source hashes, ingest model, warnings, token usage |

## Question model

Supported question types: `single_choice`, `multiple_choice`, `true_false`,
`fill_in_blank` (multiple blanks), `matching` (many-to-many, distractors allowed),
`short_answer`, `essay`, `drawing`, and `composite` (a shared stimulus with nested
sub-questions). Question content is a list of blocks — Markdown text (math as LaTeX),
images (bundle-relative `assets/...` paths with written `alt` descriptions), and
structured tables.

Every *leaf* (non-composite) question is answerable and has exactly one entry in
`grading.json`. Composite questions carry the shared stimulus; their points equal the
sum of their children's, and the exam's `total_points` equals the sum of all leaf
points.

## The answer schema

`answer_schema.json` is generated deterministically from `exam.json`. It narrows each
question to its actual ids — option ids become enums, blank and matching ids become
fixed required keys — with `additionalProperties: false` throughout, so a conforming
answer sheet can be graded mechanically. `solve` output is validated against it, and
`validate` checks it is fresh (regenerating it from the exam must yield the same
schema).

## Validation

`any-to-bench validate <bundle>` checks the whole contract: files parse, every leaf
question has a grading entry and vice versa, rule kinds fit question types (open-ended
questions must use a judge rule; fixed-answer types may fall back to one when no key
was found), option/blank/pair ids referenced by rules exist on the questions, all
referenced asset files exist, and the answer schema is fresh and itself valid.
