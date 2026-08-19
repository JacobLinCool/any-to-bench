# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

User-specified: pnpm + TypeScript + Svelte, DaisyUI for components, Lucide for
icons. Ships as a static site on GitHub Pages — no server, no build-time data.
It must live in its own directory (`site/`, not `docs/`, which already holds the
project's Markdown documentation) with a GitHub Actions Pages workflow.

## Users

Two audiences, confirmed as equally important:

1. **People running LLM evaluations** — researchers and engineers who want an
   existing benchmark to point a model at. Their job: find a real exam, see what
   it contains, and get the commands that score a model against it.
2. **People with exam material of their own** — teachers, institutions, and
   users in other countries holding PDFs or photos. Their job: understand what
   `ingest` accepts and what it produces before installing anything.

A third, narrower use: anyone who has published an a2b bundle and wants a way to
look at it, or show it to someone, without cloning a repo.

## Product Purpose

any-to-bench (`a2b`) turns any exam material — exam PDFs, photos of papers,
official answer keys, marking schemes — into a machine-gradable benchmark. One
exam becomes a *bundle*: the structured exam, a strict answer-sheet JSON Schema
any LLM harness can target, and a grading spec. Fixed-answer questions grade as
pure scripts with no model calls; open-ended ones go to LLM judges constrained by
rubrics extracted from the source material.

The site succeeds when a visitor from either audience understands what a bundle
is and leaves with the next command to run.

## Positioning

The mechanism a neighboring tool could not truthfully copy: **intelligence is
spent once at ingest and converted into structure, so that grading needs almost
none, forever.** The three phases have deliberately asymmetric goals — ingest
spends freely for exactness, solve is unconstrained because it is the thing being
measured, and grade is engineered to require as little intelligence as possible
and to be bit-for-bit reproducible.

## Operating Context

- `a2b` is a terminal tool. Its real workflow is `ingest → validate → solve →
  grade → bench`, plus `upload` / `download` against Hugging Face datasets.
- Ingest can run agentically through the Codex or Claude Code CLI (`codex:` /
  `claude:` model strings), which is slow and expensive by design.
- A published dataset repo holds many bundles; each bundle is one top-level
  directory whose name doubles as the dataset-viewer subset name.
- The viewer page reads bundles straight from Hugging Face's `resolve` endpoint
  and discovers subsets from `/api/datasets/{repo}/tree/main`. Both were verified
  to send permissive CORS headers. The `datasets-server` rows API is deliberately
  **not** used: it is a lossy flattened view of the same data and returns 500
  when its queue is busy.

## Capabilities and Constraints

- A bundle is four JSON files plus assets: `exam.json` (structured paper),
  `grading.json` (answer key, rules, judge rubrics), `answer_schema.json` (strict
  JSON Schema an answer sheet must satisfy), `manifest.json` (provenance,
  ingest warnings, token usage), `assets/` (figures).
- Question types: single_choice, multiple_choice, true_false, fill_in_blank,
  matching, short_answer, essay, drawing, and composite (a shared stimulus with
  nested sub-questions). Content blocks are text (Markdown, math as LaTeX),
  image, or table.
- Grading rule kinds: choice, per_option, true_false, fill_in_blank, matching,
  judge. `manifest.json` records ingest warnings verbatim — including the places
  the source material itself was ambiguous or defective.
- **Static-only constraints:** private datasets are out of reach (a token cannot
  be shipped in a static page); the site depends on Hugging Face's CORS policy,
  which is outside our control; anonymous HF API requests are rate-limited.
- **Never render a hash in the interface.** Source `sha256` digests and any
  other checksum stay in the bundle files, where verification tools read them.
  On screen they are unreadable noise that buys a human reader nothing. This is
  a standing constraint, not a preference to revisit per surface.
- Terminology to use consistently: *bundle*, *subset*, *ingest*, *solve*,
  *grade*, *bench*, *judge*, *rubric*, *answer sheet*.

## Brand Commitments

- Name: **any-to-bench**, CLI alias `a2b`. Both are used; `a2b` is what people
  type.
- Site language: **English throughout**, matching the README, docs, and PyPI
  page. Exam content itself renders in its original language (mostly Traditional
  Chinese today), so the viewer must set the content language per bundle from
  `exam.json`'s `language` field rather than assume English.
- Existing voice (README, docs): plain, technical, unhyped. States mechanisms and
  trade-offs rather than benefits. No marketing superlatives.

## Evidence on Hand

Real, verifiable, and already public — nothing here needs inventing:

- **`JacobLinCool/taiwan-exams`** — 182 exams, 7,772 questions, all across the
  same three years (113–115). Three Taiwanese university-entrance exams — 學測
  GSAT (21 subsets), 分科測驗 AST (23), 統測 TVE (120), ingested with
  `codex:gpt-5.6-sol` — plus 會考 CAP (18), the exam at the end of junior high,
  ingested with `claude:claude-opus-5`.
- Per-bundle statistics are computable live from the bundles themselves:
  question counts, auto-graded vs LLM-judged split, type breakdown, total points,
  and provenance — the names of the official source documents a bundle was built
  from, the ingest model, the tool version, and the date. (The manifest also
  carries source `sha256` digests; those are for verification tooling and are
  never shown in the interface.)
- `manifest.json` warnings contain genuinely interesting material — cases where
  the official answer key was amended, a question was voided, or a marking scheme
  contradicted itself.
- The repo's own README, `docs/*.md`, and the PyPI package are existing copy.
- **`JacobLinCool/taiwan-exams-results`** — the first published scores: ten
  taker configurations (`codex:gpt-5.6-luna` and `claude:claude-sonnet-5` at
  low/medium/high/xhigh, plus `codex:gpt-5.6-sol` and `claude:claude-opus-5` at
  low) over all 21 papers of the 115 year, 1,748 points apiece. Rule-graded and
  judged points are published separately, so the program-scored half can be
  compared without trusting a judge. Cost and score do not move together: the
  two low-effort frontier models score 95.0% and 95.6% for a fraction of the
  output tokens the highest-effort runs spend.
- **Absent, do not fabricate:** user testimonials, adoption numbers, funding or
  affiliation claims. Scores exist only for the 115 papers and only for those
  ten configurations, one run each — there is no error bar to quote.

## Product Principles

1. **Show the artifact, don't describe it.** The strongest argument for the tool
   is a real bundle rendered on screen. Prefer real data over illustration.
2. **The viewer serves any dataset, not just ours.** It takes a repo id as input
   and works for anyone's published a2b bundle; taiwan-exams is the default
   example, not a hard-coded assumption.
3. **Two front doors, one product.** A visitor who wants to *use* a benchmark and
   one who wants to *make* one must both find their path from the landing page.
4. **Honest about cost and limits.** Ingest is expensive and agentic; some
   questions have no official answer key. The existing voice states such things
   plainly, and the site must not start hiding them.
5. **Every claim is checkable.** Numbers come from the published dataset; commands
   are ones that actually run.

## Accessibility & Inclusion

No product-specific standard was established. General web baseline applies, with
one product-driven requirement: exam content mixes Traditional Chinese prose,
LaTeX math, and figures, so the viewer must carry correct `lang` attributes and
meaningful alternative text — bundles already store an `alt` description for
every image, and it should be used rather than discarded.
