# Models, reasoning effort, and token usage

## Model strings

Models are [pydantic-ai](https://ai.pydantic.dev) model strings — `openai:gpt-5.6-sol`,
`openai:gpt-5.6-terra`, `google:gemini-3.7-flash`, etc. — plus the `codex:` prefix for
[agentic mode](agentic-mode.md) (e.g. `codex:gpt-5.6-sol`).

Ingest, solve, and judge models are all independent, so you can extract with one
provider and benchmark another. For unbiased benchmarks, prefer a judge model different
from the taker model.

API keys come from the environment or `.env` (`OPENAI_API_KEY`, `GOOGLE_API_KEY`;
`CODEX_API_KEY` or `codex login` state for `codex:*`). The CLI loads `.env`
automatically; real environment variables take precedence.

## Reasoning effort

`ingest`, `solve`, and `grade` accept `--effort minimal|low|medium|high|xhigh|max`:

| Provider | Mapping |
|---|---|
| OpenAI | `reasoning.effort`, passed through directly |
| Google | `thinking_level` (`MINIMAL`/`LOW`/`MEDIUM`/`HIGH`; `xhigh` and `max` collapse to `HIGH`) |
| codex | `model_reasoning_effort` (`max` collapses to `xhigh`) |

Without the flag, provider defaults apply (OpenAI: `medium`; Gemini: dynamic `HIGH`;
codex: its configured default).

## Token usage

Every command reports token usage — input, output, reasoning/thinking, and cache
tokens, per phase and in total:

- `ingest` → `manifest.json` `usage` (LLM mode phases: `inventory` / `extract` /
  `answers`; agentic: `agentic:ingest`)
- `solve` → `answers.json` `usage` (what the taker spent — part of the benchmark
  record)
- `grade` → `report.json` `usage` (per judge model)

and prints a summary line, e.g.
`Tokens: 48,231 in / 12,094 out (reasoning 8,310) over 14 request(s)`.
A fully deterministic grade makes zero LLM calls and reports no usage. Agentic-mode
numbers are approximate (see [Agentic mode](agentic-mode.md)).
