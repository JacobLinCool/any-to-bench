# Publishing results (`results publish` / `fetch`)

`bench` scores one bundle. A leaderboard is what happens when those scores are
published somewhere they can accumulate:

```bash
a2b results publish runs/ user/my-results --source-repo user/my-exams --bundles-root .
a2b results fetch user/my-results -o results --entry my-model-high
a2b results reindex user/my-results
```

One **entry** is one taker configuration — a single `(model, effort)` — across
every paper it sat. Two efforts of one model are two entries, because a
leaderboard row that averaged them would be a number nobody could reproduce;
`publish` refuses a mixed set rather than guess.

## Repo layout

Namespaced under `results-`, mirroring the bundle layout of
[`upload`](publish.md) so one repo can hold exams and scores without collision:

```
user/my-results
├── README.md                             # card: header, leaderboard, one section per entry
├── results-index.json                    # the catalog; a leaderboard's first fetch
└── results-<entry>/
    ├── entry.json                        # per-paper rows for this configuration
    ├── test-*.parquet                    # per-question viewer table
    └── raw/<subset>/                     # byte-faithful bench.json, answer sheet, grade report
```

Three grains because three consumers: `results-index.json` is small enough to
draw a whole leaderboard from (one headline row per entry plus a catalog of the
papers), `entry.json` is fetched only for the entries someone selected, and the
parquet exists so the results are browsable on the Hub and reusable elsewhere.

**Merging is copying.** An entry is one directory and one config, so adding
someone else's results means copying their `results-*` directories in and running
`a2b results reindex`. Nothing existing is rewritten, and `results-index.json` is
a cache the reindex can always rebuild.

## What a paper is keyed by

The **subset name in the source repo** — `Path(bench.bundle_dir).name` — never
`exam_id`. The two disagree in 6 of the 21 papers in `JacobLinCool/taiwan-exams`
(`ast-115-history` carries `exam_id: ceec-115-history`), and only the subset name
joins a score back to the exam it was earned against. `--source-repo` is checked
against the Hub before anything is written, so a typo cannot publish scores that
point at papers nobody can fetch.

## Rule-graded and judged points are counted separately

Every paper's score is split by the **grading rule** — `grading.json`'s
`rule.kind` — not by what happened when it was graded. `QuestionResult.mode`
records the outcome: a judged question nobody could grade reads as `error`, and
counting that as rule-graded would inflate the rule-graded share and shrink its
denominator at the same time.

The split is what makes the leaderboard's "rule-graded only" view honest: those
points are scored by program and compare across any two entries, while judged
points depend on the judge model, which is per paper and named per entry.

If a bundle cannot be loaded at publish time, `--allow-mode-fallback` classifies
by outcome instead and stamps the paper `mode-fallback`; the card marks those
rows with a dagger.

## Reading the numbers

- **Coverage.** Scores are over what the taker was actually asked
  (`covered_*`): questions skipped for a missing modality leave the denominator
  rather than scoring zero. Entries covering different papers are not compared —
  the leaderboard drops them from the ranking instead of scoring them on a
  shorter exam.
- **Papers a filter empties.** Some papers have no rule-graded question at all
  (a writing test), and some have no judged question. A filter that empties a
  paper removes it from the selection and says so; it never scores it 0%.
- **Input tokens are not comparable across backends.** `codex:` counts cached
  tokens inside `input_tokens`; `claude:` reports them only under
  `cache_read_tokens`, leaving `input_tokens` near zero. Output tokens and wall
  time mean the same thing for every taker, so those are what the leaderboard
  plots. The raw per-phase counts are published unaltered.
- **One sample unless it was repeated.** `bench --repeat N` publishes N samples
  per paper and a spread is computed from them; without it there is no error bar
  and the leaderboard says so rather than drawing one.
- **Wall time is not machine-independent.** `--note` records what the run shared
  the machine with, and the card prints it beside the entry.

## The leaderboard page

The published layout is what
[the leaderboard](https://jacoblincool.github.io/any-to-bench/results.html)
reads, straight off the CDN — pass `?repo=` to point it at any results dataset,
not only ours. Selections travel in the URL (`papers`, `entries`, `grade`, `avg`,
`x`), so a view can be sent to someone.

Its charts are drawn from `site/src/lib/charts/options.ts`, which the static
renderer calls too:

```bash
cd site && pnpm figures -- --in <fetched results dir> --out ../reports/fig
```

Same option object, same data — a figure in a report and the chart on the page
cannot drift apart.
