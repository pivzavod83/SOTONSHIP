"""Checks for oracle parsing and the new audit's execution guards."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_cobol_references.py"
SPEC = importlib.util.spec_from_file_location("cobol_reference_audit", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_signed_ascii_overpunch_and_float_tolerance():
    assert audit.parse_number("p000000001") == -1
    assert audit.parse_number("y000000001") == -9000000001
    result = audit.parse_output(b"1.0009\n", "Float", 1.0)
    assert result["compatible"] is True
    assert audit.parse_output(b"1.002\n", "Float", 1.0)["compatible"] is False


def test_list_prefix_discloses_circular_expected_length_convention():
    result = audit.parse_output(b"0001\n0002\n0000\n", {"List": "Int"}, [1, 2])
    assert result["compatible"] is True
    assert result["expectedLengthUsedForListProjection"] is True
    assert result["ignoredTrailingRecordCount"] == 1
    assert audit.parse_output(b"0000\n", {"List": "String"}, [])["observed"] == []


def test_short_float_list_cannot_pass_by_zip_truncation():
    with pytest.raises(ValueError, match="Fewer serialized records"):
        audit.parse_output(b"1.0\n", {"List": "Float"}, [1.0, 2.0])


def test_invalid_boolean_cannot_be_silently_labelled_false():
    with pytest.raises(ValueError, match="neither zero nor one"):
        audit.parse_output(b"garbage\n", "Bool", False)


def test_preflight_rejects_absolute_output_and_unrelated_calls():
    canonical = "       PROGRAM-ID. FOO.\n       PROCEDURE DIVISION USING LINKED-ITEMS.\n       GOBACK."
    driver = '       SELECT F ASSIGN TO "FOO.TXT".\n       CALL "FOO" USING LINKED-ITEMS.'
    assert audit.source_preflight(canonical, driver) == "FOO.TXT"
    with pytest.raises(ValueError, match="relative"):
        audit.source_preflight(canonical, driver.replace("FOO.TXT", "/tmp/FOO.TXT"))
    with pytest.raises(ValueError, match="literal call"):
        audit.source_preflight(canonical, driver.replace('CALL "FOO"', 'CALL "SYSTEM"'))


def test_expected_value_is_not_executable_python():
    with pytest.raises(ValueError):
        audit.parse_expected({"value": "__import__('os').system('echo unsafe')"})


def test_cobol_identifier_hyphens_are_not_keyword_boundaries():
    canonical = "       PROGRAM-ID. SELECT-WORDS.\n       COPY-INPUT-ARRAY.\n       GOBACK."
    driver = '       SELECT F ASSIGN TO "SELECT-WORDS.TXT".\n       CALL "SELECT-WORDS" USING LINKED-ITEMS.'
    assert audit.source_preflight(canonical, driver) == "SELECT-WORDS.TXT"
    with pytest.raises(ValueError, match="operation"):
        audit.source_preflight(canonical + '\n       COPY "unknown.cpy".', driver)


def test_input_pinning_rejects_different_source_bytes(tmp_path):
    dataset, partition = tmp_path / "dataset.jsonl", tmp_path / "partition.json"
    dataset.write_text("{}\n")
    partition.write_text("{}\n")
    with pytest.raises(ValueError, match="Dataset bytes differ"):
        audit.load_inputs(dataset, partition)
