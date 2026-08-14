# Benchmarking multiple models (`bench`)

```bash
a2b bench out/bundle -o out/bench \
    --model openai:gpt-5.6-terra --model google:gemini-3.7-flash \
    --model codex:gpt-5.6-sol \
    --judge-model google:gemini-3.7-flash
```

`bench` runs every `--model` (repeatable; the same model twice is a variance run)
through solve + grade on one bundle, sequentially, and writes into the output
directory:

- `<model-slug>-answers.json` and `<model-slug>-report.json` per model
- `bench.json` — the full comparison report, **rewritten after every model** so an
  interrupted run keeps its completed rows

and prints a Markdown comparison table. One failing model records its error in the
row and never sinks the rest; the exit code is 1 only when every model failed.

## Metric definitions

- **score / %** — from the grade report (deterministic + judge points), over the
  questions the taker was actually asked. See **cov**.
- **cov** — coverage: the points the taker was asked, out of the exam total. Equal
  unless `--text-only-model` excluded questions. When rows differ here, their
  percentages have different denominators and `bench` warns before you compare them.
- **det full** — deterministic questions answered for full credit, out of the number
  of questions with a non-judge grading rule. The denominator is a bundle property,
  so a model that skips questions is penalized rather than flattered.

  This is about a model *declining* to answer, which is different from a question
  being **skipped** because the taker was never equipped for it — see below.
- **judge / error / unanswered counts** — per-question grading modes; judge questions
  that no judge could grade count as errors.
- **judge Δ** — inter-judge disagreement as `disagreed/comparable`, or `–` when fewer
  than two judges produced verdicts so there is nothing to compare. See
  [Judge agreement](grading.md#judge-agreement).
- **schema err** — answer-sheet violations of `answer_schema.json` (the sheet is
  still graded; bad answers degrade to per-question errors).
- **tokens / time** — solve + grade usage and wall time per model. Agentic-mode
  numbers are approximate (see [Agentic mode](agentic-mode.md)).

## Takers that cannot see images

`render_question_parts` sends figures to the taker as real image bytes, so pointing a
text-only model at an exam containing even one figure question makes the provider
reject the request — and that one failure used to cost the model its entire row.

`--text-only-model MODEL` (repeatable) declares that a taker cannot read images.
Questions requiring one are then **skipped**: left out of the answer sheet, recorded
in the report with `mode: "skipped"` and the modalities they needed, and excluded from
the score's denominator. The model is scored on what it was actually asked.

Modality is a per-question property derived from the exam's content blocks, not a
bundle-wide flag — a typical paper mixes a few figure questions into many text ones,
and the text ones remain perfectly answerable. Requirements are **inherited**: a figure
in a section's instructions or in a composite question's shared stimulus makes every
question beneath it require images, so a single banner image can exclude a whole
section. `detail.modality_sources` names where the requirement came from for exactly
this reason.

`skipped` and `unanswered` are deliberately different. An unanswered question is a
model failing to deliver and is penalized in full. A skipped question was never put to
the model, so counting it wrong would measure the harness rather than the model.
`report.json` keeps both readings: `percentage` over the whole exam, and
`covered_percentage` over the subset — the table shows the latter with `cov` beside it.

Without the flag nothing changes: takers are assumed capable of everything, exactly as
before. Agentic (`codex:`/`claude:`) takers are never gated — they open assets as files
from their workspace rather than receiving inline bytes — and `bench` warns if you
declare one text-only.

## Self-judging warning

If a taker model also appears in the effective judge list (`--judge-model`, or the
bundle's default judges when the flag is omitted), `bench` warns: self-judging tends
to be optimistic. Prefer judges that differ from every taker — see
[Grading semantics](grading.md).
