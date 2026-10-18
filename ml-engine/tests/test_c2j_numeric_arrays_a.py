"""Scientific guardrails for fixed-array shared-input adjudication."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/adjudicate_c2j_numeric_arrays_a.py'
SPEC = importlib.util.spec_from_file_location('numeric_arrays_a', SCRIPT)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)

LAYOUT = '''       01 LINKED-ITEMS.
           05 L-L OCCURS 3 TIMES INDEXED BY NI PIC S9(10).
           05 RESULT PIC S9(10).
'''
SOURCE = ('       PROGRAM-ID. MAX-ELEMENT.\n       LINKAGE SECTION.\n' + LAYOUT +
          '       PROCEDURE DIVISION USING LINKED-ITEMS.\n           GOBACK.\n')
DRIVER = ('       SELECT OUTPUT-FILE ASSIGN TO "MAX-ELEMENT.TXT"\n'
          '       01 OUTPUT-RECORD PIC S9(10) SIGN LEADING.\n' + LAYOUT +
          '       PROCEDURE DIVISION.\n'
          '           MOVE 10 TO L-L(1)\n           MOVE -2 TO L-L(2)\n           MOVE 3 TO L-L(3)\n'
          '           CALL "MAX-ELEMENT" USING LINKED-ITEMS\n'
          '           MOVE RESULT TO OUTPUT-RECORD\n           WRITE OUTPUT-RECORD.\n')


def extract(driver=DRIVER):
    return replay.parse_inputs({'COBOL_canonical_solution': SOURCE}, driver, replay.SPECS[35], 0)


def test_occurrence_mapping_survives_reordered_moves():
    assert extract()['arguments'] == [10, -2, 3]
    lines = DRIVER.splitlines(keepends=True)
    moves = [line for line in lines if 'TO L-L(' in line]
    reverse = iter(reversed(moves))
    reordered = ''.join(next(reverse) if line in moves else line for line in lines)
    assert reordered != DRIVER
    assert extract(reordered)['arguments'] == [10, -2, 3]


@pytest.mark.parametrize('replacement', ['', 'MOVE 3 TO L-L(2)', 'MOVE 3 TO L-L(4)', 'MOVE X TO L-L(3)', 'COMPUTE L-L(3) = 3'])
def test_uninitialized_duplicate_unknown_and_computed_inputs_fail_closed(replacement):
    with pytest.raises(replay.Unsupported):
        extract(DRIVER.replace('MOVE 3 TO L-L(3)', replacement))


def test_linkage_and_common_range_enforced():
    with pytest.raises(replay.Unsupported, match='linkage'):
        extract(DRIVER.replace('OCCURS 3 TIMES', 'OCCURS 4 TIMES'))
    with pytest.raises(replay.Unsupported, match='range'):
        extract(DRIVER.replace('MOVE 3 TO L-L(3)', 'MOVE 2147483648 TO L-L(3)'))


def test_reserved_unknown_and_overlap_are_rejected():
    split = {'developmentTaskIds': ['HumanEval/35'], 'finalHoldoutTaskIds': ['HumanEval/1']}
    replay.require_development('HumanEval/35', split)
    for value in ['HumanEval/1', 'HumanEval/999']:
        with pytest.raises(replay.scalar.UnsupportedContract):
            replay.require_development(value, split)
    split['finalHoldoutTaskIds'].append('HumanEval/35')
    with pytest.raises(replay.scalar.UnsupportedContract):
        replay.require_development('HumanEval/35', split)


def test_signed_decimal_is_exact_and_negative_overpunch_is_not_lost():
    spec = replay.SPECS[47]
    assert replay.same(replay.decode_cobol(b'000000003.00000\n', spec), '3.0', spec)
    assert replay.same(replay.decode_cobol(b'p00000003.00000\n', spec), '-3.0', spec)
    assert not replay.same('3.00001', '3.0', spec)
    for value in [b'3\n', b'000000003.00000\n1\n', b'000000003.0000\n']:
        with pytest.raises(replay.Unsupported):
            replay.decode_cobol(value, spec)
    with pytest.raises(replay.Unsupported):
        replay.decode_java(b'NaN', spec)


def test_list_length_is_source_frozen_not_expected_metadata_or_trimmed_zeros():
    spec = replay.SPECS[70]
    raw = b'0000000000\n' * 100
    assert replay.decode_cobol(raw, spec) == [0, 0, 0, 0]
    assert len(replay.decode_cobol(raw, spec)) == 4
    for malformed in [raw[:-1], raw[:-11], raw + b'0000000000\n']:
        with pytest.raises(replay.Unsupported):
            replay.decode_cobol(malformed, spec)
    for invalid in [b'[]', b'[0,0,0]', b'[0,0,0,true]']:
        with pytest.raises(replay.Unsupported):
            replay.decode_java(invalid, spec)


def test_native_tail_anomalies_are_retained_not_silently_trimmed():
    spec = replay.SPECS[70]
    raw = b'0000000000\n' * 4 + b'XXXXXXXXXX\n' + b'0000000000\n' * 95
    shape = replay.native_list_shape(raw, spec)
    assert shape['recordCount'] == 100
    assert shape['uncomparedTailRecords'] == 96
    assert shape['tailIntegerDecodeFailuresAtOneBasedOccurrences'] == [5]
    assert len(shape['recordHex']) == 100


def test_boolean_decoder_never_coerces_nonbinary_output():
    with pytest.raises(replay.scalar.UnsupportedContract):
        replay.decode_cobol(b'2\n', replay.SPECS[43])
    with pytest.raises(replay.Unsupported):
        replay.decode_java(b'1', replay.SPECS[43])


def test_writer_refuses_overwriting_frozen_evidence(tmp_path):
    path = tmp_path / 'frozen.json'
    replay.write_new(path, {'frozen': True})
    with pytest.raises(FileExistsError):
        replay.write_new(path, {'frozen': False})
