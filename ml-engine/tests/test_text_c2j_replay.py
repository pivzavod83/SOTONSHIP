"""Validate contract admission without executing source programs."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/replay_text_c2j_witnesses.py'
SPEC = importlib.util.spec_from_file_location('text_c2j_replay', SCRIPT)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)

SOURCE = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. COUNT-UPPER.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LINKED-ITEMS.
           05 L-S PIC X(100).
           05 RESULT PIC S9(10).
       PROCEDURE DIVISION USING LINKED-ITEMS.
           GOBACK.
'''
DRIVER = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. COUNT-UPPER-CALL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
       SELECT OUTPUT-FILE ASSIGN TO "COUNT-UPPER.TXT".
       DATA DIVISION.
       FILE SECTION.
       FD OUTPUT-FILE.
       01 OUTPUT-RECORD PIC S9(10) SIGN LEADING.
       WORKING-STORAGE SECTION.
       01 LINKED-ITEMS.
           05 L-S PIC X(100).
           05 RESULT PIC S9(10).
       PROCEDURE DIVISION.
           MOVE 'aBCdEf' TO L-S
           CALL "COUNT-UPPER" USING LINKED-ITEMS
           MOVE RESULT TO OUTPUT-RECORD
           WRITE OUTPUT-RECORD
           STOP RUN.
'''


def extract(driver=DRIVER, source=SOURCE):
    return replay.extract_input({'COBOL_canonical_solution': source}, driver)


def test_input_preserves_case_and_ignores_no_characters():
    assert extract() == 'aBCdEf'


@pytest.mark.parametrize('value', ['', 'A B', 'A\\nB', 'éA', 'A' * 101])
def test_padding_escape_encoding_and_width_ambiguities_rejected(value):
    with pytest.raises(ValueError):
        extract(DRIVER.replace('aBCdEf', value))


@pytest.mark.parametrize('statement', ['', "MOVE 'A' TO L-S\n           MOVE 'B' TO L-S", 'MOVE INPUT TO L-S'])
def test_input_initialization_must_be_one_literal_move(statement):
    with pytest.raises(ValueError):
        extract(DRIVER.replace("MOVE 'aBCdEf' TO L-S", statement))


def test_changed_storage_schema_rejected():
    with pytest.raises(ValueError, match='linkage'):
        extract(source=SOURCE.replace('X(100)', 'X(99)'))


def test_narrowing_output_rejected():
    with pytest.raises(ValueError, match='output representation'):
        extract(DRIVER.replace('OUTPUT-RECORD PIC S9(10)', 'OUTPUT-RECORD PIC S9(3)'))


def test_repeated_calls_rejected():
    with pytest.raises(ValueError, match='exactly one'):
        extract(DRIVER.replace('MOVE RESULT TO OUTPUT-RECORD',
                               'CALL "COUNT-UPPER" USING LINKED-ITEMS\n           MOVE RESULT TO OUTPUT-RECORD'))


def test_reports_refuse_overwrite(tmp_path):
    path = tmp_path / 'report.json'
    replay.write_new(path, {'first': True})
    with pytest.raises(FileExistsError):
        replay.write_new(path, {'first': False})
