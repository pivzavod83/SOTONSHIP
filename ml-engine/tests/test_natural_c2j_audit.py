"""Fail-closed checks for provenance, grouping and natural-translation screening."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/audit_natural_c2j_candidates.py'
spec = importlib.util.spec_from_file_location('natural_c2j_audit', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_modified_artifact_rejected(tmp_path):
    path = tmp_path / 'artifact'
    path.write_bytes(b'original')
    audit.verified_bytes(path, audit.sha(b'original'))
    path.write_bytes(b'edited')
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        audit.verified_bytes(path, audit.sha(b'original'))


def test_wrong_method_quarantined_despite_matching_class():
    row = {'Java_prompt': 'class Solution { public int countUpper(String x) {'}
    ok = audit.join_evidence(row, 'class Solution { public int countUpper(String x) { return 0; }}')
    bad = audit.join_evidence(row, 'class Solution { public int closestInteger(String x) { return 0; }}')
    assert ok['status'] == 'ORDINAL_WITH_METHOD_CLASS_AGREEMENT'
    assert bad['status'] == 'JOIN_UNRESOLVED'
    assert not bad['independentTaskIdPresentInOutput']


def test_comments_do_not_falsely_supply_method_identity():
    row = {'Java_prompt': 'class Solution { public int wanted() {'}
    bad = audit.join_evidence(row, 'class Solution { /* public int wanted() */ public int other() { return 1; }}')
    assert bad['status'] == 'JOIN_UNRESOLVED'


def test_partition_overlap_or_missing_task_rejected(tmp_path):
    rows = [{'task_id': str(i)} for i in range(143)]
    plan = {'developmentTaskIds': [str(i) for i in range(120)],
            'finalHoldoutTaskIds': [str(i) for i in range(120, 143)]}
    path = tmp_path / 'partition.json'
    path.write_text(json.dumps(plan))
    assert audit.load_partition(path, rows, audit.sha(path.read_bytes())) == plan
    plan['finalHoldoutTaskIds'][0] = '0'
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match='partition'):
        audit.load_partition(path, rows, audit.sha(path.read_bytes()))


@pytest.mark.parametrize('compile_result,run_result,stderr,expected', [
    ({'timedOut': True, 'returnCode': -9}, None, '', 'COMPILE_TIMEOUT'),
    ({'timedOut': False, 'returnCode': 1}, None, '', 'COMPILE_ERROR'),
    ({'timedOut': False, 'returnCode': 0}, {'timedOut': True, 'returnCode': -9}, '', 'EXECUTION_TIMEOUT'),
    ({'timedOut': False, 'returnCode': 0}, {'timedOut': False, 'returnCode': 1}, 'java.lang.AssertionError', 'JAVA_TEST_ASSERTION_FAILURE'),
    ({'timedOut': False, 'returnCode': 0}, {'timedOut': False, 'returnCode': 1}, 'java.lang.NullPointerException', 'JAVA_RUNTIME_FAILURE'),
    ({'timedOut': False, 'returnCode': 0}, {'timedOut': False, 'returnCode': 1}, 'java.lang.OutOfMemoryError', 'RESOURCE_FAILURE'),
    ({'timedOut': False, 'returnCode': 0}, {'timedOut': False, 'returnCode': 0}, '', 'JAVA_TESTS_PASS_ONLY'),
])
def test_screening_outcomes_are_distinct(compile_result, run_result, stderr, expected):
    assert audit.classify(compile_result, run_result, stderr) == expected


def test_missing_execution_after_compile_cannot_be_pass():
    with pytest.raises(ValueError, match='requires a recorded execution'):
        audit.classify({'timedOut': False, 'returnCode': 0}, None)


def test_execution_review_blocks_side_effects(tmp_path):
    result = audit.run_java('class Solution { void x() { Runtime.getRuntime(); }}',
                            'public class Main {}', tmp_path / 'blocked', tmp_path / 'no-jdk')
    assert result['status'] == 'STATIC_EXECUTION_REVIEW_REQUIRED'
    assert result['executionPerformed'] is False
    assert not (tmp_path / 'blocked' / 'Solution.java').exists()


def test_process_timeout_and_logs(tmp_path):
    import sys
    result = audit.process([sys.executable, '-c', 'while True: pass'], tmp_path, 'fixture', .15)
    assert result['timedOut']
    assert result['returnCode'] != 0
    assert (tmp_path / 'fixture.stderr').exists()


def test_inventory_keeps_all_reserved_without_execution():
    row = {'task_id': 'reserved', 'COBOL_canonical_solution': 'COBOL', 'Java_tests': 'tests',
           'Java_prompt': 'class Solution { public int x() {', 'Java_canonical_solution': 'reference'}
    outputs = {'7b': [{'completion': 'class Solution { public int x() { return 1; }}'}],
               '14b': [{'completion': 'class Solution { public int x() { return 2; }}'}]}
    entries = audit.inventory([row], outputs, {'developmentTaskIds': []})
    assert len(entries) == 3
    assert all(e['partition'] == 'reserved' and not e.get('executionPerformed') for e in entries)
