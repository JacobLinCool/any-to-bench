"""Publishing bench results: the classification join, and the Hub seams."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import any_to_bench.results as results_module
from any_to_bench.grade.aggregate import run_grade
from any_to_bench.modality import TEXT_ONLY
from any_to_bench.results import ResultsError, publish_results
from any_to_bench.schemas.results import (
    ResultsIndex,
    classify_points,
    rule_kinds,
    rule_kinds_from_modes,
)
from tests.conftest import imperfect_sheet, perfect_sheet


def test_classification_uses_rule_kind_not_mode(tiny_bundle):
    """The whole feature rests on this join.

    No judge is faked, so every judged question fails and lands at mode='error'.
    Bucketing by grading rule keeps the exam's 10 + 7 split; bucketing by mode
    would count the judged points as deterministic and report 10/10 (100%)
    instead of 10/17 (58.8%).
    """
    report = run_grade(tiny_bundle, perfect_sheet())
    assert [r.mode for r in report.results.values()].count("error") == 3

    buckets = classify_points(report, rule_kinds(tiny_bundle.grading))
    assert buckets["deterministic"].max_points == 10.0
    assert buckets["deterministic"].awarded == 10.0
    assert buckets["deterministic"].full_credit == 5
    assert buckets["judge"].max_points == 7.0
    assert buckets["judge"].awarded == 0.0
    assert buckets["judge"].errored == 3
    assert buckets["deterministic"].awarded + buckets["judge"].awarded == 10.0
    assert buckets["deterministic"].covered_max + buckets["judge"].covered_max == 17.0

    by_mode = classify_points(report, rule_kinds_from_modes(report))
    assert by_mode["deterministic"].max_points == 17.0  # the bug this guards against
    assert by_mode["judge"].max_points == 0.0


def test_unanswered_judge_questions_stay_judged(tiny_bundle):
    """Same trap, the other outcome: an unattempted judged question is still a
    judged question, and its points still belong in the judged denominator."""
    report = run_grade(tiny_bundle, imperfect_sheet())
    buckets = classify_points(report, rule_kinds(tiny_bundle.grading))
    assert buckets["judge"].max_points == 7.0
    assert buckets["judge"].unanswered == 3
    assert buckets["judge"].awarded == 0.0
    assert buckets["deterministic"].awarded == 3.5


def test_skipped_points_leave_the_denominator(tiny_bundle):
    """A question the taker was never equipped for is not a wrong answer.

    q1 carries a figure, so a text-only taker never sees it and submits no
    answer; its points must leave the denominator rather than score zero.
    """
    sheet = perfect_sheet()
    del sheet.answers["q1"]
    report = run_grade(tiny_bundle, sheet, capabilities=TEXT_ONLY)
    buckets = classify_points(report, rule_kinds(tiny_bundle.grading))
    skipped = sum(b.skipped for b in buckets.values())
    assert skipped > 0, "the fixture's image question should be out of reach for a text-only taker"
    for bucket in buckets.values():
        assert bucket.covered_max == pytest.approx(bucket.max_points - bucket.skipped_points)
    covered = sum(b.covered_max for b in buckets.values())
    assert covered == pytest.approx(report.covered_max)


def test_percentage_is_none_when_nothing_was_asked(tiny_bundle):
    """A paper with no judged questions has not scored 0% on its judged half."""
    report = run_grade(tiny_bundle, imperfect_sheet())
    buckets = classify_points(report, rule_kinds(tiny_bundle.grading))
    buckets["judge"].covered_max = 0.0
    assert buckets["judge"].percentage is None
    assert buckets["deterministic"].percentage == pytest.approx(35.0)


# --- Publishing: the seams, faked exactly as tests/test_hf.py fakes hf.py's ---


def make_bench_dir(tiny_bundle, out_dir, monkeypatch, *, effort=None, model="test:solver"):
    """A real bench run over the tiny bundle, offline."""
    import any_to_bench.solve.runner as runner_module
    from any_to_bench.bench import run_bench
    from tests.conftest import fake_build_agent
    from tests.test_solve_offline import PERFECT_OUTPUTS

    monkeypatch.setattr(runner_module, "build_agent", fake_build_agent(PERFECT_OUTPUTS))
    run_bench(tiny_bundle, [model], out_dir, effort=effort)
    return out_dir


class Seams:
    """Records calls to the results seams in order."""

    def __init__(self, monkeypatch, token="tok", files=None, index=None, card_content=""):
        self.calls: list[tuple[str, dict]] = []
        self.files = files if files is not None else ["bundle/bundle/exam.json"]
        self.index = index
        self.card_content = card_content
        monkeypatch.setattr(results_module, "_get_token", lambda: token)
        monkeypatch.setattr(
            results_module,
            "_push_dataset",
            lambda dataset, repo_id, config_name, private: self.calls.append(
                ("push", {"dataset": dataset, "config_name": config_name, "private": private})
            ),
        )
        monkeypatch.setattr(
            results_module, "_upload_folder", lambda **kw: self.calls.append(("upload_folder", kw))
        )
        monkeypatch.setattr(results_module, "_upload_file", self._upload_file)
        monkeypatch.setattr(results_module, "_list_repo_files", lambda repo_id: self.files)
        monkeypatch.setattr(results_module, "_read_index", lambda repo_id: self.index)
        monkeypatch.setattr(results_module, "_load_card", self._load_card)
        monkeypatch.setattr(
            results_module,
            "_push_card",
            lambda card, repo_id: self.calls.append(("push_card", {"card": card})),
        )

    def _upload_file(self, **kw):
        # The real seam reads the file during the call; the staging directory is
        # gone by the time a test asserts, so capture the bytes here too.
        kw["content"] = Path(kw["path_or_fileobj"]).read_text()
        self.calls.append(("upload_file", kw))

    def _load_card(self, repo_id):
        from huggingface_hub import DatasetCard

        return DatasetCard(self.card_content)

    def uploaded(self, path_in_repo):
        """The most recent upload of that path — the repo's current state."""
        for name, kw in reversed(self.calls):
            if name == "upload_file" and kw["path_in_repo"] == path_in_repo:
                return json.loads(kw["content"])
        raise AssertionError(f"{path_in_repo} was never uploaded")


def test_publish_happy_path(tiny_bundle, tmp_path, monkeypatch):
    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    seams = Seams(monkeypatch, files=[f"{tiny_bundle.root.name}/bundle/exam.json"])

    url = publish_results(
        [bench_dir],
        "user/results",
        source_repo="user/exams",
        bundles_root=tiny_bundle.root.parent,
    )

    assert url == "https://huggingface.co/datasets/user/results"
    assert [c[0] for c in seams.calls] == [
        "push",  # creates the repo before anything is written into it
        "upload_folder",
        "upload_file",  # entry.json
        "upload_file",  # results-index.json
        "push_card",
    ]
    push = seams.calls[0][1]
    assert push["config_name"] == "results-test-solver-default"
    assert push["dataset"].num_rows == 8  # one row per graded question
    folder = seams.calls[1][1]
    assert folder["path_in_repo"] == "results-test-solver-default/raw"
    assert folder["delete_patterns"] == ["results-test-solver-default/raw/**"]

    entry = seams.uploaded("results-test-solver-default/entry.json")
    assert entry["taker"]["model"] == "test:solver"
    assert entry["taker"]["effort"] is None  # provider default is its own configuration
    assert len(entry["papers"]) == 1
    paper = entry["papers"][0]
    assert paper["subset"] == tiny_bundle.root.name
    assert paper["deterministic"]["max_points"] == 10.0
    assert paper["judge"]["max_points"] == 7.0

    index = seams.uploaded("results-index.json")
    assert [e["entry_id"] for e in index["entries"]] == ["test-solver-default"]
    assert index["entries"][0]["det_percentage"] == 100.0


@pytest.mark.parametrize(
    "name, message",
    [
        ("results-oops", "already carries"),
        ("default", "invalid entry name"),
    ],
)
def test_publish_rejects_a_bad_entry_name_before_any_network_call(
    tiny_bundle, tmp_path, monkeypatch, name, message
):
    """Everything checkable offline is checked before the first request."""
    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    seams = Seams(monkeypatch)

    with pytest.raises(ResultsError, match=message):
        publish_results(
            [bench_dir],
            "user/results",
            source_repo="user/exams",
            bundles_root=tiny_bundle.root.parent,
            name=name,
        )
    assert seams.calls == []


def test_publish_refuses_when_the_bundle_is_gone(tiny_bundle, tmp_path, monkeypatch):
    """Without the bundle the judged/rule split can only be guessed from outcomes,
    so the refusal is the point — --allow-mode-fallback is the explicit override."""
    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    shutil.move(str(tiny_bundle.root), str(tmp_path / "moved-away"))
    seams = Seams(monkeypatch)

    with pytest.raises(ResultsError, match="could not load the bundle"):
        publish_results(
            [bench_dir],
            "user/results",
            source_repo="user/exams",
            bundles_root=tmp_path / "nowhere",
        )
    assert seams.calls == []

    publish_results(
        [bench_dir],
        "user/results",
        source_repo="user/exams",
        bundles_root=tmp_path / "nowhere",
        allow_mode_fallback=True,
        verify_source=False,
    )
    entry = seams.uploaded("results-test-solver-default/entry.json")
    assert entry["papers"][0]["classification"] == "mode-fallback"
    index = seams.uploaded("results-index.json")
    assert index["entries"][0]["any_mode_fallback"] is True


def test_publish_refuses_a_mixed_configuration(tiny_bundle, tmp_path, monkeypatch):
    """One entry is one taker configuration; averaging two efforts into a single
    leaderboard row would be a number nobody could reproduce."""
    make_bench_dir(tiny_bundle, tmp_path / "bench/low", monkeypatch, effort="low")
    make_bench_dir(tiny_bundle, tmp_path / "bench/high", monkeypatch, effort="high")
    seams = Seams(monkeypatch)

    with pytest.raises(ResultsError, match="one entry is one taker configuration"):
        publish_results(
            [tmp_path / "bench"],
            "user/results",
            source_repo="user/exams",
            bundles_root=tiny_bundle.root.parent,
        )
    assert seams.calls == []


def test_publish_verifies_the_source_repo_before_writing(tiny_bundle, tmp_path, monkeypatch):
    """A wrong --source-repo would publish scores pointing at papers nobody can fetch."""
    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    seams = Seams(monkeypatch, files=["some-other-exam/bundle/exam.json"])

    with pytest.raises(ResultsError, match="has no bundle for"):
        publish_results(
            [bench_dir],
            "user/results",
            source_repo="user/exams",
            bundles_root=tiny_bundle.root.parent,
        )
    assert [c[0] for c in seams.calls] == []  # the listing is a read, not a write


def test_subset_name_is_the_directory_not_the_exam_id(tiny_bundle, tmp_path, monkeypatch):
    """The two disagree in 6 of the 21 published 115 papers, and only the
    directory name joins a score back to the exam repo it was earned against."""
    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    seams = Seams(monkeypatch, files=[f"{tiny_bundle.root.name}/bundle/exam.json"])

    publish_results(
        [bench_dir], "user/results", source_repo="user/exams", bundles_root=tiny_bundle.root.parent
    )

    paper = seams.uploaded("results-test-solver-default/entry.json")["papers"][0]
    assert tiny_bundle.exam.exam_id == "tiny-exam"
    assert paper["subset"] == tiny_bundle.root.name != tiny_bundle.exam.exam_id
    assert paper["exam_id"] == "tiny-exam"  # kept, but only as provenance


def test_index_merge_keeps_other_entries(tiny_bundle, tmp_path, monkeypatch):
    """Two contributors publishing into one repo must not clobber each other."""
    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    seams = Seams(monkeypatch, files=[f"{tiny_bundle.root.name}/bundle/exam.json"])
    common = {
        "source_repo": "user/exams",
        "bundles_root": tiny_bundle.root.parent,
    }

    publish_results([bench_dir], "user/results", name="first", **common)
    seams.index = ResultsIndex.model_validate(seams.uploaded("results-index.json"))
    publish_results([bench_dir], "user/results", name="second", **common)

    index = seams.uploaded("results-index.json")
    assert sorted(e["entry_id"] for e in index["entries"]) == ["first", "second"]
    assert len(index["papers"]) == 1  # the same paper, not duplicated

    # Re-publishing an existing entry updates it in place rather than adding a row.
    seams.index = ResultsIndex.model_validate(index)
    publish_results([bench_dir], "user/results", name="second", **common)
    again = seams.uploaded("results-index.json")
    assert sorted(e["entry_id"] for e in again["entries"]) == ["first", "second"]


def test_card_rebuilds_the_board_and_keeps_foreign_prose(tiny_bundle, tmp_path, monkeypatch):
    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    seams = Seams(
        monkeypatch,
        files=[f"{tiny_bundle.root.name}/bundle/exam.json"],
        card_content="Hand-written notes that must survive.\n",
    )

    publish_results(
        [bench_dir], "user/results", source_repo="user/exams", bundles_root=tiny_bundle.root.parent
    )

    card = seams.calls[-1][1]["card"]
    assert "Hand-written notes that must survive." in card.text
    assert "## Leaderboard" in card.text
    assert "test-solver-default" in card.text
    assert "leaderboard" in card.data.tags


def test_board_ranks_every_entry_on_each_publish(tiny_bundle, tmp_path, monkeypatch):
    """A ranking cannot be maintained one row at a time: a new entry moves
    everyone else, so the board block is regenerated whole."""
    from any_to_bench.results import format_board

    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    seams = Seams(monkeypatch, files=[f"{tiny_bundle.root.name}/bundle/exam.json"])
    common = {"source_repo": "user/exams", "bundles_root": tiny_bundle.root.parent}

    publish_results([bench_dir], "user/results", name="alpha", **common)
    seams.index = ResultsIndex.model_validate(seams.uploaded("results-index.json"))
    publish_results([bench_dir], "user/results", name="beta", **common)

    board = format_board(ResultsIndex.model_validate(seams.uploaded("results-index.json")))
    ranks = [line.split("|")[1].strip() for line in board.splitlines() if line.startswith("| ")]
    assert [r for r in ranks if r.isdigit()] == ["1", "2"]
    assert "alpha" not in board  # the board names models, not entry ids
    assert board.count("`test:solver`") == 2


def test_dry_run_writes_the_repo_layout_and_touches_no_seam(tiny_bundle, tmp_path, monkeypatch):
    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    seams = Seams(monkeypatch)
    out = tmp_path / "dry"

    publish_results(
        [bench_dir],
        "user/results",
        source_repo="user/exams",
        bundles_root=tiny_bundle.root.parent,
        dry_run=out,
    )

    assert seams.calls == []
    assert (out / "results-index.json").exists()
    entry_dir = out / "results-test-solver-default"
    assert (entry_dir / "entry.json").exists()
    raw = entry_dir / "raw" / tiny_bundle.root.name
    assert (raw / "bench.json").exists()
    assert (raw / "bench.json").read_bytes() == (bench_dir / "bench.json").read_bytes()


def test_cli_publish_dry_run(tiny_bundle, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from any_to_bench.cli import app

    bench_dir = make_bench_dir(tiny_bundle, tmp_path / "bench", monkeypatch)
    out = tmp_path / "cli-dry"
    result = CliRunner().invoke(
        app,
        [
            "results",
            "publish",
            str(bench_dir),
            "user/results",
            "--source-repo",
            "user/exams",
            "--bundles-root",
            str(tiny_bundle.root.parent),
            "--dry-run",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out / "results-index.json").exists()
