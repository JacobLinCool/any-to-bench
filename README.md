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
```

`a2b` is a shorthand alias for `any-to-bench` — every command works with both.

Ingest, solve, and judge models are independent. Use a `codex:` model string (e.g.
`codex:gpt-5.6-sol`) to run a phase **agentically** via the Codex CLI instead of
direct LLM calls — same commands, same outputs. All commands accept `--effort` and
report token usage.

## Documentation

- [The exam bundle](docs/bundle.md) — output format, question model, validation
- [How ingestion works](docs/ingestion.md) — the LLM-mode extraction pipeline
- [Agentic mode](docs/agentic-mode.md) — `codex:` models, workspaces, the fix loop
- [Grading semantics](docs/grading.md) — deterministic rules and LLM judges
- [Benchmarking](docs/bench.md) — the `bench` model matrix and its metrics
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
