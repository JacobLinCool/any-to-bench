# How ingestion works (LLM mode)

Ingestion is the phase where spending is worth it: the bundle it produces is a
reusable dataset, so extraction accuracy is amortized across every future solve and
grade run. Prefer strong models (or [agentic mode](agentic-mode.md)) here — and
extract everything gradable (keys, point values, rubrics, scoring rules) into
`grading.json` now, so grading later needs as little model intelligence as possible.

`ingest` accepts any mix of PDFs and photos for one exam. **Feed it everything you
have** — question booklet, answer key, worked solutions, scoring guidelines, and the
blank answer sheet: open-ended answer formats (answer grids, graph paper) and
exam-wide scoring rules often appear only in the last two. In LLM mode (a regular
`openai:*` / `google:*` model string), every input is rasterized to page images (PDFs
via pypdfium2 at ~200 DPI, photos normalized via Pillow), then a multimodal model runs
a multi-pass pipeline:

1. **Inventory** — classify each page: questions / answer key / solutions / rubric /
   other. Pages are sent as downscaled thumbnails so even long exams fit one request.
2. **Question extraction** — chunked over question pages (4 pages per chunk, 1 page of
   overlap); verbatim Markdown + LaTeX, tables as structured blocks, figures located by
   bounding box with written descriptions. Chunks are merged and deduplicated by
   printed question number, then a **gap-repair round** detects missing question
   numbers (group-question ranges and sub-question numbers count as present) and
   re-extracts just those from the pages around the gap — the dominant failure mode of
   chunked extraction. The inventory's "questions 1 to N" reading extends detection to
   questions lost at the very end; anything still missing is recorded as a warning.
3. **Figure cropping** — each referenced figure is cropped out of the page raster into
   `assets/` (degenerate boxes fall back to the full page image; `--full-page-figures`
   forces that).
4. **Answers/rubric extraction** — correct options, accepted blank answers, matching
   pairs, model solutions, rubric criteria with point levels, grading instructions —
   aligned to the extracted questions by printed number.
5. **Assembly + validation** — grading rules per question; anything ambiguous is
   recorded in `manifest.json` warnings (e.g. a fixed-answer question with no key falls
   back to LLM-judge grading; a question with no printed point value defaults to 1).

The rendered source pages are kept under `assets/pages/` as provenance.

For the agentic alternative (a `codex:` model string), see
[Agentic mode](agentic-mode.md).
