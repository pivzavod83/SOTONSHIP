#!/usr/bin/env python3
"""Adjudicate eight development families on unchanged original driver inputs.

Post-screening exploratory curation, not unbiased model evaluation. Source-
defined return projections are frozen before execution; expected-result
metadata never supplies inputs, return lengths or oracle values. Unsupported
input initialization/serialization is quarantined rather than guessed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HELPERS = {
    'audit': ('audit_natural_c2j_candidates.py', '2bc1518b701f7f56ea58f4b14d74dd745336135908e792414879ff53cf6e4282'),
    'scalar': ('replay_scalar_c2j_witnesses.py', 'a93cb91eaed6d728032639f4b2971a483c9d10773e440ac45b94e0fc0660ea74'),
}


def helper(name):
    filename, expected = HELPERS[name]
    path = ROOT / 'scripts' / filename
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f'Pinned helper changed: {filename}')
    spec = importlib.util.spec_from_file_location(f'numeric_a_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit, scalar = helper('audit'), helper('scalar')
SPECS = {
    35: {'input': 'L-L', 'size': 3, 'method': 'maxElement', 'kind': 'int'},
    43: {'input': 'L-L', 'size': 4, 'method': 'pairsSumToZero', 'kind': 'boolean'},
    47: {'input': 'L-L', 'size': 5, 'method': 'median', 'kind': 'decimal'},
    70: {'input': 'L-LST', 'size': 4, 'method': 'strangeSortList', 'kind': 'list-int', 'outputPrefix': 4,
         'projectionEvidence': 'WS-REMAINING VALUE4 decrements once per RESULT write until0; only first4 RESULT occurrences are compared. Remaining96 records are retained as native evidence, outside the return projection.'},
    73: {'input': 'L-ARR', 'size': 7, 'method': 'smallestChange', 'kind': 'int'},
    74: {'kind': 'string-lists', 'method': 'totalMatch', 'inputTables': {'L-LST1': 10, 'L-LST2': 10},
         'unsupportedReason': 'Original drivers do not initialize all20 declared input string slots. No Java values or logical list lengths are inferred for uninitialized occurrences; RESULT has100 string slots without an explicit logical return length.'},
    85: {'input': 'L-LST', 'size': 4, 'method': 'add', 'kind': 'int'},
    88: {'input': 'L-ARRAY', 'size': 7, 'method': 'sortArray', 'kind': 'list-int', 'outputPrefix': 7,
         'projectionEvidence': 'WS-ARRAY-SIZE VALUE7 controls the loop copying exactly first7 input occurrences into RESULT; only these first7 records are compared. Remaining93 native records are outside the return projection.'},
}


class Unsupported(ValueError):
    pass


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write('\n')


def require_development(task, partition):
    scalar.require_development(task, partition)


def extract_layout(source, driver):
    source_text, driver_text = scalar.code_lines(source), scalar.code_lines(driver)
    source_link = re.search(r'LINKAGE SECTION\.(.*?)PROCEDURE DIVISION USING LINKED-ITEMS\.', source_text, re.S)
    driver_link = re.search(r'(01\s+LINKED-ITEMS\..*?)PROCEDURE DIVISION\.', driver_text, re.S)
    if not source_link or not driver_link:
        raise Unsupported('Unsupported source or driver linkage interface.')
    normal = lambda value: ' '.join(value.split())
    if normal(source_link[1]) != normal(driver_link[1]):
        raise Unsupported('Driver and original source linkage differ.')
    program = re.search(r'PROGRAM-ID\.\s*([A-Z0-9-]+)\.', source_text)[1]
    procedure = driver_text.split('PROCEDURE DIVISION.', 1)[1]
    if re.findall(r'CALL\s+"([A-Z0-9-]+)"\s+USING\s+LINKED-ITEMS', procedure) != [program]:
        raise Unsupported('Driver does not call the original program exactly once.')
    names = re.findall(r'SELECT OUTPUT-FILE ASSIGN TO "([A-Z0-9_-]+\.TXT)"', driver_text)
    if len(names) != 1:
        raise Unsupported('Unsupported or nonrelative original output path.')
    return source_link[1], driver_text, procedure, names[0]


def parse_inputs(row, driver, spec, index):
    layout, text, procedure, filename = extract_layout(row['COBOL_canonical_solution'], driver)
    before = procedure.split('CALL', 1)[0]
    common = {'driverIndex': index, 'driverSha256': audit.sha(driver), 'outputFile': filename}
    if spec['kind'] == 'string-lists':
        moves = re.findall(r'MOVE\s+([\'\"])(.*?)\1\s+TO\s+(L-LST[12])\((\d+)\)', before)
        assigned = {(table, int(position)): literal for _, literal, table, position in moves}
        missing = {table: [i for i in range(1, count + 1) if (table, i) not in assigned]
                   for table, count in spec['inputTables'].items()}
        return {**common, 'status': 'UNSUPPORTED', 'reason': spec['unsupportedReason'],
                'initializedStringSlots': [{'table': table, 'position': pos, 'literal': value}
                                           for (table, pos), value in assigned.items()], 'missingInputSlots': missing}
    name, size = spec['input'], spec['size']
    input_decl = rf'05\s+{re.escape(name)}\s+OCCURS\s+{size}\s+TIMES\s+INDEXED\s+BY\s+NI\s+PIC\s+S9\(10\)\.'
    output_decl = {'int': r'05\s+RESULT\s+PIC\s+S9\(10\)\.',
                   'boolean': r'05\s+RESULT\s+PIC\s+9\.',
                   'decimal': r'05\s+RESULT\s+COMP-2\.',
                   'list-int': r'05\s+RESULT\s+OCCURS\s+100\s+TIMES\s+INDEXED\s+BY\s+NJ\s+PIC\s+S9\(10\)\.'}[spec['kind']]
    if not re.fullmatch(r'\s*01\s+LINKED-ITEMS\.\s*' + input_decl + r'\s*' + output_decl + r'\s*', layout):
        raise Unsupported('Original linkage differs from the frozen array type/size.')
    pattern = rf'MOVE\s+(-?\d+)\s+TO\s+{re.escape(name)}\((\d+)\)\s*\.?'
    moves = re.findall(pattern, before)
    if re.sub(pattern, '', before).strip() or len(moves) != size or {int(i) for _, i in moves} != set(range(1, size + 1)):
        raise Unsupported('Every fixed-size input occurrence must be initialized exactly once by integer literals.')
    values = {int(i): int(value) for value, i in moves}
    arguments = [values[i] for i in range(1, size + 1)]
    if any(not -(2**31) <= value < 2**31 for value in arguments):
        raise Unsupported('Input outside the shared Java int / original signed COBOL range.')
    kind = spec['kind']
    if kind in {'int', 'list-int'}:
        if not re.search(r'01\s+OUTPUT-RECORD\s+PIC\s+S9\(10\)\s+SIGN\s+LEADING\.', text):
            raise Unsupported('Output record loses original signed integer width.')
    elif kind == 'boolean' and not re.search(r'01\s+OUTPUT-RECORD\s+PIC\s+9\.', text):
        raise Unsupported('Boolean output is not a one-digit record.')
    elif kind == 'decimal':
        required = [r'01\s+OUTPUT-RECORD\s+PIC\s+X\(15\)\.',
                    r'05\s+DECIMAL-PART\s+PIC\s+X\(9\)\.', r'05\s+FRACTIONAL-PART\s+PIC\s+X\(5\)\.',
                    r'01\s+FLOAT-REPR\s+REDEFINES\s+PARTS-REPR\s+PIC\s+S9\(9\)V9\(5\)\s+SIGN\s+LEADING\.',
                    r'MOVE\s+RESULT\s+TO\s+FLOAT-REPR', r'STRING\s+DECIMAL-PART\s+"\."\s+FRACTIONAL-PART\s+INTO\s+OUTPUT-RECORD']
        if not all(re.search(pattern, text) for pattern in required):
            raise Unsupported('Unverified original decimal serialization.')
        if any(abs(value) >= 10**9 for value in arguments):
            raise Unsupported('Original median inputs exceed the driver numeric output width.')
    if kind == 'list-int':
        if not re.search(r'PERFORM VARYING NJ FROM 1 BY 1 UNTIL NJ > 100\s+MOVE RESULT\s*\(NJ\) TO OUTPUT-RECORD\s+WRITE OUTPUT-RECORD\s+END-PERFORM', text):
            raise Unsupported('Original array output is not the declared100 scalar records.')
    elif kind != 'decimal' and len(re.findall(r'MOVE RESULT TO OUTPUT-RECORD', text)) != 1:
        raise Unsupported('Result is not directly serialized by the original driver.')
    return {**common, 'status': 'SUPPORTED', 'arguments': arguments,
            'inputContract': f'Exactly{size} fully initialized signed integer occurrences mapped to Java List<Integer> in original occurrence order.'}


def records(raw):
    if not raw.endswith(b'\n'):
        raise Unsupported('Expected a newline-terminated original sequential output record.')
    return raw.splitlines(keepends=True)


def decode_cobol(raw, spec):
    values = records(raw)
    kind = spec['kind']
    if kind == 'list-int':
        if len(values) != 100:
            raise Unsupported('Expected all100 original result records; never infer length from expected metadata.')
        return [scalar.parse_cobol_output(value, 'int') for value in values[:spec['outputPrefix']]]
    if len(values) != 1:
        raise Unsupported('Expected exactly one original scalar result record.')
    if kind in {'int', 'boolean'}:
        return scalar.parse_cobol_output(raw, kind)
    if kind == 'decimal':
        text = raw[:-2] if raw.endswith(b'\r\n') else raw[:-1]
        if not re.fullmatch(rb'[0-9p-y][0-9]{8}\.[0-9]{5}', text):
            raise Unsupported('Unrecognized signed decimal output; no lossy float conversion is applied.')
        text = text.decode('ascii')
        if text[0] in 'pqrstuvwxy':
            text = '-' + str('pqrstuvwxy'.index(text[0])) + text[1:]
        return str(Decimal(text))
    raise Unsupported('No comparable output adapter.')


def native_list_shape(raw, spec):
    rows = records(raw)
    tail = rows[spec['outputPrefix']:]
    decoded, rejected = [], []
    for index, value in enumerate(tail, spec['outputPrefix'] + 1):
        try:
            decoded.append(scalar.parse_cobol_output(value, 'int'))
        except (scalar.UnsupportedContract, UnicodeError):
            rejected.append(index)
    return {'recordCount': len(rows), 'recordHex': [value.hex() for value in rows],
            'comparedPrefixRecords': spec['outputPrefix'], 'uncomparedTailRecords': len(tail),
            'tailRecordByteWidthCountsIncludingNewline': dict(Counter(map(len, tail))),
            'tailIntegerDecodeFailuresAtOneBasedOccurrences': rejected,
            'tailDecodedNonzeroRecords': sum(value != 0 for value in decoded),
            'tailScope': 'Retained native evidence only; not part of frozen return projection and never used to infer logical result length.'}


def decode_java(raw, spec):
    if spec['kind'] == 'list-int':
        value = json.loads(raw)
        if not isinstance(value, list) or len(value) != spec['outputPrefix'] or any(type(v) is not int for v in value):
            raise Unsupported('Java result does not match the frozen source-defined integer-list length.')
        return value
    if spec['kind'] == 'boolean':
        if raw not in (b'true', b'false'):
            raise Unsupported('Java boolean result is not exactly true or false.')
        return raw == b'true'
    if spec['kind'] == 'int':
        if not re.fullmatch(rb'-?\d+', raw):
            raise Unsupported('Java integer result is malformed.')
        return int(raw)
    if spec['kind'] == 'decimal':
        try:
            value = Decimal(raw.decode('ascii'))
        except (ValueError, InvalidOperation, UnicodeError) as error:
            raise Unsupported('Malformed Java decimal output.') from error
        if not value.is_finite():
            raise Unsupported('Nonfinite Java decimal output.')
        return str(value)
    raise Unsupported('No Java output contract.')


def same(a, b, spec):
    return Decimal(a) == Decimal(b) if spec['kind'] == 'decimal' else a == b


def probe(spec):
    return ('import java.util.*; public final class NumericAReplay { public static void main(String[] args) { '
            'List<Integer> values=new ArrayList<>(); for(String value:args) values.add(Integer.parseInt(value)); '
            f'System.out.print(new Solution().{spec["method"]}(values));' + ' } }\n')


def cohort(cache, partition):
    provenance, rows, candidates = audit.load_sources(cache, False)
    split = audit.load_partition(partition, rows)
    chosen = []
    for position, row in enumerate(rows):
        number = int(row['task_id'].split('/')[1])
        if number not in SPECS:
            continue
        require_development(row['task_id'], split)
        chosen.append((position, row, SPECS[number]))
    if len(chosen) != len(SPECS):
        raise Unsupported('The exact assigned development cohort is required.')
    return provenance, chosen, candidates


def prepare(cache, partition, output):
    provenance, chosen, candidates = cohort(cache, partition)
    tasks = []
    for position, row, spec in chosen:
        cases = []
        for index, item in enumerate(row['tests']):
            try:
                case = parse_inputs(row, item['test'], spec, index)
            except (Unsupported, scalar.UnsupportedContract) as error:
                case = {'driverIndex': index, 'driverSha256': audit.sha(item['test']), 'status': 'UNSUPPORTED', 'reason': str(error)}
            cases.append(case)
        tasks.append({'taskId': row['task_id'], 'rowOrdinalZeroBased': position, 'contract': spec, 'cases': cases,
                      'sourceHashes': {'cobol': audit.sha(row['COBOL_canonical_solution']),
                                       'canonical': audit.sha(row['Java_canonical_solution']),
                                       **{name: audit.sha(values[position]['completion']) for name, values in candidates.items()}},
                      'probeSha256': audit.sha(probe(spec)) if spec['kind'] != 'string-lists' else None})
    result = {'schemaVersion': 1, 'createdAt': datetime.now(timezone.utc).isoformat(),
              'status': 'FROZEN_EXPLORATORY_NUMERIC_A_BEFORE_NEW_EXECUTION', 'artifacts': provenance,
              'partitionSha256': audit.PARTITION_SHA, 'scriptSha256': audit.sha(Path(__file__).read_bytes()),
              'helpers': {name: {'filename': value[0], 'sha256': value[1]} for name, value in HELPERS.items()},
              'selection': 'Assigned eight development families after Java screening; no unbiased prevalence or detector-accuracy claim.',
              'outputScope': 'Returned scalar or explicit source-written list prefix only; input mutations and unassigned result tails are outside comparisons.',
              'expectedResultMetadataUsed': False, 'generatedInputs': 0, 'reservedTasksExecuted': 0,
              'tasks': tasks, 'independentHumanReviewsPerformed': 0, 'admittedDefectLabels': 0}
    write_new(output, result)
    return result


def successful(value):
    return value['returnCode'] == 0 and not value['timedOut']


def run(args):
    frozen = json.loads(args.contract.read_bytes())
    provenance, chosen, candidates = cohort(args.cache, args.partition)
    if (frozen['status'] != 'FROZEN_EXPLORATORY_NUMERIC_A_BEFORE_NEW_EXECUTION'
            or frozen['scriptSha256'] != audit.sha(Path(__file__).read_bytes())
            or frozen['artifacts'] != provenance or frozen['partitionSha256'] != audit.sha(args.partition.read_bytes())):
        raise Unsupported('Frozen provenance changed before execution.')
    args.raw.mkdir(parents=True, exist_ok=False)
    tools = {}
    for name, binary in {'cobc': args.cobc, 'java': args.jdk / 'java', 'javac': args.jdk / 'javac'}.items():
        result = audit.process([str(binary), '--version' if name == 'cobc' else '-version'], args.raw, name, 10)
        if not successful(result):
            raise Unsupported(f'Tool unavailable: {name}')
        tools[name] = {'path': str(binary), 'sha256': audit.sha(binary.read_bytes()), 'version': result,
                       'versionText': (args.raw / f'{name}.stdout').read_text() + (args.raw / f'{name}.stderr').read_text()}
    tasks = []
    for (position, row, spec), planned in zip(chosen, frozen['tasks']):
        if row['task_id'] != planned['taskId'] or spec != planned['contract']:
            raise Unsupported('Frozen task or contract differs.')
        folder = args.raw / row['task_id'].replace('/', '-')
        folder.mkdir()
        (folder / 'source.cob').write_text(row['COBOL_canonical_solution'])
        variants = {'canonical': row['Java_canonical_solution'], **{name: values[position]['completion'] for name, values in candidates.items()}}
        java = {}
        if any(c['status'] == 'SUPPORTED' for c in planned['cases']):
            for name, source in variants.items():
                if audit.DANGEROUS.search(audit.strip_comments(source)):
                    raise Unsupported('Java execution requires further source review.')
                target = folder / name
                target.mkdir()
                (target / 'Solution.java').write_text(source)
                (target / 'NumericAReplay.java').write_text(probe(spec))
                compiled = audit.process([str(args.jdk / 'javac'), '-J-Xmx128m', '-J-XX:ActiveProcessorCount=1', '-proc:none',
                                          '-encoding', 'UTF-8', 'Solution.java', 'NumericAReplay.java'], target, 'compile', 15)
                java[name] = {'compilation': compiled, 'cases': []}
        cases = []
        for original in planned['cases']:
            index = original['driverIndex']
            driver = row['tests'][index]['test']
            if audit.sha(driver) != original['driverSha256']:
                raise Unsupported('Driver changed after freezing.')
            case = {**original, 'canonicalControl': 'NOT_COMPARABLE'}
            target = folder / f'driver-{index}'
            target.mkdir()
            (target / 'driver.cob').write_text(driver)
            # Even an unsupported Java adapter retains actual unchanged COBOL
            # observations for later review; it never fabricates Java inputs.
            compilation = audit.process([str(args.cobc), '-w', '-fformat=variable', '-x', '-o', 'replay', 'driver.cob', '../source.cob'], target, 'compile', 15)
            case['cobolCompilation'] = compilation
            if successful(compilation):
                execution = audit.process([str(target / 'replay')], target, 'run', 5)
                case['cobolExecution'] = execution
                try:
                    filename = original.get('outputFile') or extract_layout(row['COBOL_canonical_solution'], driver)[3]
                    data = (target / filename).read_bytes()
                    case.update(cobolOutputHex=data.hex(), cobolOutputSha256=audit.sha(data))
                    if spec['kind'] == 'list-int':
                        case['nativeOutputShape'] = native_list_shape(data, spec)
                    if original['status'] == 'SUPPORTED' and successful(execution):
                        case['cobolResult'] = decode_cobol(data, spec)
                except (OSError, Unsupported, scalar.UnsupportedContract, UnicodeError) as error:
                    case['cobolDecodeReason'] = str(error)
            if original['status'] != 'SUPPORTED':
                cases.append(case)
                continue
            for name, variant in java.items():
                observed = {'driverIndex': index, 'status': 'COMPILE_FAILURE'}
                if successful(variant['compilation']):
                    execution = audit.process([str(args.jdk / 'java'), '-Xmx128m', '-Xss1m', '-XX:ActiveProcessorCount=1', '-XX:+UseSerialGC',
                                               '-ea', '-cp', str(folder / name), 'NumericAReplay', *map(str, original['arguments'])], folder / name, f'case-{index}', 5)
                    observed['execution'] = execution
                    observed['status'] = 'EXECUTION_TIMEOUT' if execution['timedOut'] else 'EXECUTION_FAILURE'
                    if successful(execution):
                        try:
                            observed['result'] = decode_java((folder / name / f'case-{index}.stdout').read_bytes(), spec)
                            observed['status'] = 'OBSERVED'
                        except (Unsupported, ValueError) as error:
                            observed.update(status='OUTPUT_CONTRACT_UNRESOLVED', reason=str(error))
                variant['cases'].append(observed)
            canonical = java['canonical']['cases'][-1]
            control = ('cobolResult' in case and canonical['status'] == 'OBSERVED' and same(case['cobolResult'], canonical['result'], spec))
            case['canonicalControl'] = 'AGREES' if control else 'REFERENCE_CONFLICT_OR_UNRESOLVED'
            for name in candidates:
                observed = java[name]['cases'][-1]
                observed['comparison'] = 'NOT_COMPARABLE'
                if 'cobolResult' in case and observed['status'] == 'OBSERVED':
                    equal = same(case['cobolResult'], observed['result'], spec)
                    observed['ungatedObservedSourceComparison'] = 'AGREEMENT' if equal else 'DIFFERENCE_WITH_ORIGINAL_COBOL'
                    if control:
                        observed['comparison'] = 'AGREEMENT' if equal else 'MISMATCH_PENDING_REVIEW'
                elif control and observed['status'] in {'COMPILE_FAILURE', 'EXECUTION_FAILURE'}:
                    observed['comparison'] = 'COMPILE_OR_RUNTIME_DISCREPANCY_PENDING_REVIEW'
            cases.append(case)
        comparisons = [c['comparison'] for n in candidates for c in java.get(n, {}).get('cases', [])]
        failures = any(c in {'MISMATCH_PENDING_REVIEW', 'COMPILE_OR_RUNTIME_DISCREPANCY_PENDING_REVIEW'} for c in comparisons)
        conflicts = sum(c['status'] == 'SUPPORTED' and c['canonicalControl'] != 'AGREES' for c in cases)
        supported = sum(c['canonicalControl'] == 'AGREES' for c in cases)
        status = ('reproduced discrepancy pending human review' if failures else 'reference conflict or unresolved' if conflicts
                  else 'no mismatch observed on shared original inputs' if supported else 'unsupported')
        code = ('REPRODUCED_DISCREPANCY_PENDING_HUMAN_REVIEW' if failures else 'REFERENCE_CONFLICT_OR_UNRESOLVED' if conflicts
                else 'NO_MISMATCH_OBSERVED_SCOPED' if supported else 'UNSUPPORTED')
        tasks.append({'taskId': row['task_id'], 'adjudication': status, 'contract': spec,
                      'adjudicationCode': code,
                      'sourceHashes': planned['sourceHashes'], 'cases': cases, 'javaVariants': java,
                      'comparableInputCases': supported, 'referenceConflictOrUnresolvedCases': conflicts,
                      'candidateComparisons': dict(Counter(comparisons))})
    result = {'schemaVersion': 1, 'status': 'EXPLORATORY_MACHINE_ADJUDICATION_PENDING_HUMAN_REVIEW',
              'createdAt': datetime.now(timezone.utc).isoformat(), 'frozenPlanSha256': audit.sha(args.contract.read_bytes()),
              'scriptSha256': audit.sha(Path(__file__).read_bytes()), 'helperSources': frozen['helpers'], 'toolchain': tools,
              'rawEvidenceDirectory': str(args.raw), 'tasks': tasks,
              'familyAdjudicationCounts': dict(Counter(t['adjudication'] for t in tasks)),
              'independentHumanReviewsPerformed': 0, 'admittedDefectTrainingLabels': 0,
              'modelTrainingPerformed': False, 'generatedInputs': 0, 'sourceRewritesPerformed': False,
              'reservedTasksExecuted': 0, 'expectedResultMetadataUsed': False,
              'limitations': ['Post-screening selected cohort; no detector accuracy or unbiased prevalence estimate.',
                              'Task families, not driver cases, are the independent source units reported here.',
                              'List comparison scope is the source-written return prefix; unassigned native tail records and mutated inputs are not claimed equivalent.',
                              'Passing original inputs means finite compatibility only; a reference conflict remains visible and blocks automatic gold-label admission.',
                              'All defect descriptions and adapters are AI curated pending independent human review.']}
    write_new(args.report, result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'run'])
    p.add_argument('--contract', type=Path, required=True)
    p.add_argument('--report', type=Path)
    p.add_argument('--raw', type=Path)
    p.add_argument('--cache', type=Path, default=ROOT / 'evaluation/corpora/natural-c2j')
    p.add_argument('--partition', type=Path, default=ROOT / 'evaluation/paired-code/cv-partition-plan.json')
    p.add_argument('--cobc', type=Path, default=Path('/private/tmp/sotonship-cobol-toolchain/install/bin/cobc'))
    p.add_argument('--jdk', type=Path, default=Path('/Users/volodymyrsydorenko/Developer/jdk-21.0.10.jdk/Contents/Home/bin'))
    args = p.parse_args()
    if args.action == 'prepare':
        result = prepare(args.cache, args.partition, args.contract)
        print(json.dumps({'tasks': len(result['tasks']), 'inputCases': sum(len(t['cases']) for t in result['tasks'])}))
    else:
        if not args.report or not args.raw:
            p.error('run requires --report and --raw')
        args.raw = args.raw.resolve()
        result = run(args)
        print(json.dumps(result['familyAdjudicationCounts']))


if __name__ == '__main__':
    main()
