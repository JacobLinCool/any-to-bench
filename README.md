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

Requires Python ≥ 3.12.

```bash
uv tool install any-to-bench   # or: pip install any-to-bench
a2b --help
```

Set the API keys for the providers you use as environment variables (or in a
`.env` file in your working directory): `OPENAI_API_KEY`, `GOOGLE_API_KEY`,
`HF_TOKEN`, ...

For development, clone the repo and:

```bash
uv sync
cp .env.example .env   # fill in the API keys for the providers you use
```

## Usage

```bash
# 1. Ingest: any mix of PDFs and photos for ONE exam -> a bundle
a2b ingest exam.pdf answer-key.jpg rubric.pdf -o out/bundle --model openai:gpt-5.6-sol

# 2. Check the bundle
a2b validate out/bundle

# 3. Have an LLM take the exam (any provider — this is the benchmark part)
a2b solve out/bundle --model google:gemini-3.7-flash -o out/answers.json

# 4. Grade the answer sheet
a2b grade out/bundle out/answers.json -o out/report.json
# override judge model(s): --judge-model openai:gpt-5.6-sol --judge-model codex:gpt-5.6-sol

# Or benchmark several models at once: solve + grade each, compare in one table
a2b bench out/bundle -o out/bench \
    --model openai:gpt-5.6-terra --model google:gemini-3.7-flash

# Share bundles via Hugging Face datasets (viewer-friendly, byte-faithful round trip)
a2b upload out/bundle user/my-exams --name matha
a2b download user/my-exams --name matha -o local/bundle

# Publish what you measured, so it accumulates into a leaderboard
a2b results publish out/bench user/my-results --source-repo user/my-exams
```

`a2b` is a shorthand alias for `any-to-bench` — every command works with both. In a
cloned repo without installing, prefix commands with `uv run` (e.g. `uv run a2b ...`).

Ingest, solve, and judge models are independent. Use a `codex:` or `claude:` model
string (e.g. `codex:gpt-5.6-sol`, `claude:opus`) to run a phase **agentically** via
that CLI instead of direct LLM calls — same commands, same outputs. All commands accept `--effort` and
report token usage.

## Example dataset

[**JacobLinCool/taiwan-exams**](https://huggingface.co/datasets/JacobLinCool/taiwan-exams)
is a corpus built with this tool: 182 Taiwanese national exams, 7,772 questions,
ingested from the official papers, answer keys, and marking schemes with
`codex:gpt-5.6-sol` (`cap` with `claude:claude-opus-5`). One subset per exam, named
`<exam>-<year>-<subject>`, where the year is the ROC year the exam is named for
(113–115 = 2024–2026):

| Prefix | Exam | Subsets |
|---|---|---|
| `gsat` | 學測 General Scholastic Ability Test | 21 — three years × 7 subjects |
| `ast` | 分科測驗 Advanced Subjects Test | 23 — three years, every subject |
| `tve` | 統測 vocational Unified Entrance Examination | 120 — three years × 5 common + 35 group papers |
| `cap` | 會考 Comprehensive Assessment Program, end of junior high | 18 — three years × 6 papers |

英語（聽力）is the one paper left out: its questions are spoken and published as
audio, and a bundle carries text and images.

The dataset viewer shows the extracted questions with their figures embedded;
`<subset>/bundle/` holds the bundle itself. Benchmark against any of them:

```bash
a2b download JacobLinCool/taiwan-exams --name gsat-115-math-a -o bundle
a2b solve bundle --model google:gemini-3.7-flash -o answers.json
a2b grade bundle answers.json -o report.json
```

## Published results

[**JacobLinCool/taiwan-exams-results**](https://huggingface.co/datasets/JacobLinCool/taiwan-exams-results)
holds the first scores against that corpus: eight taker configurations —
`codex:gpt-5.6-luna` and `claude:claude-sonnet-5`, each at low, medium, high and
xhigh — over all 21 papers of the 115 year, 1,748 points apiece.

| Configuration | Score | Rule-graded |
|---|---|---|
| `codex:gpt-5.6-luna` xhigh | 98.1% | 98.2% |
| `codex:gpt-5.6-luna` high | 95.6% | 95.3% |
| `claude:claude-sonnet-5` xhigh | 94.3% | 94.8% |
| `claude:claude-sonnet-5` low | 92.2% | 93.1% |
| `codex:gpt-5.6-luna` low | 78.8% | 80.0% |

Rule-graded points are scored by program, so that column compares across any two
rows; judged points depend on the judge model, which is named per entry. One run
per paper, so there is no error bar — read small gaps as unresolved.

```bash
a2b bench bundle -o out --model your:model --effort high
a2b results publish out user/your-results --source-repo JacobLinCool/taiwan-exams
```

[Browse it as a leaderboard](https://jacoblincool.github.io/any-to-bench/results.html)
— pick the papers, decide whether judged questions count, and compare cost
against score. See [docs/results.md](docs/results.md) for the layout.

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
- [Agentic mode](docs/agentic-mode.md) — `codex:`/`claude:` models, workspaces, the fix loop
- [Grading semantics](docs/grading.md) — deterministic rules and LLM judges
- [Benchmarking](docs/bench.md) — the `bench` model matrix and its metrics
- [Publishing](docs/publish.md) — sharing bundles as Hugging Face datasets
- [Publishing results](docs/results.md) — leaderboard entries, and how scores are counted
- [Models, effort, usage](docs/models.md) — model strings, `--effort`, token reporting

## Development

```bash
uv run pytest -q        # fully offline — model requests are forbidden in tests
uv run ruff check .
uv run ruff format .    # CI enforces this with --check
```

The test suite fakes the LLM layer (`any_to_bench.llm.build_agent`) and the agentic
subprocess layer (`any_to_bench.agentic.runner.run_codex` / `run_claude`), so the
entire ingest → solve → grade pipeline runs end-to-end in every mode without network
access or either CLI binary installed.
