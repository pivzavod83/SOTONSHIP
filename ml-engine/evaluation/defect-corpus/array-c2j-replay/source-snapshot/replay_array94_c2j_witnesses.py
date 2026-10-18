#!/usr/bin/env python3
"""Exploratory same-input replay of original HumanEval/94 COBOL and Java.

This post-screening cohort is deliberately limited to the exact three existing
fully initialized six-integer drivers. No source repairs, mutations, new tests,
held-out tasks, LLM requests or model fitting are performed. Differences remain
machine-reproduced discrepancies pending independent review, never gold labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HELPERS = {
    'audit': ('audit_natural_c2j_candidates.py', '2bc1518b701f7f56ea58f4b14d74dd745336135908e792414879ff53cf6e4282'),
    'scalar': ('replay_scalar_c2j_witnesses.py', 'a93cb91eaed6d728032639f4b2971a483c9d10773e440ac45b94e0fc0660ea74'),
}


def helper(name: str):
    import hashlib
    filename, expected = HELPERS[name]
    path = ROOT / 'scripts' / filename
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f'Helper source changed: {filename}')
    spec = importlib.util.spec_from_file_location(f'array94_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = helper('audit')
scalar = helper('scalar')
LAYOUT = r'01\s+LINKED-ITEMS\.\s*05\s+L-LST\s+OCCURS\s+6\s+TIMES\s+INDEXED\s+BY\s+NI\s+PIC\s+S9\(10\)\.\s*05\s+RESULT\s+PIC\s+S9\(10\)\.'
PROBE = ('import java.util.*;\npublic final class Array94Replay { public static void main(String[] args) { '
         'List<Integer> values = new ArrayList<>(); for (String value : args) values.add(Integer.parseInt(value)); '
         'System.out.print(new Solution().skjkasdkd(values)); } }\n')


def new_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write('\n')


def extract_case(source: str, driver: str, index: int) -> dict:
    text = scalar.code_lines(source)
    section = re.search(r'LINKAGE SECTION\.(.*?)PROCEDURE DIVISION USING LINKED-ITEMS\.', text, re.S)
    if not section or not re.fullmatch(LAYOUT, section[1].strip()):
        raise ValueError('Unexpected original COBOL six-integer linkage.')
    body = scalar.code_lines(driver)
    section = re.search(r'(01\s+LINKED-ITEMS\..*?)PROCEDURE DIVISION\.', body, re.S)
    if not section or not re.fullmatch(LAYOUT, section[1].strip()):
        raise ValueError('Driver linkage differs from original source.')
    procedure = body.split('PROCEDURE DIVISION.', 1)[1]
    calls = re.findall(r'CALL\s+"([A-Z0-9-]+)"\s+USING\s+LINKED-ITEMS', procedure)
    if calls != ['SKJKASDKD']:
        raise ValueError('Driver must call only the exact original program.')
    before = procedure.split('CALL', 1)[0]
    moves = re.findall(r'MOVE\s+(-?\d+)\s+TO\s+L-LST\((\d+)\)\s*\.?', before)
    rest = re.sub(r'MOVE\s+-?\d+\s+TO\s+L-LST\(\d+\)\s*\.?', '', before)
    if rest.strip() or len(moves) != 6 or {int(i) for _, i in moves} != set(range(1, 7)):
        raise ValueError('All six positions must be initialized exactly once by integer literals.')
    mapped = {int(i): int(value) for value, i in moves}
    values = [mapped[i] for i in range(1, 7)]
    if any(not -(2**31) <= v < 2**31 for v in values):
        raise ValueError('An input is outside the shared Java-int and COBOL S9(10) range.')
    names = re.findall(r'SELECT OUTPUT-FILE ASSIGN TO "([A-Z0-9_-]+\.TXT)"', body)
    if names != ['SKJKASDKD.TXT'] or not re.search(r'01\s+OUTPUT-RECORD\s+PIC\s+S9\(10\)\s+SIGN\s+LEADING\.', body):
        raise ValueError('Unsupported output path or non-full-width signed output.')
    after = procedure.split('CALL', 1)[1]
    if len(re.findall(r'MOVE RESULT TO OUTPUT-RECORD', after)) != 1:
        raise ValueError('Result must be copied directly to the output record.')
    return {'driverIndex': index, 'arguments': values, 'driverSha256': audit.sha(driver),
            'outputFile': names[0], 'outputPic': 'S9(10) SIGN LEADING'}


def inputs(cache: Path, partition: Path):
    provenance, rows, candidates = audit.load_sources(cache, False)
    plan = audit.load_partition(partition, rows)
    position = next(i for i, row in enumerate(rows) if row['task_id'] == 'HumanEval/94')
    row = rows[position]
    scalar.require_development(row['task_id'], plan)
    if len(row['tests']) != 3:
        raise ValueError('The exact three original drivers are required.')
    for values in candidates.values():
        if not audit.join_evidence(row, values[position]['completion'])['methodAgreement']:
            raise ValueError('Candidate class/method disagrees with pinned task interface.')
    return provenance, row, candidates, position


def prepare(cache: Path, partition: Path, target: Path) -> dict:
    provenance, row, candidates, position = inputs(cache, partition)
    frozen = {
        'schemaVersion': 1, 'status': 'FROZEN_EXPLORATORY_POST_SCREENING_BEFORE_ARRAY_REPLAY',
        'createdAt': datetime.now(timezone.utc).isoformat(), 'taskId': row['task_id'], 'rowOrdinalZeroBased': position,
        'cohortSelection': 'Exploratory selection after Java-only screening and source inspection; not an unbiased evaluation cohort.',
        'artifacts': provenance, 'partitionSha256': audit.PARTITION_SHA,
        'scriptSha256': audit.sha(Path(__file__).read_bytes()),
        'helpers': {name: {'filename': spec[0], 'sha256': spec[1]} for name, spec in HELPERS.items()},
        'javaProbeSha256': audit.sha(PROBE),
        'sourceHashes': {'cobol': audit.sha(row['COBOL_canonical_solution']),
                         'canonical': audit.sha(row['Java_canonical_solution']),
                         **{name: audit.sha(values[position]['completion']) for name, values in candidates.items()}},
        'commonInputContract': 'Exactly six fully initialized integer elements, in COBOL occurrence order; Java List<Integer> length6; original drivers only.',
        'commonOutputContract': 'Integer result: direct original RESULT->OUTPUT-RECORD, signed S9(10), strict GNU ASCII sign decoding; Java int return.',
        'cases': [extract_case(row['COBOL_canonical_solution'], item['test'], i) for i, item in enumerate(row['tests'])],
        'sourceRewritesPerformed': False, 'originalExpectedMetadataUsedAsOracle': False,
        'reservedTasksExecuted': 0, 'modelTrainingPerformed': False,
    }
    new_json(target, frozen)
    return frozen


def run(frozen_path: Path, report_path: Path, raw: Path, cache: Path, partition: Path,
        cobc: Path, jdk: Path) -> dict:
    frozen = json.loads(frozen_path.read_bytes())
    provenance, row, candidates, position = inputs(cache, partition)
    if (frozen['status'] != 'FROZEN_EXPLORATORY_POST_SCREENING_BEFORE_ARRAY_REPLAY'
            or frozen['scriptSha256'] != audit.sha(Path(__file__).read_bytes())
            or frozen['artifacts'] != provenance or frozen['partitionSha256'] != audit.sha(partition.read_bytes())):
        raise ValueError('Frozen script/artifact/partition provenance differs.')
    cases = [extract_case(row['COBOL_canonical_solution'], item['test'], i) for i, item in enumerate(row['tests'])]
    if frozen['cases'] != cases or frozen['javaProbeSha256'] != audit.sha(PROBE):
        raise ValueError('Frozen inputs or adapter changed.')
    raw.mkdir(parents=True, exist_ok=False)
    tools = {}
    for name, binary in {'cobc': cobc, 'java': jdk / 'java', 'javac': jdk / 'javac'}.items():
        version = audit.process([str(binary), '--version' if name == 'cobc' else '-version'], raw, name, 10)
        if version['returnCode'] or version['timedOut']:
            raise ValueError(f'Toolchain unavailable: {name}')
        tools[name] = {'path': str(binary), 'sha256': audit.sha(binary.read_bytes()), 'version': version,
                       'versionText': (raw / f'{name}.stdout').read_text() + (raw / f'{name}.stderr').read_text()}
    (raw / 'source.cob').write_text(row['COBOL_canonical_solution'])
    variants = {'canonical': row['Java_canonical_solution'],
                **{name: values[position]['completion'] for name, values in candidates.items()}}
    java = {}
    for name, source in variants.items():
        if audit.DANGEROUS.search(audit.strip_comments(source)):
            raise ValueError('Source requires further execution review.')
        folder = raw / name
        folder.mkdir()
        (folder / 'Solution.java').write_text(source)
        (folder / 'Array94Replay.java').write_text(PROBE)
        compilation = audit.process([str(jdk / 'javac'), '-J-Xmx128m', '-J-XX:ActiveProcessorCount=1',
                                     '-proc:none', '-encoding', 'UTF-8', 'Solution.java', 'Array94Replay.java'], folder, 'compile', 15)
        java[name] = {'javaSourceSha256': audit.sha(source), 'compilation': compilation, 'cases': []}
    outcomes = []
    for case in cases:
        folder = raw / f"driver-{case['driverIndex']}"
        folder.mkdir()
        (folder / 'driver.cob').write_text(row['tests'][case['driverIndex']]['test'])
        compilation = audit.process([str(cobc), '-w', '-fformat=variable', '-x', '-o', 'replay', 'driver.cob', '../source.cob'], folder, 'compile', 15)
        observed = {**case, 'cobolCompilation': compilation, 'status': 'NOT_COMPARABLE'}
        if compilation['returnCode'] == 0 and not compilation['timedOut']:
            execution = audit.process([str(folder / 'replay')], folder, 'run', 5)
            observed['cobolExecution'] = execution
            if execution['returnCode'] == 0 and not execution['timedOut'] and (folder / case['outputFile']).is_file():
                output = (folder / case['outputFile']).read_bytes()
                observed['cobolOutputHex'] = output.hex()
                observed['cobolOutputSha256'] = audit.sha(output)
                observed['cobolResult'] = scalar.parse_cobol_output(output, 'int')
                if not -(2**31) <= observed['cobolResult'] < 2**31:
                    raise ValueError('COBOL output outside shared Java integer range.')
                observed['status'] = 'OBSERVED'
        for name, variant in java.items():
            entry = {'driverIndex': case['driverIndex'], 'status': 'NOT_COMPARABLE'}
            if variant['compilation']['returnCode'] == 0 and not variant['compilation']['timedOut']:
                execution = audit.process([str(jdk / 'java'), '-Xmx128m', '-Xss1m', '-XX:ActiveProcessorCount=1',
                                           '-XX:+UseSerialGC', '-ea', '-cp', str(raw / name), 'Array94Replay',
                                           *map(str, case['arguments'])], raw / name, f"case-{case['driverIndex']}", 5)
                entry['execution'] = execution
                output = (raw / name / f"case-{case['driverIndex']}.stdout").read_bytes()
                if execution['returnCode'] == 0 and not execution['timedOut'] and re.fullmatch(rb'-?\d+', output):
                    entry.update(status='OBSERVED', result=int(output))
                else:
                    entry['status'] = 'EXECUTION_OR_OUTPUT_FAILURE'
            variant['cases'].append(entry)
        reference = java['canonical']['cases'][-1]
        control = (observed['status'] == reference['status'] == 'OBSERVED'
                   and observed['cobolResult'] == reference['result'])
        observed['canonicalControl'] = 'AGREES' if control else 'QUARANTINED'
        for name in candidates:
            entry = java[name]['cases'][-1]
            entry['comparison'] = ('AGREEMENT' if entry.get('result') == observed.get('cobolResult')
                                   else 'MISMATCH_PENDING_REVIEW') if control and entry['status'] == 'OBSERVED' else 'NOT_COMPARABLE'
        outcomes.append(observed)
    result = {'schemaVersion': 1, 'status': 'EXPLORATORY_MACHINE_REPLAY_PENDING_INDEPENDENT_REVIEW',
              'taskId': row['task_id'], 'frozenContractSha256': audit.sha(frozen_path.read_bytes()),
              'scriptSha256': audit.sha(Path(__file__).read_bytes()), 'helpers': frozen['helpers'],
              'toolchain': tools, 'rawEvidenceDirectory': str(raw), 'sourceHashes': frozen['sourceHashes'],
              'cohortSelection': frozen['cohortSelection'], 'cases': outcomes, 'javaVariants': java,
              'candidateSummary': {name: dict(Counter(c['comparison'] for c in java[name]['cases'])) for name in candidates},
              'originalExpectedMetadataUsedAsOracle': False, 'sourceRewritesPerformed': False,
              'independentHumanReviewsPerformed': 0, 'admittedDefectTrainingLabels': 0,
              'reservedTasksExecuted': 0, 'modelTrainingPerformed': False,
              'limitations': ['Actual same-input differences are pending independent review; these are not human-reviewed gold labels.',
                              'The three related inputs belong to one original task family, not three independent defects.',
                              'This cohort was selected after screening and cannot estimate overall defect prevalence or detector accuracy.',
                              'Agreement is finite compatibility, not formal equivalence.']} 
    new_json(report_path, result)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'run'])
    p.add_argument('--contract', required=True, type=Path)
    p.add_argument('--report', type=Path)
    p.add_argument('--raw', type=Path)
    p.add_argument('--cache', type=Path, default=ROOT / 'evaluation/corpora/natural-c2j')
    p.add_argument('--partition', type=Path, default=ROOT / 'evaluation/paired-code/cv-partition-plan.json')
    p.add_argument('--cobc', type=Path, default=Path('/private/tmp/sotonship-cobol-toolchain/install/bin/cobc'))
    p.add_argument('--jdk', type=Path, default=Path('/Users/volodymyrsydorenko/Developer/jdk-21.0.10.jdk/Contents/Home/bin'))
    a = p.parse_args()
    if a.action == 'prepare':
        result = prepare(a.cache, a.partition, a.contract)
        print(json.dumps({'status': result['status'], 'cases': len(result['cases'])}))
    else:
        if not a.report or not a.raw:
            p.error('run requires --report and --raw')
        result = run(a.contract, a.report, a.raw.resolve(), a.cache, a.partition, a.cobc, a.jdk)
        print(json.dumps(result['candidateSummary']))


if __name__ == '__main__':
    main()
