# any-to-bench

Convert **any exam materials** — photos of exam papers, exam PDFs, solution
PDFs/photos, official answer keys, scoring rubrics — into a **machine-gradable
benchmark**.

Give it everything you have for one exam; it produces an [exam bundle](docs/bundle.md):
the structured exam, a strict answer-sheet JSON Schema for any LLM harness, and a
grading spec. Fixed-answer questions grade deterministically; open-ended questions are
graded by multimodal LLM judges with rubrics extracted from your materials. All common
paper-exam question types are supported, including nested sub-questions, figures,
tables, and LaTeX math.

## Install

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # fill in the API keys for the providers you use
```

## Usage

```bash
# 1. Ingest: any mix of PDFs and photos for ONE exam -> a bundle
uv run any-to-bench ingest exam.pdf answer-key.jpg rubric.pdf -o out/bundle \
    --model openai:gpt-5.6-sol

# 2. Check the bundle
uv run any-to-bench validate out/bundle

# 3. Have an LLM take the exam (any provider — this is the benchmark part)
uv run any-to-bench solve out/bundle --model google:gemini-3.7-flash -o out/answers.json

# 4. Grade the answer sheet
uv run any-to-bench grade out/bundle out/answers.json -o out/report.json
# override judge model(s): --judge-model openai:gpt-5.6-sol --judge-model codex:gpt-5.6-sol

# Or benchmark several models at once: solve + grade each, compare in one table
uv run any-to-bench bench out/bundle -o out/bench \
    --model openai:gpt-5.6-terra --model google:gemini-3.7-flash

# Share bundles via Hugging Face datasets (viewer-friendly, byte-faithful round trip)
uv run any-to-bench upload out/bundle user/my-exams --name matha
uv run any-to-bench download user/my-exams --name matha -o local/bundle
```

`a2b` is a shorthand alias for `any-to-bench` — every command works with both.

Ingest, solve, and judge models are independent. Use a `codex:` model string (e.g.
`codex:gpt-5.6-sol`) to run a phase **agentically** via the Codex CLI instead of
direct LLM calls — same commands, same outputs. All commands accept `--effort` and
report token usage.

## Design principles

The three phases have deliberately **asymmetric goals**:

- **Ingest: spend freely, be exact.** A bundle is a dataset — built once, reused by
  everyone who ever benchmarks against it. Extraction accuracy is worth almost any
  model cost and wall time; this is why ingestion supports the expensive agentic mode,
  gap-repair rounds, and validate-and-fix loops. Intelligence spent here is amortized
  across every future run.
- **Solve: no constraints.** The taker is the thing being measured — anything from a
  cheap LLM call to a full agent belongs here.
- **Grade: require as little intelligence as possible.** The same answer sheet must
  earn the same score every time. Fixed-answer questions grade as pure scripts — zero
  model calls, bit-for-bit reproducible. Where an LLM judge is unavoidable
  (open-ended questions), it is *constrained*, not creative: precise rubrics with
  defined point levels, reference answers, and level snapping mean the judge follows
  the rubric mechanically instead of improvising — so even a non-frontier judge model
  grades accurately and consistently.

Put differently: ingest converts intelligence into structure (keys, rubrics, schemas)
exactly once, so that grading needs almost none, forever.

## Documentation

- [The exam bundle](docs/bundle.md) — output format, question model, validation
- [How ingestion works](docs/ingestion.md) — the LLM-mode extraction pipeline
- [Agentic mode](docs/agentic-mode.md) — `codex:` models, workspaces, the fix loop
- [Grading semantics](docs/grading.md) — deterministic rules and LLM judges
- [Benchmarking](docs/bench.md) — the `bench` model matrix and its metrics
- [Publishing](docs/publish.md) — sharing bundles as Hugging Face datasets
- [Models, effort, usage](docs/models.md) — model strings, `--effort`, token reporting

## Development

```bash
uv run pytest -q        # fully offline — model requests are forbidden in tests
uv run ruff check .
```

The test suite fakes the LLM layer (`any_to_bench.llm.build_agent`) and the codex
subprocess layer (`any_to_bench.agentic.runner.run_codex`), so the entire
ingest → solve → grade pipeline runs end-to-end in both modes without network access
or a codex binary.
