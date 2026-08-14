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

- **score / %** — from the grade report (deterministic + judge points).
- **det full** — deterministic questions answered for full credit, out of the number
  of questions with a non-judge grading rule. The denominator is a bundle property,
  so a model that skips questions is penalized rather than flattered.
- **judge / error / unanswered counts** — per-question grading modes; judge questions
  that no judge could grade count as errors.
- **schema err** — answer-sheet violations of `answer_schema.json` (the sheet is
  still graded; bad answers degrade to per-question errors).
- **tokens / time** — solve + grade usage and wall time per model. Agentic-mode
  numbers are approximate (see [Agentic mode](agentic-mode.md)).

## Self-judging warning

If a taker model also appears in the effective judge list (`--judge-model`, or the
bundle's default judges when the flag is omitted), `bench` warns: self-judging tends
to be optimistic. Prefer judges that differ from every taker — see
[Grading semantics](grading.md).
