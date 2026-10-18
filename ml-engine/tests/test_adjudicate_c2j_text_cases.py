"""Fail-closed tests for source-derived text/list common-input contracts."""
import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[1] / 'scripts/adjudicate_c2j_text_cases.py'
SPEC = importlib.util.spec_from_file_location('adjudicate_c2j_text_cases', PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture(number, moves):
    spec = module.SPECS[number]
    declarations = '\n'.join('           ' + field.strip() + '.' for field in spec['sourceLayout'].split('.') if field.strip())
    source = (f'       IDENTIFICATION DIVISION.\n       PROGRAM-ID. {spec["program"]}.\n'
              '       DATA DIVISION.\n       LINKAGE SECTION.\n       01 LINKED-ITEMS.\n' + declarations + '\n'
              '       PROCEDURE DIVISION USING LINKED-ITEMS.\n           GOBACK.\n')
    driver_declarations = '\n'.join('           ' + field.strip() + '.' for field in spec.get('driverLayout', spec['sourceLayout']).split('.') if field.strip())
    pic = 'X(100)' if spec['result'] in {'string', 'stringList'} else 'S9(10) SIGN LEADING'
    if spec['result'].endswith('List'):
        output = ('           PERFORM VARYING NJ FROM 1 BY 1 UNTIL NJ > 100\n'
                  '               MOVE RESULT (NJ) TO OUTPUT-RECORD\n               WRITE OUTPUT-RECORD\n           END-PERFORM\n')
    else:
        output = '           MOVE RESULT TO OUTPUT-RECORD\n           WRITE OUTPUT-RECORD\n'
    driver = (f'       IDENTIFICATION DIVISION.\n       PROGRAM-ID. {spec["program"]}-CALL.\n'
              f'       ENVIRONMENT DIVISION.\n       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n       SELECT OUTPUT-FILE ASSIGN TO "{spec["program"]}.TXT"\n'
              '           ORGANIZATION IS LINE SEQUENTIAL.\n       DATA DIVISION.\n       FILE SECTION.\n       FD OUTPUT-FILE.\n'
              f'       01 OUTPUT-RECORD PIC {pic}.\n       WORKING-STORAGE SECTION.\n       01 LINKED-ITEMS.\n'
              + driver_declarations + '\n       PROCEDURE DIVISION.\n'
              + '\n'.join('           ' + move for move in moves) + '\n'
              + f'           CALL "{spec["program"]}" USING LINKED-ITEMS\n           OPEN OUTPUT OUTPUT-FILE\n'
              + output + '           CLOSE OUTPUT-FILE.\n')
    return {'COBOL_canonical_solution': source}, driver


def test_music_shape_comes_from_input_grammar_not_expected_answer():
    row, driver = fixture(17, ["MOVE 'o o| .|' TO L-MUSIC-STRING"])
    case = module.extract_case(17, row, driver, 0)
    assert case['logicalResultLength'] == 3
    assert case['arguments'] == ['o o| .|']
    result, evidence = module.parse_output(17, b'0000000004\n0000000002\n0000000001\n' + b'0000000000\n' * 97, case)
    assert result == [4, 2, 1]
    assert evidence['verifiedPaddingRecordCount'] == 97


def test_nonzero_tail_cannot_be_silently_discarded():
    with pytest.raises(ValueError, match='zero tail'):
        module.parse_output(17, b'0000000004\n' + b'0000000000\n' * 98 + b'0000000001\n', {'logicalResultLength': 1})


def test_missing_array_slot_or_duplicate_is_rejected():
    for moves in [
        [f'MOVE {i} TO L-ARR({i})' for i in range(1, 8)],
        [f'MOVE {i} TO L-ARR({i})' for i in range(1, 9)] + ['MOVE 1 TO L-ARR(1)'],
        [f'MOVE {i} TO L-ARR({i})' for i in range(1, 9)] + ['MOVE 1 TO L-ARR(9)'],
    ]:
        row, driver = fixture(105, moves)
        with pytest.raises(ValueError):
            module.extract_case(105, row, driver, 0)


@pytest.mark.parametrize('text', ['', 'o  o', 'o\to', 'o x', 'ø'])
def test_unestablished_music_inputs_are_rejected(text):
    row, driver = fixture(17, [f"MOVE '{text}' TO L-MUSIC-STRING"])
    with pytest.raises(ValueError):
        module.extract_case(17, row, driver, 0)


def test_array_numeric_bounds_and_quoted_numbers_rejected():
    for value in ['100001', '1.1', "'1'"]:
        moves = [f'MOVE 1 TO L-ARR({i})' for i in range(1, 9)]
        moves[0] = f'MOVE {value} TO L-ARR(1)'
        row, driver = fixture(105, moves)
        with pytest.raises(ValueError):
            module.extract_case(105, row, driver, 0)


def test_extra_initialization_statement_rejected():
    row, driver = fixture(143, ['MOVE "This is a test" TO L-SENTENCE', 'COMPUTE EXTRA = 1'])
    with pytest.raises(ValueError):
        module.extract_case(143, row, driver, 0)


def test_source_driver_layout_change_cannot_be_hidden_by_matching_prefix():
    row, driver = fixture(143, ['MOVE "This is a test" TO L-SENTENCE'])
    driver = driver.replace('       PROCEDURE DIVISION.', '           05 EXTRA PIC 9.\n       PROCEDURE DIVISION.')
    with pytest.raises(ValueError, match='interface'):
        module.extract_case(143, row, driver, 0)


def test_signed_records_keep_negative_values_and_check_full_tail():
    raw = b'p000000001\n0000000002\n0000000003\n0000000004\n0000000005\n' + b'0000000000\n' * 95
    result, evidence = module.parse_output(145, raw, {'logicalResultLength': 5})
    assert result == [-1, 2, 3, 4, 5]
    assert evidence['logicalLengthDerivedFrom'] == 'source declaration'
    with pytest.raises(ValueError):
        module.parse_output(145, raw + b'0000000000\n', {'logicalResultLength': 5})


def test_string_normalization_only_removes_cobol_right_padding():
    result, _ = module.parse_output(143, b' leading internal  spaces   \n', {})
    assert result == ' leading internal  spaces'
    result, _ = module.parse_output(143, b'\n', {})
    assert result == ''
    with pytest.raises(ValueError):
        module.parse_output(143, b'abc\x00\n', {})


def test_comp2_does_not_infer_java_integer_boxing_from_literal_spelling():
    row, driver = fixture(151, ['MOVE 0.2 TO L-LST(1)', 'MOVE 3 TO L-LST(2)', 'MOVE 5 TO L-LST(3)'])
    case = module.extract_case(151, row, driver, 0)
    assert case['numericInputs'] == [[0.2, 3.0, 5.0]]
    assert 'Double for every COMP-2 field' in case['javaElementRuntimeType']
    assert 'doubles(args[0])' in module.probe(151)


def test_quoted_numeric_comp2_mapping_is_not_eligible():
    row, driver = fixture(99, ['MOVE "14.5" TO L-VALUE'])
    case = module.extract_case(99, row, driver, 0)
    assert case['mappingEligible'] is False
    assert case['arguments'] == ['14.5']


def test_java_result_type_guard_does_not_coerce_boolean_into_integer():
    assert module.valid_java_result(151, 34)
    assert not module.valid_java_result(151, True)
    assert not module.valid_java_result(17, [4, True])


def test_immutable_write_refuses_overwrite(tmp_path):
    path = tmp_path / 'plan.json'
    module.write_new(path, {'frozen': True})
    with pytest.raises(FileExistsError):
        module.write_new(path, {'frozen': False})
