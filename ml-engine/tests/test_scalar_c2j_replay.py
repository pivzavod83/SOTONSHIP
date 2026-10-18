"""Guard the bounded common-input adapter; do not execute upstream programs."""
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/replay_scalar_c2j_witnesses.py"
SPEC = importlib.util.spec_from_file_location("scalar_c2j_replay", SCRIPT)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)

SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ADD.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LINKED-ITEMS.
           05 L-X PIC S9(10).
           05 L-Y PIC S9(10).
           05 RESULT PIC S9(10).
       PROCEDURE DIVISION USING LINKED-ITEMS.
           COMPUTE RESULT = L-X + L-Y
           GOBACK.
"""
DRIVER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ADD-CALL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
       SELECT OUTPUT-FILE ASSIGN TO "ADD.TXT"
           ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD OUTPUT-FILE.
       01 OUTPUT-RECORD PIC S9(10) SIGN LEADING.
       WORKING-STORAGE SECTION.
       01 LINKED-ITEMS.
           05 L-X PIC S9(10).
           05 L-Y PIC S9(10).
           05 RESULT PIC S9(10).
       PROCEDURE DIVISION.
           MOVE 2 TO L-X
           MOVE 3 TO L-Y
           CALL "ADD" USING LINKED-ITEMS
           OPEN OUTPUT OUTPUT-FILE
           MOVE RESULT TO OUTPUT-RECORD
           WRITE OUTPUT-RECORD
           CLOSE OUTPUT-FILE.
"""


def extract(driver=DRIVER, spec=None):
    return replay.extract_case({"COBOL_canonical_solution": SOURCE}, driver,
                               spec or replay.CONTRACTS[53], 0)


def test_literal_inputs_are_ordered_by_linkage_not_move_order():
    driver = DRIVER.replace("MOVE 2 TO L-X\n           MOVE 3 TO L-Y", "MOVE 3 TO L-Y\n           MOVE 2 TO L-X")
    assert extract(driver)["arguments"] == [2, 3]


@pytest.mark.parametrize("replacement", ["", "MOVE 3 TO L-X", "MOVE 3 TO L-Z", "MOVE X TO L-Y", "COMPUTE L-Y = 3"])
def test_missing_duplicate_unknown_and_nonliteral_initializations_rejected(replacement):
    with pytest.raises(replay.UnsupportedContract):
        extract(DRIVER.replace("MOVE 3 TO L-Y", replacement))


def test_extra_move_rejected():
    with pytest.raises(replay.UnsupportedContract):
        extract(DRIVER.replace('CALL "ADD"', 'MOVE 8 TO L-Z\n           CALL "ADD"'))


def test_bounds_are_common_contract_bounds_not_java_parsing_only():
    with pytest.raises(replay.UnsupportedContract, match="bounds"):
        extract(DRIVER.replace("MOVE 2 TO L-X", "MOVE 1001 TO L-X"))
    with pytest.raises(replay.UnsupportedContract, match="bounds"):
        extract(DRIVER.replace("MOVE 2 TO L-X", "MOVE 2147483648 TO L-X"),
                ("add", ["X", "Y"], "int", 0, 10**10))


def test_split_guard_rejects_holdout_and_unknown_and_overlap():
    partition = {"developmentTaskIds": ["HumanEval/53"], "finalHoldoutTaskIds": ["HumanEval/1"]}
    replay.require_development("HumanEval/53", partition)
    for task_id in ["HumanEval/1", "HumanEval/999"]:
        with pytest.raises(replay.UnsupportedContract):
            replay.require_development(task_id, partition)
    partition["finalHoldoutTaskIds"].append("HumanEval/53")
    with pytest.raises(replay.UnsupportedContract):
        replay.require_development("HumanEval/53", partition)


@pytest.mark.parametrize("driver", [DRIVER.replace("       MOVE", "000100 MOVE"),
    DRIVER.replace("           MOVE 2", "      -    MOVE 2"),
    DRIVER + "       " + "X" * 249 + "\n"])
def test_unverified_source_column_conventions_rejected(driver):
    with pytest.raises(replay.UnsupportedContract):
        extract(driver)


def test_variable_format_code_beyond_column_72_is_preserved():
    line = "       " + " " * 65 + "MOVE 1 TO X"
    assert "MOVE 1 TO X" in replay.code_lines(line)


def test_source_driver_linkage_mismatch_rejected():
    with pytest.raises(replay.UnsupportedContract, match="linkage"):
        extract(DRIVER.replace("05 L-Y PIC S9(10).", "05 L-Y PIC S9(20)."))


def test_wrong_target_and_nonrelative_output_rejected():
    with pytest.raises(replay.UnsupportedContract):
        extract(DRIVER.replace('CALL "ADD"', 'CALL "OTHER"'))
    with pytest.raises(replay.UnsupportedContract):
        extract(DRIVER.replace('"ADD.TXT"', '"../ADD.TXT"'))


def test_signed_display_decoder_preserves_actual_negative_result():
    assert replay.parse_cobol_output(b"0000000005\n", "int") == 5
    assert replay.parse_cobol_output(b"p000000001\n", "int") == -1
    assert replay.parse_cobol_output(b"q234567890\r\n", "int") == -1234567890
    for raw in [b"5\n", b"+000000005\n", b"0000000005\n1\n"]:
        with pytest.raises(replay.UnsupportedContract):
            replay.parse_cobol_output(raw, "int")


def test_bool_decoder_does_not_coerce_nonbinary_values():
    assert replay.parse_cobol_output(b"1\n", "boolean") is True
    assert replay.parse_cobol_output(b"0\n", "boolean") is False
    with pytest.raises(replay.UnsupportedContract):
        replay.parse_cobol_output(b"2\n", "boolean")


def test_immutable_artifact_writer_refuses_overwrite(tmp_path):
    path = tmp_path / "frozen.json"
    replay.write_new(path, {"frozen": True})
    with pytest.raises(FileExistsError):
        replay.write_new(path, {"frozen": False})
