"""The generated answer-sheet JSON Schema: acceptance and rejection."""

import jsonschema
import pytest

from any_to_bench.schemas.answers import generate_answer_schema
from tests.conftest import build_tiny_exam, imperfect_sheet, perfect_sheet


@pytest.fixture(scope="module")
def schema():
    return generate_answer_schema(build_tiny_exam())


def _validate(schema, payload):
    return sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(payload), key=str
    )


def test_schema_is_valid_jsonschema(schema):
    jsonschema.Draft202012Validator.check_schema(schema)


def test_perfect_sheet_passes(schema):
    assert _validate(schema, perfect_sheet().model_dump(mode="json")) == []


def test_missing_question_rejected(schema):
    payload = perfect_sheet().model_dump(mode="json")
    del payload["answers"]["q3"]
    assert any("q3" in e.message for e in _validate(schema, payload))


def test_unknown_question_rejected(schema):
    payload = perfect_sheet().model_dump(mode="json")
    payload["answers"]["q99"] = {"type": "text", "text": "hi"}
    assert _validate(schema, payload)


def test_invalid_option_id_rejected(schema):
    payload = perfect_sheet().model_dump(mode="json")
    payload["answers"]["q1"] = {"type": "single_choice", "selected": "Z"}
    assert _validate(schema, payload)


def test_wrong_blank_keys_rejected(schema):
    payload = perfect_sheet().model_dump(mode="json")
    payload["answers"]["q4"] = {"type": "fill_in_blank", "blanks": {"b1": "x", "wrong": "y"}}
    assert _validate(schema, payload)


def test_matching_value_must_be_right_id(schema):
    payload = perfect_sheet().model_dump(mode="json")
    payload["answers"]["q5"] = {"type": "matching", "pairs": {"L1": "L2", "L2": "R1"}}
    assert _validate(schema, payload)


def test_wrong_answer_type_for_question_rejected(schema):
    payload = perfect_sheet().model_dump(mode="json")
    payload["answers"]["q1"] = {"type": "text", "text": "B"}
    assert _validate(schema, payload)


def test_incomplete_sheet_is_rejected_but_parses(schema):
    # An imperfect sheet missing open-ended answers parses as a model but
    # fails the schema's required-question check.
    payload = imperfect_sheet().model_dump(mode="json")
    errors = _validate(schema, payload)
    assert any("q6.a" in e.message for e in errors)
