# Agentic mode (`codex:` / `claude:` models)

Swap any model string for an agentic one — `--model codex:gpt-5.6-sol`,
`--judge-model claude:opus` — and that phase runs **agentically** through a CLI coding
agent instead of direct LLM calls. Commands, outputs, and bundle format are identical;
only the model string changes.

Two backends are available, selected by the prefix:

| | `codex:` | `claude:` |
|---|---|---|
| Binary | [`codex`](https://developers.openai.com/codex) ≥ 0.147 | [`claude`](https://claude.ai/code) ≥ 2.1 |
| Install | `npm install -g @openai/codex` | `npm install -g @anthropic-ai/claude-code` |
| Auth | `codex login` state or `CODEX_API_KEY` | `claude` login state or `ANTHROPIC_API_KEY` |
| `--effort` | `model_reasoning_effort` (`max` → `xhigh`) | `--effort` (`minimal` → `low`) |
| Timeout env | `ANY_TO_BENCH_CODEX_TIMEOUT` | `ANY_TO_BENCH_CLAUDE_TIMEOUT` |

`ANY_TO_BENCH_AGENTIC_TIMEOUT` applies to both; a backend-specific variable wins.

## How it works

Each agentic phase:

1. builds a temporary workspace: the raw inputs (no pre-rendering — the agent inspects
   PDFs/photos itself), an `AGENTS.md` contract, and JSON Schemas for the required
   outputs;
2. runs the agent in that workspace, sandboxed and offline;
3. validates the produced files with the same validators as LLM mode, and on failure
   resumes the session with the exact problem list — up to 3 rounds until everything
   passes. If resuming a session fails, the round is retried once as a fresh session
   carrying the full context.

Both backends share every step above; only the subprocess invocation differs. `AGENTS.md`
is the single contract file for both — the `claude:` backend passes its contents as
`--append-system-prompt` rather than relying on auto-discovery, since it runs with
customizations disabled.

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
- **`grade`** — one batch session per agentic judge model covers all open-ended
  questions; verdicts are validated against a generated per-question schema, then go
  through the same rubric-level snapping and aggregation as LLM judges. Agentic and
  regular judge models can be mixed.

## Usage accounting

Token usage is tracked per phase (`agentic:ingest`, `agentic:solve`,
`judge:<model string>`) but is approximate: `requests` counts agent turns. For
`codex:` it comes from the `--json` event stream and input tokens include cached
tokens; for `claude:` it comes from the run's result object, where cache reads and
writes are reported separately. Anthropic reports no separate reasoning-token count,
so `claude:` phases record zero rather than guessing.

## Isolation

Both backends run confined, by different mechanisms:

- **`codex:`** — `-s workspace-write`, which restricts writes to the workspace and
  disables network access.
- **`claude:`** — `--safe-mode` (no `CLAUDE.md`, skills, plugins, hooks, or MCP servers
  from your machine leak into a benchmark run), `--setting-sources ""`, and an explicit
  sandbox passed via `--settings`: writes confined to the workspace, `allowedDomains: []`
  for network, and `failIfUnavailable: true`.

  That last flag matters: `claude -p` **silently ignores settings that fail validation**,
  so without it a misconfigured sandbox would look identical to a working one. The
  permission mode is `acceptEdits`, which auto-approves file edits but *not* Bash —
  Bash is auto-approved only by `autoAllowBashIfSandboxed`, which fires only while the
  sandbox is live. So if the sandbox is unavailable the agent loses its shell and the
  run fails loudly instead of quietly continuing unconfined.

## Trust note

Exam materials are untrusted input processed by an agent that can run shell commands.

Both sandboxes restrict **writes** to the temp workspace and block **network access**.
Neither restricts **reads** — the agent can read any file your user account can,
including credentials in your home directory. Reading alone cannot exfiltrate anything
(there is no network), but an agent following instructions hidden in exam materials
could copy what it reads into the bundle it writes. Review materials from sources you
don't trust before ingesting them, and review a bundle before publishing it.
