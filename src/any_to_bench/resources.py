"""Byte-faithful public resource corpora and direct-LLM retrieval tools."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from typing import Any

from any_to_bench.schemas.resources import ResourceAccess, ResourceAccessMode, ResourceFile
from any_to_bench.util import sha256_file

RESOURCES_DIR = "resources"
MAX_LIST_LIMIT = 200
MAX_SEARCH_RESULTS = 50
MAX_READ_LINES = 200
MAX_READ_BYTES = 64 * 1024

# These container/media formats can happen to contain only UTF-8 bytes in a
# small fixture (an ASCII-only PDF is valid), but they are not directly
# readable text resources. Office Open XML files are ZIP containers.
_KNOWN_BINARY_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".ico",
    ".heic",
    ".avif",
    ".svg",
    ".eps",
    ".ps",
    ".ai",
}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _safe_resource_path(relative: Path) -> str:
    posix = PurePosixPath(RESOURCES_DIR, *relative.parts).as_posix()
    parsed = PurePosixPath(posix)
    if parsed.is_absolute() or ".." in parsed.parts or parsed.parts[0] != RESOURCES_DIR:
        raise ValueError(f"unsafe resource path: {relative}")
    return posix


def is_utf8_text(path: Path) -> bool:
    """Strict resource text classification used by both ingest and validation."""
    if path.suffix.casefold() in _KNOWN_BINARY_SUFFIXES:
        return False
    data = path.read_bytes()
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    return True


def snapshot_resources(source_dir: Path, bundle_root: Path) -> list[ResourceFile]:
    """Copy one ordinary directory into ``bundle/resources`` without ignore semantics."""
    source_arg = Path(source_dir)
    if source_arg.is_symlink():
        raise ValueError(f"resources directory must not be a symlink: {source_dir}")
    source = source_arg.resolve()
    output = Path(bundle_root).resolve()
    if not source.is_dir():
        raise ValueError(f"resources directory does not exist or is not a directory: {source_dir}")
    if _is_relative_to(output, source) or _is_relative_to(source, output):
        raise ValueError("resources directory and bundle output directory must not overlap")

    files: list[tuple[Path, Path]] = []
    for path in sorted(source.rglob("*"), key=lambda p: p.relative_to(source).as_posix()):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise ValueError(f"resources must not contain symlinks: {relative.as_posix()}")
        if path.is_file():
            files.append((path, relative))
    if not files:
        raise ValueError(f"resources directory contains no regular files: {source_dir}")

    target = output / RESOURCES_DIR
    if target.is_symlink():
        raise ValueError(f"bundle resources target must not be a symlink: {target}")
    if target.exists():
        shutil.rmtree(target)
    entries: list[ResourceFile] = []
    for source_path, relative in files:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        entries.append(
            ResourceFile(
                path=_safe_resource_path(relative),
                sha256=sha256_file(destination),
                size_bytes=destination.stat().st_size,
                text=is_utf8_text(destination),
            )
        )
    return entries


def resource_access(entries: Iterable[ResourceFile], mode: ResourceAccessMode) -> ResourceAccess:
    listed = list(entries)
    if mode == "all_files":
        exposed = listed
    elif mode == "utf8_text_only":
        exposed = [entry for entry in listed if entry.text]
    elif mode == "unknown":
        exposed = []
    else:
        raise ValueError(f"unknown resource access mode: {mode}")
    return ResourceAccess(
        mode=mode,
        total_files=len(listed),
        total_bytes=sum(entry.size_bytes for entry in listed),
        exposed_files=len(exposed),
        exposed_bytes=sum(entry.size_bytes for entry in exposed),
    )


def validate_resource_tree(root: Path, entries: list[ResourceFile]) -> list[str]:
    """Validate the exact resource file set and every recorded byte property."""
    problems: list[str] = []
    resource_root = root / RESOURCES_DIR
    if resource_root.is_symlink():
        return ["resources/ must not be a symlink"]
    if not entries:
        if resource_root.exists():
            extras = [p for p in resource_root.rglob("*") if p.is_file() or p.is_symlink()]
            if extras:
                problems.append("resources/ contains files but manifest.resources is empty")
        return problems
    if not resource_root.is_dir():
        return ["manifest declares resources but resources/ is missing"]

    expected: dict[str, ResourceFile] = {}
    for entry in entries:
        parsed = PurePosixPath(entry.path)
        if (
            parsed.is_absolute()
            or ".." in parsed.parts
            or len(parsed.parts) < 2
            or parsed.parts[0] != RESOURCES_DIR
        ):
            problems.append(f"unsafe resource manifest path: {entry.path!r}")
            continue
        if entry.path in expected:
            problems.append(f"duplicate resource manifest path: {entry.path}")
            continue
        expected[entry.path] = entry

    actual: dict[str, Path] = {}
    for path in sorted(resource_root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            problems.append(f"resource is a symlink: {relative}")
        elif path.is_file():
            actual[relative] = path
    for missing in sorted(set(expected) - set(actual)):
        problems.append(f"missing resource file: {missing}")
    for extra in sorted(set(actual) - set(expected)):
        problems.append(f"unmanifested resource file: {extra}")
    for path in sorted(set(expected) & set(actual)):
        entry, file_path = expected[path], actual[path]
        size = file_path.stat().st_size
        if size != entry.size_bytes:
            problems.append(f"resource {path}: size {size} != manifest {entry.size_bytes}")
        digest = sha256_file(file_path)
        if digest != entry.sha256:
            problems.append(f"resource {path}: sha256 does not match manifest")
        text = is_utf8_text(file_path)
        if text != entry.text:
            problems.append(f"resource {path}: text classification does not match manifest")
    return problems


class ResourceTools:
    """Read-only literal retrieval over the UTF-8 portion of a bundle corpus."""

    def __init__(self, root: Path, entries: Iterable[ResourceFile]) -> None:
        self.root = Path(root)
        self.entries = {entry.path: entry for entry in entries if entry.text}

    def _paths(self, prefix: str = "") -> list[str]:
        return [path for path in sorted(self.entries) if path.startswith(prefix)]

    def list_resources(self, prefix: str = "", offset: int = 0, limit: int = 100) -> dict[str, Any]:
        """List UTF-8 resource paths. Use offset to retrieve the next page."""
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIST_LIMIT}")
        paths = self._paths(prefix)
        page = paths[offset : offset + limit]
        return {
            "paths": page,
            "offset": offset,
            "next_offset": offset + len(page),
            "total": len(paths),
        }

    def search_resources(
        self, query: str, prefix: str = "", max_results: int = 20
    ) -> dict[str, Any]:
        """Case-insensitive literal search returning exact one-line excerpts."""
        if not query:
            raise ValueError("query must not be empty")
        if not 1 <= max_results <= MAX_SEARCH_RESULTS:
            raise ValueError(f"max_results must be between 1 and {MAX_SEARCH_RESULTS}")
        needle = query.casefold()
        matches: list[dict[str, Any]] = []
        for resource_path in self._paths(prefix):
            text = (self.root / resource_path).read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if needle in line.casefold():
                    matches.append({"path": resource_path, "line": line_number, "excerpt": line})
                    if len(matches) >= max_results:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    def read_resource(
        self, path: str, start_line: int = 1, end_line: int | None = None
    ) -> dict[str, Any]:
        """Read at most 200 lines/64 KiB from one exact UTF-8 resource path."""
        if path not in self.entries:
            raise ValueError(f"resource is not available as UTF-8 text: {path!r}")
        if start_line < 1:
            raise ValueError("start_line must be at least 1")
        if end_line is None:
            end_line = start_line + MAX_READ_LINES - 1
        if end_line < start_line or end_line - start_line + 1 > MAX_READ_LINES:
            raise ValueError(f"read range must contain between 1 and {MAX_READ_LINES} lines")
        lines = (self.root / path).read_text(encoding="utf-8").splitlines(keepends=True)
        requested = lines[start_line - 1 : end_line]
        selected_parts: list[str] = []
        selected_bytes = 0
        truncated = False
        for line in requested:
            encoded = line.encode("utf-8")
            remaining = MAX_READ_BYTES - selected_bytes
            if remaining <= 0:
                truncated = True
                break
            if len(encoded) <= remaining:
                selected_parts.append(line)
                selected_bytes += len(encoded)
                continue
            selected_parts.append(encoded[:remaining].decode("utf-8", errors="ignore"))
            truncated = True
            break
        selected = "".join(selected_parts)
        actual_end = min(start_line + len(selected_parts) - 1, len(lines))
        return {
            "path": path,
            "start_line": start_line,
            "end_line": actual_end,
            "text": selected,
            "truncated": truncated,
        }

    def tool_functions(self) -> list[Callable[..., Any]]:
        return [self.list_resources, self.search_resources, self.read_resource]
