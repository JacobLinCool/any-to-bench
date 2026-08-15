"""Hugging Face publish/fetch: offline, faking only the network seams."""

import shutil

import pytest
from typer.testing import CliRunner

import any_to_bench.hf as hf_module
from any_to_bench.cli import app
from any_to_bench.hf import HubError, build_question_rows, download_bundle, upload_bundle
from tests.conftest import build_tiny_bundle

runner = CliRunner()


def test_build_question_rows(tiny_bundle):
    rows = build_question_rows(tiny_bundle)
    assert [r["id"] for r in rows] == ["q1", "q2", "q3", "q4", "q5", "q6.a", "q6.b", "q7"]

    q1 = rows[0]
    assert q1["images"] == ["assets/q1-fig1.png"]
    assert q1["image_alts"] == ["a solid red rectangle"]
    assert "[Figure: a solid red rectangle]" in q1["prompt"]
    assert len(q1["options"]) == 4 and q1["options"][0] == "(A) Blue"
    assert q1["grading"] == "choice"
    assert q1["points"] == 2.0

    q6a = next(r for r in rows if r["id"] == "q6.a")
    assert "photosynthesis" in q6a["context"]
    assert q6a["grading"] == "judge"

    q4 = next(r for r in rows if r["id"] == "q4")
    assert q4["blanks"] == ["b1 (i)", "b2 (ii)"]
    q5 = next(r for r in rows if r["id"] == "q5")
    assert "[L1] Japan" in q5["matching"] and "[R3] Madrid" in q5["matching"]


class Seams:
    """Records calls to the network seams in order."""

    def __init__(self, monkeypatch, token="tok", files=None, card_content=""):
        self.calls: list[tuple[str, dict]] = []
        self.files = files or []
        self.card_content = card_content
        monkeypatch.setattr(hf_module, "_get_token", lambda: token)
        monkeypatch.setattr(
            hf_module,
            "_push_dataset",
            lambda dataset, repo_id, config_name, private: self.calls.append(
                (
                    "push",
                    {
                        "dataset": dataset,
                        "repo_id": repo_id,
                        "config_name": config_name,
                        "private": private,
                    },
                )
            ),
        )
        monkeypatch.setattr(
            hf_module,
            "_upload_folder",
            lambda **kw: self.calls.append(("upload_folder", kw)),
        )
        monkeypatch.setattr(hf_module, "_list_repo_files", lambda repo_id: self.files)
        monkeypatch.setattr(hf_module, "_load_card", self._load_card)
        monkeypatch.setattr(
            hf_module,
            "_push_card",
            lambda card, repo_id: self.calls.append(("push_card", {"card": card})),
        )

    def _load_card(self, repo_id):
        from huggingface_hub import DatasetCard

        return DatasetCard(self.card_content)


def test_upload_bundle_happy_path(tiny_bundle, monkeypatch):
    seams = Seams(monkeypatch)
    url = upload_bundle(tiny_bundle.root, "user/exams")

    assert url == "https://huggingface.co/datasets/user/exams"
    # push creates the repo; the card is refreshed last
    assert [c[0] for c in seams.calls] == ["push", "upload_folder", "push_card"]
    push = seams.calls[0][1]
    assert push["config_name"] == "bundle"  # slugified directory name
    assert push["private"] is False  # public by default
    dataset = push["dataset"]
    assert dataset.num_rows == 8
    assert dataset.features["images"].feature._type == "Image"
    up = seams.calls[1][1]
    assert up["path_in_repo"] == "bundle/bundle"
    assert up["delete_patterns"] == ["bundle/bundle/**"]
    assert up["repo_type"] == "dataset"


def test_upload_bundle_private_and_name(tiny_bundle, monkeypatch):
    seams = Seams(monkeypatch)
    upload_bundle(tiny_bundle.root, "user/exams", name="matha", private=True)
    push = seams.calls[0][1]
    assert push["config_name"] == "matha" and push["private"] is True
    assert seams.calls[1][1]["path_in_repo"] == "matha/bundle"


def test_upload_rejects_invalid_bundle_before_any_network_call(tiny_bundle, monkeypatch):
    seams = Seams(monkeypatch)
    (tiny_bundle.root / "assets" / "q1-fig1.png").unlink()
    with pytest.raises(HubError, match="invalid bundle"):
        upload_bundle(tiny_bundle.root, "user/exams")
    assert seams.calls == []


def test_upload_rejects_reserved_name(tiny_bundle, monkeypatch):
    Seams(monkeypatch)
    with pytest.raises(HubError, match="reserved"):
        upload_bundle(tiny_bundle.root, "user/exams", name="data")


def test_upload_requires_token(tiny_bundle, monkeypatch):
    seams = Seams(monkeypatch, token=None)
    with pytest.raises(HubError, match="token"):
        upload_bundle(tiny_bundle.root, "user/exams")
    assert seams.calls == []


def test_upload_generates_dataset_card(tiny_bundle, monkeypatch):
    seams = Seams(monkeypatch)
    upload_bundle(tiny_bundle.root, "user/exams", name="tiny", license="cc-by-4.0")

    card = seams.calls[-1][1]["card"]
    assert card.data.pretty_name == "Tiny Exam"
    assert card.data.language == ["en"]
    assert "any-to-bench" in card.data.tags
    assert card.data.task_categories == ["question-answering"]
    assert card.data.license == "cc-by-4.0"
    assert "## Usage" in card.text
    assert "Answer key included" in card.text
    assert "## tiny — Tiny Exam" in card.text
    assert "| Total points | 17 |" in card.text
    assert "a2b download user/exams --name tiny -o bundle" in card.text


def test_card_update_is_idempotent_and_preserves_foreign_content(tiny_bundle):
    from huggingface_hub import DatasetCard

    from any_to_bench.hf import update_card

    existing = DatasetCard(
        "---\nconfigs:\n- config_name: other\n  data_files: other/test-*\n---\n"
        "My hand-written notes.\n"
    )
    card = update_card(existing, "tiny", tiny_bundle, "user/exams")
    card = update_card(card, "tiny", tiny_bundle, "user/exams")  # re-upload same name

    assert card.text.count("## tiny — Tiny Exam") == 1
    assert "My hand-written notes." in card.text  # foreign prose kept
    assert card.data.to_dict()["configs"][0]["config_name"] == "other"  # configs untouched
    assert getattr(card.data, "license", None) is None  # never set without --license

    card = update_card(card, "second", tiny_bundle, "user/exams")
    assert card.text.count("## tiny — Tiny Exam") == 1
    assert "## second — Tiny Exam" in card.text


def test_copyright_note_is_optional_but_not_sticky(tiny_bundle):
    from huggingface_hub import DatasetCard

    from any_to_bench.hf import COPYRIGHT_NOTE, update_card

    card = update_card(DatasetCard(""), "tiny", tiny_bundle, "user/exams")
    assert COPYRIGHT_NOTE in card.text  # on by default

    card = update_card(card, "tiny", tiny_bundle, "user/exams", copyright_note=False)
    assert COPYRIGHT_NOTE not in card.text
    assert "Answer key included" in card.text  # the rest of the header survives

    # The header is rebuilt in full every time, so one upload without the flag
    # brings the line back. Callers must pass it on every upload.
    card = update_card(card, "second", tiny_bundle, "user/exams")
    assert COPYRIGHT_NOTE in card.text


def _fake_snapshot(monkeypatch, name="matha"):
    def snapshot(**kwargs):
        local_dir = kwargs["local_dir"]
        build_tiny_bundle(hf_module.Path(local_dir) / name / "bundle")
        (hf_module.Path(local_dir) / ".cache" / "huggingface").mkdir(parents=True)
        return local_dir

    monkeypatch.setattr(hf_module, "_snapshot_download", snapshot)


def test_download_single_bundle_auto_selects(tmp_path, monkeypatch):
    monkeypatch.setattr(
        hf_module, "_list_repo_files", lambda repo_id: ["matha/bundle/exam.json", "README.md"]
    )
    _fake_snapshot(monkeypatch)
    out = tmp_path / "dl"
    result = download_bundle("user/exams", out)
    assert result == out
    assert (out / "exam.json").exists()
    assert not list(out.rglob(".cache"))
    from any_to_bench.bundle import validate_bundle

    assert validate_bundle(out) == []


def test_download_round_trip_is_byte_identical(tmp_path, monkeypatch):
    source = build_tiny_bundle(tmp_path / "src")

    def snapshot(**kwargs):
        dest = hf_module.Path(kwargs["local_dir"]) / "matha" / "bundle"
        shutil.copytree(source.root, dest)
        return kwargs["local_dir"]

    monkeypatch.setattr(hf_module, "_list_repo_files", lambda repo_id: ["matha/bundle/exam.json"])
    monkeypatch.setattr(hf_module, "_snapshot_download", snapshot)
    out = tmp_path / "dl"
    download_bundle("user/exams", out)
    for path in sorted(source.root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(source.root)
            assert (out / rel).read_bytes() == path.read_bytes()


def test_download_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_module, "_list_repo_files", lambda repo_id: ["README.md"])
    with pytest.raises(HubError, match="no bundles"):
        download_bundle("user/exams", tmp_path / "a")

    monkeypatch.setattr(
        hf_module,
        "_list_repo_files",
        lambda repo_id: ["matha/bundle/exam.json", "english/bundle/exam.json"],
    )
    with pytest.raises(HubError, match="several bundles"):
        download_bundle("user/exams", tmp_path / "b")
    with pytest.raises(HubError, match="not found"):
        download_bundle("user/exams", tmp_path / "c", name="ghost")

    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "existing.txt").write_text("x")
    with pytest.raises(HubError, match="not empty"):
        download_bundle("user/exams", busy, name="matha")


def test_upload_download_cli(tiny_bundle, tmp_path, monkeypatch):
    Seams(monkeypatch, files=["tiny/bundle/exam.json"])
    _fake_snapshot(monkeypatch, name="tiny")

    result = runner.invoke(app, ["upload", str(tiny_bundle.root), "user/exams", "--name", "tiny"])
    assert result.exit_code == 0, result.output
    assert "Viewer:" in result.output

    out = tmp_path / "dl"
    result = runner.invoke(app, ["download", "user/exams", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "is valid" in result.output

    # A repo with no bundles fails cleanly.
    monkeypatch.setattr(hf_module, "_list_repo_files", lambda repo_id: [])
    result = runner.invoke(app, ["download", "user/exams", "-o", str(tmp_path / "dl2")])
    assert result.exit_code == 1
