"""Publish and fetch exam bundles to/from Hugging Face dataset repos.

Repo layout: one dataset repo holds many bundles; each bundle is one top-level
subdirectory whose name doubles as the dataset-viewer subset (config) name:

    <repo_id>/
      README.md                      # configs: managed by push_to_hub
      <name>/test-*.parquet          # per-question viewer table, images embedded
      <name>/bundle/...              # the byte-faithful raw bundle

Heavy imports (datasets, huggingface_hub) stay inside functions: they read
HF_TOKEN at import time, so they must load after the CLI's load_dotenv().
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from any_to_bench.bundle import ExamBundle, validate_bundle
from any_to_bench.schemas.content import (
    ContentBlock,
    ImageBlock,
    TableBlock,
    TextBlock,
    table_to_markdown,
)
from any_to_bench.solve.render import leaf_context
from any_to_bench.util import slugify

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RESERVED_NAMES = {"data", "default"}  # push_to_hub reserves both
_BUNDLE_MARKER = re.compile(r"([^/]+)/bundle/exam\.json$")


class HubError(RuntimeError):
    """User-facing upload/download failure (bad bundle, missing token, bad name)."""


def _blocks_to_markdown(blocks: list[ContentBlock]) -> str:
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            parts.append(block.markdown)
        elif isinstance(block, ImageBlock):
            marker = f"[Figure: {block.alt}]"
            if block.caption:
                marker += f" ({block.caption})"
            parts.append(marker)
        elif isinstance(block, TableBlock):
            parts.append(table_to_markdown(block))
    return "\n\n".join(p for p in parts if p)


def _collect_images(block_groups: list[list[ContentBlock]]) -> tuple[list[str], list[str]]:
    """Image assets + alts in document order, deduped by first occurrence.

    Deliberately not workspace.question_assets(): that returns an unordered set
    and does not include composite-ancestor context.
    """
    images: list[str] = []
    alts: list[str] = []
    seen: set[str] = set()
    for blocks in block_groups:
        for block in blocks:
            if isinstance(block, ImageBlock) and block.asset not in seen:
                seen.add(block.asset)
                images.append(block.asset)
                alts.append(block.alt)
    return images, alts


def build_question_rows(bundle: ExamBundle) -> list[dict[str, Any]]:
    """One dataset-viewer row per leaf question, in document order.

    The images column holds bundle-relative asset paths; upload_bundle
    absolutizes them before embedding.
    """
    rows: list[dict[str, Any]] = []
    for section in bundle.exam.sections:
        for top in section.questions:
            for leaf in top.iter_leaves():
                ancestors = leaf_context(top, leaf.id)
                block_groups = [a.prompt for a in ancestors] + [leaf.prompt]
                for option in leaf.options or []:
                    block_groups.append(option.content)
                if leaf.matching:
                    for item in leaf.matching.left + leaf.matching.right:
                        block_groups.append(item.content)
                images, alts = _collect_images(block_groups)

                matching = ""
                if leaf.matching:
                    left = " ".join(
                        f"[{i.id}] {_blocks_to_markdown(i.content)}" for i in leaf.matching.left
                    )
                    right = " ".join(
                        f"[{i.id}] {_blocks_to_markdown(i.content)}" for i in leaf.matching.right
                    )
                    matching = f"Left: {left}\nRight: {right}"
                grading = bundle.grading.questions.get(leaf.id)
                rows.append(
                    {
                        "id": leaf.id,
                        "number": leaf.number or leaf.id,
                        "section_id": section.id,
                        "section_title": section.title,
                        "type": leaf.type.value,
                        "points": leaf.points,
                        "context": "\n\n".join(_blocks_to_markdown(a.prompt) for a in ancestors),
                        "prompt": _blocks_to_markdown(leaf.prompt),
                        "options": [
                            f"({o.id}) {_blocks_to_markdown(o.content)}"
                            for o in (leaf.options or [])
                        ],
                        "blanks": [
                            b.id + (f" {b.label}" if b.label else "")
                            for b in (leaf.blanks or [])
                        ],
                        "matching": matching,
                        "grading": grading.rule.kind if grading else "",
                        "images": images,
                        "image_alts": alts,
                    }
                )
    return rows


# --- Dataset card generation ---

_HEADER_START = "<!-- a2b:header:start -->"
_HEADER_END = "<!-- a2b:header:end -->"


def _section_markers(name: str) -> tuple[str, str]:
    return f"<!-- a2b:bundle:{name}:start -->", f"<!-- a2b:bundle:{name}:end -->"


def _replace_block(text: str, start: str, end: str, block: str) -> str:
    """Replace the marked block in text, or append it; text outside markers is kept."""
    if start in text and end in text:
        before = text.split(start, 1)[0]
        after = text.split(end, 1)[1]
        return before + block + after
    return (text.rstrip() + "\n\n" + block + "\n").lstrip("\n")


def _header_block(repo_id: str) -> str:
    return f"""{_HEADER_START}
Machine-gradable exam benchmarks produced by **any-to-bench**. Each subset is one
exam: the viewer table shows one row per answerable question (figures embedded);
the raw, byte-faithful bundle lives under `<subset>/bundle/` — `exam.json`
(structured paper), `answer_schema.json` (strict JSON Schema an answer sheet must
satisfy), `grading.json` (deterministic rules + judge rubrics), `manifest.json`
(provenance), and `assets/` (figures).

## Usage

Benchmark any model against an exam:

```bash
a2b download {repo_id} --name <subset> -o bundle
a2b solve bundle --model <your-model> -o answers.json
a2b grade bundle answers.json -o report.json
```

Or load the question table directly:

```python
from datasets import load_dataset
ds = load_dataset("{repo_id}", "<subset>", split="test")
```

## ⚠️ Answer key included

`<subset>/bundle/grading.json` contains the full answer key and scoring rubrics.
If you benchmark models against this dataset, keep it out of training corpora.

*Exam content copyright belongs to the original exam publisher.*
{_HEADER_END}"""


def _bundle_block(name: str, bundle: ExamBundle, repo_id: str) -> str:
    start, end = _section_markers(name)
    exam = bundle.exam
    leaves = list(exam.iter_leaves())
    judge = sum(
        1 for qg in bundle.grading.questions.values() if qg.rule.kind == "judge"
    )
    types: dict[str, int] = {}
    for leaf in leaves:
        types[leaf.type.value] = types.get(leaf.type.value, 0) + 1
    type_summary = ", ".join(f"{t} ×{n}" for t, n in sorted(types.items(), key=lambda x: -x[1]))
    manifest = bundle.manifest
    sources = "<br>".join(
        f"`{Path(s.path).name}` `sha256:{s.sha256[:12]}…`" for s in manifest.sources
    )
    lines = [
        start,
        f"## {name} — {exam.title}",
        "",
        "| | |",
        "|---|---|",
    ]
    if exam.subject:
        lines.append(f"| Subject | {exam.subject} |")
    lines += [
        f"| Language | {exam.language} |",
        f"| Questions | {len(leaves)} ({len(leaves) - judge} auto-graded, {judge} LLM-judged) |",
        f"| Total points | {exam.total_points:g} |",
        f"| Question types | {type_summary} |",
    ]
    if manifest.ingest_model:
        lines.append(
            f"| Ingested by | `{manifest.ingest_model}` (any-to-bench {manifest.tool_version}) |"
        )
    lines.append(f"| Created | {manifest.created_at:%Y-%m-%d} |")
    if sources:
        lines.append(f"| Sources | {sources} |")
    lines += [
        "",
        f"`a2b download {repo_id} --name {name} -o bundle`",
        end,
    ]
    return "\n".join(lines)


def update_card(card: Any, name: str, bundle: ExamBundle, repo_id: str,
                license: str | None = None) -> Any:
    """Refresh the header and this bundle's section; other sections and any
    hand-written text outside the markers are preserved, as is the
    push_to_hub-managed configs YAML."""
    data = card.data
    if not getattr(data, "pretty_name", None):
        data.pretty_name = bundle.exam.title
    lang = bundle.exam.language.split("-")[0].lower()
    existing_lang = getattr(data, "language", None)
    languages = existing_lang if isinstance(existing_lang, list) else (
        [existing_lang] if existing_lang else []
    )
    if lang and lang not in languages:
        data.language = [*languages, lang]
    tags = list(getattr(data, "tags", None) or [])
    for tag in ("exam", "benchmark", "any-to-bench"):
        if tag not in tags:
            tags.append(tag)
    data.tags = tags
    if not getattr(data, "task_categories", None):
        data.task_categories = ["question-answering"]
    if license is not None:
        data.license = license

    text = card.text
    text = _replace_block(text, _HEADER_START, _HEADER_END, _header_block(repo_id))
    start, end = _section_markers(name)
    text = _replace_block(text, start, end, _bundle_block(name, bundle, repo_id))
    card.text = text
    return card


# --- Hub seams: the only functions that talk to the network (faked in tests) ---


def _get_token() -> str | None:
    from huggingface_hub import get_token

    return get_token()


def _push_dataset(dataset: Any, repo_id: str, config_name: str, private: bool) -> None:
    dataset.push_to_hub(repo_id, config_name=config_name, split="test", private=private)


def _upload_folder(**kwargs: Any) -> None:
    from huggingface_hub import HfApi

    HfApi().upload_folder(**kwargs)


def _snapshot_download(**kwargs: Any) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(**kwargs)


def _list_repo_files(repo_id: str) -> list[str]:
    from huggingface_hub import HfApi

    return HfApi().list_repo_files(repo_id, repo_type="dataset")


def _load_card(repo_id: str) -> Any:
    from huggingface_hub import DatasetCard

    try:
        return DatasetCard.load(repo_id)
    except Exception:  # noqa: BLE001 — no card yet (or transient); start fresh
        return DatasetCard("")


def _push_card(card: Any, repo_id: str) -> None:
    card.push_to_hub(repo_id, repo_type="dataset", commit_message="Update dataset card")


def _build_dataset(bundle: ExamBundle) -> Any:
    import datasets

    rows = build_question_rows(bundle)
    for row in rows:
        row["images"] = [str(bundle.asset_path(a)) for a in row["images"]]
    list_feature = getattr(datasets, "List", None) or datasets.Sequence
    features = datasets.Features(
        {
            "id": datasets.Value("string"),
            "number": datasets.Value("string"),
            "section_id": datasets.Value("string"),
            "section_title": datasets.Value("string"),
            "type": datasets.Value("string"),
            "points": datasets.Value("float64"),
            "context": datasets.Value("string"),
            "prompt": datasets.Value("string"),
            "options": list_feature(datasets.Value("string")),
            "blanks": list_feature(datasets.Value("string")),
            "matching": datasets.Value("string"),
            "grading": datasets.Value("string"),
            "images": list_feature(datasets.Image()),
            "image_alts": list_feature(datasets.Value("string")),
        }
    )
    return datasets.Dataset.from_list(rows, features=features)


def upload_bundle(
    bundle_dir: Path,
    repo_id: str,
    *,
    name: str | None = None,
    private: bool = False,
    license: str | None = None,
) -> str:
    """Publish one bundle: viewer table (embedded images), raw files, dataset card."""
    bundle_dir = Path(bundle_dir)
    problems = validate_bundle(bundle_dir)
    if problems:
        raise HubError(
            "refusing to upload an invalid bundle:\n"
            + "\n".join(f"- {p}" for p in problems[:10])
        )
    name = name or slugify(bundle_dir.resolve().name)
    if not _NAME_RE.match(name) or name in _RESERVED_NAMES:
        raise HubError(
            f"invalid bundle name {name!r}: use letters, digits, '.', '_', '-' "
            "and avoid the reserved names 'data' and 'default'"
        )
    if _get_token() is None:
        raise HubError(
            "no Hugging Face token found; set HF_TOKEN in .env or run `hf auth login`"
        )

    bundle = ExamBundle.load(bundle_dir)
    dataset = _build_dataset(bundle)
    # push_to_hub goes first: it creates the repo (applying the private flag)
    # and merges this bundle's viewer config into the dataset card.
    _push_dataset(dataset, repo_id, name, private)
    _upload_folder(
        folder_path=str(bundle_dir),
        repo_id=repo_id,
        repo_type="dataset",
        path_in_repo=f"{name}/bundle",
        commit_message=f"Upload bundle {name}",
        delete_patterns=[f"{name}/bundle/**"],
    )
    card = update_card(_load_card(repo_id), name, bundle, repo_id, license=license)
    _push_card(card, repo_id)
    return f"https://huggingface.co/datasets/{repo_id}"


def download_bundle(repo_id: str, out_dir: Path, *, name: str | None = None) -> Path:
    """Fetch one bundle's raw files back into out_dir (byte-faithful)."""
    out_dir = Path(out_dir)
    files = _list_repo_files(repo_id)
    available = sorted({m.group(1) for f in files if (m := _BUNDLE_MARKER.match(f))})
    if name is None:
        if not available:
            raise HubError(f"no bundles found in {repo_id}")
        if len(available) > 1:
            raise HubError(
                f"{repo_id} holds several bundles; pass --name, one of: "
                + ", ".join(available)
            )
        name = available[0]
    elif name not in available:
        raise HubError(
            f"bundle {name!r} not found in {repo_id}; available: "
            + (", ".join(available) or "(none)")
        )
    if out_dir.exists() and any(out_dir.iterdir()):
        raise HubError(f"output directory {out_dir} is not empty")

    tmp = Path(tempfile.mkdtemp(prefix="a2b-hf-"))
    try:
        _snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            allow_patterns=[f"{name}/bundle/*"],
            local_dir=str(tmp),
        )
        src = tmp / name / "bundle"
        if not src.is_dir():
            raise HubError(f"download produced no {name}/bundle directory")
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        if out_dir.exists():
            out_dir.rmdir()  # empty (checked above); move needs the target absent
        shutil.move(str(src), str(out_dir))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # discards local_dir's .cache/huggingface
    return out_dir
