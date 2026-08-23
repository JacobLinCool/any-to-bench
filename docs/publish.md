# Publishing bundles to Hugging Face (`upload` / `download`)

```bash
a2b upload out/bundle user/my-exams --name matha           # public by default
a2b download user/my-exams --name matha -o local/bundle    # byte-faithful reverse
```

One dataset repo holds many bundles. Each bundle is a top-level subdirectory whose
name doubles as the **dataset-viewer subset** name:

```
user/my-exams (dataset repo)
├── README.md                       # configs: one viewer subset per bundle
├── matha/
│   ├── test-00000-of-00001.parquet # per-question table, images embedded
│   └── bundle/                     # the raw bundle, byte-faithful
│       ├── exam.json / answer_schema.json / grading.json / manifest.json
│       ├── assets/**
│       └── resources/**                # optional public solver corpus
└── english/
    ├── test-*.parquet
    └── bundle/...
```

The viewer table has one row per leaf question — id, printed number, type, points,
composite-parent context, prompt (Markdown), options, blanks/matching, grading rule
kind — with the question's figures **embedded as images** so they render as
thumbnails in the viewer.

## Semantics

- `--name` defaults to the bundle directory's name (slugified). It is the bundle's
  identity in the repo: re-uploading the same name is an **in-place update** (stale
  parquet shards and deleted raw files are removed in the same commit); a different
  name adds a new subset. The names `data` and `default` are reserved.
- Upload refuses an invalid bundle (`validate` runs first). Download validates after
  fetching and exits 1 on problems (files are kept for inspection).
- `download` without `--name` auto-selects when the repo has exactly one bundle;
  otherwise it lists the available names.
- The raw `bundle/` files round-trip byte-faithfully; the parquet table is derived,
  never read back.
- Arbitrarily nested `resources/` files round-trip with the rest of the bundle. The
  card publishes total files/bytes and direct-text coverage and labels the entire
  folder as public solver input.

## The dataset card

`upload` also maintains the repo's README: YAML metadata (`pretty_name`, `language`,
`tags`, `task_categories`; `--license <id>` sets a license — exam content copyright
stays with the original publisher, so none is set by default) plus a generated body —
a usage section (download/solve/grade + `load_dataset`), an answer-key warning, and
one section per bundle with auto-computed stats (question counts, auto-graded vs
LLM-judged, type breakdown, total points, ingest provenance, source hashes).

Generated blocks live between `<!-- a2b:...:start/end -->` markers: re-uploading a
bundle rewrites only its own section, and anything you write outside the markers is
preserved. `pretty_name` is set only when absent (from the first uploaded exam's
title) — edit it freely on the Hub; uploads won't clobber it.

`--no-copyright-note` drops the "exam content copyright belongs to the original
publisher" line from the header — useful when you own the material or say it
elsewhere. Unlike a hand edit on the Hub, which the next upload overwrites, the flag
survives *that* upload — but the header block is rebuilt in full every time, so pass
it on **every** upload to the repo or the line comes back.

## Auth and visibility

- Token: `HF_TOKEN` in `.env` (or environment), or the cached `hf auth login` state.
- **Repos are public by default** — note that a bundle includes `grading.json`, i.e.
  the full answer key and rubrics. Publishing it makes the answers public and feeds
  future training corpora (benchmark contamination). Use `--private` if that
  matters; the flag only takes effect when the repo is first created (flip
  visibility later in the repo settings on the Hub).
- A resource-backed bundle publishes every file selected by `--resources`, including
  hidden, ignored, answer-like, or secret files. No upload-time exclusion is applied.
- The dataset viewer on **private** repos requires a PRO account or a Team/Enterprise
  organization; public repos get the viewer for free.

## Results are published the same way

Scores live in their own namespace (`results-*`) with the same shape: a derived
viewer table beside the byte-faithful artifact. One repo can hold exams and
scores without collision — see [Publishing results](results.md).
