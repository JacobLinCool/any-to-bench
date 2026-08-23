"""Offline agentic ingest: a fake runner plants a bundle for validation."""

import pytest

import any_to_bench.agentic.runner as runner_module
from any_to_bench.agentic.ingest import _bundle_problems
from any_to_bench.agentic.runner import AgenticError
from any_to_bench.bundle import validate_bundle
from any_to_bench.ingest.pipeline import run_ingest
from any_to_bench.util import sha256_file, write_json
from tests.conftest import FakeAgenticRun, build_tiny_exam, build_tiny_grading, make_png


def _write_bundle(workspace, with_grading=True, warnings_list=None):
    staging = workspace / "bundle"
    write_json(staging / "exam.json", build_tiny_exam())
    if with_grading:
        write_json(staging / "grading.json", build_tiny_grading())
    make_png(staging / "assets" / "q1-fig1.png")
    if warnings_list is not None:
        write_json(staging / "ingest_warnings.json", warnings_list)


def _source(tmp_path):
    src = tmp_path / "exam.pdf"
    src.write_bytes(b"%PDF-1.4 fake exam booklet")
    return src


def test_agentic_ingest_happy_path(tmp_path, monkeypatch):
    src = _source(tmp_path)
    out = tmp_path / "out"
    seen: dict = {}

    def writer(workspace):
        seen["input"] = sorted(p.name for p in (workspace / "input").iterdir())
        seen["schemas"] = sorted(p.name for p in (workspace / "schemas").iterdir())
        seen["agents_md"] = (workspace / "AGENTS.md").exists()
        _write_bundle(workspace, warnings_list=["points not printed for q3"])

    fake = FakeAgenticRun([writer])
    monkeypatch.setattr(runner_module, "run_codex", fake)

    bundle = run_ingest([src], out, model="codex:test")

    assert seen["input"] == ["01-exam.pdf"]  # originals staged verbatim, no pre-rendering
    assert seen["schemas"] == ["exam.schema.json", "grading.schema.json"]
    assert seen["agents_md"]
    assert validate_bundle(out) == []
    assert bundle.manifest.ingest_model == "codex:test"
    assert bundle.manifest.sources[0].sha256 == sha256_file(src)
    assert "points not printed for q3" in bundle.manifest.warnings
    assert bundle.manifest.usage is not None
    assert set(bundle.manifest.usage.phases) == {"agentic:ingest"}
    assert (out / "assets" / "q1-fig1.png").exists()
    assert not (out / "ingest_warnings.json").exists()
    assert fake.calls[0]["cli_model"] == "test"


def test_agentic_ingest_fix_loop(tmp_path, monkeypatch):
    src = _source(tmp_path)
    out = tmp_path / "out"
    fake = FakeAgenticRun(
        [
            lambda ws: _write_bundle(ws, with_grading=False),
            lambda ws: _write_bundle(ws),
        ]
    )
    monkeypatch.setattr(runner_module, "run_codex", fake)

    bundle = run_ingest([src], out, model="codex:test")

    assert validate_bundle(out) == []
    assert len(fake.calls) == 2
    assert fake.calls[1]["resume_session_id"] == "sess-1"
    assert "missing file: grading.json" in fake.calls[1]["prompt"]
    assert any("agentic ingest round 1" in w for w in bundle.manifest.warnings)


def test_agentic_ingest_exhaustion_raises(tmp_path, monkeypatch):
    src = _source(tmp_path)
    fake = FakeAgenticRun([])  # never writes anything
    monkeypatch.setattr(runner_module, "run_codex", fake)

    with pytest.raises(AgenticError, match="workspace kept"):
        run_ingest([src], tmp_path / "out", model="codex:test")
    assert len(fake.calls) == 3


def test_full_page_figures_is_noop_with_warning(tmp_path, monkeypatch):
    src = _source(tmp_path)
    monkeypatch.setattr(runner_module, "run_codex", FakeAgenticRun([_write_bundle]))

    bundle = run_ingest([src], tmp_path / "out", model="codex:test", full_page_figures=True)
    assert any("full-page-figures" in w for w in bundle.manifest.warnings)


def test_bundle_problems_rejects_escaping_assets(tmp_path):
    staging = tmp_path / "bundle"
    outside = tmp_path / "outside.png"
    make_png(outside)
    exam = build_tiny_exam()
    # An absolute asset path that EXISTS: validate_bundle's existence check
    # passes it, so only the path-escape hardening can catch it.
    exam.sections[0].questions[0].prompt[1].asset = str(outside)
    write_json(staging / "exam.json", exam)
    write_json(staging / "grading.json", build_tiny_grading())

    problems = _bundle_problems(staging)
    assert any("must be a relative path" in p for p in problems)
