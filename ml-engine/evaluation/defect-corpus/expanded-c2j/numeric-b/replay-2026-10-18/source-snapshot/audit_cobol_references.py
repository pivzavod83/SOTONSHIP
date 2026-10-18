#!/usr/bin/env python3
"""Audit canonical COBOL controls; never execute the reserved holdout.

This is an oracle-health audit, not an equivalence test or training pipeline.
The original benchmark's list serializer writes fixed-capacity arrays and uses
the expected answer's length. We disclose that convention rather than treating
it as independently established output-length equivalence.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

DATASET_SHA256 = "ff1b2e308ea006d905fd979103f32486c57d586c5fdbc0325a23f8ae23a6530d"
PARTITION_SHA256 = "a191deec018fe29d873fa6183d4bb6b366d36f7dd4424e769048ba63f7f57e53"
UPSTREAM_COMMIT = "2b14b7bf7e55556205654c6f7657fa60e36251fa"
LIMIT_LAUNCHER = """import os, resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
resource.setrlimit(resource.RLIMIT_FSIZE, (16777216, 16777216))
resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
os.execv(sys.argv[1], sys.argv[1:])
"""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_inputs(dataset: Path, partition: Path) -> tuple[list[dict], dict]:
    data_bytes, plan_bytes = dataset.read_bytes(), partition.read_bytes()
    if sha256_bytes(data_bytes) != DATASET_SHA256:
        raise ValueError("Dataset bytes differ from the pinned 143-task corpus")
    if sha256_bytes(plan_bytes) != PARTITION_SHA256:
        raise ValueError("Partition bytes differ from the preserved 120/23 split")
    rows = [json.loads(line) for line in data_bytes.splitlines() if line.strip()]
    plan = json.loads(plan_bytes)
    development, holdout = set(plan["developmentTaskIds"]), set(plan["finalHoldoutTaskIds"])
    ids = [row["task_id"] for row in rows]
    if len(ids) != len(set(ids)) or len(development) != 120 or len(holdout) != 23:
        raise ValueError("Unexpected task cardinality")
    if development & holdout or set(ids) != development | holdout:
        raise ValueError("Invalid development/holdout partition")
    return rows, plan


def parse_expected(result: dict):
    value = ast.literal_eval(result["value"])
    return list(value) if isinstance(value, tuple) else value


def parse_number(text: str, floating: bool = False):
    text = text.strip()
    # GnuCOBOL's non-separate leading SIGN uses ASCII overpunch p..y.
    if text and text[0] in "pqrstuvwxy":
        text = "-" + str(ord(text[0]) - ord("p")) + text[1:]
    return float(text) if floating else int(text)


def parse_output(raw: bytes, result_type, expected) -> dict:
    lines = raw.decode("utf-8", errors="strict").splitlines()
    is_list = isinstance(result_type, dict) and set(result_type) == {"List"}
    scalar_type = result_type["List"] if is_list else result_type
    count = len(expected) if is_list else 1
    if len(lines) < count:
        raise ValueError("Fewer serialized records than required by declared oracle")
    selected = lines[:count]

    def scalar(line):
        if scalar_type == "Bool":
            if line.strip() not in {"0", "1"}:
                raise ValueError("Boolean serialization is neither zero nor one")
            return line.strip() == "1"
        if scalar_type == "Int":
            return parse_number(line)
        if scalar_type == "Float":
            value = parse_number(line, floating=True)
            if not math.isfinite(value):
                raise ValueError("Non-finite floating output")
            return value
        if scalar_type == "String":
            return line.strip()
        raise ValueError(f"Unsupported result type: {result_type!r}")

    values = [scalar(line) for line in selected]
    observed = values if is_list else values[0]
    if scalar_type == "Float":
        trues = expected if is_list else [expected]
        compatible = len(values) == len(trues) and all(
            math.isclose(value, true, rel_tol=1e-9, abs_tol=0.001)
            for value, true in zip(values, trues)
        )
    else:
        compatible = observed == expected
    return {
        "observed": observed,
        "compatible": compatible,
        "serializedRecordCount": len(lines),
        "usedRecordCount": count,
        "ignoredTrailingRecordCount": len(lines) - count,
        "expectedLengthUsedForListProjection": is_list,
        "stringWhitespaceNormalizationUsed": scalar_type == "String",
        "floatAbsoluteTolerance": 0.001 if scalar_type == "Float" else None,
    }


def executable_lines(source: str) -> str:
    return "\n".join(line.split("*>", 1)[0] for line in source.splitlines()
                     if not line.lstrip().startswith("*"))


def source_preflight(canonical: str, driver: str) -> str:
    """Conservative review guard for this pinned, locally inspected corpus.

    This is not an adversarial source-code sandbox. No arbitrary sources are
    accepted: load_inputs verifies the entire source archive and fixed split.
    """
    solution, caller = executable_lines(canonical), executable_lines(driver)
    combined = solution + "\n" + caller
    token_left, token_right = r"(?<![A-Z0-9-])", r"(?![A-Z0-9-])"
    if re.search(token_left + r"(?:ACCEPT|DELETE|CHAIN|COPY|EXEC)" + token_right
                 + r"|" + token_left + r"OPEN\s+(?:INPUT|I-O|EXTEND)" + token_right, combined, re.I):
        raise ValueError("Source contains an operation outside the reviewed execution contract")
    program = re.search(r"PROGRAM-ID\.\s+([A-Z][A-Z0-9-]*)\.", solution, re.I)
    calls = re.findall(r"\bCALL\s+([^\s.]+)", combined, re.I)
    if not program or not calls or any(call.upper() != f'"{program.group(1).upper()}"' for call in calls):
        raise ValueError("Expected only a literal call to the canonical program")
    assigned = re.findall(r"\bASSIGN\s+(?:TO\s+)?[\"']([^\"']+)[\"']", combined, re.I)
    if len(assigned) != 1 or not re.fullmatch(r"[A-Z0-9-]+\.TXT", assigned[0], re.I):
        raise ValueError("Expected one relative .TXT output file")
    if re.search(token_left + r"SELECT" + token_right, solution, re.I):
        raise ValueError("Canonical program unexpectedly performs file I/O")
    return assigned[0]


def run_bounded(command: list[str], directory: Path, prefix: str, timeout: float) -> dict:
    stdout_path, stderr_path = directory / f"{prefix}.stdout", directory / f"{prefix}.stderr"
    started = datetime.now(timezone.utc)
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-c", LIMIT_LAUNCHER, *command], cwd=directory,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            start_new_session=True,
            env={**os.environ, "LC_ALL": "C", "COB_SCREEN_EXCEPT": "N"},
        )
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    return {
        "returncode": process.returncode,
        "timedOut": timed_out,
        "elapsedSeconds": round((datetime.now(timezone.utc) - started).total_seconds(), 4),
        "stdoutSha256": sha256_bytes(stdout_path.read_bytes()),
        "stderrSha256": sha256_bytes(stderr_path.read_bytes()),
        "stdoutBytes": stdout_path.stat().st_size,
        "stderrBytes": stderr_path.stat().st_size,
    }


def audit_driver(row: dict, index: int, cobc: str, cache: Path, timeout: float) -> dict:
    test = row["tests"][index]
    record = {
        "taskId": row["task_id"], "driverIndex": index,
        "canonicalSourceSha256": sha256_bytes(row["COBOL_canonical_solution"].encode()),
        "driverSourceSha256": sha256_bytes(test["test"].encode()),
        "expected": parse_expected(test["result"]), "resultType": test["result"]["type_"],
        "status": "UNRESOLVED", "executed": False,
    }
    directory = cache / (row["task_id"].replace("/", "-") + f"-driver-{index:02d}")
    directory.mkdir()
    record["rawEvidencePath"] = str(directory)
    try:
        output_name = source_preflight(row["COBOL_canonical_solution"], test["test"])
        (directory / "solution.cbl").write_text(row["COBOL_canonical_solution"])
        (directory / "driver.cbl").write_text(test["test"])
        command = [cobc, "-w", "-fformat=variable", "-x", "-o", str(directory / "driver"),
                   str(directory / "driver.cbl"), str(directory / "solution.cbl")]
        record["compile"] = run_bounded(command, directory, "compile", timeout)
        if record["compile"]["timedOut"]:
            record["status"] = "COMPILATION_TIMEOUT"
            return record
        if record["compile"]["returncode"]:
            record["status"] = "COMPILATION_FAILURE"
            return record
        record["executed"] = True
        record["run"] = run_bounded([str(directory / "driver")], directory, "run", timeout)
        if record["run"]["timedOut"]:
            record["status"] = "RUNTIME_TIMEOUT"
            return record
        if record["run"]["returncode"]:
            record["status"] = "RUNTIME_FAILURE"
            return record
        output_path = directory / output_name
        if not output_path.is_file():
            record["reason"] = "Expected serialized output file was not produced"
            return record
        raw = output_path.read_bytes()
        record["outputSha256"] = sha256_bytes(raw)
        record["outputBytes"] = len(raw)
        parsed = parse_output(raw, test["result"]["type_"], record["expected"])
        record.update(parsed)
        record["status"] = "DECLARED_ORACLE_COMPATIBLE" if parsed["compatible"] else "DECLARED_ORACLE_MISMATCH"
    except (ValueError, OSError, UnicodeError, SyntaxError) as error:
        record["reason"] = str(error)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/corpora/cobol-javatrans/COBOL-JavaTrans.jsonl"))
    parser.add_argument("--partition", type=Path, default=Path("evaluation/paired-code/cv-partition-plan.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path("evaluation/corpora/natural-c2j/cobol-reference-audit"))
    parser.add_argument("--cobc", default="cobc")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; evidence reports are immutable")
    if not 1 <= args.workers <= 4 or not 1 <= args.timeout <= 30:
        parser.error("Use 1..4 workers and 1..30 second process timeout")
    rows, plan = load_inputs(args.dataset, args.partition)
    development = set(plan["developmentTaskIds"])
    requested = set(args.task_id) if args.task_id else development
    if not requested <= development:
        parser.error("Only preserved development tasks may be executed, never holdout tasks")
    selected = [row for row in rows if row["task_id"] in requested]
    report = {
        "schemaVersion": "cobol-reference-oracle-audit-v1",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Canonical COBOL driver/oracle health; not cross-language equivalence or model accuracy",
        "datasetSha256": DATASET_SHA256, "partitionSha256": PARTITION_SHA256,
        "upstreamCommit": UPSTREAM_COMMIT,
        "upstreamEvaluator": f"https://github.com/COBOL-Coder/COBOL-Coder/blob/{UPSTREAM_COMMIT}/evaluation/evaluate_coboleval.py",
        "executionPerformed": not args.inventory_only,
        "auditScriptSha256": sha256_bytes(Path(__file__).read_bytes()),
        "sourceReview": {"reviewType": "AI source inspection and automated conservative preflight",
                         "independentHumanAdjudicationPerformed": False},
        "modelTrainingPerformed": False, "introducedMutations": 0,
        "holdoutExecutedTaskCount": 0,
        "holdoutInventory": [{"taskId": row["task_id"], "driverCount": len(row["tests"])}
                             for row in rows if row["task_id"] not in development],
        "developmentTaskCount": len(selected),
        "developmentDriverCount": sum(len(row["tests"]) for row in selected),
        "limitations": [
            "Runs canonical COBOL and its COBOL drivers only; Java inputs have not been joined.",
            "A canonical reference can disagree with a benchmark answer; this is not automatically a translation defect.",
            "Lists are projected using expected-answer length, as upstream; output-length equivalence is not established.",
            "String records are stripped, as upstream; significant leading/trailing-space behavior is not established.",
            "Float comparison uses upstream abs_tol=0.001 and rel_tol=1e-9.",
            "No section reordering, source repair, expected-answer changes, or canonical-source normalization.",
            "Compiler execution is bounded by time, CPU, output-file size and file-descriptor limits; it is not a hostile-code sandbox.",
            "Passing finite tests establishes compatibility only under these serializers, not universal equivalence.",
        ],
    }
    if not args.inventory_only:
        cobc = shutil.which(args.cobc)
        if not cobc:
            parser.error("GnuCOBOL cobc compiler was not found")
        cobc = str(Path(cobc).resolve())
        args.cache = args.cache.resolve()
        args.cache.mkdir(parents=True, exist_ok=False)
        version = subprocess.run([cobc, "-V"], capture_output=True, text=True, timeout=10, check=True)
        report["compiler"] = {"path": cobc, "sha256": sha256_bytes(Path(cobc).read_bytes()),
                              "versionOutput": version.stdout.strip(),
                              "flags": ["-w", "-fformat=variable", "-x"],
                              "compilationAndRuntimeTimeoutSeconds": args.timeout}
        jobs = [(row, i) for row in selected for i in range(len(row["tests"]))]
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            records = list(executor.map(lambda pair: audit_driver(*pair, cobc, args.cache, args.timeout), jobs))
        report["driverResults"] = records
        report["driverStatusCounts"] = dict(sorted(Counter(row["status"] for row in records).items()))
        report["taskResults"] = []
        for row in selected:
            rs = [r for r in records if r["taskId"] == row["task_id"]]
            report["taskResults"].append({"taskId": row["task_id"], "driverCount": len(rs),
                "allDriversDeclaredOracleCompatible": all(r["status"] == "DECLARED_ORACLE_COMPATIBLE" for r in rs),
                "driverStatusCounts": dict(sorted(Counter(r["status"] for r in rs).items()))})
        report["allDriversCompatibleTaskCount"] = sum(r["allDriversDeclaredOracleCompatible"] for r in report["taskResults"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(report, output, indent=2, ensure_ascii=False)
        output.write("\n")
    print(json.dumps({key: report[key] for key in ["developmentTaskCount", "developmentDriverCount", "holdoutExecutedTaskCount"]}
                     | {"driverStatusCounts": report.get("driverStatusCounts", {}), "output": str(args.output)}))


if __name__ == "__main__":
    main()
