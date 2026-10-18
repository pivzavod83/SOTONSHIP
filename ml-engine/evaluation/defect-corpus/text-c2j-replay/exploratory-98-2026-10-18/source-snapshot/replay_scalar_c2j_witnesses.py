"""Replay a frozen, bounded set of scalar COBOL/Java contracts.

Only original development-set drivers are used. Their expected-result metadata
is deliberately ignored: the actual COBOL execution is the comparison oracle.
This is a local corpus-curation command, not an application execution endpoint.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evaluation/corpora/natural-c2j/COBOL-JavaTrans.jsonl"
PARTITION = ROOT / "evaluation/paired-code/cv-partition-plan.json"
MODEL_FILES = {
    "7b": ROOT / "evaluation/corpora/natural-c2j/translation_COBOL_to_Java_COBOL-Coder_7b.jsonl",
    "14b": ROOT / "evaluation/corpora/natural-c2j/translation_COBOL_to_Java_COBOL-Coder_14b.jsonl",
}
# Declared before observing replay outputs; integer inputs are restricted to the
# original drivers and bounded further below. These are task contracts, not an
# inferred universal adapter.
CONTRACTS = {
    24: ("largestDivisor", ["N"], "int", 1, 100),
    31: ("isPrime", ["N"], "boolean", 1, 1_000_000),
    36: ("fizzBuzz", ["N"], "int", 1, 100_000),
    46: ("fib4", ["N"], "int", 0, 12),
    49: ("modp", ["N", "P"], "int", 0, 1101),
    53: ("add", ["X", "Y"], "int", 0, 1000),
    55: ("fib", ["N"], "int", 0, 12),
    59: ("largestPrimeFactor", ["N"], "int", 2, 13195),
    60: ("sumToN", ["N"], "int", 1, 100),
    63: ("fibfib", ["N"], "int", 0, 14),
    77: ("iscube", ["A"], "boolean", -1729, 1729),
    83: ("startsOneEnds", ["N"], "int", 1, 5),
    97: ("multiply", ["A", "B"], "int", -2020, 2020),
    131: ("digits", ["N"], "int", 1, 9_999_999),
    138: ("isEqualToSumEven", ["N"], "boolean", 0, 100),
    150: ("xOrY", ["N", "X", "Y"], "int", -1, 7919),
    157: ("rightAngleTriangle", ["A", "B", "C"], "boolean", 1, 100),
}
COBOL_FLAGS = ["-w", "-fformat=variable", "-x"]
DECODER = "ASCII display digits; leading p..y denotes a negative leading digit 0..9; one LF/CRLF record"


class UnsupportedContract(ValueError):
    pass


def digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def code_lines(source: str) -> str:
    """Validate the upstream variable-format columns without rewriting source."""
    code = []
    for index, line in enumerate(source.splitlines(), 1):
        if not line.strip():
            continue
        if len(line) < 7 or line[:6] != "      ":
            raise UnsupportedContract(f"line {index}: unexpected sequence columns")
        if line[6] == "*":
            continue
        if line[6] != " ":
            raise UnsupportedContract(f"line {index}: unsupported indicator column")
        if len(line) > 255 and line[255:].strip():
            raise UnsupportedContract(f"line {index}: code exceeds variable-format column 255")
        code.append(line[7:255])
    return "\n".join(code)


def require_development(task_id: str, partition: dict) -> None:
    if task_id not in partition["developmentTaskIds"] or task_id in partition["finalHoldoutTaskIds"]:
        raise UnsupportedContract("task is not exclusively in the development partition")


def linkage(source: str) -> list[tuple[str, str]]:
    text = code_lines(source)
    section = re.search(r"LINKAGE SECTION\.(.*?)PROCEDURE DIVISION USING LINKED-ITEMS\.", text, re.S)
    if not section:
        raise UnsupportedContract("unsupported linkage or procedure interface")
    body = section[1].strip()
    declarations = re.findall(r"05\s+([A-Z][A-Z0-9-]*)\s+PIC\s+(S?9(?:\(\d+\))?)\.", body)
    remainder = re.sub(r"01\s+LINKED-ITEMS\.", "", body)
    remainder = re.sub(r"05\s+[A-Z][A-Z0-9-]*\s+PIC\s+S?9(?:\(\d+\))?\.", "", remainder)
    if remainder.strip() or not declarations:
        raise UnsupportedContract("non-scalar or unexpected linkage declaration")
    return declarations


def extract_case(row: dict, driver: str, spec: tuple, index: int) -> dict:
    method, parameters, return_type, low, high = spec
    source = row["COBOL_canonical_solution"]
    expected_linkage = [(f"L-{name}", "S9(10)") for name in parameters]
    expected_linkage.append(("RESULT", "9" if return_type == "boolean" else "S9(10)"))
    if linkage(source) != expected_linkage:
        raise UnsupportedContract("source linkage does not match the frozen task contract")
    text = code_lines(driver)
    # Driver working storage must use exactly the same scalar linkage layout.
    block = re.search(r"01\s+LINKED-ITEMS\.(.*?)PROCEDURE DIVISION\.", text, re.S)
    if not block:
        raise UnsupportedContract("driver has no supported linkage storage")
    declarations = re.findall(r"05\s+([A-Z][A-Z0-9-]*)\s+PIC\s+(S?9(?:\(\d+\))?)\.", block[1])
    if declarations != expected_linkage:
        raise UnsupportedContract("driver and source linkage differ")
    procedure = text.split("PROCEDURE DIVISION.", 1)[1]
    calls = re.findall(r'CALL\s+"([A-Z0-9-]+)"\s+USING\s+LINKED-ITEMS', procedure)
    program = re.search(r"PROGRAM-ID\.\s*([A-Z0-9-]+)\.", code_lines(source))[1]
    if calls != [program]:
        raise UnsupportedContract("driver must call the source program exactly once")
    prefix = procedure.split("CALL", 1)[0]
    moves = re.findall(r"MOVE\s+(-?\d+)\s+TO\s+(L-[A-Z0-9-]+)\s*\.?", prefix)
    remainder = re.sub(r"MOVE\s+-?\d+\s+TO\s+L-[A-Z0-9-]+\s*\.?", "", prefix)
    if remainder.strip():
        raise UnsupportedContract("unsupported input initialization statement")
    if len(moves) != len(parameters) or len({name for _, name in moves}) != len(parameters):
        raise UnsupportedContract("missing, duplicate or extra scalar MOVE")
    values = {name: int(value) for value, name in moves}
    if set(values) != {f"L-{name}" for name in parameters}:
        raise UnsupportedContract("MOVE parameter names differ from the contract")
    arguments = [values[f"L-{name}"] for name in parameters]
    if any(value < low or value > high or not -(2**31) <= value < 2**31 for value in arguments):
        raise UnsupportedContract("input outside the frozen common numeric bounds")
    if method == "modp" and values["L-P"] <= 0:
        raise UnsupportedContract("modulus must be positive")
    if method == "xOrY" and values["L-N"] <= 0:
        raise UnsupportedContract("primality discriminator must be positive")
    filenames = re.findall(r'SELECT OUTPUT-FILE ASSIGN TO "([A-Z0-9_-]+\.TXT)"', text)
    if len(filenames) != 1:
        raise UnsupportedContract("unsupported output path")
    output_pic = "9" if return_type == "boolean" else "S9(10) SIGN LEADING"
    if not re.search(rf"01\s+OUTPUT-RECORD\s+PIC\s+{re.escape(output_pic)}\.", text):
        raise UnsupportedContract("output record cannot represent the full scalar result")
    # No custom output adapters: require direct RESULT -> OUTPUT-RECORD.
    if len(re.findall(r"MOVE RESULT TO OUTPUT-RECORD", text)) != 1:
        raise UnsupportedContract("output is not a direct scalar result")
    return {"driverIndex": index, "driverSha256": digest(driver), "arguments": arguments,
            "outputFile": filenames[0], "outputPic": output_pic}


def java_probe(method: str, parameter_count: int) -> str:
    arguments = ", ".join(f"Integer.parseInt(args[{i}])" for i in range(parameter_count))
    return ("public final class ScalarReplay { public static void main(String[] args) { "
            f"System.out.print(new Solution().{method}({arguments}));" + " } }\n")


def parse_cobol_output(raw: bytes, return_type: str) -> int | bool:
    record = raw[:-2] if raw.endswith(b"\r\n") else raw[:-1] if raw.endswith(b"\n") else raw
    if return_type == "boolean":
        if record not in (b"0", b"1"):
            raise UnsupportedContract("boolean record is not exactly 0 or 1")
        return record == b"1"
    if len(record) != 10:
        raise UnsupportedContract("signed scalar record is not exactly ten display digits")
    text = record.decode("ascii")
    if text.isdecimal():
        return int(text)
    if text[0] in "pqrstuvwxy" and text[1:].isdecimal():
        return -int(str("pqrstuvwxy".index(text[0])) + text[1:])
    raise UnsupportedContract("unsupported signed display encoding")


def prepare(output: Path) -> dict:
    partition = json.loads(PARTITION.read_text())
    rows = [json.loads(line) for line in DATA.read_text().splitlines()]
    candidates = {name: [json.loads(line) for line in path.read_text().splitlines()]
                  for name, path in MODEL_FILES.items()}
    if len(rows) != 143 or any(len(values) != len(rows) for values in candidates.values()):
        raise UnsupportedContract("positional upstream candidate alignment is not 143 rows")
    tasks, rejected = [], []
    for position, row in enumerate(rows):
        task_id = row["task_id"]
        number = int(task_id.split("/")[1])
        if number not in CONTRACTS:
            continue
        require_development(task_id, partition)
        spec = CONTRACTS[number]
        method, parameters, return_type, low, high = spec
        signature = rf"public\s+{return_type}\s+{method}\(\s*" + r"\s*,\s*".join(
            r"int\s+[A-Za-z][A-Za-z0-9_]*" for _ in parameters) + r"\s*\)"
        if not re.search(signature, row["Java_canonical_solution"]):
            raise UnsupportedContract(f"reference Java signature differs: {task_id}")
        cases = []
        for index, original in enumerate(row["tests"]):
            try:
                cases.append(extract_case(row, original["test"], spec, index))
            except UnsupportedContract as error:
                rejected.append({"taskId": task_id, "driverIndex": index, "reason": str(error)})
        tasks.append({"taskId": task_id, "rowPosition": position, "method": method,
                      "parameters": parameters, "returnType": return_type,
                      "inputBoundsInclusive": [low, high], "cases": cases,
                      "cobolSourceSha256": digest(row["COBOL_canonical_solution"]),
                      "canonicalJavaSha256": digest(row["Java_canonical_solution"]),
                      "candidateJavaSha256": {name: digest(values[position]["completion"])
                                               for name, values in candidates.items()},
                      "probeSha256": digest(java_probe(method, len(parameters)))})
    report = {"schemaVersion": "scalar-c2j-frozen-contract-v1", "createdAt": utc_now(),
              "status": "FROZEN_BEFORE_REPLAY", "aiGeneratedAdapters": True,
              "trainingPerformed": False, "heldoutSourceInspected": False,
              "expectedResultMetadataUsedAsOracle": False,
              "candidateAlignment": "position against the exact pinned 143-row upstream file",
              "partitionSha256": digest(PARTITION.read_bytes()),
              "datasetSha256": digest(DATA.read_bytes()),
              "candidateFilesSha256": {name: digest(path.read_bytes()) for name, path in MODEL_FILES.items()},
              "scriptSha256": digest(Path(__file__).read_bytes()),
              "compilerFlags": COBOL_FLAGS, "outputDecoder": DECODER,
              "excludedContracts": [{"taskId": "HumanEval/139", "reason": "source result PIC S9(20), driver output PIC S9(10): truncated output cannot establish full result equivalence"}],
              "tasks": tasks, "quarantinedInputs": rejected,
              "taskCount": len(tasks), "inputCaseCount": sum(len(task["cases"]) for task in tasks)}
    write_new(output, report)
    return report


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def command(arguments: list[str], folder: Path, log_name: str, timeout: int = 30) -> dict:
    try:
        result = subprocess.run(arguments, cwd=folder, capture_output=True, timeout=timeout)
        value = {"returnCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
                 "timedOut": False}
    except subprocess.TimeoutExpired as error:
        value = {"returnCode": None, "stdout": error.stdout or b"", "stderr": error.stderr or b"",
                 "timedOut": True}
    (folder / f"{log_name}.stdout").write_bytes(value["stdout"])
    (folder / f"{log_name}.stderr").write_bytes(value["stderr"])
    return {"command": arguments, "returnCode": value["returnCode"], "timedOut": value["timedOut"],
            "stdoutSha256": digest(value["stdout"]), "stderrSha256": digest(value["stderr"]),
            "stdoutHex": value["stdout"].hex(), "stderrBytes": len(value["stderr"])}


def succeeded(run: dict) -> bool:
    return run["returnCode"] == 0 and not run["timedOut"]


def run_replay(frozen_path: Path, output: Path, raw: Path, cobc: Path, java: Path, javac: Path) -> dict:
    frozen_bytes = frozen_path.read_bytes()
    frozen = json.loads(frozen_bytes)
    if frozen["status"] != "FROZEN_BEFORE_REPLAY" or frozen["scriptSha256"] != digest(Path(__file__).read_bytes()):
        raise UnsupportedContract("frozen plan status or script digest differs")
    if frozen["partitionSha256"] != digest(PARTITION.read_bytes()) or frozen["datasetSha256"] != digest(DATA.read_bytes()):
        raise UnsupportedContract("dataset or partition changed after freezing")
    for name, path in MODEL_FILES.items():
        if frozen["candidateFilesSha256"][name] != digest(path.read_bytes()):
            raise UnsupportedContract("candidate artifact changed after freezing")
    raw.mkdir(parents=True, exist_ok=False)
    partition = json.loads(PARTITION.read_text())
    rows = [json.loads(line) for line in DATA.read_text().splitlines()]
    candidates = {name: [json.loads(line) for line in path.read_text().splitlines()]
                  for name, path in MODEL_FILES.items()}
    tools = {}
    for name, executable in {"cobc": cobc, "java": java, "javac": javac}.items():
        executable = executable.resolve()
        tools[name] = {"path": str(executable), "sha256": digest(executable.read_bytes()),
                       "version": command([str(executable), "-version" if name != "cobc" else "--version"], raw, name)}
    results = []
    for task in frozen["tasks"]:
        require_development(task["taskId"], partition)
        row = rows[task["rowPosition"]]
        if row["task_id"] != task["taskId"]:
            raise UnsupportedContract("positional task alignment changed")
        folder = raw / task["taskId"].replace("/", "-")
        folder.mkdir()
        (folder / "source.cob").write_text(row["COBOL_canonical_solution"])
        variant_results = {}
        for name, source in {"canonical": row["Java_canonical_solution"],
                             **{key: values[task["rowPosition"]]["completion"] for key, values in candidates.items()}}.items():
            variant = folder / name
            variant.mkdir()
            (variant / "Solution.java").write_text(source)
            (variant / "ScalarReplay.java").write_text(java_probe(task["method"], len(task["parameters"])))
            compilation = command([str(javac), "-encoding", "UTF-8", "Solution.java", "ScalarReplay.java"], variant, "compile")
            variant_results[name] = {"compilation": compilation, "cases": []}
        case_results = []
        for case in task["cases"]:
            driver = row["tests"][case["driverIndex"]]["test"]
            if digest(driver) != case["driverSha256"]:
                raise UnsupportedContract("driver changed after freezing")
            case_folder = folder / f"case-{case['driverIndex']}"
            case_folder.mkdir()
            (case_folder / "driver.cob").write_text(driver)
            compilation = command([str(cobc), *COBOL_FLAGS, "-o", "replay", "driver.cob", "../source.cob"], case_folder, "compile")
            observed = {**case, "cobolCompilation": compilation, "cobolStatus": "COMPILE_FAILURE"}
            if succeeded(compilation):
                execution = command([str(case_folder / "replay")], case_folder, "execute", 5)
                observed["cobolExecution"] = execution
                file_path = case_folder / case["outputFile"]
                observed["cobolStatus"] = "EXECUTION_FAILURE"
                if succeeded(execution) and file_path.is_file():
                    actual = file_path.read_bytes()
                    observed["cobolOutputHex"] = actual.hex()
                    observed["cobolOutputSha256"] = digest(actual)
                    try:
                        observed["cobolResult"] = parse_cobol_output(actual, task["returnType"])
                        if task["returnType"] == "int" and not -(2**31) <= observed["cobolResult"] < 2**31:
                            raise UnsupportedContract("actual COBOL result outside Java int range")
                        observed["cobolStatus"] = "OBSERVED"
                    except (UnsupportedContract, UnicodeDecodeError) as error:
                        observed["cobolStatus"] = "QUARANTINED_OUTPUT"
                        observed["reason"] = str(error)
            for name, variant in variant_results.items():
                entry = {"driverIndex": case["driverIndex"], "arguments": case["arguments"], "status": "COMPILE_FAILURE"}
                if succeeded(variant["compilation"]):
                    execution = command([str(java), "-cp", str(folder / name), "ScalarReplay", *map(str, case["arguments"])],
                                        folder / name, f"case-{case['driverIndex']}", 5)
                    entry["execution"] = execution
                    entry["status"] = "EXECUTION_FAILURE"
                    if succeeded(execution):
                        text = bytes.fromhex(execution["stdoutHex"]).decode("ascii", errors="replace")
                        if task["returnType"] == "boolean" and text in ("true", "false"):
                            entry["result"] = text == "true"
                            entry["status"] = "OBSERVED"
                        elif task["returnType"] == "int" and re.fullmatch(r"-?\d+", text):
                            entry["result"] = int(text)
                            entry["status"] = "OBSERVED"
                        else:
                            entry["status"] = "QUARANTINED_OUTPUT"
                variant["cases"].append(entry)
            canonical = variant_results["canonical"]["cases"][-1]
            control_ok = (observed["cobolStatus"] == "OBSERVED" and canonical["status"] == "OBSERVED"
                          and canonical["result"] == observed["cobolResult"])
            observed["canonicalControl"] = "AGREES" if control_ok else "QUARANTINED"
            for name in MODEL_FILES:
                entry = variant_results[name]["cases"][-1]
                entry["comparison"] = "NOT_COMPARABLE"
                if control_ok and entry["status"] == "OBSERVED":
                    entry["comparison"] = "AGREEMENT" if entry["result"] == observed["cobolResult"] else "MISMATCH_PENDING_REVIEW"
            case_results.append(observed)
        results.append({"taskId": task["taskId"], "cobolCases": case_results, "javaVariants": variant_results})
    candidate_summary = {}
    for name in MODEL_FILES:
        comparisons = Counter(case["comparison"] for task in results for case in task["javaVariants"][name]["cases"])
        mismatch_tasks = [task["taskId"] for task in results if any(case["comparison"] == "MISMATCH_PENDING_REVIEW" for case in task["javaVariants"][name]["cases"])]
        candidate_summary[name] = {"inputComparisons": dict(comparisons), "tasksWithMismatchPendingReview": mismatch_tasks,
                                   "taskCountWithMismatchPendingReview": len(mismatch_tasks),
                                   "compilationFailureTaskCount": sum(not succeeded(task["javaVariants"][name]["compilation"]) for task in results)}
    mismatch_families = sorted({task_id for summary in candidate_summary.values() for task_id in summary["tasksWithMismatchPendingReview"]})
    report = {"schemaVersion": "scalar-c2j-replay-v1", "createdAt": utc_now(),
              "status": "EXECUTED_PENDING_REVIEW", "frozenContractSha256": digest(frozen_bytes),
              "frozenContractPath": str(frozen_path.relative_to(ROOT)), "rawEvidenceDirectory": str(raw),
              "scriptSha256": digest(Path(__file__).read_bytes()), "toolchain": tools,
              "trainingPerformed": False, "admittedDefectLabels": 0,
              "humanReviewPerformed": False, "aiGeneratedHarnessAndReview": True,
              "expectedResultMetadataUsedAsOracle": False, "heldoutSourceInspected": False,
              "sourceRewritesPerformed": False, "originalDriverRewritesPerformed": False,
              "compilerFlags": COBOL_FLAGS, "outputDecoder": DECODER,
              "taskCount": len(results), "inputCaseCount": frozen["inputCaseCount"],
              "candidateSummary": candidate_summary, "distinctTaskFamiliesWithMismatchPendingReview": mismatch_families,
              "independentDefectFamiliesConfirmed": 0,
              "limitations": ["Only the declared bounded scalar contracts and original driver inputs were replayed.",
                              "Agreement is finite test compatibility, not formal equivalence.",
                              "A mismatching source-task family is not automatically an independently reviewed defect family.",
                              "Candidate source is executed locally with timeouts; this command is not a sandboxed service.",
                              "Canonical Java agreement gates candidate comparisons; a failed control is quarantined.",
                              "No model training, repair fitting or heldout evaluation occurred."],
              "tasks": results}
    write_new(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--output", type=Path, required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--contract", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--raw-directory", type=Path, required=True)
    run_parser.add_argument("--cobc", type=Path, required=True)
    run_parser.add_argument("--java", type=Path, required=True)
    run_parser.add_argument("--javac", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        report = prepare(args.output.resolve())
        print(json.dumps({"contract": str(args.output), "taskCount": report["taskCount"], "inputCaseCount": report["inputCaseCount"],
                          "quarantinedInputs": len(report["quarantinedInputs"])}))
    else:
        report = run_replay(args.contract.resolve(), args.output.resolve(), args.raw_directory.resolve(),
                            args.cobc.resolve(), args.java.resolve(), args.javac.resolve())
        print(json.dumps({"report": str(args.output), "candidateSummary": report["candidateSummary"]}))


if __name__ == "__main__":
    main()
