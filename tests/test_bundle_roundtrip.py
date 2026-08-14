"""Bundle save/load round-trip and validate_bundle checks."""

from any_to_bench.bundle import ExamBundle, validate_bundle
from any_to_bench.util import read_json, write_json
from tests.conftest import perfect_sheet


def test_roundtrip(tiny_bundle):
    loaded = ExamBundle.load(tiny_bundle.root)
    assert loaded.exam == tiny_bundle.exam
    assert loaded.grading == tiny_bundle.grading
    assert loaded.answer_schema == tiny_bundle.answer_schema


def test_valid_bundle_passes(tiny_bundle):
    assert validate_bundle(tiny_bundle.root) == []


def test_missing_files_detected(tmp_path):
    problems = validate_bundle(tmp_path)
    assert any("missing file" in p for p in problems)


def test_missing_asset_detected(tiny_bundle):
    (tiny_bundle.root / "assets" / "q1-fig1.png").unlink()
    problems = validate_bundle(tiny_bundle.root)
    assert any("missing image asset" in p for p in problems)


def test_missing_grading_entry_detected(tiny_bundle):
    grading = read_json(tiny_bundle.root / "grading.json")
    del grading["questions"]["q3"]
    write_json(tiny_bundle.root / "grading.json", grading)
    problems = validate_bundle(tiny_bundle.root)
    assert any("q3 has no grading entry" in p for p in problems)


def test_bad_correct_option_detected(tiny_bundle):
    grading = read_json(tiny_bundle.root / "grading.json")
    grading["questions"]["q1"]["rule"]["correct"] = ["Z"]
    write_json(tiny_bundle.root / "grading.json", grading)
    problems = validate_bundle(tiny_bundle.root)
    assert any("correct option 'Z'" in p for p in problems)


def test_stale_answer_schema_detected(tiny_bundle):
    schema = read_json(tiny_bundle.root / "answer_schema.json")
    del schema["properties"]["answers"]["properties"]["q1"]
    write_json(tiny_bundle.root / "answer_schema.json", schema)
    problems = validate_bundle(tiny_bundle.root)
    assert any("stale" in p for p in problems)


def test_validate_answer_sheet(tiny_bundle):
    assert tiny_bundle.validate_answer_sheet(perfect_sheet()) == []
    bad = perfect_sheet()
    bad.answers["q1"].selected = "Z"
    errors = tiny_bundle.validate_answer_sheet(bad)
    assert errors and any("q1" in e for e in errors)
