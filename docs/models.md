# Models, reasoning effort, and token usage

## Model strings

Models are [pydantic-ai](https://ai.pydantic.dev) model strings — `openai:gpt-5.6-sol`,
`openai:gpt-5.6-terra`, `google:gemini-3.7-flash`, etc. — plus the `codex:` and
`claude:` prefixes for [agentic mode](agentic-mode.md) (e.g. `codex:gpt-5.6-sol`,
`claude:opus`).

Note `claude:` is the agentic prefix, distinct from pydantic-ai's own `anthropic:`
provider prefix: `claude:opus` drives the Claude Code CLI over a workspace, while
`anthropic:*` would be a direct API call.

### Vertex AI (`google-cloud:`)

`google-cloud:gemini-3.7-flash` runs the same Google models through Vertex AI with
Google Cloud credentials instead of an API key — a service-account key, or whatever
`gcloud auth application-default login` left behind:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
a2b solve bundle --model google-cloud:gemini-3.7-flash -o answers.json
```

A service-account key names its own project, so that is all it takes. Set
`GOOGLE_CLOUD_PROJECT` to bill a different project (or when using `gcloud` ADC
rather than a key file).

`GOOGLE_CLOUD_LOCATION` picks the region, and defaults to `global` rather than
pydantic-ai's `us-central1`. That region carries the most models by count, but
count is the wrong axis here: on a real project every current Gemini —
`gemini-3.5-flash`, `3.6-flash`, `3.7-flash` — answered 404 in `us-central1` and
resolved on `global`, where new models land first. A wrong region fails loudly
with a 404 naming it, so set the variable if the model you want is regional.

**`GOOGLE_API_KEY` is not an alternative here.** Left to provider inference, a
`google-cloud:` model with an API key in the environment quietly runs on Vertex AI
Express Mode — a different product, and not the credentials you asked for. `a2b`
requires a project instead, which turns that path off, and fails with a message
naming both variables when it cannot find one.

Ingest, solve, and judge models are all independent, so you can extract with one
provider and benchmark another. For unbiased benchmarks, prefer a judge model different
from the taker model.

API keys come from the environment or `.env` (`OPENAI_API_KEY`, `GOOGLE_API_KEY`;
`GOOGLE_APPLICATION_CREDENTIALS` for `google-cloud:*`; `CODEX_API_KEY` or
`codex login` state for `codex:*`; `ANTHROPIC_API_KEY` or `claude` login state for
`claude:*`). The CLI loads `.env` automatically; real environment variables take
precedence.

## Reasoning effort

`ingest`, `solve`, and `grade` accept `--effort minimal|low|medium|high|xhigh|max`:

| Provider | Mapping |
|---|---|
| OpenAI | `reasoning.effort`, passed through directly |
| Google (`google:`, `google-cloud:`) | `thinking_level` (`MINIMAL`/`LOW`/`MEDIUM`/`HIGH`; `xhigh` and `max` collapse to `HIGH`) |
| codex | `model_reasoning_effort` (`max` collapses to `xhigh`) |
| claude | `--effort` (`minimal` collapses to `low`) |

The two agentic backends collapse at opposite ends — codex has no `max`, Claude Code
has no `minimal` — so an `--effort` sweep is only strictly comparable in the
`low`..`xhigh` range they share.

Without the flag, provider defaults apply (OpenAI: `medium`; Gemini: dynamic `HIGH`;
codex and claude: their configured defaults).

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
