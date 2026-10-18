#!/usr/bin/env python3
"""Freeze then replay eight development COBOL/Java source-fidelity contracts.

Original source and drivers remain byte-identical. Actual COBOL output is the
comparison oracle; canonical Java disagreement is retained, not gated away.
This is bounded AI-assisted corpus adjudication, not admitted human gold data.
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
HELPERS = {
    "audit_natural_c2j_candidates": "2bc1518b701f7f56ea58f4b14d74dd745336135908e792414879ff53cf6e4282",
    "replay_scalar_c2j_witnesses": "a93cb91eaed6d728032639f4b2971a483c9d10773e440ac45b94e0fc0660ea74",
    "audit_cobol_references": "04033f2be18f62c79ff3633389ea44a90db52ee06a46652321b84f7d641fb206",
}


def helper(name):
    import hashlib
    path = ROOT / "scripts" / (name + ".py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != HELPERS[name]:
        raise ValueError(f"Pinned helper changed: {name}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = helper("audit_natural_c2j_candidates")
scalar = helper("replay_scalar_c2j_witnesses")
guard = helper("audit_cobol_references")

# Input declarations and output projections are source-derived, declared before
# any new execution. No expected-answer lengths or benchmark outputs are read.
SPECS = {
    92: {"method": "anyInt", "fields": [("L-X", "COMP-2", 1), ("L-Y", "COMP-2", 1), ("L-Z", "COMP-2", 1)], "output": "boolean",
         "contract": "Three COBOL COMP-2 binary64 values map homogeneously to Java Double Objects. Integer literal spelling cannot recover a Java Integer type erased by COMP-2 storage."},
    103: {"method": "roundedAvg", "fields": [("L-N", "S9(10)", 1), ("L-M", "S9(10)", 1)], "output": "text100",
          "contract": "Two signed integer inputs; Java Object return is observed as String.valueOf and represented as a PIC X(100) text field. Source input overwrites and malformed binary formatting remain unchanged."},
    113: {"method": "oddCount", "fields": [("L-LST", "X(2)", 2)], "output": "two-text100",
          "contract": "Exactly two PIC X(2) input cells: original literal is truncated to width2, Java receives the truncated logical string, COBOL right-space-pads storage. Exactly two result cells are observable because the source loop writes NI=1..2. Full 100-character output cells are compared including internal padding; the other98 emitted storage records must remain blank. No expected-answer length is used."},
    119: {"method": "matchParens", "fields": [("L-LST", "X(100)", 2)], "output": "text100",
          "contract": "Exactly two nonempty parentheses-only logical strings, each<=100 and combined<=100; COBOL right-pads PIC X(100), Java receives the same logical strings. Source concatenation and execution order remain unchanged."},
    120: {"method": "maximum", "fields": [("L-ARR", "S9(10)", 3), ("L-K", "S9(10)", 1)], "output": "k-integers",
          "contract": "Exactly3 signed integers within[-1000,1000] and input k in0..3. Observable list length is input k, not expected-answer length. Java length must equal k; all100 serialized COBOL records are retained and the unused100-k records checked for zero."},
    126: {"method": "isSorted", "fields": [("L-LST", "S9(10)", 5)], "output": "boolean",
          "contract": "Exactly5 nonnegative signed-display integers within Java int range. Source duplicate/order policy is preserved even when it conflicts with canonical Java's benchmark policy."},
    128: {"method": "prodSigns", "fields": [("L-ARR", "S9(10)", 4)], "output": "integer",
          "contract": "Exactly4 signed integers bounded[-1000,1000]. Java Optional<Integer> is unwrapped; empty Optional remains null and cannot silently equal a COBOL integer. Empty arrays are outside the COBOL fixed-size interface."},
    134: {"method": "checkIfLastCharIsALetter", "fields": [("L-TXT", "X(100)", 1)], "output": "boolean",
          "contract": "One original ASCII logical string length0..100, with literal trailing spaces preserved. COBOL right-pads PIC X(100); Java receives the logical literal. COBOL's trailing-space scan remains authoritative and reference-policy conflicts are reported explicitly."},
}
EXPECTED_RESULTS = {
    92: [("RESULT", "9", 1)], 103: [("RESULT", "X(100)", 1)],
    113: [("RESULT", "X(100)", 100)], 119: [("RESULT", "X(100)", 1)],
    120: [("RESULT", "S9(10)", 100)], 126: [("RESULT", "9", 1)],
    128: [("RESULT", "S9(10)", 1)], 134: [("RESULT", "9", 1)],
}
MOVE = re.compile(r'''MOVE\s+('(?:[^']|'')*'|"(?:[^"]|"")*"|-?\d+(?:\.\d+)?)\s+TO\s+(L-[A-Z0-9-]+)(?:\((\d+)\))?\s*''')


def declarations(text):
    found = []
    pattern = re.compile(r"05\s+([A-Z][A-Z0-9-]*)\s+(?:OCCURS\s+(\d+)\s+TIMES\s+)?(?:INDEXED\s+BY\s+[A-Z0-9-]+\s+)?(?:PIC\s+(S?9(?:\(\d+\))?|X\(\d+\))|(COMP-2))\.")
    body = re.sub(r"01\s+LINKED-ITEMS\.", "", text).strip()
    for match in pattern.finditer(body):
        found.append((match[1], match[3] or match[4], int(match[2] or 1)))
    if pattern.sub("", body).strip():
        raise ValueError("Unexpected linkage declaration")
    return found


def literal(value):
    if value.startswith(("'", '"')):
        quote = value[0]
        return value[1:-1].replace(quote * 2, quote)
    return float(value) if "." in value else int(value)


def extract_case(row, index):
    number = int(row["task_id"].split("/")[1])
    if number not in SPECS:
        raise ValueError("Task is outside the frozen eight-family cohort")
    spec, driver = SPECS[number], row["tests"][index]["test"]
    source_text, driver_text = scalar.code_lines(row["COBOL_canonical_solution"]), scalar.code_lines(driver)
    source_link = re.search(r"LINKAGE SECTION\.(.*?)PROCEDURE DIVISION USING LINKED-ITEMS\.", source_text, re.S)
    driver_link = re.search(r"01\s+LINKED-ITEMS\.(.*?)PROCEDURE DIVISION\.", driver_text, re.S)
    wanted = spec["fields"] + EXPECTED_RESULTS[number]
    if not source_link or not driver_link or declarations(source_link[1]) != wanted or declarations(driver_link[1]) != wanted:
        raise ValueError("Source/driver linkage differs from the declared contract")
    output_file = guard.source_preflight(row["COBOL_canonical_solution"], driver)
    body = driver_text.split("PROCEDURE DIVISION.", 1)[1]
    prefix = body.split("CALL", 1)[0]
    values = {}
    for match in MOVE.finditer(prefix):
        key = match[2], int(match[3] or 1)
        if key in values:
            raise ValueError("Duplicate input cell initialization")
        values[key] = literal(match[1])
    if MOVE.sub("", prefix).strip():
        raise ValueError("Unsupported input initialization statement")
    wanted_cells = {(name, i) for name, _, count in spec["fields"] for i in range(1, count + 1)}
    if set(values) != wanted_cells:
        raise ValueError("Input initialization does not cover exactly the fixed interface")
    arguments, storage, truncations = [], [], []
    for name, kind, count in spec["fields"]:
        cells, physical = [], []
        for i in range(1, count + 1):
            value = values[name, i]
            if kind.startswith("X"):
                if not isinstance(value, str) or not value.isascii() or any(ord(c) < 32 or ord(c) > 126 for c in value):
                    raise ValueError("Only printable ASCII string literals are mapped")
                width = int(re.search(r"\d+", kind)[0])
                effective = value[:width]
                if effective != value:
                    truncations.append({"field": name, "index": i, "originalLiteral": value, "storedPrefix": effective, "width": width})
                cells.append(effective)
                physical.append(effective.ljust(width))
            elif kind == "COMP-2":
                if isinstance(value, str) or abs(value) > 1_000_000:
                    raise ValueError("Unsupported COMP-2 initialization")
                cells.append(float(value))
                physical.append(float(value))
            else:
                if type(value) is not int or abs(value) > 1_000_000:
                    raise ValueError("Integer outside frozen common bounds")
                cells.append(value)
                physical.append(value)
        arguments.append(cells if count > 1 else cells[0])
        storage.append(physical if count > 1 else physical[0])
    if number == 119 and (any(not re.fullmatch(r"[()]+", value) for value in arguments[0]) or sum(map(len, arguments[0])) > 100):
        raise ValueError("Parentheses logical input exceeds the bounded concatenation contract")
    if number == 120 and (not 0 <= arguments[1] <= 3 or any(abs(v) > 1000 for v in arguments[0])):
        raise ValueError("Maximum input outside fixed3/k contract")
    if number == 126 and any(value < 0 for value in arguments[0]):
        raise ValueError("Negative list values outside the common sorted-input contract")
    if number == 128 and any(abs(value) > 1000 for value in arguments[0]):
        raise ValueError("Product-sign input outside bounded overflow-free contract")
    expected_pic = "9" if spec["output"] == "boolean" else "X(100)" if spec["output"] in {"text100", "two-text100"} else "S9(10) SIGN LEADING"
    if not re.search(r"01\s+OUTPUT-RECORD\s+PIC\s+" + re.escape(expected_pic) + r"\.", driver_text):
        raise ValueError("Output serialization differs from source result width")
    if spec["output"] in {"two-text100", "k-integers"}:
        if not re.search(r"PERFORM VARYING NJ FROM 1 BY 1 UNTIL NJ > 100\s+MOVE RESULT \(NJ\) TO OUTPUT-RECORD\s+WRITE OUTPUT-RECORD", driver_text):
            raise ValueError("Expected original all100-record result serialization")
    elif driver_text.count("MOVE RESULT TO OUTPUT-RECORD") != 1:
        raise ValueError("Expected direct scalar result serialization")
    return {"driverIndex": index, "driverSha256": audit.sha(driver), "arguments": arguments,
            "cobolStoredInputs": storage, "sourceDefinedInputTruncations": truncations,
            "outputFile": output_file, "outputPic": expected_pic,
            "logicalResultLength": 2 if number == 113 else arguments[1] if number == 120 else None}


ENCODER = r'''import java.util.*;
public final class NumericBReplay {
  static String quote(String s) {
    StringBuilder b=new StringBuilder("\"");
    for(char c:s.toCharArray()) {
      if(c=='"' || c=='\\') b.append('\\').append(c);
      else if(c<32) b.append(String.format("\\u%04x", (int)c));
      else b.append(c);
    }
    return b.append('"').toString();
  }
  static String encode(Object x) {
    if(x==null) return "null";
    if(x instanceof Optional) return encode(((Optional<?>)x).orElse(null));
    if(x instanceof String) return quote((String)x);
    if(x instanceof List) {
      StringJoiner j=new StringJoiner(",","[","]");
      for(Object v:(List<?>)x) j.add(encode(v));
      return j.toString();
    }
    if(x instanceof Number || x instanceof Boolean) return x.toString();
    throw new IllegalArgumentException("Unsupported output object");
  }
  public static void main(String[] args) {
    Object value = INVOCATION;
    System.out.print(encode(OUTPUT));
  }
}
'''


def java_probe(number):
    if number == 92:
        invocation = "new Solution().anyInt(Double.valueOf(args[0]), Double.valueOf(args[1]), Double.valueOf(args[2]))"
    elif number == 103:
        invocation = "new Solution().roundedAvg(Integer.parseInt(args[0]), Integer.parseInt(args[1]))"
    elif number in {113, 119}:
        invocation = f"new Solution().{SPECS[number]['method']}(new ArrayList<String>(Arrays.asList(args)))"
    elif number == 120:
        invocation = "new Solution().maximum(new ArrayList<Integer>(Arrays.asList(Integer.valueOf(args[0]),Integer.valueOf(args[1]),Integer.valueOf(args[2]))),Integer.parseInt(args[3]))"
    elif number in {126, 128}:
        invocation = "new Solution()." + SPECS[number]["method"] + "(new ArrayList<Integer>(Arrays.asList(" + ",".join(f"Integer.valueOf(args[{i}])" for i in range(5 if number == 126 else 4)) + ")))"
    else:
        invocation = "new Solution().checkIfLastCharIsALetter(args[0])"
    return ENCODER.replace("INVOCATION", invocation).replace("OUTPUT", "String.valueOf(value)" if number == 103 else "value")


def text_field(value):
    if not isinstance(value, str) or not value.isascii() or len(value) > 100:
        raise ValueError("Output does not fit the declared ASCII PIC X(100) observation")
    return value.ljust(100)


def decode_cobol(number, raw, case):
    if not raw.endswith(b"\n"):
        raise ValueError("Missing original line-sequential record terminator")
    records = raw[:-1].split(b"\n")
    mode = SPECS[number]["output"]
    if mode == "boolean":
        return scalar.parse_cobol_output(raw, "boolean"), {"serializedRecords": len(records)}
    if mode == "integer":
        return scalar.parse_cobol_output(raw, "int"), {"serializedRecords": len(records)}
    if mode == "text100":
        if len(records) != 1:
            raise ValueError("Expected exactly one text record")
        return text_field(records[0].decode("ascii")), {"serializedRecords": 1, "nativeTextWidth": 100, "serializedTrailingSpaceRestoration": True}
    if len(records) != 100:
        raise ValueError("Expected exactly100 original result records")
    count = case["logicalResultLength"]
    if mode == "two-text100":
        all_values = [text_field(record.decode("ascii")) for record in records]
        unused_clean = all(value == " " * 100 for value in all_values[count:])
    else:
        all_values = [scalar.parse_cobol_output(record + b"\n", "int") for record in records]
        unused_clean = all(value == 0 for value in all_values[count:])
    if not unused_clean:
        raise ValueError("Unused original result storage is not blank/zero as frozen")
    return all_values[:count], {"serializedRecords": 100, "sourceDerivedLogicalResultLength": count,
                               "unusedStorageRecordsChecked": 100 - count, "unusedStorageBlankOrZero": True,
                               "expectedAnswerLengthUsed": False, "nativeTextWidth": 100 if mode == "two-text100" else None}


def map_java_output(number, value, case):
    mode = SPECS[number]["output"]
    if mode == "boolean":
        if type(value) is not bool:
            raise ValueError("Expected Boolean output")
    elif mode == "integer":
        if type(value) is not int:
            raise ValueError("Optional output is absent or not an Integer")
    elif mode == "text100":
        value = text_field(value)
    else:
        if not isinstance(value, list) or len(value) != case["logicalResultLength"]:
            raise ValueError("Java result list length differs from the source-defined contract")
        if mode == "two-text100":
            value = [text_field(v) for v in value]
        elif any(type(v) is not int for v in value):
            raise ValueError("Java result list contains non-integers")
    return value


def comparison(java, cobol, reference_agrees):
    if java.get("status") == "COMPILATION_FAILURE":
        return "COMPILATION_FAILURE_NOT_BEHAVIORALLY_COMPARABLE"
    if java.get("status") == "CANDIDATE_PROGRAM_EXCEPTION":
        return "CANDIDATE_RUNTIME_FAILURE_ON_COMMON_INPUT"
    if java.get("status") != "OBSERVED":
        return "OUTPUT_OR_EXECUTION_UNRESOLVED"
    if java["mappedResult"] == cobol:
        return "SOURCE_AGREEMENT" if reference_agrees else "SOURCE_AGREEMENT_WITH_REFERENCE_POLICY_CONFLICT"
    return "SOURCE_DIVERGENCE_REFERENCE_SUPPORTS_COBOL" if reference_agrees else "SOURCE_DIVERGENCE_WITH_REFERENCE_POLICY_CONFLICT"


def exception_evidence(stderr):
    exception = re.search(r'Exception in thread "main" ([A-Za-z0-9_.$]+)(?:: ([^\n]*))?', stderr)
    frame = re.search(r"\bat ([A-Za-z0-9_.$]+)\(", stderr)
    if not exception:
        return {"status": "RUNTIME_FAILURE_UNRESOLVED"}
    kind = exception[1]
    origin = frame[1] if frame else None
    deterministic = bool(origin and origin.startswith("Solution.") and kind not in {"java.lang.OutOfMemoryError", "java.lang.StackOverflowError"})
    return {"status": "CANDIDATE_PROGRAM_EXCEPTION" if deterministic else "RUNTIME_FAILURE_UNRESOLVED",
            "exceptionType": kind, "exceptionMessage": exception[2], "topStackFrame": origin,
            "deterministicCandidateOrigin": deterministic}


def family_disposition(task, driver_count):
    outcomes = {}
    for name, counts in task["candidateClassificationCounts"].items():
        outcomes[name] = {
            "no_mismatch": counts.get("SOURCE_AGREEMENT", 0) + counts.get("SOURCE_AGREEMENT_WITH_REFERENCE_POLICY_CONFLICT", 0),
            "source_diff_control_agrees": counts.get("SOURCE_DIVERGENCE_REFERENCE_SUPPORTS_COBOL", 0),
            "source_diff_reference_conflict": counts.get("SOURCE_DIVERGENCE_WITH_REFERENCE_POLICY_CONFLICT", 0),
            "execution_failure": counts.get("CANDIDATE_RUNTIME_FAILURE_ON_COMMON_INPUT", 0),
            "unsupported": sum(value for label, value in counts.items() if label in {"OUTPUT_OR_EXECUTION_UNRESOLVED", "SOURCE_UNRESOLVED", "COMPILATION_FAILURE_NOT_BEHAVIORALLY_COMPARABLE"}),
        }
    strong = sum(v["source_diff_control_agrees"] + v["execution_failure"] for v in outcomes.values())
    conflict = sum(v["source_diff_reference_conflict"] for v in outcomes.values())
    supported = sum(c["status"] == "SOURCE_OBSERVED" for c in task["cases"])
    if strong:
        disposition = "SOURCE_DISCREPANCY_OBSERVED_PENDING_INDEPENDENT_REVIEW"
    elif conflict:
        disposition = "SOURCE_DIVERGENCE_WITH_REFERENCE_POLICY_CONFLICT_PENDING_REVIEW"
    elif task["canonicalReferenceSourceDisagreements"]:
        disposition = "SOURCE_AGREEMENT_WITH_REFERENCE_POLICY_CONFLICT"
    elif not supported:
        disposition = "UNSUPPORTED_NO_COMMON_SOURCE_OBSERVATIONS"
    else:
        disposition = "NO_SOURCE_DISCREPANCY_OBSERVED_WITHIN_CONTRACT"
    return {"taskId": task["taskId"], "disposition": disposition, "driverCount": driver_count,
            "supportedDriverCount": supported, "candidateSummary": outcomes,
            "reason": task["contract"]["contract"], "excludedDrivers": task["excludedDrivers"]}


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def load(cache, partition):
    provenance, rows, outputs = audit.load_sources(cache, False)
    split = audit.load_partition(partition, rows)
    selected = []
    for position, row in enumerate(rows):
        number = int(row["task_id"].split("/")[1])
        if number not in SPECS:
            continue
        scalar.require_development(row["task_id"], split)
        for name, values in outputs.items():
            if not audit.join_evidence(row, values[position]["completion"])["methodAgreement"]:
                raise ValueError(f"Unresolved candidate ordinal/interface mapping: {name}/{number}")
        selected.append((position, row))
    if len(selected) != 8:
        raise ValueError("Expected exactly eight assigned development families")
    return provenance, selected, outputs


def prepare(args):
    provenance, selected, outputs = load(args.cache, args.partition)
    args.output.mkdir(parents=True, exist_ok=False)
    snapshot = args.output / "source-snapshot"
    snapshot.mkdir()
    script_hashes = {}
    for name in [Path(__file__).stem, *HELPERS]:
        source = ROOT / "scripts" / (name + ".py")
        shutil.copyfile(source, snapshot / source.name)
        script_hashes[source.name] = audit.sha(source.read_bytes())
    test = ROOT / "tests/test_adjudicate_c2j_numeric_arrays_b.py"
    shutil.copyfile(test, snapshot / test.name)
    script_hashes[test.name] = audit.sha(test.read_bytes())
    tasks = []
    for position, row in selected:
        number = int(row["task_id"].split("/")[1])
        cases, excluded = [], []
        for index in range(len(row["tests"])):
            try:
                cases.append(extract_case(row, index))
            except ValueError as error:
                excluded.append({"driverIndex": index, "reason": str(error)})
        tasks.append({"taskId": row["task_id"], "rowPosition": position, "contract": SPECS[number],
                      "cases": cases, "excludedDrivers": excluded,
                      "sourceHashes": {"cobol": audit.sha(row["COBOL_canonical_solution"]),
                                       "canonical": audit.sha(row["Java_canonical_solution"]),
                                       **{name: audit.sha(values[position]["completion"]) for name, values in outputs.items()}},
                      "probeSha256": audit.sha(java_probe(number))})
    plan = {"schemaVersion": "expanded-numeric-b-contract-v1", "status": "FROZEN_BEFORE_NEW_EXECUTION",
            "preparedAtUtc": datetime.now(timezone.utc).isoformat(), "selection": "All eight assigned unresolved development screen-flagged families, selected after earlier screening",
            "artifacts": provenance, "partitionSha256": audit.PARTITION_SHA, "scriptHashes": script_hashes,
            "tasks": tasks, "taskCount": 8, "driverCases": sum(len(t["cases"]) for t in tasks),
            "expectedAnswerMetadataUsedAsOracle": False, "expectedAnswerLengthUsed": False,
            "humanReviews": 0, "trainingPerformed": False, "holdoutExecutionPermitted": False,
            "reviewPolicy": "Actual-source fidelity and reference/benchmark-policy conflict are distinct. No automatic gold or human review; source disagreement is retained even if canonical Java disagrees too.",
            "limitations": ["Finite original driver inputs only; one fresh process per invocation.",
                            "Explicit logical-string/PIC storage representation relation; source-defined truncation and padding are retained.",
                            "Unused output storage is outside the declared logical result but all native serialized records are retained and checked.",
                            "Published outputs have ordinal rather than independent task-ID joins."]}
    write_new(args.output / "frozen-plan.json", plan)
    print(json.dumps({"taskCount": 8, "driverCases": plan["driverCases"], "excludedDrivers": sum(len(t["excludedDrivers"]) for t in tasks)}))


def flatten(arguments):
    return [str(value) for argument in arguments for value in (argument if isinstance(argument, list) else [argument])]


def execute(args):
    plan_path = args.output / "frozen-plan.json"
    plan = json.loads(plan_path.read_text())
    if (args.output / "replay-report.json").exists():
        raise FileExistsError("Completed replay is immutable")
    _, selected, outputs = load(args.cache, args.partition)
    rows = {row["task_id"]: (position, row) for position, row in selected}
    for filename, digest in plan["scriptHashes"].items():
        actual = ROOT / ("tests" if filename.startswith("test_") else "scripts") / filename
        audit.verified_bytes(actual, digest)
        audit.verified_bytes(args.output / "source-snapshot" / filename, digest)
    raw = args.cache / "expanded-numeric-b" / args.output.name
    raw.mkdir(parents=True, exist_ok=False)
    tools = {}
    for name, executable in {"cobc": args.cobc, "java": args.jdk / "java", "javac": args.jdk / "javac"}.items():
        version = audit.process([str(executable), "--version" if name == "cobc" else "-version"], raw, name + "-version", 10)
        tools[name] = {"path": str(executable), "sha256": audit.sha(executable.read_bytes()), "version": version}
    task_results = []
    for task in plan["tasks"]:
        position, row = rows[task["taskId"]]
        number = int(row["task_id"].split("/")[1])
        if position != task["rowPosition"] or audit.sha(java_probe(number)) != task["probeSha256"]:
            raise ValueError("Task/probe changed after freezing")
        folder = raw / row["task_id"].replace("/", "-")
        folder.mkdir()
        sources = {"canonical": row["Java_canonical_solution"], **{name: values[position]["completion"] for name, values in outputs.items()}}
        variants = {}
        for name, source in sources.items():
            if audit.sha(source) != task["sourceHashes"][name] or audit.DANGEROUS.search(audit.strip_comments(source)):
                raise ValueError("Source hash changed or source requires further execution review")
            variant = folder / name
            variant.mkdir()
            (variant / "Solution.java").write_text(source)
            (variant / "NumericBReplay.java").write_text(java_probe(number))
            compiled = audit.process([str(args.jdk / "javac"), "-J-Xmx128m", "-proc:none", "-encoding", "UTF-8", "Solution.java", "NumericBReplay.java"], variant, "compile", 15)
            variants[name] = {"compilation": compiled}
        if audit.sha(row["COBOL_canonical_solution"]) != task["sourceHashes"]["cobol"]:
            raise ValueError("COBOL source changed after freezing")
        (folder / "source.cbl").write_text(row["COBOL_canonical_solution"])
        records = []
        for case in task["cases"]:
            original = row["tests"][case["driverIndex"]]["test"]
            if extract_case(row, case["driverIndex"]) != case or audit.sha(original) != case["driverSha256"]:
                raise ValueError("Original input/driver changed after freezing")
            case_folder = folder / f"driver-{case['driverIndex']}"
            case_folder.mkdir()
            (case_folder / "driver.cbl").write_text(original)
            record = {**case, "status": "UNRESOLVED", "java": {}}
            record["cobolCompilation"] = audit.process([str(args.cobc), "-w", "-fformat=variable", "-x", "-o", "driver", "driver.cbl", "../source.cbl"], case_folder, "compile", 15)
            if record["cobolCompilation"]["returnCode"] == 0 and not record["cobolCompilation"]["timedOut"]:
                record["cobolExecution"] = audit.process([str(case_folder / "driver")], case_folder, "run", 5)
                if record["cobolExecution"]["returnCode"] == 0 and not record["cobolExecution"]["timedOut"]:
                    native = (case_folder / case["outputFile"]).read_bytes()
                    record["cobolOutputSha256"] = audit.sha(native)
                    record["cobolOutputBytes"] = len(native)
                    try:
                        value, metadata = decode_cobol(number, native, case)
                        record.update(cobolResult=value, outputContractEvidence=metadata, status="SOURCE_OBSERVED")
                    except ValueError as error:
                        record["reason"] = str(error)
            for name, variant in variants.items():
                compilation = variant["compilation"]
                observed = {"status": "COMPILATION_FAILURE"}
                if compilation["returnCode"] == 0 and not compilation["timedOut"]:
                    variant_folder = folder / name
                    phase = "case-" + str(case["driverIndex"])
                    run = audit.process([str(args.jdk / "java"), "-Xmx128m", "-XX:+UseSerialGC", "-ea", "-cp", str(variant_folder), "NumericBReplay", *flatten(case["arguments"])], variant_folder, phase, 5)
                    observed = {"execution": run, "status": "RUNTIME_FAILURE_UNRESOLVED"}
                    if run["returnCode"] != 0 and not run["timedOut"]:
                        observed.update(exception_evidence((variant_folder / (phase + ".stderr")).read_text(errors="replace")))
                    if run["returnCode"] == 0 and not run["timedOut"]:
                        try:
                            output = json.loads((variant_folder / (phase + ".stdout")).read_text())
                            observed.update(status="OBSERVED", javaResult=output, mappedResult=map_java_output(number, output, case))
                        except (ValueError, UnicodeError) as error:
                            observed.update(status="OUTPUT_MAPPING_UNRESOLVED", reason=str(error))
                record["java"][name] = observed
            if record["status"] == "SOURCE_OBSERVED":
                reference = record["java"]["canonical"]
                reference_agrees = reference.get("status") == "OBSERVED" and reference["mappedResult"] == record["cobolResult"]
                record["canonicalReferenceAgreesWithSource"] = reference_agrees
                for name in ["7b", "14b"]:
                    record["java"][name]["classification"] = comparison(record["java"][name], record["cobolResult"], reference_agrees)
            records.append(record)
        counts = {name: dict(Counter(r["java"][name].get("classification", "SOURCE_UNRESOLVED") for r in records)) for name in ["7b", "14b"]}
        task_results.append({"taskId": task["taskId"], "sourceHashes": task["sourceHashes"], "contract": task["contract"],
                             "cases": records, "excludedDrivers": task["excludedDrivers"], "javaCompilation": variants,
                             "candidateClassificationCounts": counts,
                             "canonicalReferenceSourceDisagreements": sum(r.get("canonicalReferenceAgreesWithSource") is False for r in records)})
        print(json.dumps({"taskId": task["taskId"], "counts": counts}), flush=True)
    report = {"schemaVersion": "expanded-numeric-b-replay-v1", "status": "EXECUTED_PENDING_INDEPENDENT_REVIEW",
              "frozenPlanSha256": audit.sha(plan_path.read_bytes()), "rawEvidencePath": str(raw), "toolchain": tools,
              "tasks": task_results, "taskCount": len(task_results), "driverCases": sum(len(t["cases"]) for t in task_results),
              "familyDispositions": [family_disposition(task, len(rows[task["taskId"]][1]["tests"])) for task in task_results],
              "goldTrainingLabelsAdmitted": 0, "independentHumanReviews": 0, "modelTrainingPerformed": False,
              "heldoutTasksExecuted": 0, "mutationsIntroduced": 0, "sourceProgramsOrDriversRewritten": False,
              "llmApiCalls": 0, "expectedAnswerMetadataUsedAsOracle": False,
              "limitations": plan["limitations"], "aiDisclosure": "All contracts, adapters and source-level interpretation are AI-generated; execution observations are not independent human review or gold localization."}
    write_new(args.output / "replay-report.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=ROOT / "evaluation/corpora/natural-c2j")
    parser.add_argument("--partition", type=Path, default=ROOT / "evaluation/paired-code/cv-partition-plan.json")
    parser.add_argument("--cobc", type=Path, default=Path("/tmp/sotonship-cobol-toolchain/install/bin/cobc"))
    parser.add_argument("--jdk", type=Path, default=Path("/Users/volodymyrsydorenko/Developer/jdk-21.0.10.jdk/Contents/Home/bin"))
    args = parser.parse_args()
    args.output, args.cache, args.partition = args.output.resolve(), args.cache.resolve(), args.partition.resolve()
    (prepare if args.prepare else execute)(args)


if __name__ == "__main__":
    main()
