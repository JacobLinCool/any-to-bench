# Judge reliability study

The experiment behind the paper *Grading Needs a Rubric, Not Intelligence*
(`report/paper.tex`; build it with the commands below). It tests the asymmetry any-to-bench is built on: a
frontier model extracts questions and rubrics once at ingestion, and small
models do all the grading.

Six configurations (GPT-5.6 Luna and Claude Sonnet 5, each at low, medium,
and high reasoning effort) wrote answers to 24 open-ended questions from the
[taiwan-exams](https://huggingface.co/datasets/JacobLinCool/taiwan-exams)
corpus, then graded all eight answer sheets (six writers plus two anchors)
three times each: 144 grading passes, 3,456 verdicts. Two ablations then
re-graded the twelve stratum-C/D questions with the rubric's criteria
stripped (key only) and with the official answer stripped as well (zero
guidance): 96 further passes, 1,152 further verdicts.

## Layout

| Path | What it is |
|---|---|
| `reports24/` | the 144 main-study grading reports, one per (sheet, judge, repeat) |
| `reports_ab/`, `reports_bare/` | the 48+48 ablation reports (key only; zero guidance) |
| `study24-answers-*.json` | the eight answer sheets that were graded |
| `ablate12-answers-*.json`, `ablate12bare-answers-*.json` | the same sheets filtered to the 12 ablated questions |
| `build_ablate.py` | derives the ablation bundles from the study24 bundle |
| `analyse_ablate.py`, `figures_ablate.py` | the three-condition ablation analysis and figure |
| `provenance-study24.json` | where each of the 24 questions came from, and its stratum |
| `study24-anchor-notes.json` | which questions publish no official answer |
| `study24.py` | loads the reports and prints the headline statistics |
| `asymmetry.py` | the effort-dial and variance-decomposition analysis |
| `figures24.py`, `figures_paper.py` | draw the paper's figures into `report/fig/` |
| `report/` | `paper.tex` and `data.csv` (one row per verdict) |

## Regenerating

Every number and figure comes from `reports24/`:

Figure PDFs and the paper PDF are build artifacts and are not committed; the
figure scripts must run before the paper compiles.

```sh
uv run --with matplotlib python study24.py        # statistics
uv run --with matplotlib python asymmetry.py      # asymmetry cuts
uv run --with matplotlib python figures24.py      # figures 1, 3, 4
uv run --with matplotlib python figures_paper.py  # figures 2, 5 + data.csv numbers
cd report && latexmk -pdf paper.tex
```

The grading itself was run with `a2b grade` using `codex:gpt-5.6-luna` and
`claude:claude-sonnet-5` as judges; the raw (pre-snap) verdicts in the
reports require any-to-bench with pre-snap recording (commit `7bde6f8` or
later).
