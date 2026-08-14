# Agentic mode (`codex:` models)

Swap any model string for a `codex:` one — `--model codex:gpt-5.6-sol`,
`--judge-model codex:gpt-5.6-sol` — and that phase runs **agentically** through the
[Codex CLI](https://developers.openai.com/codex) instead of direct LLM calls. Commands,
outputs, and bundle format are identical; only the model string changes.

## How it works

Each agentic phase:

1. builds a temporary workspace: the raw inputs (no pre-rendering — the agent inspects
   PDFs/photos itself), an `AGENTS.md` contract, and JSON Schemas for the required
   outputs;
2. runs `codex exec` in that workspace (`workspace-write` sandbox, no network);
3. validates the produced files with the same validators as LLM mode, and on failure
   resumes the session with the exact problem list — up to 3 rounds until everything
   passes. If resuming a session fails, the round is retried once as a fresh session
   carrying the full context.

## Requirements

The `codex` binary on PATH (≥ 0.147) and Codex auth — either `codex login` state or
`CODEX_API_KEY` in `.env`.

## Per-phase behavior

- **`ingest`** — the agent reads the raw materials, extracts every question, creates
  its own figure crops, and writes `exam.json` / `grading.json` / `assets/`;
  `answer_schema.json` and `manifest.json` are still generated deterministically by
  the tool. `--full-page-figures` is a no-op (the agent decides its own crops). The
  agent can note anything ambiguous in an `ingest_warnings.json`, which is folded into
  the manifest warnings.
- **`solve`** — the agent gets `exam.json` plus **only the assets the exam references**
  (never `grading.json`, the manifest, or provenance page renders — those could leak
  the answer key) and writes an answer sheet conforming to the bundle's answer schema.
- **`grade`** — one batch codex session per `codex:` judge model covers all open-ended
  questions; verdicts are validated against a generated per-question schema, then go
  through the same rubric-level snapping and aggregation as LLM judges. `codex:` and
  regular judge models can be mixed.

## Usage accounting

Token usage is tracked from codex's `--json` event stream (phases `agentic:ingest`,
`agentic:solve`, `judge:codex:*`) but is approximate: `requests` counts agent turns,
and input tokens include cached tokens.

`--effort` maps to codex `model_reasoning_effort` (`max` collapses to `xhigh`).

## Environment knobs

- On failure the workspace is kept and its path printed; set
  `ANY_TO_BENCH_KEEP_WORKSPACE=1` to always keep it.
- `ANY_TO_BENCH_CODEX_TIMEOUT` (seconds, default 3600) bounds each codex invocation.

## Trust note

Exam materials are untrusted input processed by an agent that can run shell commands.
The sandbox restricts writes to the temp workspace and blocks network access, but
review materials from sources you don't trust.
