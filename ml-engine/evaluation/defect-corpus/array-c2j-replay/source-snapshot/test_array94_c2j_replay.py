"""Validate the exact fixed-array adapter without executing upstream programs."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/replay_array94_c2j_witnesses.py'
SPEC = importlib.util.spec_from_file_location('array94_replay', SCRIPT)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)

LINKAGE = '''       01 LINKED-ITEMS.
           05 L-LST OCCURS 6 TIMES INDEXED BY NI PIC S9(10).
           05 RESULT PIC S9(10).
'''
SOURCE = ('       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SKJKASDKD.\n'
          '       DATA DIVISION.\n       LINKAGE SECTION.\n' + LINKAGE +
          '       PROCEDURE DIVISION USING LINKED-ITEMS.\n           GOBACK.\n')
DRIVER = ('       SELECT OUTPUT-FILE ASSIGN TO "SKJKASDKD.TXT"\n'
          '       01 OUTPUT-RECORD PIC S9(10) SIGN LEADING.\n' + LINKAGE +
          '       PROCEDURE DIVISION.\n' +
          ''.join(f'           MOVE {v} TO L-LST({i + 1})\n' for i, v in enumerate([0, 8, 1, 2, 1, 7])) +
          '           CALL "SKJKASDKD" USING LINKED-ITEMS\n'
          '           MOVE RESULT TO OUTPUT-RECORD\n           WRITE OUTPUT-RECORD.\n')


def test_all_six_inputs_preserve_occurrence_order():
    assert replay.extract_case(SOURCE, DRIVER, 1)['arguments'] == [0, 8, 1, 2, 1, 7]
    lines = DRIVER.splitlines(keepends=True)
    moves = [line for line in lines if 'MOVE ' in line and 'TO L-LST(' in line]
    reversed_moves = iter(reversed(moves))
    moved = ''.join(next(reversed_moves) if line in moves else line for line in lines)
    assert moved != DRIVER
    assert replay.extract_case(SOURCE, moved, 1)['arguments'] == [0, 8, 1, 2, 1, 7]


@pytest.mark.parametrize('replacement', ['', 'MOVE 7 TO L-LST(5)', 'MOVE 7 TO L-LST(7)',
                                          'MOVE X TO L-LST(6)', 'MOVE 2147483648 TO L-LST(6)'])
def test_missing_duplicate_unknown_nonliteral_and_out_of_range_inputs_rejected(replacement):
    with pytest.raises(ValueError):
        replay.extract_case(SOURCE, DRIVER.replace('MOVE 7 TO L-LST(6)', replacement), 0)


def test_linkage_size_mismatch_rejected():
    with pytest.raises(ValueError, match='linkage'):
        replay.extract_case(SOURCE, DRIVER.replace('OCCURS 6 TIMES', 'OCCURS 5 TIMES'), 0)


def test_extra_computation_before_call_rejected():
    with pytest.raises(ValueError, match='initialized'):
        replay.extract_case(SOURCE, DRIVER.replace('           CALL', '           ADD 1 TO L-LST(1)\n           CALL'), 0)


def test_output_contract_cannot_silently_truncate():
    with pytest.raises(ValueError, match='output'):
        replay.extract_case(SOURCE, DRIVER.replace('OUTPUT-RECORD PIC S9(10)', 'OUTPUT-RECORD PIC S9(4)'), 0)


def test_immutable_contract_writer(tmp_path):
    path = tmp_path / 'frozen.json'
    replay.new_json(path, {'frozen': True})
    with pytest.raises(FileExistsError):
        replay.new_json(path, {'frozen': False})
