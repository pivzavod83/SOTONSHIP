"""Explore one frozen ASCII-text contract using unchanged upstream programs.

This cohort was selected AFTER Java screening and is exploratory. It uses only
HumanEval/98 development drivers. No reference answer is used as the oracle.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
TASK = 'HumanEval/98'
PROBE = ('public final class TextReplay { public static void main(String[] args) { '
         'System.out.print(new Solution().countUpper(args[0])); } }\n')


def helper(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = helper('audit_natural_c2j_candidates')
scalar = helper('replay_scalar_c2j_witnesses')


def write_new(path: Path, content: dict) -> None:
    with path.open('x') as stream:
        json.dump(content, stream, indent=2, allow_nan=False)
        stream.write('\n')


def extract_input(row: dict, driver: str) -> str:
    source = scalar.code_lines(row['COBOL_canonical_solution'])
    text = scalar.code_lines(driver)
    layout = r'01\s+LINKED-ITEMS\.\s+05\s+L-S\s+PIC X\(100\)\.\s+05\s+RESULT\s+PIC S9\(10\)\.'
    if not re.search(layout, source) or not re.search(layout, text):
        raise ValueError('Unexpected source/driver linkage schema')
    if 'PROCEDURE DIVISION USING LINKED-ITEMS.' not in source:
        raise ValueError('Unexpected source procedure interface')
    body = text.split('PROCEDURE DIVISION.', 1)[1]
    prefix, suffix = body.split('CALL "COUNT-UPPER" USING LINKED-ITEMS', 1)
    match = re.fullmatch(r"\s*MOVE '([^']*)' TO L-S\s*", prefix)
    if not match:
        raise ValueError('Expected exactly one literal input MOVE')
    value = match[1]
    if not 0 < len(value) <= 100 or not re.fullmatch(r'[A-Za-z]+', value):
        raise ValueError('Contract requires 1..100 ASCII letters; no padding/escape ambiguity')
    if re.search(r'\bCALL\b', suffix):
        raise ValueError('Expected exactly one source invocation')
    if len(re.findall(r'MOVE RESULT TO OUTPUT-RECORD', suffix)) != 1:
        raise ValueError('Expected direct result serialization')
    if not re.search(r'01\s+OUTPUT-RECORD PIC S9\(10\) SIGN LEADING\.', text):
        raise ValueError('Unexpected output representation')
    audit_guard = helper('audit_cobol_references')
    if audit_guard.source_preflight(row['COBOL_canonical_solution'], driver) != 'COUNT-UPPER.TXT':
        raise ValueError('Unexpected output file')
    return value


def inputs(cache: Path, partition: Path):
    provenance, rows, outputs = audit.load_sources(cache, False)
    split = audit.load_partition(partition, rows)
    scalar.require_development(TASK, split)
    position, row = next((i, row) for i, row in enumerate(rows) if row['task_id'] == TASK)
    for name, values in outputs.items():
        if not audit.join_evidence(row, values[position]['completion'])['methodAgreement']:
            raise ValueError(f'Unresolved ordinal/interface mapping: {name}')
    return provenance, row, {name: values[position]['completion'] for name, values in outputs.items()}


def prepare(args):
    provenance, row, outputs = inputs(args.cache, args.partition)
    cases, rejected = [], []
    for i, driver in enumerate(row['tests']):
        try:
            value = extract_input(row, driver['test'])
            cases.append({'driverIndex': i, 'input': value, 'driverSha256': audit.sha(driver['test'])})
        except ValueError as error:
            rejected.append({'driverIndex': i, 'reason': str(error)})
    args.output.mkdir(parents=True, exist_ok=False)
    snapshots = args.output / 'source-snapshot'
    snapshots.mkdir()
    hashes = {}
    for name in ('replay_text_c2j_witnesses', 'replay_scalar_c2j_witnesses',
                 'audit_natural_c2j_candidates', 'audit_cobol_references'):
        script = ROOT / 'scripts' / (name + '.py')
        shutil.copyfile(script, snapshots / script.name)
        hashes[name + '.py'] = audit.sha(script.read_bytes())
    plan = {'schemaVersion': 1, 'preparedAtUtc': datetime.now(timezone.utc).isoformat(),
            'selection': 'EXPLORATORY_SELECTED_AFTER_DEVELOPMENT_JAVA_SCREENING',
            'taskId': TASK, 'partitionSha256': audit.PARTITION_SHA, 'artifacts': provenance,
            'contract': 'One fresh invocation; original driver ASCII letters 1..100 mapped to Java String and COBOL PIC X(100) with right-space padding. Source stops at first space; no input contains spaces. Exact integer result comparison.',
            'cases': cases, 'rejectedCases': rejected, 'scriptHashes': hashes,
            'cobolSourceSha256': audit.sha(row['COBOL_canonical_solution']),
            'canonicalJavaSha256': audit.sha(row['Java_canonical_solution']),
            'candidateJavaSha256': {name: audit.sha(source) for name, source in outputs.items()},
            'probeSha256': audit.sha(PROBE), 'independentHumanReviews': 0,
            'expectedAnswerMetadataUsedAsOracle': False, 'holdoutExecutionPermitted': False}
    write_new(args.output / 'frozen-plan.json', plan)
    print(json.dumps({'preparedCases': len(cases), 'rejectedCases': len(rejected),
                      'frozenPlanSha256': audit.sha((args.output / 'frozen-plan.json').read_bytes())}))


def execute(args):
    plan_path = args.output / 'frozen-plan.json'
    plan = json.loads(plan_path.read_text())
    _, row, candidates = inputs(args.cache, args.partition)
    for filename, expected in plan['scriptHashes'].items():
        audit.verified_bytes(ROOT / 'scripts' / filename, expected)
    if (audit.sha(row['COBOL_canonical_solution']) != plan['cobolSourceSha256']
            or audit.sha(PROBE) != plan['probeSha256']
            or audit.sha(row['Java_canonical_solution']) != plan['canonicalJavaSha256']):
        raise ValueError('Source/probe changed after freezing')
    for name, source in candidates.items():
        if audit.sha(source) != plan['candidateJavaSha256'][name]:
            raise ValueError('Candidate changed after freezing')
    report_path = args.output / 'replay-report.json'
    if report_path.exists():
        raise FileExistsError('Completed replay reports are immutable')
    raw = args.cache / 'text-replay' / args.output.name
    raw.mkdir(parents=True, exist_ok=False)
    java = {}
    for name, source in {'reference': row['Java_canonical_solution'], **candidates}.items():
        if audit.DANGEROUS.search(audit.strip_comments(source)):
            raise ValueError('Source requires further execution review')
        folder = raw / name
        folder.mkdir()
        (folder / 'Solution.java').write_text(source)
        (folder / 'TextReplay.java').write_text(PROBE)
        java[name] = audit.process([str(args.jdk / 'javac'), '-J-Xmx128m', '-proc:none',
                                  'Solution.java', 'TextReplay.java'], folder, 'compile', 15)
    records = []
    for case in plan['cases']:
        index = case['driverIndex']
        driver = row['tests'][index]['test']
        if audit.sha(driver) != case['driverSha256'] or extract_input(row, driver) != case['input']:
            raise ValueError('Driver/input changed after freezing')
        folder = raw / f'cobol-{index}'
        folder.mkdir()
        (folder / 'source.cbl').write_text(row['COBOL_canonical_solution'])
        (folder / 'driver.cbl').write_text(driver)
        record = {**case, 'status': 'UNRESOLVED', 'java': {}}
        record['cobolCompilation'] = audit.process([str(args.cobc), '-w', '-fformat=variable',
                                                  '-x', '-o', 'driver', 'driver.cbl', 'source.cbl'],
                                                 folder, 'compile', 15)
        if record['cobolCompilation']['returnCode'] == 0:
            record['cobolExecution'] = audit.process([str(folder / 'driver')], folder, 'run', 5)
            if record['cobolExecution']['returnCode'] == 0:
                output = (folder / 'COUNT-UPPER.TXT').read_bytes()
                record['cobolOutputSha256'] = audit.sha(output)
                record['cobolResult'] = scalar.parse_cobol_output(output, 'int')
                for name, compiled in java.items():
                    if compiled['returnCode'] or compiled['timedOut']:
                        record['java'][name] = {'status': 'COMPILATION_FAILURE'}
                        continue
                    phase = f'case-{index}'
                    jdir = raw / name
                    run = audit.process([str(args.jdk / 'java'), '-Xmx128m', '-XX:+UseSerialGC',
                                         '-ea', '-cp', str(jdir), 'TextReplay', case['input']],
                                        jdir, phase, 5)
                    output_text = (jdir / (phase + '.stdout')).read_text()
                    observed = {'execution': run, 'status': 'EXECUTION_FAILURE'}
                    if run['returnCode'] == 0 and not run['timedOut'] and re.fullmatch(r'-?\d+', output_text):
                        observed.update(status='OBSERVED', result=int(output_text),
                                        agreesWithCobol=int(output_text) == record['cobolResult'])
                    record['java'][name] = observed
                reference = record['java']['reference']
                record['status'] = ('SHARED_INPUT_REPLAY' if reference.get('agreesWithCobol')
                                    else 'REFERENCE_DISAGREEMENT_UNRESOLVED')
        records.append(record)
    summary = {}
    for name in candidates:
        eligible = [r for r in records if r['status'] == 'SHARED_INPUT_REPLAY'
                    and r['java'][name].get('status') == 'OBSERVED']
        summary[name] = {'comparedCases': len(eligible),
                         'agreementCases': sum(r['java'][name]['agreesWithCobol'] for r in eligible),
                         'disagreementCases': sum(not r['java'][name]['agreesWithCobol'] for r in eligible)}
    versions = {name: subprocess_output(command) for name, command in {
        'cobc': [str(args.cobc), '-V'], 'java': [str(args.jdk / 'java'), '-version']}.items()}
    report = {'taskId': TASK, 'selection': plan['selection'], 'frozenPlanSha256': audit.sha(plan_path.read_bytes()),
              'sourceHashes': {k: plan[k] for k in ('cobolSourceSha256', 'canonicalJavaSha256', 'candidateJavaSha256')},
              'toolchainVersions': versions, 'cobcSha256': audit.sha(args.cobc.read_bytes()),
              'javaSha256': audit.sha((args.jdk / 'java').read_bytes()),
              'rawEvidencePath': str(raw), 'records': records, 'summary': summary,
              'caseStatusCounts': dict(Counter(r['status'] for r in records)),
              'newTrainingLabelsAdmitted': 0, 'independentHumanReviews': 0,
              'modelTrainingPerformed': False, 'holdoutTasksExecuted': 0,
              'limitations': ['AI-curated exploratory cases, pending independent adjudication.',
                              'Only these original inputs and this ASCII contract are measured; no universal equivalence proof.',
                              'Runtime/helper semantics are pinned to this host, GnuCOBOL3.2 and Java21.']}
    write_new(report_path, report)
    print(json.dumps(summary, indent=2))


def subprocess_output(command):
    import subprocess
    result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
    return result.stdout + result.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, default=ROOT / 'evaluation/corpora/natural-c2j')
    parser.add_argument('--partition', type=Path, default=ROOT / 'evaluation/paired-code/cv-partition-plan.json')
    parser.add_argument('--jdk', type=Path, default=Path('/Users/volodymyrsydorenko/Developer/jdk-21.0.10.jdk/Contents/Home/bin'))
    parser.add_argument('--cobc', type=Path, default=Path('/tmp/sotonship-cobol-toolchain/install/bin/cobc'))
    args = parser.parse_args()
    args.cache, args.output, args.partition = args.cache.resolve(), args.output.resolve(), args.partition.resolve()
    (prepare if args.prepare else execute)(args)


if __name__ == '__main__':
    main()
