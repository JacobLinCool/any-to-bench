# Grading semantics

Fixed-answer questions grade **deterministically**; open-ended questions grade via one
or more **multimodal LLM judges**. A bundle whose grading is fully deterministic grades
with zero API calls.

## Deterministic rules

- **Choice** (`single_choice`, `multiple_choice`): exact-set match; optional partial
  credit `points × |selected ∩ correct| / |correct|`, per-wrong-selection penalty, and
  negative marking for fully wrong answers; results are clamped to
  `[min_points, max_points]`.
- **Per-option choice** (`per_option`, for `multiple_choice`): every option is judged
  independently and the score ratio is looked up by `k = |selected △ correct|` in
  `ratio_by_errors` (e.g. Taiwan GSAT's "wrong on 1 option: 3/5, wrong on 2: 1/5" is
  `[1.0, 0.6, 0.2]`); `k` beyond the table and fully blank answers score 0. Ingestion
  produces this rule automatically when the exam's general instructions state such a
  scoring scheme.
- **True/false**: exact match, optional negative marking.
- **Fill-in-blank**: per-blank accepted answers with weights; normalization before
  comparison (case folding, whitespace collapsing, Unicode NFKC, numeric tolerance —
  including fractions and comma separators); `all_or_nothing` optional.
- **Matching**: per-pair points, wrong-pair penalty, `all_or_nothing` optional.
- Unanswered questions score 0 without penalties.

## LLM-judge rules

Each judge model sees the question exactly as the solver did (text + figures), the
maximum points, any official grading instructions, the rubric, the reference solution
(text and figures), and the student's answer (drawings as their textual description
plus an optional rendered image). Deterministic-type questions that had no answer key
fall back to judge grading, with the answer rendered as text.

Post-processing keeps judges honest:

- With a rubric, every criterion must be scored at one of its defined point levels;
  scores are **snapped** to the nearest level and the total is recomputed. Missing or
  unknown criteria are warned about.
- Holistic verdicts (no rubric) are clamped to `[min_points, max_points]`.
- Multiple judges (repeat `--judge-model`, any mix of providers and `codex:` agentic
  judges) aggregate by `mean` / `median` / `min` / `max`; all raw verdicts are kept in
  the report.
- A failing judge never sinks the run — its absence is recorded as a warning, and a
  question with no verdicts at all is reported as an error, not silently zero.

**For serious benchmarks, use judge models different from the taker.** Self-judging
has a measurable optimism bias (in our GSAT test, a model judging its own English
essay awarded itself full marks). `--judge-model` is repeatable and accepts any mix of
providers and `codex:` agentic judges; `bench` warns when a taker also appears in the
judge list.
