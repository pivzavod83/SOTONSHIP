#!/usr/bin/env python3
"""Audit pinned natural COBOL-to-Java outputs against Java benchmark tests.

Development partition only. This screening is NOT COBOL equivalence checking,
does not create mutations, and admits zero semantic training labels. Source,
class files and raw process logs stay in the ignored cache. Never runs reserved
tasks, repairs source, calls a model, or overwrites an existing audit directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import time
import urllib.request

COMMIT = '2b14b7bf7e55556205654c6f7657fa60e36251fa'
BASE = f'https://raw.githubusercontent.com/COBOL-Coder/COBOL-Coder/{COMMIT}/'
PARTITION_SHA = 'a191deec018fe29d873fa6183d4bb6b366d36f7dd4424e769048ba63f7f57e53'
ARTIFACTS = {
    'data': ('evaluation/data/COBOL-JavaTrans.jsonl', 'ff1b2e308ea006d905fd979103f32486c57d586c5fdbc0325a23f8ae23a6530d'),
    '7b': ('evaluation/output/translation_COBOL_to_Java_COBOL-Coder_7b.jsonl', 'f2a640f57159d257de6d6c3fdbd5af970ef447ab4fb24a72b928e7f77b76dba6'),
    '14b': ('evaluation/output/translation_COBOL_to_Java_COBOL-Coder_14b.jsonl', '5282a929afc7b0e0775f2f2109805a19052f8885e8143d81f7736b24906f4c41'),
    'license': ('LICENSE', '50e6751797c50dedd75ef1b8a0d9e42f5f8472e9fbce91f34718e9f97b0c780a'),
    'generator': ('evaluation/generate_cobol_javatrans.py', 'ae23e080366a54bbdf427acd572d67091ed3ec68dc7548ac25e5d7a2bd548497'),
    'evaluator': ('evaluation/evaluate_translation_c2j.py', 'c188f079d7f2152720fd8695328a26f6e844680dc8bf7a47bfbc314c1df0a4b8'),
    'utils': ('evaluation/utils.py', '273eb153d1045b26d104f0e73c4dcabf5b2f3a5cf020187223863b87019d85b8'),
}
METHOD = re.compile(r'public\s+(?:(?:static|final|synchronized)\s+)*(?:[\w.$<>,?\[\] ]+?)\s+(\w+)\s*\(')
DANGEROUS = re.compile(
    r'\b(?:java\.(?:io|nio|net|lang\.reflect)|javax\.|ProcessBuilder|Runtime|'
    r'Thread|ClassLoader|SecurityManager|Unsafe|native)\b|'
    r'\bSystem\s*\.\s*(?:exit|set\w*|load\w*|getenv|getProperties)\s*\(|'
    r'\bClass\s*\.\s*forName\s*\('
)


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode('utf-8') if isinstance(data, str) else data).hexdigest()


def verified_bytes(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError(f'Pinned SHA256 mismatch: {path.name}')
    return data


def strip_comments(source: str) -> str:
    # Retain string literals while removing comments; conservative review only,
    # not a Java parser or a security sandbox.
    return re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*[\s\S]*?\*/|//[^\n]*',
                  lambda m: ' ' if m[0].startswith(('/*', '//')) else m[0], source)


def join_evidence(row: dict, completion: str) -> dict:
    expected = METHOD.findall(strip_comments(row['Java_prompt']))
    found = METHOD.findall(strip_comments(completion))
    classes = re.findall(r'\bclass\s+(\w+)', strip_comments(completion))
    ok = len(expected) == 1 and expected[0] in found and 'Solution' in classes
    return {'methodAgreement': ok, 'expectedMethod': expected[0] if len(expected) == 1 else None,
            'observedPublicMethods': found, 'solutionClassPresent': 'Solution' in classes,
            'status': 'ORDINAL_WITH_METHOD_CLASS_AGREEMENT' if ok else 'JOIN_UNRESOLVED',
            'independentTaskIdPresentInOutput': False}


def load_partition(path: Path, rows: list[dict], expected_sha: str = PARTITION_SHA) -> dict:
    plan = json.loads(verified_bytes(path, expected_sha))
    development = plan['developmentTaskIds']
    reserved = plan['finalHoldoutTaskIds']
    task_ids = [row['task_id'] for row in rows]
    if (len(rows) != 143 or len(set(task_ids)) != 143 or len(development) != 120
            or len(reserved) != 23 or len(set(development)) != 120 or len(set(reserved)) != 23
            or set(development) & set(reserved) or set(task_ids) != set(development) | set(reserved)):
        raise ValueError('Invalid or incomplete 120/23 task-family partition.')
    return plan


def load_sources(cache: Path, fetch: bool) -> tuple[dict, list[dict], dict[str, list[dict]]]:
    cache.mkdir(parents=True, exist_ok=True)
    provenance = {}
    data = {}
    for key, (relative, expected) in ARTIFACTS.items():
        target = cache / Path(relative).name
        if not target.exists():
            if not fetch:
                raise FileNotFoundError(f'Missing {target}; use --fetch for pinned public artifacts.')
            payload = urllib.request.urlopen(BASE + relative, timeout=60).read()
            if sha(payload) != expected:
                raise ValueError(f'Download changed: {relative}')
            with target.open('xb') as handle:
                handle.write(payload)
        payload = verified_bytes(target, expected)
        data[key] = payload
        provenance[key] = {'url': BASE + relative, 'sha256': expected, 'bytes': len(payload)}
    rows = [json.loads(line) for line in data['data'].splitlines() if line.strip()]
    outputs = {key: [json.loads(line) for line in data[key].splitlines() if line.strip()] for key in ('7b', '14b')}
    if any(len(values) != len(rows) for values in outputs.values()):
        raise ValueError('Candidate and benchmark row counts differ; refusing positional truncation.')
    for values in outputs.values():
        if any(set(row) != {'completion'} or not isinstance(row['completion'], str) for row in values):
            raise ValueError('Unexpected completion-only output schema.')
    return provenance, rows, outputs


def preexec_limits(cpu_seconds: int) -> None:
    os.setsid()
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def process(command: list[str], folder: Path, phase: str, seconds: float) -> dict:
    started = time.monotonic()
    out, err = folder / f'{phase}.stdout', folder / f'{phase}.stderr'
    # A new process group permits killing children on a wall-clock timeout.
    # Files bound output; this avoids unlimited capture_output memory use.
    with out.open('xb') as stdout, err.open('xb') as stderr:
        proc = subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
                                     'TMPDIR': str(folder)}, preexec_fn=lambda: preexec_limits(int(seconds) + 1))
        timed_out = False
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    return {'command': command, 'returnCode': proc.returncode, 'timedOut': timed_out,
            'elapsedSeconds': round(time.monotonic() - started, 4),
            'stdoutSha256': sha(out.read_bytes()), 'stderrSha256': sha(err.read_bytes()),
            'stdoutBytes': out.stat().st_size, 'stderrBytes': err.stat().st_size}


def classify(compile_result: dict, run_result: dict | None, stderr: str = '') -> str:
    if compile_result['timedOut']:
        return 'COMPILE_TIMEOUT'
    if compile_result['returnCode'] != 0:
        return 'COMPILE_ERROR'
    if run_result is None:
        raise ValueError('A successful compilation requires a recorded execution.')
    if run_result['timedOut']:
        return 'EXECUTION_TIMEOUT'
    if run_result['returnCode'] == 0:
        return 'JAVA_TESTS_PASS_ONLY'
    if re.search(r'\bjava\.lang\.AssertionError\b', stderr):
        return 'JAVA_TEST_ASSERTION_FAILURE'
    if any(term in stderr for term in ('OutOfMemoryError', 'StackOverflowError')):
        return 'RESOURCE_FAILURE'
    return 'JAVA_RUNTIME_FAILURE'


def run_java(source: str, tests: str, folder: Path, jdk: Path,
             compile_timeout: float = 15, run_timeout: float = 5) -> dict:
    folder.mkdir(parents=True, exist_ok=False)
    if DANGEROUS.search(strip_comments(source)) or DANGEROUS.search(strip_comments(tests)):
        return {'status': 'STATIC_EXECUTION_REVIEW_REQUIRED', 'executionPerformed': False}
    (folder / 'Solution.java').write_text(source, encoding='utf-8')
    # Exactly the import wrapper applied by the pinned upstream evaluator.
    (folder / 'Main.java').write_text('import java.util.*;\n' + tests, encoding='utf-8')
    compile_result = process([str(jdk / 'javac'), '-J-Xmx128m', '-J-XX:ActiveProcessorCount=1',
                              '-proc:none', '-encoding', 'UTF-8', '-d', str(folder),
                              'Solution.java', 'Main.java'], folder, 'compile', compile_timeout)
    run_result = None
    if compile_result['returnCode'] == 0 and not compile_result['timedOut']:
        run_result = process([str(jdk / 'java'), '-Xmx128m', '-Xss1m', '-XX:ActiveProcessorCount=1',
                              '-XX:+UseSerialGC', '-ea', '-cp', str(folder), 'Main'], folder, 'run', run_timeout)
    stderr = (folder / 'run.stderr').read_text(errors='replace') if run_result else ''
    return {'status': classify(compile_result, run_result, stderr), 'executionPerformed': True,
            'compilation': compile_result, 'execution': run_result,
            'runnerScope': 'Java benchmark assertions only; no COBOL execution or equivalence claim'}


def inventory(rows: list[dict], outputs: dict[str, list[dict]], plan: dict) -> list[dict]:
    development = set(plan['developmentTaskIds'])
    result = []
    for ordinal, row in enumerate(rows):
        partition = 'development' if row['task_id'] in development else 'reserved'
        common = {'taskId': row['task_id'], 'rowOrdinalZeroBased': ordinal, 'partition': partition,
                  'cobolSourceSha256': sha(row['COBOL_canonical_solution']),
                  'javaTestsSha256': sha(row['Java_tests']), 'javaPromptSha256': sha(row['Java_prompt'])}
        result.append({**common, 'variant': 'reference', 'javaSourceSha256': sha(row['Java_canonical_solution']),
                       'join': {'status': 'TASK_ID_IN_PINNED_DATASET'}, 'status': 'NOT_EXECUTED'})
        for model, values in outputs.items():
            completion = values[ordinal]['completion']
            cutoff = completion[100:].find('import java')
            upstream_cleaned = completion[:cutoff + 100] if cutoff != -1 else completion
            result.append({**common, 'variant': model, 'javaSourceSha256': sha(completion),
                           'upstreamCleanerWouldChangeSource': upstream_cleaned != completion,
                           'upstreamCleanerResultSha256': sha(upstream_cleaned),
                           'join': join_evidence(row, completion), 'status': 'NOT_EXECUTED'})
    return result


def audit(args: argparse.Namespace) -> dict:
    date.fromisoformat(args.collected_date)
    provenance, rows, outputs = load_sources(args.cache, args.fetch)
    plan = load_partition(args.partition, rows)
    entries = inventory(rows, outputs, plan)
    args.output.mkdir(parents=True, exist_ok=False)
    raw_run = args.cache / 'runs' / args.output.name
    raw_run.mkdir(parents=True, exist_ok=False)
    versions = {}
    if args.execute_development:
        for executable in ('java', 'javac'):
            binary = args.jdk / executable
            result = subprocess.run([str(binary), '-version'], capture_output=True, timeout=10)
            if result.returncode:
                raise ValueError(f'Cannot inspect {executable} version.')
            versions[executable] = {'path': str(binary), 'binarySha256': sha(binary.read_bytes()),
                                    'versionOutput': (result.stdout + result.stderr).decode(errors='replace').strip()}
        def execute(entry: dict) -> dict:
            if entry['partition'] != 'development':
                entry['status'] = 'RESERVED_NOT_EXECUTED'
                return entry
            if entry['join']['status'] == 'JOIN_UNRESOLVED':
                entry['status'] = 'JOIN_UNRESOLVED_NOT_EXECUTED'
                return entry
            row = rows[entry['rowOrdinalZeroBased']]
            source = (row['Java_canonical_solution'] if entry['variant'] == 'reference'
                      else outputs[entry['variant']][entry['rowOrdinalZeroBased']]['completion'])
            case = raw_run / f"{entry['rowOrdinalZeroBased']:03d}-{entry['variant']}"
            result = run_java(source, row['Java_tests'], case, args.jdk, args.compile_timeout, args.run_timeout)
            # Absolute raw paths and source remain ignored; report stable relative IDs.
            for phase in ('compilation', 'execution'):
                if result.get(phase):
                    result[phase]['command'] = [word.replace(str(raw_run), '<IGNORED_RUN_CACHE>')
                                                for word in result[phase]['command']]
            entry.update(result)
            entry['rawEvidenceCase'] = case.name
            return entry
        # External JVMs have independent limits. Avoid Python preexec_fn in worker
        # threads: sequential execution is intentional and reliable on macOS.
        for index, entry in enumerate(entries):
            entries[index] = execute(entry)
            if (index + 1) % 30 == 0:
                print(f'Screened inventory entries {index + 1}/{len(entries)}', flush=True)
    else:
        for entry in entries:
            if entry['partition'] == 'reserved':
                entry['status'] = 'RESERVED_NOT_EXECUTED'
    counts = {variant: dict(Counter(e['status'] for e in entries if e['variant'] == variant
                                   and e['partition'] == 'development')) for variant in ('reference', '7b', '14b')}
    result = {
        'schemaVersion': 1, 'collectedDate': args.collected_date,
        'status': 'DEVELOPMENT_JAVA_SCREENING_ONLY' if args.execute_development else 'INVENTORY_ONLY',
        'upstreamCommit': COMMIT, 'artifacts': provenance, 'partitionSha256': PARTITION_SHA,
        'scriptSha256': sha(Path(__file__).read_bytes()), 'toolchain': versions,
        'frozenPlanSha256': sha((Path(__file__).resolve().parents[1] / 'evaluation/defect-corpus/natural-c2j-plan.json').read_bytes()),
        'limits': {'compilationWallSeconds': args.compile_timeout, 'executionWallSeconds': args.run_timeout,
                   'javaHeapMiB': 128, 'outputFileLimitBytes': 1048576,
                   'processGroupKilledOnTimeout': True, 'assertionsEnabled': True,
                   'note': 'Static source review and process limits are not an OS security sandbox.'},
        'developmentTaskFamilies': len(plan['developmentTaskIds']),
        'reservedTaskFamilies': len(plan['finalHoldoutTaskIds']),
        'candidateTranslations': len(rows) * len(outputs),
        'reservedCandidateTranslationsExecuted': sum(e.get('executionPerformed', False) for e in entries
                                                      if e['partition'] == 'reserved' and e['variant'] != 'reference'),
        'developmentStatusCounts': counts,
        'newSemanticLabelsAdmitted': 0, 'modelTrainingPerformed': False, 'mutationsIntroduced': 0,
        'limitations': [
            'Output files have no task IDs. Joins use pinned ordinal order supported by generator code and method/class checks; this does not independently prove row identity. A mismatched method may reflect a wrong translation rather than a misordered row; quarantined cases require review.',
            'Raw completion bytes are preserved as source: the upstream clean_java_response truncation heuristic is not applied, so these are not claimed as exact reproductions of paper compilation/pass rates.',
            'Java test failures are screening outcomes, not proven COBOL-to-Java semantic defects. Java tests may exceed COBOL input domains.',
            'Passing finite Java assertions is not proof of equivalence to the COBOL source.',
            'Canonical Java is a reference control, not an independently established COBOL oracle.',
            'No source correction, output cleaning, bug injection, LLM request, reserved execution or training is performed.',
            'Source, logs, tests, model provenance and execution results must not become static detector inputs.',
            'Repository LICENSE is Apache-2.0; upstream HumanEval-derived source notices and dataset-specific rights still apply.',
        ], 'entries': entries,
    }
    (args.output / 'screening-report.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=root / 'evaluation/corpora/natural-c2j')
    parser.add_argument('--partition', type=Path, default=root / 'evaluation/paired-code/cv-partition-plan.json')
    parser.add_argument('--output', type=Path, required=True, help='New report directory; refuses overwrite')
    parser.add_argument('--collected-date', required=True)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--execute-development', action='store_true')
    parser.add_argument('--jdk', type=Path, default=Path('/Users/volodymyrsydorenko/Developer/jdk-21.0.10.jdk/Contents/Home/bin'))
    parser.add_argument('--compile-timeout', type=float, default=15)
    parser.add_argument('--run-timeout', type=float, default=5)
    args = parser.parse_args()
    if args.compile_timeout <= 0 or args.run_timeout <= 0:
        parser.error('Timeouts must be positive.')
    result = audit(args)
    print(json.dumps({key: result[key] for key in ('status', 'developmentStatusCounts',
                                                  'reservedCandidateTranslationsExecuted', 'newSemanticLabelsAdmitted')}, indent=2))


if __name__ == '__main__':
    main()
