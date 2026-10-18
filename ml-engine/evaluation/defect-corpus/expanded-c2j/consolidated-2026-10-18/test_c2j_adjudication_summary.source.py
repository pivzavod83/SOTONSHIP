"""Guard evidence aggregation and the human-review boundary."""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / 'scripts/summarize_c2j_adjudication.py'
SPEC = importlib.util.spec_from_file_location('c2j_adjudication_summary', PATH)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


def fixture():
    ids = [f'HumanEval/{n}' for n in range(23)]
    return ({'assignedFamilies': {'cohort': list(range(23))}},
            [{'taskId': task, 'disposition': 'no_mismatch'} for task in ids],
            {'developmentTaskIds': ids, 'finalHoldoutTaskIds': ['HumanEval/100'],
             'graphPartitioning': {'groups': [[task] for task in ids]}})


def test_every_family_requires_one_disposition():
    plan, families, partition = fixture()
    summary.validate_coverage(plan, families, partition)
    with pytest.raises(ValueError, match='exactly once'):
        summary.validate_coverage(plan, families[:-1], partition)
    with pytest.raises(ValueError, match='exactly once'):
        summary.validate_coverage(plan, families + families[:1], partition)


def test_reserved_task_cannot_be_promoted_into_development_report():
    plan, families, partition = fixture()
    partition['finalHoldoutTaskIds'].append('HumanEval/0')
    with pytest.raises(ValueError, match='reserved'):
        summary.validate_coverage(plan, families, partition)


def test_unknown_outcome_requires_explicit_interpretation():
    plan, families, partition = fixture()
    families[0]['disposition'] = 'probably_correct'
    with pytest.raises(ValueError, match='Unknown'):
        summary.validate_coverage(plan, families, partition)


def test_graph_component_keeps_related_tasks_together():
    partition = {'graphPartitioning': {'groups': [['HumanEval/40', 'HumanEval/43'], ['HumanEval/47']]}}
    assert summary.group_for('HumanEval/43', partition) == ['HumanEval/40', 'HumanEval/43']
    with pytest.raises(ValueError):
        summary.group_for('HumanEval/999', partition)


def witness_fixture():
    _, _, partition = fixture()
    rows = {'HumanEval/0': {'COBOL_canonical_solution': 'source', 'Java_canonical_solution': 'reference',
                           'tests': [{'test': 'original driver'}]}}
    outputs = {'7b': {'HumanEval/0': 'candidate'}}
    case = {'driverIndex': 0, 'driverSha256': summary.sha('original driver'), 'arguments': [1],
            'cobolResult': 1, 'cobolOutputSha256': summary.sha('1')}
    return rows, outputs, partition, case


def test_machine_witness_does_not_create_human_gold_label():
    rows, outputs, partition, case = witness_fixture()
    queue = {}
    summary.append_witness(queue, 'HumanEval/0', '7b', case, {'result': 2}, 'contract', 'numericA',
                           rows, outputs, partition)
    record = next(iter(queue.values()))
    assert record['humanReview']['decision'] == 'PENDING'
    assert record['humanReview']['reviewer'] is None
    assert record['trainingEligible'] is False
    assert record['witnesses'][0]['isIndependentDefectExample'] is False


def test_repeated_witness_cannot_inflate_program_count():
    rows, outputs, partition, case = witness_fixture()
    queue = {}
    args = (queue, 'HumanEval/0', '7b', case, {'result': 2}, 'contract', 'numericA', rows, outputs, partition)
    summary.append_witness(*args)
    with pytest.raises(ValueError, match='Duplicate witness'):
        summary.append_witness(*args)


def test_changed_driver_does_not_enter_review_queue():
    rows, outputs, partition, case = witness_fixture()
    case['driverSha256'] = summary.sha('modified driver')
    with pytest.raises(ValueError, match='unchanged'):
        summary.append_witness({}, 'HumanEval/0', '7b', case, {}, '', 'numericA', rows, outputs, partition)


def test_existing_evidence_and_changed_pinned_bytes_fail_closed(tmp_path):
    path = tmp_path / 'evidence.json'
    summary.write_new(path, {'original': True})
    with pytest.raises(FileExistsError):
        summary.write_new(path, {'original': False})
    with pytest.raises(ValueError, match='Pinned bytes'):
        summary.verified(path, '0' * 64)


def test_explicit_unsupported_family_has_no_candidate_observation():
    assert summary.variant_case({'adjudicationCode': 'UNSUPPORTED', 'javaVariants': {}}, '7b', 0) is None


@pytest.mark.parametrize('cases', [[], [{'driverIndex': 1}], [{'driverIndex': 0}, {'driverIndex': 0}]])
def test_missing_wrong_or_duplicate_supported_observation_rejected(cases):
    task = {'adjudicationCode': 'NO_MISMATCH_OBSERVED_SCOPED', 'javaVariants': {'7b': {'cases': cases}}}
    with pytest.raises(ValueError, match='exactly one'):
        summary.variant_case(task, '7b', 0)
