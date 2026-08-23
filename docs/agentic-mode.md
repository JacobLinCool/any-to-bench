# Agentic mode (`codex:` / `claude:` / `agy:` models)

Swap any model string for an agentic one — `--model codex:gpt-5.6-sol`,
`--model agy:gemini-3.7-flash-high`, or `--judge-model claude:opus` — and that
phase runs through a CLI coding agent instead of direct LLM calls. Commands, outputs,
and bundle format are identical; only the model string changes.

Three backends are available, selected by prefix:

| | `codex:` | `claude:` | `agy:` |
|---|---|---|---|
| Binary | [`codex`](https://developers.openai.com/codex) ≥ 0.147 | [`claude`](https://claude.ai/code) ≥ 2.1 | [`agy`](https://antigravity.google/docs/cli/install/) ≥ 1.1.17 |
| Install | `npm install -g @openai/codex` | `npm install -g @anthropic-ai/claude-code` | [Antigravity installer](https://antigravity.google/docs/cli/install/) |
| Auth | `codex login` or `CODEX_API_KEY` | `claude` login or `ANTHROPIC_API_KEY` | interactive `agy` login, or its configured API-key provider |
| `--effort` | `model_reasoning_effort` (`max` → `xhigh`) | `--effort` (`minimal` → `low`) | `--effort` (`minimal` → `low`; `xhigh`/`max` → `high`) |
| Timeout env | `ANY_TO_BENCH_CODEX_TIMEOUT` | `ANY_TO_BENCH_CLAUDE_TIMEOUT` | `ANY_TO_BENCH_AGY_TIMEOUT` |

`ANY_TO_BENCH_AGENTIC_TIMEOUT` applies to all three; a backend-specific variable
wins. Model names after the prefix are passed through exactly, so use a slug listed by
that CLI. A bare prefix such as `agy:` is invalid.

## How it works

Each agentic phase:

1. builds a temporary workspace: the raw inputs (no pre-rendering — the agent inspects
   PDFs/photos itself), an `AGENTS.md` contract, and JSON Schemas for the required
   outputs;
2. runs the selected CLI in that workspace, sandboxed and offline;
3. validates the produced files with the same validators as LLM mode, and on failure
   resumes the exact session with the problem list — up to 3 rounds until everything
   passes. If resuming fails, the round is retried once as a fresh session carrying the
   full task and validation context.

All backends share those steps. Codex records the workspace contract in its session,
Claude receives it as an appended system prompt because customizations are disabled,
and AGY discovers the generated `AGENTS.md` from its working directory. AGY resumes
with the explicit conversation ID returned by the previous turn; it never uses the
process-global “most recent conversation.”

## Per-phase behavior

- **`ingest`** — the agent reads the raw materials, extracts every question, creates
  its own figure crops, and writes `exam.json` / `grading.json` / `assets/`;
  `answer_schema.json` and `manifest.json` are still generated deterministically by
  the tool. `--full-page-figures` is a no-op (the agent decides its own crops). The
  agent can note anything ambiguous in an `ingest_warnings.json`, which is folded into
  the manifest warnings.
- **`solve`** — the agent gets `exam.json`, **only the assets the exam references**,
  and, for a [resource-backed benchmark](retrieval.md), the complete public
  `resources/` corpus (never `grading.json`, the manifest, or provenance page renders
  — those could leak the answer key). Resource hashes are checked before and after
  the run; any mutation fails the solve.
- **`grade`** — one batch session per agentic judge model covers all open-ended
  questions; verdicts are validated against a generated per-question schema, then go
  through the same rubric-level snapping and aggregation as LLM judges. Agentic and
  regular judge models can be mixed.

## Antigravity safety profile

AGY headless mode reads its persistent profile from
`~/.gemini/antigravity-cli/settings.json`. Before every model turn, any-to-bench reads
but never edits that file and requires these effective fields:

```json
{
  "toolPermission": "proceed-in-sandbox",
  "allowNonWorkspaceAccess": false,
  "permissions": {
    "allow": []
  }
}
```

Merge these fields into an existing profile; other settings and `permissions.deny` /
`permissions.ask` entries may remain. The file must be valid JSON, and
`permissions.allow` must be absent or empty. The runner also forces `--sandbox`,
`--mode accept-edits`, and `--disable-slash-commands`, then verifies the streamed
`init` event reports the requested working directory, model, and
`proceed-in-sandbox` permission mode.

The runner deliberately never passes `--dangerously-skip-permissions`: AGY has an
[open upstream issue](https://github.com/google-antigravity/antigravity-cli/issues/36)
where combining it with `--sandbox` can approve a request to bypass that sandbox.
Unsafe or missing settings, malformed stream events, a changed conversation ID, or a
non-success result fail the phase; there is no unsafe or text-output fallback.

## Usage accounting

Token usage is tracked per phase (`agentic:ingest`, `agentic:solve`,
`judge:<model string>`) and is approximate; `requests` counts agent turns.

- **`codex:`** — usage comes from the `--json` event stream; input tokens include
  cached input.
- **`claude:`** — the result object reports cache reads and writes separately;
  Anthropic exposes no separate reasoning-token count here, so it remains zero.
- **`agy:`** — each result reports cumulative `num_turns` and token counters for the
  conversation. The fix loop records the first snapshot, then only the non-negative
  delta for each resumed turn. `thinking_tokens` become reasoning tokens and cache
  reads remain separate. A fresh-session retry resets the cumulative baseline.

## Isolation and trust

- **`codex:`** uses `-s workspace-write`, restricting writes to the workspace and
  disabling agent-initiated network access.
- **`claude:`** uses `--safe-mode`, ignores user/project settings, and receives an
  explicit sandbox with workspace-only writes, no allowed network domains, and
  `failIfUnavailable: true`.
- **`agy:`** forces its native sandbox and requires non-workspace access to be off.
  Empty persistent allow rules leave web, MCP, and unsandboxed actions unapproved in
  headless mode.

Exam materials are still untrusted instructions processed by a powerful agent. Codex
and Claude's sandboxes restrict writes and network tools but do not prevent reading
every host file available to the current user; AGY is run with the stricter
non-workspace-access restriction. Review untrusted source materials before ingestion
and inspect generated bundles before publishing them.

The solve workspace's root contract also treats every file under `resources/` as
untrusted data: agents must not follow instructions found there, execute corpus code,
or modify it. Corpus-local `AGENTS.md` and `CLAUDE.md` files are data, not replacements
for the harness contract.
