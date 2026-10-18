"""Exploratory, frozen-contract adjudication of seven development task families.

The unchanged COBOL driver output is the oracle, never its answer metadata.
All results remain AI-curated and pending independent human adjudication.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
TASKS = [17, 99, 105, 110, 143, 145, 151]


def helper(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = helper('audit_natural_c2j_candidates')
scalar = helper('replay_scalar_c2j_witnesses')
guard = helper('audit_cobol_references')

SPECS = {
    17: {'program': 'PARSE-MUSIC', 'method': 'parseMusic', 'result': 'integerList',
         'input': 'music', 'sourceLayout': '05 L-MUSIC-STRING PIC X(100). 05 RESULT OCCURS 100 TIMES INDEXED BY NI PIC S9(10).',
         'logicalOutput': 'one integer per original grammar token; all remaining serialized slots must be zero'},
    99: {'program': 'CLOSEST-INTEGER', 'method': 'countUpper', 'result': 'integer',
         'input': 'numericStringUnresolved', 'sourceLayout': '05 L-VALUE COMP-2. 05 RESULT PIC S9(10).',
         'logicalOutput': 'scalar integer, but quoted text MOVE to COMP-2 has unresolved correspondence to Java String API'},
    105: {'program': 'BY-LENGTH', 'method': 'byLength', 'result': 'stringList',
          'input': 'eightIntegers', 'sourceLayout': '05 L-ARR OCCURS 8 TIMES INDEXED BY NI PIC S9(10). 05 RESULT OCCURS 100 TIMES INDEXED BY NJ PIC X(100).',
          'logicalOutput': 'eight names for eight in-range digits; remaining 92 serialized slots must be blank'},
    110: {'program': 'EXCHANGE', 'method': 'exchange', 'result': 'string',
          'input': 'twoFourIntegerLists', 'sourceLayout': '05 L-LST1 OCCURS 4 TIMES INDEXED BY NI PIC S9(10). 05 L-LST2 OCCURS 4 TIMES INDEXED BY NJ PIC S9(10). 05 RESULT PIC X(100).',
          'logicalOutput': 'one ASCII text record with COBOL right-space padding removed only'},
    143: {'program': 'WORDS-IN-SENTENCE', 'method': 'wordsInSentence', 'result': 'string',
          'input': 'sentence', 'sourceLayout': '05 L-SENTENCE PIC X(100). 05 RESULT PIC X(100).',
          'logicalOutput': 'one ASCII text record with COBOL right-space padding removed only'},
    145: {'program': 'ORDER-BY-POINTS', 'method': 'orderByPoints', 'result': 'integerList',
          'input': 'fiveIntegers', 'sourceLayout': '05 L-NUMS OCCURS 5 TIMES INDEXED BY NI PIC S9(10). 05 RESULT OCCURS 5 TIMES INDEXED BY NJ PIC S9(10).',
          'driverLayout': '05 L-NUMS OCCURS 5 TIMES INDEXED BY NI PIC S9(10). 05 RESULT OCCURS 100 TIMES INDEXED BY NJ PIC S9(10).',
          'logicalOutput': 'source declares five output elements; remaining 95 driver slots must be zero'},
    151: {'program': 'DOUBLE-THE-DIFFERENCE', 'method': 'doubleTheDifference', 'result': 'integer',
          'input': 'threeDoubles', 'sourceLayout': '05 L-LST OCCURS 3 TIMES INDEXED BY NI COMP-2. 05 RESULT PIC S9(10).',
          'logicalOutput': 'scalar integer; every COMP-2 input maps to Java Double, never inferred Integer boxing'},
}

PROBE_HELPERS = r'''
  static java.util.List<Integer> ints(String arg) {
    java.util.List<Integer> result = new java.util.ArrayList<>();
    for (String item : arg.split(",", -1)) result.add(Integer.valueOf(item));
    return result;
  }
  static java.util.List<Object> doubles(String arg) {
    java.util.List<Object> result = new java.util.ArrayList<>();
    for (String item : arg.split(",", -1)) result.add(Double.valueOf(item));
    return result;
  }
  static String json(Object value) {
    if (value instanceof String text) {
      StringBuilder out = new StringBuilder("\"");
      for (int i=0; i<text.length(); i++) {
        char c=text.charAt(i);
        if (c=='"' || c=='\\') out.append('\\').append(c);
        else if (c=='\n') out.append("\\n");
        else if (c=='\r') out.append("\\r");
        else if (c=='\t') out.append("\\t");
        else if (c<32) throw new IllegalArgumentException("unsupported control character");
        else out.append(c);
      }
      return out.append('"').toString();
    }
    if (value instanceof Integer || value instanceof Long) return value.toString();
    if (value instanceof java.util.List<?> values) {
      StringBuilder out=new StringBuilder("[");
      for (int i=0; i<values.size(); i++) {
        if (i>0) out.append(','); out.append(json(values.get(i)));
      }
      return out.append(']').toString();
    }
    throw new IllegalArgumentException("unsupported result type");
  }
'''


def probe(number: int) -> str:
    kind = SPECS[number]['input']
    arguments = ('ints(args[0]), ints(args[1])' if kind == 'twoFourIntegerLists' else
                 'ints(args[0])' if kind in {'eightIntegers', 'fiveIntegers'} else
                 'doubles(args[0])' if kind == 'threeDoubles' else 'args[0]')
    return ('public final class TextCaseReplay {\n' + PROBE_HELPERS
            + ' public static void main(String[] args) { System.out.print(json(new Solution().'
            + SPECS[number]['method'] + '(' + arguments + '))); }\n}\n')


def normalize(text: str) -> str:
    return ' '.join(text.split())


def layout(source: str, driver: bool = False) -> str:
    text = scalar.code_lines(source)
    section = re.search(r'01\s+LINKED-ITEMS\.(.*?)PROCEDURE DIVISION(?: USING LINKED-ITEMS)?\.', text, re.S)
    if not section:
        raise ValueError('Missing declared linkage interface')
    # Comments are absent from these declared linkage blocks, except prompt prose
    # already removed by code_lines. No inferred or partial field mapping.
    return normalize(section[1])


def literal_moves(prefix: str) -> list[tuple[str, str, bool]]:
    pattern = re.compile(r'''\s*MOVE\s+(?:'([^']*)'|"([^"]*)"|(-?\d+(?:\.\d+)?))\s+TO\s+([A-Z][A-Z0-9-]*(?:\(\d+\))?)\s*''')
    position, result = 0, []
    while position < len(prefix) and prefix[position:].strip():
        match = pattern.match(prefix, position)
        if not match:
            raise ValueError('Input requires exactly literal MOVEs without extra statements')
        value = next(v for v in match.groups()[:3] if v is not None)
        result.append((match[4], value, match[3] is None))
        position = match.end()
    if len({name for name, _, _ in result}) != len(result):
        raise ValueError('Duplicate input MOVE')
    return result


def extract_case(number: int, row: dict, driver: str, index: int) -> dict:
    spec = SPECS[number]
    source = row['COBOL_canonical_solution']
    if layout(source) != normalize(spec['sourceLayout']):
        raise ValueError('Source interface differs from declared task contract')
    if layout(driver, True) != normalize(spec.get('driverLayout', spec['sourceLayout'])):
        raise ValueError('Driver interface differs from declared task contract')
    text = scalar.code_lines(driver)
    if not re.search(r'PROGRAM-ID\.\s*' + re.escape(spec['program']) + r'\.', scalar.code_lines(source)):
        raise ValueError('Unexpected source program')
    body = text.split('PROCEDURE DIVISION.', 1)[1]
    call = f'CALL "{spec["program"]}" USING LINKED-ITEMS'
    if body.count(call) != 1:
        raise ValueError('Expected exactly one call to the declared source')
    prefix, suffix = body.split(call)
    if re.search(r'\bCALL\b', suffix):
        raise ValueError('Extra source call')
    moves = literal_moves(prefix)
    names = {name for name, _, _ in moves}
    values = {name: (value, quoted) for name, value, quoted in moves}
    output = guard.source_preflight(source, driver)
    kind = spec['input']
    case = {'driverIndex': index, 'driverSha256': audit.sha(driver), 'outputFile': output,
            'inputMapping': kind, 'mappingEligible': number != 99}
    if kind in {'music', 'sentence', 'numericStringUnresolved'}:
        field = {'music': 'L-MUSIC-STRING', 'sentence': 'L-SENTENCE', 'numericStringUnresolved': 'L-VALUE'}[kind]
        if names != {field} or not values[field][1]:
            raise ValueError('Expected one quoted original text input')
        value = values[field][0]
        if not value.isascii() or not 0 < len(value) <= 100:
            raise ValueError('Empty quoted COBOL literal or non-ASCII/oversize text is outside contract')
        if kind == 'music' and not re.fullmatch(r'(?:o|o\||\.\|)(?: (?:o|o\||\.\|))*', value):
            raise ValueError('Music input is outside the single-space note grammar')
        if kind == 'sentence' and not re.fullmatch(r'[A-Za-z]+(?: [A-Za-z]+)*', value):
            raise ValueError('Sentence requires ASCII letters and single internal spaces')
        if kind == 'numericStringUnresolved' and not re.fullmatch(r'-?\d+(?:\.\d+)?', value):
            raise ValueError('Numeric string artifact must be a finite decimal lexeme')
        case.update(arguments=[value], sourceInputLiteral=value,
                    logicalResultLength=len(value.split(' ')) if kind == 'music' else None)
        if number == 99:
            case['mappingLimitation'] = 'Quoted alphanumeric MOVE into COMP-2 does not establish a shared numeric input; Java API takes String. Any observed difference remains a source/interface artifact, never an admitted semantic defect.'
    else:
        groups = {'eightIntegers': [('L-ARR', 8)], 'twoFourIntegerLists': [('L-LST1', 4), ('L-LST2', 4)],
                  'fiveIntegers': [('L-NUMS', 5)], 'threeDoubles': [('L-LST', 3)]}[kind]
        required = {f'{field}({i})' for field, count in groups for i in range(1, count + 1)}
        if names != required or any(quoted for _, quoted in values.values()):
            raise ValueError('Array input requires every declared index exactly once with numeric literal')
        arguments, observed = [], []
        for field, count in groups:
            lexemes = [values[f'{field}({i})'][0] for i in range(1, count + 1)]
            if kind != 'threeDoubles' and any(not re.fullmatch(r'-?\d+', value) for value in lexemes):
                raise ValueError('Integer PIC array cannot receive fractional literals')
            numbers = [float(value) if kind == 'threeDoubles' else int(value) for value in lexemes]
            if any(not math.isfinite(value) or abs(value) > 100_000 for value in numbers):
                raise ValueError('Array value outside frozen finite bounds')
            if number == 105 and any(not 1 <= value <= 9 for value in numbers):
                raise ValueError('This common contract admits eight digits 1..9 only')
            arguments.append(','.join(lexemes)); observed.append(numbers)
        case.update(arguments=arguments, numericInputs=observed,
                    logicalResultLength=8 if number == 105 else 5 if number == 145 else None)
        if number == 151:
            case['javaElementRuntimeType'] = 'java.lang.Double for every COMP-2 field, regardless literal spelling'
            case['representationLimitation'] = 'The supplied canonical Java uses Integer runtime tags despite COBOL COMP-2 inputs. A reference disagreement is quarantined as a representation-contract conflict.'
    expected_pic = 'X(100)' if spec['result'] in {'string', 'stringList'} else 'S9(10) SIGN LEADING'
    if not re.search(r'01\s+OUTPUT-RECORD\s+PIC\s+' + re.escape(expected_pic) + r'\.', text):
        raise ValueError('Unexpected serialized result field')
    array_output = spec['result'].endswith('List')
    if array_output:
        if not re.search(r'PERFORM VARYING (?:NI|NJ) FROM 1 BY 1 UNTIL (?:NI|NJ) > 100', suffix):
            raise ValueError('Expected all 100 original serialized slots')
        if not re.search(r'MOVE RESULT \((?:NI|NJ)\) TO OUTPUT-RECORD', suffix):
            raise ValueError('Unsupported list serialization')
    elif suffix.count('MOVE RESULT TO OUTPUT-RECORD') != 1:
        raise ValueError('Expected direct scalar result serialization')
    return case


def parse_output(number: int, raw: bytes, case: dict) -> tuple[object, dict]:
    kind = SPECS[number]['result']
    records = raw.splitlines()
    if kind in {'integer', 'integerList'}:
        decoded = [scalar.parse_cobol_output(record, 'int') for record in records]
        if kind == 'integer':
            if len(decoded) != 1:
                raise ValueError('Scalar output must have one record')
            return decoded[0], {'serializedRecordCount': 1, 'discardedRecordCount': 0}
        length = case['logicalResultLength']
        if len(decoded) != 100 or any(value != 0 for value in decoded[length:]):
            raise ValueError('List output must have 100 slots and an entirely zero tail')
        return decoded[:length], {'serializedRecordCount': 100, 'logicalLengthDerivedFrom': 'source declaration' if number == 145 else 'original input grammar',
                                  'logicalResultLength': length, 'verifiedPaddingRecordCount': 100 - length, 'verifiedPaddingValue': 0}
    decoded = [record.decode('ascii') for record in records]
    if any(len(record) > 100 or any(ord(c) < 32 for c in record) for record in decoded):
        raise ValueError('Non-ASCII/control or oversized text output')
    normalized = [record.rstrip(' ') for record in decoded]
    if kind == 'string':
        if len(normalized) != 1:
            raise ValueError('Text scalar must have one record, including an empty result')
        return normalized[0], {'serializedRecordCount': 1, 'normalization': 'right ASCII spaces only'}
    length = case['logicalResultLength']
    if len(normalized) != 100 or any(normalized[length:]):
        raise ValueError('Text list requires 100 records and an entirely blank tail')
    return normalized[:length], {'serializedRecordCount': 100, 'logicalResultLength': length,
                                'logicalLengthDerivedFrom': 'eight declared in-range input digits',
                                'verifiedPaddingRecordCount': 100 - length, 'verifiedPaddingValue': '',
                                'normalization': 'right ASCII spaces only'}


def valid_java_result(number: int, value) -> bool:
    kind = SPECS[number]['result']
    return (type(value) is int if kind == 'integer' else type(value) is str if kind == 'string' else
            type(value) is list and all(type(x) is int for x in value) if kind == 'integerList' else
            type(value) is list and all(type(x) is str for x in value))


def write_new(path: Path, value: dict) -> None:
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


def load(args):
    provenance, rows, candidates = audit.load_sources(args.cache, False)
    split = audit.load_partition(args.partition, rows)
    selected = {}
    for position, row in enumerate(rows):
        number = int(row['task_id'].split('/')[1])
        if number in TASKS:
            scalar.require_development(row['task_id'], split)
            selected[number] = (row, {name: values[position]['completion'] for name, values in candidates.items()})
    if set(selected) != set(TASKS):
        raise ValueError('An assigned development task is missing')
    return provenance, selected


def prepare(args):
    provenance, selected = load(args)
    args.output.mkdir(parents=True, exist_ok=False)
    snapshots = args.output / 'source-snapshot'; snapshots.mkdir()
    hashes = {}
    for name in [SCRIPT.name, 'replay_scalar_c2j_witnesses.py', 'audit_natural_c2j_candidates.py', 'audit_cobol_references.py']:
        source = ROOT / 'scripts' / name
        shutil.copyfile(source, snapshots / name); hashes[name] = audit.sha(source.read_bytes())
    tasks = []
    for number, (row, candidates) in selected.items():
        cases, rejected = [], []
        for index, original in enumerate(row['tests']):
            try:
                cases.append(extract_case(number, row, original['test'], index))
            except ValueError as error:
                rejected.append({'driverIndex': index, 'driverSha256': audit.sha(original['test']), 'reason': str(error)})
        tasks.append({'taskId': row['task_id'], 'contract': SPECS[number], 'cases': cases, 'rejectedCases': rejected,
                      'cobolSha256': audit.sha(row['COBOL_canonical_solution']), 'canonicalJavaSha256': audit.sha(row['Java_canonical_solution']),
                      'candidateJavaSha256': {name: audit.sha(source) for name, source in candidates.items()},
                      'probeSha256': audit.sha(probe(number)),
                      'candidateInterfaceEvidence': {name: audit.join_evidence(row, source) for name, source in candidates.items()}})
    value = {'schemaVersion': 'expanded-c2j-text-contract-v1', 'preparedAtUtc': datetime.now(timezone.utc).isoformat(),
             'status': 'FROZEN_BEFORE_EXECUTION', 'selection': 'EXPLORATORY_AFTER_JAVA_SCREENING',
             'artifacts': provenance, 'partitionSha256': audit.PARTITION_SHA, 'scriptHashes': hashes, 'tasks': tasks,
             'expectedAnswerMetadataUsed': False, 'reservedTasksExecuted': 0, 'admittedLabels': 0,
             'logicalLengthsNeverReadFromExpectedAnswers': True, 'numericRepresentationPolicy': 'Every COMP-2 array element maps to Java Double. Integer boxing is not inferred from literal spelling.',
             'source99Policy': 'Quoted alphanumeric MOVE into COMP-2 and Java String API is not an established common numeric contract; observe as artifact evidence only.',
             'taskCount': len(tasks), 'acceptedOriginalDrivers': sum(len(task['cases']) for task in tasks),
             'rejectedOriginalDrivers': sum(len(task['rejectedCases']) for task in tasks)}
    write_new(args.output / 'frozen-plan.json', value)
    print(json.dumps({key: value[key] for key in ['taskCount', 'acceptedOriginalDrivers', 'rejectedOriginalDrivers']}))


def success(record):
    return record['returnCode'] == 0 and not record['timedOut']


def execute(args):
    plan_path = args.output / 'frozen-plan.json'; plan_bytes = plan_path.read_bytes(); plan = json.loads(plan_bytes)
    for name, expected in plan['scriptHashes'].items():
        audit.verified_bytes(ROOT / 'scripts' / name, expected)
    _, selected = load(args)
    if (args.output / 'replay-report.json').exists():
        raise FileExistsError('Completed replay reports cannot be overwritten')
    raw = args.cache / 'expanded-text' / args.output.name
    raw.mkdir(parents=True, exist_ok=False)
    results = []
    for task in plan['tasks']:
        number = int(task['taskId'].split('/')[1]); row, candidates = selected[number]
        if audit.sha(row['COBOL_canonical_solution']) != task['cobolSha256'] or audit.sha(row['Java_canonical_solution']) != task['canonicalJavaSha256'] or audit.sha(probe(number)) != task['probeSha256']:
            raise ValueError('Frozen reference/probe changed')
        for name, source in candidates.items():
            if audit.sha(source) != task['candidateJavaSha256'][name]:
                raise ValueError('Frozen candidate changed')
        folder = raw / str(number); folder.mkdir()
        variants = {}
        for name, source in {'canonical': row['Java_canonical_solution'], **candidates}.items():
            directory = folder / name; directory.mkdir()
            if audit.DANGEROUS.search(audit.strip_comments(source)):
                raise ValueError('Java source requires further execution review')
            (directory / 'Solution.java').write_text(source)
            (directory / 'TextCaseReplay.java').write_text(probe(number))
            variants[name] = audit.process([str(args.jdk / 'javac'), '-J-Xmx128m', '-proc:none', '-encoding', 'UTF-8',
                                             'Solution.java', 'TextCaseReplay.java'], directory, 'compile', 15)
        records = []
        for case in task['cases']:
            index = case['driverIndex']; driver = row['tests'][index]['test']
            if audit.sha(driver) != case['driverSha256'] or extract_case(number, row, driver, index) != case:
                raise ValueError('Driver contract changed after freezing')
            directory = folder / f'case-{index}'; directory.mkdir()
            (directory / 'source.cbl').write_text(row['COBOL_canonical_solution']); (directory / 'driver.cbl').write_text(driver)
            record = {**case, 'java': {}, 'status': 'COBOL_COMPILATION_FAILURE'}
            record['cobolCompilation'] = audit.process([str(args.cobc), '-w', '-fformat=variable', '-x', '-o', 'driver', 'driver.cbl', 'source.cbl'], directory, 'compile', 15)
            if success(record['cobolCompilation']):
                record['cobolExecution'] = audit.process([str(directory / 'driver')], directory, 'execute', 5)
                record['status'] = 'COBOL_EXECUTION_FAILURE'
                if success(record['cobolExecution']):
                    try:
                        output = (directory / case['outputFile']).read_bytes()
                        record['cobolOutputHex'] = output.hex(); record['cobolOutputSha256'] = audit.sha(output)
                        record['cobolResult'], record['outputDecoding'] = parse_output(number, output, case)
                        record['status'] = 'COBOL_OBSERVED'
                    except (ValueError, OSError, UnicodeError) as error:
                        record['status'] = 'COBOL_OUTPUT_QUARANTINED'; record['reason'] = str(error)
            for name, compilation in variants.items():
                variant = {'compilation': compilation, 'status': 'COMPILATION_FAILURE'}
                if name in candidates and not task['candidateInterfaceEvidence'][name]['methodAgreement']:
                    variant['interfaceArtifact'] = True
                if success(compilation):
                    phase = f'case-{index}'; jdir = folder / name
                    execution = audit.process([str(args.jdk / 'java'), '-Xmx128m', '-XX:+UseSerialGC', '-ea', '-cp', str(jdir),
                                               'TextCaseReplay', *case['arguments']], jdir, phase, 5)
                    variant.update(status='EXECUTION_FAILURE', execution=execution)
                    stderr = (jdir / f'{phase}.stderr').read_text(errors='replace')
                    exception = re.search(r'Exception in thread "main" ([A-Za-z0-9_.$]+)(?:: ([^\n]*))?', stderr)
                    if execution['timedOut'] or re.search(r'\b(?:OutOfMemoryError|StackOverflowError)\b', stderr):
                        variant['status'] = 'RESOURCE_OR_TIMEOUT'
                    elif not success(execution) and exception:
                        variant.update(status='PROGRAM_EXCEPTION', exceptionType=exception[1], exceptionMessage=exception[2])
                    if success(execution):
                        try:
                            value = json.loads((jdir / f'{phase}.stdout').read_text())
                            if not valid_java_result(number, value):
                                raise ValueError('Java result type differs from declared task contract')
                            variant.update(status='OBSERVED', result=value)
                        except (ValueError, OSError, UnicodeError) as error:
                            variant.update(status='OUTPUT_QUARANTINED', reason=str(error))
                if record['status'] == 'COBOL_OBSERVED' and variant['status'] == 'OBSERVED':
                    variant['agreesWithObservedCobol'] = variant['result'] == record['cobolResult']
                record['java'][name] = variant
            canonical = record['java']['canonical']
            record['canonicalControl'] = ('AGREES' if canonical.get('agreesWithObservedCobol') is True else 'UNRESOLVED_OR_DISAGREES')
            for name in candidates:
                variant = record['java'][name]
                classification = 'NOT_COMPARABLE'
                if not case['mappingEligible']:
                    classification = 'SOURCE_INTERFACE_MAPPING_UNRESOLVED'
                elif record['canonicalControl'] != 'AGREES':
                    classification = 'REFERENCE_CONFLICT_OR_UNRESOLVED'
                elif variant['status'] == 'OBSERVED':
                    classification = 'AGREEMENT' if variant['agreesWithObservedCobol'] else 'BEHAVIOR_MISMATCH_PENDING_REVIEW'
                elif variant['status'] == 'PROGRAM_EXCEPTION':
                    classification = 'RUNTIME_FAILURE_PENDING_REVIEW'
                elif variant.get('interfaceArtifact'):
                    classification = 'INTERFACE_ARTIFACT'
                variant['classification'] = classification
            records.append(record)
        summary = {name: dict(Counter(record['java'][name]['classification'] for record in records)) for name in candidates}
        results.append({'taskId': task['taskId'], 'contract': task['contract'], 'rejectedCases': task['rejectedCases'],
                        'candidateInterfaceEvidence': task['candidateInterfaceEvidence'], 'records': records, 'summary': summary})
    versions = {}
    for name, path in {'cobc': args.cobc, 'java': args.jdk / 'java', 'javac': args.jdk / 'javac'}.items():
        versions[name] = {'path': str(path), 'sha256': audit.sha(path.read_bytes()),
                          'versionCommand': audit.process([str(path), '--version' if name == 'cobc' else '-version'], raw, f'version-{name}', 10)}
    report = {'schemaVersion': 'expanded-c2j-text-replay-v1', 'createdAtUtc': datetime.now(timezone.utc).isoformat(),
              'status': 'EXECUTED_PENDING_INDEPENDENT_REVIEW', 'frozenPlanSha256': audit.sha(plan_bytes), 'rawEvidencePath': str(raw),
              'selection': plan['selection'], 'toolchain': versions, 'tasks': results,
              'taskCount': len(results), 'originalDriverCasesExecuted': sum(len(task['records']) for task in results),
              'candidateSummary': {name: dict(Counter(record['java'][name]['classification'] for task in results for record in task['records'])) for name in ['7b', '14b']},
              'admittedTrainingLabels': 0, 'independentHumanReviews': 0, 'trainingPerformed': False, 'reservedTasksExecuted': 0,
              'expectedAnswerMetadataUsed': False, 'sourceOrDriverRewrites': False,
              'limitations': ['Task families were selected after Java screening and are exploratory, not unbiased prevalence or model accuracy estimates.',
                              'All original inputs and original serialized padding are retained in raw evidence; logical lengths are source/input derived, never answer derived.',
                              'COMP-2 maps to Double for every element; Java runtime Integer tags are not recovered from COBOL numeric spelling.',
                              'Task99 has unresolved quoted-text-to-numeric storage and an alternative candidate API; it cannot supply a strong source-equivalence defect label.',
                              'A failing canonical control quarantines candidate disagreements; finite agreements are not proofs.',
                              'Witnesses remain AI-curated, not independent human-reviewed ground truth.']}
    dispositions = []
    for task in results:
        records = task['records']
        witnessed = any(record['java'][name]['classification'] in {'BEHAVIOR_MISMATCH_PENDING_REVIEW', 'RUNTIME_FAILURE_PENDING_REVIEW'}
                        for record in records for name in ['7b', '14b'])
        conflict = any(record['status'] == 'COBOL_OBSERVED' and record['java']['canonical']['status'] == 'OBSERVED'
                       and record['canonicalControl'] != 'AGREES' for record in records)
        supported = sum(record['mappingEligible'] for record in records)
        comparable = sum(record['mappingEligible'] and record['canonicalControl'] == 'AGREES' for record in records)
        disposition = ('source_diff_control_agrees' if witnessed else 'unsupported' if not supported else
                       'source_diff_reference_conflict' if conflict else
                       'execution_failure' if not comparable else 'no_mismatch')
        dispositions.append({'taskId': task['taskId'], 'disposition': disposition,
                             'driverCount': len(records) + len(task['rejectedCases']),
                             'supportedDriverCount': supported, 'controlComparableDriverCount': comparable,
                             'executedOriginalDriverCount': len(records), 'candidateSummary': task['summary'],
                             'reason': ('Source/API numeric mapping unresolved; inspect raw evidence only.' if not supported else
                                        'At least one actual shared-input source discrepancy with agreeing canonical control; AI-curated, pending review.' if witnessed else
                                        'At least one canonical Java/source conflict quarantines its comparisons.' if conflict else
                                        'No independently reviewed defect label is admitted.')})
    report['familyDispositions'] = dispositions
    write_new(args.output / 'replay-report.json', report)
    print(json.dumps({'taskCount': report['taskCount'], 'originalDriverCasesExecuted': report['originalDriverCasesExecuted'], 'candidateSummary': report['candidateSummary']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true'); mode.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, default=ROOT / 'evaluation/corpora/natural-c2j')
    parser.add_argument('--partition', type=Path, default=ROOT / 'evaluation/paired-code/cv-partition-plan.json')
    parser.add_argument('--cobc', type=Path, default=Path('/tmp/sotonship-cobol-toolchain/install/bin/cobc'))
    parser.add_argument('--jdk', type=Path, default=Path('/Users/volodymyrsydorenko/Developer/jdk-21.0.10.jdk/Contents/Home/bin'))
    args = parser.parse_args()
    args.output = args.output.resolve(); args.cache = args.cache.resolve(); args.partition = args.partition.resolve()
    (prepare if args.prepare else execute)(args)


if __name__ == '__main__':
    main()
