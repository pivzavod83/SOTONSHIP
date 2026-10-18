"""Build a coverage summary and pending-review queue from immutable replays.

This command reads evidence only. It never executes programs, trains a model,
creates approval votes, or promotes machine observations to human gold labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'evaluation/defect-corpus'
PARTITION_SHA = 'a191deec018fe29d873fa6183d4bb6b366d36f7dd4424e769048ba63f7f57e53'
DATA_SHA = 'ff1b2e308ea006d905fd979103f32486c57d586c5fdbc0325a23f8ae23a6530d'
OUTPUT_SHAS = {'7b': 'f2a640f57159d257de6d6c3fdbd5af970ef447ab4fb24a72b928e7f77b76dba6',
               '14b': '5282a929afc7b0e0775f2f2109805a19052f8885e8143d81f7736b24906f4c41'}
PATHS = {
    'plan': 'expanded-c2j/run-plan-2026-10-18.json',
    'previous': 'natural-c2j-audit-summary-2026-10-18.json',
    'numericA': 'expanded-c2j/numeric-a/adjudication-2026-10-18.json',
    'numericAFamilies': 'expanded-c2j/numeric-a/family-dispositions.json',
    'numericB': 'expanded-c2j/numeric-b/replay-2026-10-18/replay-report.json',
    'text': 'expanded-c2j/text/replay-report.json',
    'oldText': 'text-c2j-replay/exploratory-98-2026-10-18/replay-report.json',
    'oldArray': 'array-c2j-replay/replay-2026-10-18.json',
}
DISPOSITIONS = {
    'no_mismatch': 'NO_MISMATCH_WITHIN_CONTRACT',
    'NO_SOURCE_DISCREPANCY_OBSERVED_WITHIN_CONTRACT': 'NO_MISMATCH_WITHIN_CONTRACT',
    'source_diff_control_agrees': 'DISCREPANCY_WITH_AGREEING_CONTROL',
    'SOURCE_DISCREPANCY_OBSERVED_PENDING_INDEPENDENT_REVIEW': 'DISCREPANCY_WITH_AGREEING_CONTROL',
    'source_diff_reference_conflict': 'REFERENCE_OR_REPRESENTATION_CONFLICT',
    'SOURCE_AGREEMENT_WITH_REFERENCE_POLICY_CONFLICT': 'REFERENCE_OR_REPRESENTATION_CONFLICT',
    'SOURCE_DIVERGENCE_WITH_REFERENCE_POLICY_CONFLICT_PENDING_REVIEW': 'REFERENCE_OR_REPRESENTATION_CONFLICT',
    'unsupported': 'UNSUPPORTED_MAPPING',
}


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def verified(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError(f'Pinned bytes changed: {path}')
    return raw


def validate_coverage(plan: dict, families: list[dict], partition: dict) -> None:
    expected = {f'HumanEval/{number}' for values in plan['assignedFamilies'].values() for number in values}
    actual = [row['taskId'] for row in families]
    if len(actual) != len(set(actual)) or set(actual) != expected or len(actual) != 23:
        raise ValueError('Every one of the 23 assigned families must occur exactly once')
    if not expected <= set(partition['developmentTaskIds']) or expected & set(partition['finalHoldoutTaskIds']):
        raise ValueError('Review queue must exclude reserved task families')
    if any(row['disposition'] not in DISPOSITIONS for row in families):
        raise ValueError('Unknown disposition must be interpreted explicitly')


def group_for(task_id: str, partition: dict) -> list[str]:
    matches = [group for group in partition['graphPartitioning']['groups'] if task_id in group]
    if len(matches) != 1:
        raise ValueError('Task must belong to exactly one frozen graph component')
    return matches[0]


def variant_case(task: dict, variant: str, driver_index: int) -> dict | None:
    if task['adjudicationCode'] == 'UNSUPPORTED':
        return None
    matches = [case for case in task.get('javaVariants', {}).get(variant, {}).get('cases', [])
               if case['driverIndex'] == driver_index]
    if len(matches) != 1:
        raise ValueError('Supported input must have exactly one candidate outcome')
    return matches[0]


def append_witness(queue: dict, task_id: str, variant: str, case: dict, observed: dict,
                   contract, report_name: str, rows: dict, outputs: dict, partition: dict) -> None:
    if task_id not in partition['developmentTaskIds'] or task_id in partition['finalHoldoutTaskIds']:
        raise ValueError('Reserved source cannot enter a review packet')
    if variant not in OUTPUT_SHAS:
        raise ValueError('Only generated candidates enter the defect queue')
    index = case['driverIndex']
    row = rows[task_id]
    if sha(row['tests'][index]['test']) != case['driverSha256']:
        raise ValueError('Witness must bind an unchanged original driver')
    key = task_id, variant
    if key not in queue:
        source_sha = sha(row['COBOL_canonical_solution'])
        target_sha = sha(outputs[variant][task_id])
        queue[key] = {'reviewId': sha(source_sha + ':' + target_sha)[:24], 'taskId': task_id,
                      'variant': variant, 'splitGroupTaskIds': group_for(task_id, partition),
                      'cobolSourceSha256': source_sha, 'candidateJavaSha256': target_sha,
                      'canonicalJavaSha256': sha(row['Java_canonical_solution']),
                      'machineStatus': 'REPRODUCED_DISCREPANCY_PENDING_INDEPENDENT_REVIEW',
                      'humanReview': {'decision': 'PENDING', 'reviewer': None, 'reviewedAt': None,
                                      'reason': None, 'validatedFaultSpans': []},
                      'trainingEligible': False, 'witnesses': []}
    if any(w['driverIndex'] == index for w in queue[key]['witnesses']):
        raise ValueError('Duplicate witness must not inflate a review packet')
    execution = observed.get('execution', {})
    queue[key]['witnesses'].append({
        'driverIndex': index, 'driverSha256': case['driverSha256'],
        'input': case.get('arguments', case.get('input')),
        'cobolResult': case['cobolResult'], 'cobolOutputSha256': case['cobolOutputSha256'],
        'javaResult': observed.get('result', observed.get('javaResult')),
        'exceptionType': observed.get('exceptionType'), 'exceptionMessage': observed.get('exceptionMessage'),
        'javaStdoutSha256': execution.get('stdoutSha256'), 'javaStderrSha256': execution.get('stderrSha256'),
        'contract': contract, 'sourceReport': PATHS[report_name],
        'canonicalControl': 'AGREES', 'isIndependentDefectExample': False})


def build() -> tuple[dict, dict]:
    reports, evidence = {}, {}
    for name, relative in PATHS.items():
        raw = (BASE / relative).read_bytes()
        reports[name] = json.loads(raw)
        evidence[name] = {'path': str((BASE / relative).relative_to(ROOT.parent)), 'sha256': sha(raw)}
    partition = json.loads(verified(ROOT / 'evaluation/paired-code/cv-partition-plan.json', PARTITION_SHA))
    raw_rows = [json.loads(line) for line in verified(ROOT / 'evaluation/corpora/natural-c2j/COBOL-JavaTrans.jsonl', DATA_SHA).splitlines()]
    rows = {row['task_id']: row for row in raw_rows}
    outputs = {}
    for variant, digest in OUTPUT_SHAS.items():
        raw = verified(ROOT / f'evaluation/corpora/natural-c2j/translation_COBOL_to_Java_COBOL-Coder_{variant}.jsonl', digest)
        values = [json.loads(line)['completion'] for line in raw.splitlines()]
        if len(values) != len(raw_rows) or len(rows) != 143:
            raise ValueError('Pinned positional correspondence is incomplete')
        outputs[variant] = dict(zip(rows, values))
    families = (reports['numericAFamilies']['familyDispositions']
                + reports['numericB']['familyDispositions'] + reports['text']['familyDispositions'])
    validate_coverage(reports['plan'], families, partition)
    if reports['plan']['previousSummary']['sha256'] != evidence['previous']['sha256']:
        raise ValueError('Previous evidence changed after expansion plan was frozen')
    if reports['numericAFamilies']['sourceReportSha256'] != evidence['numericA']['sha256']:
        raise ValueError('Normalized numeric-A report does not bind its execution report')
    for name, field in [('numericA', 'reservedTasksExecuted'), ('numericB', 'heldoutTasksExecuted'), ('text', 'reservedTasksExecuted')]:
        if reports[name][field] != 0:
            raise ValueError('Reserved execution invalidates this development-only audit')

    queue = {}
    def add(task, variant, case, observed, contract, report):
        append_witness(queue, task, variant, case, observed, contract, report, rows, outputs, partition)
    for case in reports['oldText']['records']:
        for variant in OUTPUT_SHAS:
            target = case['java'][variant]
            if case['status'] == 'SHARED_INPUT_REPLAY' and target.get('agreesWithCobol') is False:
                add('HumanEval/98', variant, case, target, 'Frozen ASCII text98 contract', 'oldText')
    old_array = reports['oldArray']
    for case in old_array['cases']:
        for variant in OUTPUT_SHAS:
            target = next(c for c in old_array['javaVariants'][variant]['cases'] if c['driverIndex'] == case['driverIndex'])
            if case['canonicalControl'] == 'AGREES' and target['comparison'] == 'MISMATCH_PENDING_REVIEW':
                add(old_array['taskId'], variant, case, target, 'Frozen six-integer array94 contract', 'oldArray')
    for task in reports['numericA']['tasks']:
        for case in task['cases']:
            for variant in OUTPUT_SHAS:
                target = variant_case(task, variant, case['driverIndex'])
                if target is None:
                    continue
                if case.get('canonicalControl') == 'AGREES' and target.get('comparison') == 'MISMATCH_PENDING_REVIEW':
                    add(task['taskId'], variant, case, target, task['contract'], 'numericA')
    for task in reports['numericB']['tasks']:
        for case in task['cases']:
            for variant in OUTPUT_SHAS:
                target = case['java'][variant]
                if (case['canonicalReferenceAgreesWithSource'] and target.get('status') == 'CANDIDATE_PROGRAM_EXCEPTION'
                        and target.get('deterministicCandidateOrigin')):
                    add(task['taskId'], variant, case, target, task['contract'], 'numericB')
                elif case['canonicalReferenceAgreesWithSource'] and target.get('classification') == 'SOURCE_DIVERGENCE_CONTROL_AGREES':
                    add(task['taskId'], variant, case, target, task['contract'], 'numericB')
    for task in reports['text']['tasks']:
        for case in task['records']:
            for variant in OUTPUT_SHAS:
                target = case['java'][variant]
                if (case['mappingEligible'] and case['canonicalControl'] == 'AGREES'
                        and target.get('classification') in {'BEHAVIOR_MISMATCH_PENDING_REVIEW', 'RUNTIME_FAILURE_PENDING_REVIEW'}):
                    add(task['taskId'], variant, case, target, task['contract'], 'text')
    ordered = sorted(queue.values(), key=lambda row: (int(row['taskId'].split('/')[1]), row['variant']))
    counts = Counter(DISPOSITIONS[family['disposition']] for family in families)
    summary = {
        'schemaVersion': 1, 'status': 'EXPANDED_EXPLORATORY_ADJUDICATION_COMPLETED',
        'scriptSha256': sha(Path(__file__).read_bytes()), 'evidence': evidence,
        'remainingFlaggedFamiliesBeforeThisRun': 23, 'familiesWithExplicitDisposition': len(families),
        'untriagedFlaggedFamilies': 0, 'familyDispositionCounts': dict(counts),
        'familyDispositions': [{**family, 'normalizedDisposition': DISPOSITIONS[family['disposition']]} for family in families],
        'strongSourceDiscrepancies': {'candidatePrograms': len(ordered), 'sourceTaskFamilies': len({r['taskId'] for r in ordered}),
                                    'inputWitnesses': sum(len(row['witnesses']) for row in ordered),
                                    'programs': [{'taskId': row['taskId'], 'variant': row['variant'], 'witnesses': len(row['witnesses'])} for row in ordered]},
        'reservedFamilies': 23, 'reservedExecutions': 0, 'modelTrainingPerformed': False,
        'independentHumanReviews': 0, 'goldTrainingLabelsAdmitted': 0,
        'trainingReadiness': 'Six source-task groups with machine-reproduced discrepancies support a pilot corpus. They do not establish a reliable supervised defect-detector evaluation. Review is pending; no model was fitted.',
        'limitations': ['All expansion families were selected after Java screening; this is not a prevalence or model-accuracy estimate.',
                        'No mismatch means finite compatibility only within each frozen input/output contract.',
                        'Reference-policy and representation conflicts remain excluded from the strong review queue.',
                        'Input witnesses from one program are grouped; they are not independent faulty programs.',
                        'Original23 reserved tasks have historical retrieval exposure; they remain unexecuted in these audits.']}
    review = {'schemaVersion': 1, 'status': 'PENDING_INDEPENDENT_REVIEW', 'evidence': evidence,
              'reviewInstructions': ['Read the exact source/candidate, frozen contract and raw replay evidence linked by each witness.',
                                     'Check shared input representation, observable output scope and whether the behavior change is an intentional migration policy.',
                                     'Record an actual reviewer identity, decision and reason in a new versioned artifact; do not fabricate approval.',
                                     'Only validated fault spans are localization labels. Candidate source/model names, test outcomes and reference Java are not static-detector features.'],
              'trainingPerformed': False, 'cases': ordered}
    return summary, review


def write_new(path: Path, data: dict) -> None:
    with path.open('x') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; completed evidence refuses overwrite')
    args = parser.parse_args()
    summary, queue = build()
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / 'summary.json', summary)
    write_new(args.output / 'review-queue.json', queue)
    (args.output / 'summarize_c2j_adjudication.source.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'familyDispositionCounts': summary['familyDispositionCounts'],
                      'strongSourceDiscrepancies': summary['strongSourceDiscrepancies']}, indent=2))


if __name__ == '__main__':
    main()
