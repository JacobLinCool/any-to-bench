"""Workspace construction for agentic runs.

Each run gets a fresh temp directory holding `workspace/` (the agent's working
root) and `control/` (files the agent writes for us but must not see, e.g. the
last-message capture).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

from any_to_bench.schemas.content import ImageBlock
from any_to_bench.schemas.exam import Exam, Question


def new_workspace(kind: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"any2bench-{kind}-"))
    workspace = root / "workspace"
    workspace.mkdir()
    return workspace


def cleanup_workspace(workspace: Path) -> None:
    """Remove the workspace and its control dir; no-op if the user wants to keep it."""
    if os.environ.get("ANY_TO_BENCH_KEEP_WORKSPACE"):
        return
    shutil.rmtree(workspace.parent, ignore_errors=True)


def write_agents_md(workspace: Path, content: str) -> None:
    (workspace / "AGENTS.md").write_text(content, encoding="utf-8")


def stage_inputs(inputs: list[Path], workspace: Path) -> None:
    """Copy the original input files verbatim into workspace/input/."""
    input_dir = workspace / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    for i, path in enumerate(inputs, start=1):
        shutil.copy2(path, input_dir / f"{i:02d}-{path.name}")


def _iter_question_blocks(question: Question) -> Iterable:
    stack = [question]
    while stack:
        q = stack.pop()
        yield from q.prompt
        for option in q.options or []:
            yield from option.content
        if q.matching:
            for item in q.matching.left + q.matching.right:
                yield from item.content
        stack.extend(q.children)


def question_assets(question: Question) -> set[str]:
    """All image assets referenced by one question (including its children)."""
    return {b.asset for b in _iter_question_blocks(question) if isinstance(b, ImageBlock)}


def collect_exam_assets(exam: Exam) -> set[str]:
    """All image assets referenced by the exam's visible content.

    Deliberately excludes everything else in the bundle (grading references,
    provenance page renders): a solver workspace built from this set cannot
    leak the answer key.
    """
    assets: set[str] = set()
    for section in exam.sections:
        assets.update(b.asset for b in section.instructions if isinstance(b, ImageBlock))
        for question in section.questions:
            assets.update(question_assets(question))
    return assets


def copy_assets(bundle_root: Path, assets: Iterable[str], dest_root: Path) -> None:
    """Copy bundle-relative asset files under dest_root, preserving paths."""
    for asset in sorted(set(assets)):
        src = bundle_root / asset
        if not src.is_file():
            continue  # validate/report paths surface missing assets; don't crash here
        dest = dest_root / asset
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
