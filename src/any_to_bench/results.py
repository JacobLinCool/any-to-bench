"""Publish `a2b bench` results to a Hugging Face dataset repo.

Repo layout, deliberately isomorphic to `hf.py`'s bundle layout and namespaced so
results and bundles can share one repo without colliding:

    <repo_id>/
      README.md                                 # card, marker-managed
      results-index.json                        # catalog; the leaderboard's first fetch
      results-<entry_id>/entry.json             # per-paper rows, fetched lazily
      results-<entry_id>/test-*.parquet         # per-question viewer table
      results-<entry_id>/raw/<subset>/...       # byte-faithful bench artifacts

One **entry** is one taker configuration — a single `(model, effort)` — across N
papers. Adding a contributor's results is copying their `results-*` directories
in and reindexing; nothing existing is rewritten.

Heavy imports (datasets, huggingface_hub) stay inside functions: they read
HF_TOKEN at import time, so they must load after the CLI's load_dotenv().
"""

from __future__ import annotations

import json
import shutil
import statistics
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from any_to_bench import tool_version
from any_to_bench.bundle import ExamBundle
from any_to_bench.hf import (
    _BUNDLE_MARKER,
    _NAME_RE,
    _RESERVED_NAMES,
    HubError,
    _replace_block,
)
from any_to_bench.schemas.bench import BenchReport, BenchRow
from any_to_bench.schemas.report import GradeReport
from any_to_bench.schemas.results import (
    IndexEntry,
    PaperMeta,
    PaperResult,
    PointBucket,
    ResultsEntry,
    ResultsIndex,
    RuleClass,
    TakerIdentity,
    classify_points,
    rule_kinds,
    rule_kinds_from_modes,
)
from any_to_bench.schemas.usage import PhaseUsage, UsageSummary
from any_to_bench.util import read_json, slugify

RESULTS_PREFIX = "results-"
INDEX_FILE = "results-index.json"
ENTRY_FILE = "entry.json"
BENCH_FILE = "bench.json"


class ResultsError(HubError):
    """User-facing publish failure (unloadable runs, mixed configurations, bad id)."""


@dataclass
class LoadedRun:
    """One taker invocation: a bench row plus the grade report it points at."""

    bench_dir: Path
    bench: BenchReport
    row: BenchRow
    grade: GradeReport | None
    subset: str
    bundle: ExamBundle | None = None
    kinds: dict[str, RuleClass] = field(default_factory=dict)
    classification: str = "rule-kind"


# --- Loading -----------------------------------------------------------------


def load_runs(run_dirs: Sequence[Path], *, model: str | None = None) -> list[LoadedRun]:
    """Every bench row under the given directories, with its grade report.

    `bundle_dir` in bench.json is a local path from whoever ran the benchmark, so
    the paper's identity comes from its basename — see resolve_bundles.
    """
    runs: list[LoadedRun] = []
    seen: set[Path] = set()
    for run_dir in run_dirs:
        run_dir = Path(run_dir)
        if not run_dir.exists():
            raise ResultsError(f"no such directory: {run_dir}")
        bench_files = sorted(run_dir.rglob(BENCH_FILE))
        if not bench_files:
            raise ResultsError(f"no {BENCH_FILE} found under {run_dir}")
        for bench_file in bench_files:
            if bench_file in seen:
                continue
            seen.add(bench_file)
            try:
                bench = BenchReport.model_validate(read_json(bench_file))
            except ValueError as e:
                raise ResultsError(f"{bench_file} is not a usable bench report: {e}") from e
            subset = Path(bench.bundle_dir).name
            for row in bench.rows:
                if model is not None and row.model != model:
                    continue
                grade = None
                if row.status == "ok":
                    if not row.report_path:
                        raise ResultsError(f"{bench_file}: row {row.slug} has no report path")
                    report_file = bench_file.parent / row.report_path
                    if not report_file.exists():
                        raise ResultsError(f"missing grade report: {report_file}")
                    try:
                        grade = GradeReport.model_validate(read_json(report_file))
                    except ValueError as e:
                        raise ResultsError(f"{report_file} is not a usable report: {e}") from e
                runs.append(
                    LoadedRun(
                        bench_dir=bench_file.parent,
                        bench=bench,
                        row=row,
                        grade=grade,
                        subset=subset,
                    )
                )
    if not runs:
        raise ResultsError(
            "no runs to publish"
            + (f" for model {model!r}" if model else "")
            + "; check the run directories"
        )
    return runs


def resolve_bundles(
    runs: Sequence[LoadedRun], bundles_root: Path, *, allow_mode_fallback: bool = False
) -> None:
    """Attach each run's bundle, which is what makes the judged/rule split real.

    Without the bundle we can only read `QuestionResult.mode`, which records what
    happened rather than how the question is graded — a judged question nobody
    could grade would be counted as rule-graded. That is a refusal by default.
    """
    bundles_root = Path(bundles_root)
    cache: dict[str, ExamBundle] = {}
    missing: list[str] = []
    for run in runs:
        if run.subset in cache:
            run.bundle = cache[run.subset]
        else:
            # --bundles-root wins, then the path bench.json recorded. Joining an
            # absolute recorded path would silently ignore the flag, so the
            # relocatable form is tried first.
            candidates = (
                bundles_root / run.subset,
                bundles_root / run.bench.bundle_dir,
                Path(run.bench.bundle_dir),
            )
            for candidate in candidates:
                try:
                    bundle = ExamBundle.load(candidate)
                except Exception:  # noqa: BLE001 — any unreadable bundle is a miss
                    continue
                cache[run.subset] = bundle
                run.bundle = bundle
                break
        if run.bundle is None:
            missing.append(run.subset)
            continue
        run.kinds = rule_kinds(run.bundle.grading)
    if missing:
        names = ", ".join(sorted(set(missing)))
        if not allow_mode_fallback:
            raise ResultsError(
                f"could not load the bundle for: {names}\n"
                f"pass --bundles-root pointing at the directory holding them, or "
                "--allow-mode-fallback to classify by outcome instead (less accurate)"
            )
        for run in runs:
            if run.bundle is None and run.grade is not None:
                run.kinds = rule_kinds_from_modes(run.grade)
                run.classification = "mode-fallback"


# --- Aggregation -------------------------------------------------------------


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _mean_bucket(buckets: Sequence[PointBucket]) -> PointBucket:
    if not buckets:
        return PointBucket()
    return PointBucket(
        questions=buckets[0].questions,
        max_points=round(_mean([b.max_points for b in buckets]), 6),
        skipped_points=round(_mean([b.skipped_points for b in buckets]), 6),
        covered_max=round(_mean([b.covered_max for b in buckets]), 6),
        awarded=round(_mean([b.awarded for b in buckets]), 6),
        full_credit=round(_mean([b.full_credit for b in buckets]), 6),
        unanswered=round(_mean([b.unanswered for b in buckets]), 6),
        errored=round(_mean([b.errored for b in buckets]), 6),
        skipped=round(_mean([b.skipped for b in buckets]), 6),
    )


def _mean_usage(usages: Sequence[UsageSummary | None]) -> PhaseUsage | None:
    """Mean per run, rounded. None when no run reported any usage at all —
    'nothing was judged' must not read as 'judging was free'."""
    totals = [u.total for u in usages if u is not None]
    if not totals:
        return None
    return PhaseUsage(
        requests=round(_mean([t.requests for t in totals])),
        input_tokens=round(_mean([t.input_tokens for t in totals])),
        output_tokens=round(_mean([t.output_tokens for t in totals])),
        reasoning_tokens=round(_mean([t.reasoning_tokens for t in totals])),
        cache_read_tokens=round(_mean([t.cache_read_tokens for t in totals])),
        cache_write_tokens=round(_mean([t.cache_write_tokens for t in totals])),
    )


def build_paper_result(runs: Sequence[LoadedRun]) -> PaperResult:
    """All of one configuration's runs on one paper, averaged."""
    first = runs[0]
    ok = [r for r in runs if r.row.status == "ok" and r.grade is not None]
    warnings: list[str] = []
    if len(runs) > 1:
        warnings.append(f"{len(runs)} runs merged; every figure below is their mean")

    det_buckets: list[PointBucket] = []
    judge_buckets: list[PointBucket] = []
    awarded_samples: list[float] = []
    det_samples: list[float] = []
    for run in ok:
        assert run.grade is not None
        buckets = classify_points(run.grade, run.kinds)
        det_buckets.append(buckets["deterministic"])
        judge_buckets.append(buckets["judge"])
        total = buckets["deterministic"].awarded + buckets["judge"].awarded
        awarded_samples.append(round(total, 6))
        det_samples.append(buckets["deterministic"].awarded)

    exam = first.bundle.exam if first.bundle else None
    return PaperResult(
        subset=first.subset,
        exam_id=first.bench.exam_id,
        title=first.bench.title,
        subject=exam.subject if exam else None,
        language=exam.language if exam else "und",
        total_points=first.bench.total_points,
        judge_models=list(first.bench.judge_models),
        runs=len(runs),
        ok_runs=len(ok),
        failed=[r.row.status for r in runs if r.row.status != "ok"],
        deterministic=_mean_bucket(det_buckets),
        judge=_mean_bucket(judge_buckets),
        awarded_samples=awarded_samples,
        det_awarded_samples=det_samples,
        schema_errors=round(_mean([r.row.schema_error_count or 0 for r in ok]), 6),
        multi_judge_questions=round(_mean([r.row.multi_judge_questions or 0 for r in ok]), 6),
        judge_disagreements=round(_mean([r.row.judge_disagreements or 0 for r in ok]), 6),
        judge_mean_spread=(
            round(_mean([r.row.judge_mean_spread or 0.0 for r in ok]), 6) if ok else None
        ),
        solve_secs=round(_mean([r.row.solve_secs or 0.0 for r in ok]), 3) if ok else None,
        grade_secs=round(_mean([r.row.grade_secs or 0.0 for r in ok]), 3) if ok else None,
        solve_usage=_mean_usage([r.row.solve_usage for r in ok]) or PhaseUsage(),
        grade_usage=_mean_usage([r.row.grade_usage for r in ok]),
        classification="mode-fallback" if first.classification == "mode-fallback" else "rule-kind",
        warnings=warnings,
    )


def _is_agentic(model: str) -> bool:
    from any_to_bench.agentic.runner import parse_agentic

    return parse_agentic(model) is not None


def default_entry_id(model: str, effort: str | None) -> str:
    return slugify(f"{model}-{effort or 'default'}")


def build_entry(
    runs: Sequence[LoadedRun],
    *,
    entry_id: str,
    source_repo: str,
    note: str | None = None,
    now: datetime | None = None,
) -> ResultsEntry:
    """One taker configuration's whole result set.

    Refuses a mixed set: a leaderboard row that averaged two efforts together
    would be a number nobody could reproduce.
    """
    configs = {(r.row.model, r.bench.effort) for r in runs}
    if len(configs) > 1:
        listed = ", ".join(f"{m} ({e or 'provider default'})" for m, e in sorted(configs))
        raise ResultsError(
            f"one entry is one taker configuration, but these runs hold {len(configs)}: {listed}\n"
            "publish them separately, or pass --model to select one"
        )
    model, effort = configs.pop()

    by_subset: dict[str, list[LoadedRun]] = {}
    for run in runs:
        by_subset.setdefault(run.subset, []).append(run)
    papers = [build_paper_result(group) for _, group in sorted(by_subset.items())]

    starts = [r.bench.started_at for r in runs]
    ends = [r.bench.finished_at or r.bench.started_at for r in runs]
    return ResultsEntry(
        entry_id=entry_id,
        tool_version=tool_version(),
        source_repo=source_repo,
        taker=TakerIdentity(
            model=model,
            effort=effort,
            agentic=_is_agentic(model),
            repeat=max(r.row.run_index for r in runs),
        ),
        note=note,
        published_at=now or datetime.now(UTC),
        first_run_at=min(starts),
        last_run_at=max(ends),
        papers=papers,
    )


def entry_config_name(entry_id: str) -> str:
    """The repo directory and dataset-viewer config for an entry."""
    return f"{RESULTS_PREFIX}{entry_id}"


def build_index_entry(entry: ResultsEntry) -> IndexEntry:
    papers = entry.papers
    awarded = sum(p.awarded for p in papers)
    covered = sum(p.covered_max for p in papers)
    det_awarded = sum(p.deterministic.awarded for p in papers)
    det_covered = sum(p.deterministic.covered_max for p in papers)
    judges: list[str] = []
    for paper in papers:
        for model in paper.judge_models:
            if model not in judges:
                judges.append(model)
    solve = [p.solve_usage for p in papers]
    grade = [p.grade_usage for p in papers if p.grade_usage is not None]
    return IndexEntry(
        entry_id=entry.entry_id,
        path=f"{entry_config_name(entry.entry_id)}/{ENTRY_FILE}",
        model=entry.taker.model,
        effort=entry.taker.effort,
        agentic=entry.taker.agentic,
        judge_models=judges,
        tool_version=entry.tool_version,
        repeat=entry.taker.repeat,
        published_at=entry.published_at,
        papers=[p.subset for p in papers],
        ok_papers=sum(1 for p in papers if p.ok_runs > 0),
        awarded=round(awarded, 6),
        covered_max=round(covered, 6),
        percentage=round(100.0 * awarded / covered, 4) if covered > 0 else None,
        det_awarded=round(det_awarded, 6),
        det_covered_max=round(det_covered, 6),
        det_percentage=round(100.0 * det_awarded / det_covered, 4) if det_covered > 0 else None,
        solve_input_tokens=sum(u.input_tokens for u in solve),
        solve_output_tokens=sum(u.output_tokens for u in solve),
        solve_reasoning_tokens=sum(u.reasoning_tokens for u in solve),
        solve_cache_read_tokens=sum(u.cache_read_tokens for u in solve),
        grade_input_tokens=sum(u.input_tokens for u in grade),
        grade_output_tokens=sum(u.output_tokens for u in grade),
        solve_secs=round(sum(p.solve_secs or 0.0 for p in papers), 3),
        grade_secs=round(sum(p.grade_secs or 0.0 for p in papers), 3),
        any_mode_fallback=any(p.classification == "mode-fallback" for p in papers),
        note=entry.note,
    )


def build_paper_meta(entry: ResultsEntry, runs: Sequence[LoadedRun]) -> list[PaperMeta]:
    """The picker's view of the corpus, taken from the bundles themselves."""
    bundles = {r.subset: r.bundle for r in runs if r.bundle is not None}
    metas: list[PaperMeta] = []
    for paper in entry.papers:
        bundle = bundles.get(paper.subset)
        parts = paper.subset.split("-")
        judge_questions = 0
        questions = 0
        if bundle is not None:
            questions = len(bundle.grading.questions)
            judge_questions = sum(
                1 for g in bundle.grading.questions.values() if g.rule.kind == "judge"
            )
        metas.append(
            PaperMeta(
                subset=paper.subset,
                source_repo=entry.source_repo,
                title=paper.title,
                subject=paper.subject,
                exam=parts[0] if len(parts) > 1 else None,
                year=parts[1] if len(parts) > 2 and parts[1].isdigit() else None,
                total_points=paper.total_points,
                deterministic_points=paper.deterministic.max_points,
                judge_points=paper.judge.max_points,
                questions=questions,
                judge_questions=judge_questions,
            )
        )
    return metas


def merge_index(
    existing: ResultsIndex | None,
    entry: ResultsEntry,
    papers: Sequence[PaperMeta],
    *,
    now: datetime | None = None,
) -> ResultsIndex:
    """Add or replace one entry. Everything else in the index survives untouched,
    so two people publishing to one repo never clobber each other."""
    entries = [e for e in (existing.entries if existing else []) if e.entry_id != entry.entry_id]
    entries.append(build_index_entry(entry))
    entries.sort(key=lambda e: (-(e.percentage or -1), e.entry_id))

    known = {p.subset: p for p in (existing.papers if existing else [])}
    for meta in papers:
        known[meta.subset] = meta
    repos = list(existing.source_repos if existing else [])
    if entry.source_repo not in repos:
        repos.append(entry.source_repo)
    return ResultsIndex(
        generated_at=now or datetime.now(UTC),
        tool_version=tool_version(),
        source_repos=sorted(repos),
        papers=sorted(known.values(), key=lambda p: p.subset),
        entries=entries,
    )


# --- Per-question rows (the parquet table) -----------------------------------


def build_question_rows(entry: ResultsEntry, runs: Sequence[LoadedRun]) -> list[dict[str, Any]]:
    """One row per (run, question). The taker's prose and the judges' rationales
    stay in raw/**; this table is for slicing, not for reading back."""
    rows: list[dict[str, Any]] = []
    for run in runs:
        if run.grade is None:
            continue
        leaves = {q.id: q for q in run.bundle.exam.iter_leaves()} if run.bundle else {}
        sections = {}
        if run.bundle:
            for section in run.bundle.exam.sections:
                for leaf in section.questions:
                    for q in leaf.iter_leaves():
                        sections[q.id] = section.id
        for qid, result in run.grade.results.items():
            leaf = leaves.get(qid)
            detail = result.detail or {}
            agreement = detail.get("agreement") or {}
            rows.append(
                {
                    "entry_id": entry.entry_id,
                    "model": entry.taker.model,
                    "effort": entry.taker.effort or "",
                    "source_repo": entry.source_repo,
                    "subset": run.subset,
                    "run_index": run.row.run_index,
                    "question_id": qid,
                    "section_id": sections.get(qid, ""),
                    "number": (leaf.number if leaf and leaf.number else qid),
                    "question_type": leaf.type.value if leaf else "",
                    "rule_kind": run.kinds.get(qid, ""),
                    "mode": result.mode,
                    "max_points": result.max_points,
                    "awarded": result.awarded,
                    "ratio": (result.awarded / result.max_points if result.max_points else None),
                    "judge_verdicts": len(result.judge_verdicts),
                    "judge_spread": agreement.get("spread"),
                    "detail_json": json.dumps(detail, ensure_ascii=False, default=str),
                }
            )
    return rows


# --- Dataset card ------------------------------------------------------------

_HEADER_START = "<!-- a2b:results:header:start -->"
_HEADER_END = "<!-- a2b:results:header:end -->"
_BOARD_START = "<!-- a2b:results:board:start -->"
_BOARD_END = "<!-- a2b:results:board:end -->"
SITE_URL = "https://jacoblincool.github.io/any-to-bench/results.html"


def _entry_markers(entry_id: str) -> tuple[str, str]:
    return (
        f"<!-- a2b:results:entry:{entry_id}:start -->",
        f"<!-- a2b:results:entry:{entry_id}:end -->",
    )


def _header_block(repo_id: str) -> str:
    return f"""{_HEADER_START}
Benchmark results produced by **any-to-bench**. One subset here is one *taker
configuration* — a single model at a single reasoning effort — sat against the
exams in another dataset repo. Every row names the exam repo and subset it was
earned against, so results from several corpora, and from several people, can
live side by side.

- `results-index.json` — the catalog: one headline row per configuration
- `results-<entry>/entry.json` — that configuration's per-paper scores
- `results-<entry>/raw/<subset>/` — the byte-faithful `bench.json`, answer sheet
  and grade report behind those scores
- the viewer table — one row per graded question

Explore it as a leaderboard: [{SITE_URL}]({SITE_URL}?repo={repo_id})

```python
from datasets import load_dataset
ds = load_dataset("{repo_id}", "results-<entry>", split="test")
```

## How to read these numbers

- **Judged questions depend on the judge model**, which is named per entry. Two
  configurations graded by different judges are not strictly comparable on their
  judged half; the rule-graded half is deterministic and always comparable.
- **A score is one sample per paper** unless the entry's `repeat` is above 1. The
  run-to-run spread of a single sample is unknown.
- **Input-token counts are not comparable across backends.** `codex:` reports
  cached tokens inside `input_tokens`; `claude:` reports them only under
  `cache_read_tokens`, leaving `input_tokens` near zero. Output tokens and wall
  time are the measures that mean the same thing for every taker; the raw
  per-phase counts are published unaltered so you can judge for yourself.
- **Token counts for agentic takers are approximate**, and wall time depends on
  how many runs shared the machine — see each entry's note.
- Percentages are over what the taker was actually asked. When two entries cover
  different papers, their percentages have different denominators.
{_HEADER_END}"""


def format_board(index: ResultsIndex) -> str:
    """The leaderboard, rebuilt in full every publish.

    Unlike hf.py's per-bundle sections, this block cannot be maintained one row
    at a time: a new entry changes everyone else's rank.
    """
    lines = [
        _BOARD_START,
        "## Leaderboard",
        "",
        "| # | Model | Effort | Papers | Score | % | Rule-graded % "
        "| Solve output tokens | Solve s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, entry in enumerate(index.entries, start=1):
        dagger = "†" if entry.any_mode_fallback else ""
        pct = f"{entry.percentage:.1f}%" if entry.percentage is not None else "–"
        det = f"{entry.det_percentage:.1f}%" if entry.det_percentage is not None else "–"
        lines.append(
            f"| {rank} | `{entry.model}` | {entry.effort or 'default'} | {entry.ok_papers} "
            f"| {entry.awarded:g}/{entry.covered_max:g} | {pct}{dagger} | {det} "
            f"| {entry.solve_output_tokens:,} "
            f"| {entry.solve_secs:,.0f} |"
        )
    if any(e.any_mode_fallback for e in index.entries):
        lines += [
            "",
            "† classified by grading outcome rather than by grading rule, because the "
            "bundle was unavailable at publish time; its judged/rule split is approximate.",
        ]
    lines.append(_BOARD_END)
    return "\n".join(lines)


def _entry_block(entry: ResultsEntry, repo_id: str) -> str:
    start, end = _entry_markers(entry.entry_id)
    judges = sorted({m for p in entry.papers for m in p.judge_models})
    lines = [
        start,
        f"### {entry.entry_id}",
        "",
        "| | |",
        "|---|---|",
        f"| Model | `{entry.taker.model}` |",
        f"| Effort | {entry.taker.effort or 'provider default'} |",
        f"| Papers | {len(entry.papers)} from `{entry.source_repo}` |",
        f"| Judges | {', '.join(f'`{m}`' for m in judges) or '–'} |",
        f"| Runs per paper | {entry.taker.repeat} |",
        f"| Ingested by | any-to-bench {entry.tool_version} |",
        f"| Ran | {entry.first_run_at:%Y-%m-%d} |",
    ]
    if entry.note:
        lines.append(f"| Note | {entry.note} |")
    lines += [
        "",
        "| Paper | Score | % | Rule-graded | Judged |",
        "|---|---|---|---|---|",
    ]
    for paper in entry.papers:
        det = paper.deterministic.percentage
        jud = paper.judge.percentage
        total = paper.covered_max
        pct = f"{100.0 * paper.awarded / total:.1f}%" if total > 0 else "–"
        lines.append(
            f"| `{paper.subset}` | {paper.awarded:g}/{total:g} | {pct} "
            f"| {f'{det:.1f}%' if det is not None else '–'} "
            f"| {f'{jud:.1f}%' if jud is not None else '–'} |"
        )
    lines += [
        "",
        f"`a2b results fetch {repo_id} --entry {entry.entry_id} -o results`",
        end,
    ]
    return "\n".join(lines)


def update_card(
    card: Any, index: ResultsIndex, entry: ResultsEntry, repo_id: str, license: str | None = None
) -> Any:
    """Refresh the header, the whole board, and this entry's section. Other
    entries' sections and any hand-written prose outside the markers survive, as
    does the push_to_hub-managed configs YAML."""
    data = card.data
    if not getattr(data, "pretty_name", None):
        data.pretty_name = f"any-to-bench results — {repo_id.split('/')[-1]}"
    tags = list(getattr(data, "tags", None) or [])
    for tag in ("leaderboard", "evaluation", "benchmark", "any-to-bench"):
        if tag not in tags:
            tags.append(tag)
    data.tags = tags
    if not getattr(data, "task_categories", None):
        data.task_categories = ["question-answering"]
    if license is not None:
        data.license = license

    text = card.text
    text = _replace_block(text, _HEADER_START, _HEADER_END, _header_block(repo_id))
    text = _replace_block(text, _BOARD_START, _BOARD_END, format_board(index))
    start, end = _entry_markers(entry.entry_id)
    text = _replace_block(text, start, end, _entry_block(entry, repo_id))
    card.text = text
    return card


def check_entry_id(entry_id: str) -> None:
    if not _NAME_RE.match(entry_id) or entry_id in _RESERVED_NAMES:
        raise ResultsError(
            f"invalid entry name {entry_id!r}: use letters, digits, '.', '_', '-' "
            "and avoid the reserved names 'data' and 'default'"
        )
    if entry_id.startswith(RESULTS_PREFIX):
        raise ResultsError(
            f"entry name {entry_id!r} already carries the {RESULTS_PREFIX!r} prefix; "
            "pass the bare name — the prefix is added when it is published"
        )


def write_entry_files(entry: ResultsEntry, index: ResultsIndex, out_dir: Path) -> Path:
    """Lay an entry out on disk exactly as it appears in the repo. The publish
    path uploads this; --dry-run stops here."""
    from any_to_bench.util import write_json

    out_dir = Path(out_dir)
    config = entry_config_name(entry.entry_id)
    write_json(out_dir / INDEX_FILE, index)
    write_json(out_dir / config / ENTRY_FILE, entry)
    return out_dir


def copy_raw_artifacts(runs: Sequence[LoadedRun], dest: Path) -> Path:
    """The bench artifacts, byte-faithful, one directory per paper."""
    dest = Path(dest)
    for run in runs:
        target = dest / run.subset
        target.mkdir(parents=True, exist_ok=True)
        names: Iterable[str] = (
            BENCH_FILE,
            *(p for p in (run.row.answers_path, run.row.report_path) if p),
        )
        for name in names:
            source = run.bench_dir / name
            if source.exists():
                shutil.copy2(source, target / Path(name).name)
    return dest


# --- Hub seams: the only functions that talk to the network (faked in tests) ---


def _get_token() -> str | None:
    from huggingface_hub import get_token

    return get_token()


def _push_dataset(dataset: Any, repo_id: str, config_name: str, private: bool) -> None:
    dataset.push_to_hub(repo_id, config_name=config_name, split="test", private=private)


def _upload_folder(**kwargs: Any) -> None:
    from huggingface_hub import HfApi

    HfApi().upload_folder(**kwargs)


def _upload_file(**kwargs: Any) -> None:
    from huggingface_hub import HfApi

    HfApi().upload_file(**kwargs)


def _download_file(repo_id: str, filename: str) -> str | None:
    """Local path of one repo file, or None when it is not there yet."""
    from huggingface_hub import hf_hub_download

    try:
        return hf_hub_download(repo_id=repo_id, filename=filename, repo_type="dataset")
    except Exception:  # noqa: BLE001 — absent (first publish) or transient; treat as absent
        return None


def _list_repo_files(repo_id: str) -> list[str]:
    from huggingface_hub import HfApi

    return HfApi().list_repo_files(repo_id, repo_type="dataset")


def _snapshot_download(**kwargs: Any) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(**kwargs)


def _load_card(repo_id: str) -> Any:
    from huggingface_hub import DatasetCard

    try:
        return DatasetCard.load(repo_id)
    except Exception:  # noqa: BLE001 — no card yet (or transient); start fresh
        return DatasetCard("")


def _push_card(card: Any, repo_id: str) -> None:
    card.push_to_hub(repo_id, repo_type="dataset", commit_message="Update results card")


def _build_dataset(rows: list[dict[str, Any]]) -> Any:
    import datasets

    features = datasets.Features(
        {
            "entry_id": datasets.Value("string"),
            "model": datasets.Value("string"),
            "effort": datasets.Value("string"),
            "source_repo": datasets.Value("string"),
            "subset": datasets.Value("string"),
            "run_index": datasets.Value("int32"),
            "question_id": datasets.Value("string"),
            "section_id": datasets.Value("string"),
            "number": datasets.Value("string"),
            "question_type": datasets.Value("string"),
            "rule_kind": datasets.Value("string"),
            "mode": datasets.Value("string"),
            "max_points": datasets.Value("float64"),
            "awarded": datasets.Value("float64"),
            "ratio": datasets.Value("float64"),
            "judge_verdicts": datasets.Value("int32"),
            "judge_spread": datasets.Value("float64"),
            "detail_json": datasets.Value("string"),
        }
    )
    return datasets.Dataset.from_list(rows, features=features)


def _read_index(repo_id: str) -> ResultsIndex | None:
    path = _download_file(repo_id, INDEX_FILE)
    if path is None:
        return None
    try:
        return ResultsIndex.model_validate(read_json(Path(path)))
    except ValueError as e:
        raise ResultsError(
            f"{repo_id} holds a {INDEX_FILE} this version cannot read: {e}\n"
            "run `a2b results reindex` to rebuild it"
        ) from e


def _verify_source(source_repo: str, subsets: Sequence[str]) -> None:
    """A read before any write: a wrong --source-repo would publish scores that
    point at papers nobody can fetch."""
    files = _list_repo_files(source_repo)
    available = {m.group(1) for f in files if (m := _BUNDLE_MARKER.match(f))}
    unknown = sorted(set(subsets) - available)
    if unknown:
        raise ResultsError(
            f"{source_repo} has no bundle for: {', '.join(unknown)}\n"
            "check --source-repo, or pass --no-verify-source if the papers live elsewhere"
        )


def publish_results(
    run_dirs: Sequence[Path],
    repo_id: str,
    *,
    source_repo: str,
    bundles_root: Path = Path(),
    name: str | None = None,
    model: str | None = None,
    note: str | None = None,
    private: bool = False,
    license: str | None = None,
    allow_mode_fallback: bool = False,
    verify_source: bool = True,
    dry_run: Path | None = None,
) -> str:
    """Publish one taker configuration's results. Everything that can be checked
    without the network is checked first."""
    runs = load_runs(run_dirs, model=model)
    resolve_bundles(runs, bundles_root, allow_mode_fallback=allow_mode_fallback)
    configs = {(r.row.model, r.bench.effort) for r in runs}
    entry_id = name or default_entry_id(*sorted(configs)[0])
    check_entry_id(entry_id)
    entry = build_entry(runs, entry_id=entry_id, source_repo=source_repo, note=note)
    papers = build_paper_meta(entry, runs)
    rows = build_question_rows(entry, runs)
    config = entry_config_name(entry_id)

    if dry_run is not None:
        out = Path(dry_run)
        index = merge_index(None, entry, papers)
        write_entry_files(entry, index, out)
        copy_raw_artifacts(runs, out / config / "raw")
        from any_to_bench.util import write_json

        write_json(out / config / "questions.json", rows)
        return str(out)

    if _get_token() is None:
        raise ResultsError(
            "no Hugging Face token found; set HF_TOKEN in .env or run `hf auth login`"
        )
    if verify_source:
        _verify_source(source_repo, [p.subset for p in entry.papers])

    # push_to_hub goes first: it creates the repo, applies private, and merges
    # this entry's viewer config into the card's YAML.
    _push_dataset(_build_dataset(rows), repo_id, config, private)

    staging = Path(tempfile.mkdtemp(prefix="a2b-results-"))
    try:
        copy_raw_artifacts(runs, staging)
        _upload_folder(
            folder_path=str(staging),
            repo_id=repo_id,
            repo_type="dataset",
            path_in_repo=f"{config}/raw",
            commit_message=f"Upload results {entry_id}",
            delete_patterns=[f"{config}/raw/**"],
        )
        entry_path = staging / ENTRY_FILE
        entry_path.write_text(entry.model_dump_json(indent=2) + "\n", encoding="utf-8")
        _upload_file(
            path_or_fileobj=str(entry_path),
            path_in_repo=f"{config}/{ENTRY_FILE}",
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Update {entry_id} results",
        )
        index = merge_index(_read_index(repo_id), entry, papers)
        index_path = staging / INDEX_FILE
        index_path.write_text(index.model_dump_json(indent=2) + "\n", encoding="utf-8")
        _upload_file(
            path_or_fileobj=str(index_path),
            path_in_repo=INDEX_FILE,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Index {entry_id}",
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    _push_card(update_card(_load_card(repo_id), index, entry, repo_id, license=license), repo_id)
    return f"https://huggingface.co/datasets/{repo_id}"


def reindex_results(repo_id: str) -> ResultsIndex:
    """Rebuild the catalog from every entry in the repo — the recovery path when
    the index drifts, and how someone else's copied-in entries get listed."""
    files = _list_repo_files(repo_id)
    entry_files = sorted(
        f for f in files if f.startswith(RESULTS_PREFIX) and f.endswith(f"/{ENTRY_FILE}")
    )
    if not entry_files:
        raise ResultsError(f"no results entries found in {repo_id}")
    index: ResultsIndex | None = None
    for path in entry_files:
        local = _download_file(repo_id, path)
        if local is None:
            continue
        entry = ResultsEntry.model_validate(read_json(Path(local)))
        papers = [
            PaperMeta(
                subset=p.subset,
                source_repo=entry.source_repo,
                title=p.title,
                subject=p.subject,
                exam=p.subset.split("-")[0] if "-" in p.subset else None,
                total_points=p.total_points,
                deterministic_points=p.deterministic.max_points,
                judge_points=p.judge.max_points,
            )
            for p in entry.papers
        ]
        index = merge_index(index, entry, papers)
    if index is None:
        raise ResultsError(f"could not read any entry from {repo_id}")
    staging = Path(tempfile.mkdtemp(prefix="a2b-results-"))
    try:
        index_path = staging / INDEX_FILE
        index_path.write_text(index.model_dump_json(indent=2) + "\n", encoding="utf-8")
        _upload_file(
            path_or_fileobj=str(index_path),
            path_in_repo=INDEX_FILE,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message="Rebuild results index",
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return index


def fetch_results(repo_id: str, out_dir: Path, *, entry: str | None = None) -> Path:
    """Pull published results back, byte-faithful."""
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ResultsError(f"output directory {out_dir} is not empty")
    files = _list_repo_files(repo_id)
    available = sorted(
        {
            f.split("/")[0][len(RESULTS_PREFIX) :]
            for f in files
            if f.startswith(RESULTS_PREFIX) and "/" in f
        }
    )
    if entry is not None and entry not in available:
        raise ResultsError(
            f"entry {entry!r} not found in {repo_id}; available: {', '.join(available) or '(none)'}"
        )
    patterns = [INDEX_FILE]
    patterns.append(f"{entry_config_name(entry)}/**" if entry else f"{RESULTS_PREFIX}*/**")
    tmp = Path(tempfile.mkdtemp(prefix="a2b-results-"))
    try:
        _snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            allow_patterns=patterns,
            local_dir=str(tmp),
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        for item in tmp.iterdir():
            if item.name.startswith("."):
                continue  # local_dir's .cache/huggingface
            shutil.move(str(item), str(out_dir / item.name))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_dir
