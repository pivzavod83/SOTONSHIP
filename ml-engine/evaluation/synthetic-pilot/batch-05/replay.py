#!/usr/bin/env python3
"""Offline execution audit of inspected, hash-pinned synthetic final batch05.

This is not a generic uploaded-code runner or a training/evaluation benchmark.
Original programs, labels and supplied tests are preserved without correction.
Only the supplied validation/test cases are executed; no new probes are generated.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


INPUT_SHA256 = "b77464a12665fd053c9a17bd7cce6956420d19ea374a334acef586cb97547dc3"
EXTRA_CASES = {"F009": [], "F010": []}


def sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def normalized(raw: str, family: str) -> str:
    if family not in ("F009", "F010"):
        raise ValueError("Unexpected inspected family")
    text = raw.strip(" \t\r\n\v\f")
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        raise ValueError("Expected exactly one base-ten scalar integer")
    return str(int(text))


def check_domain(family: str, stdin: str) -> None:
    parts = stdin.splitlines()
    count = 3 if family == "F009" else 2 if family == "F010" else None
    if count is None or len(parts) != count or any(not 1 <= len(part) <= 20 for part in parts):
        raise ValueError("Unexpected family or canonical input line count/length")
    for part in parts:
        if not re.fullmatch(r"(?:0|[1-9][0-9]*|-[1-9][0-9]*)", part) or not -99999 <= int(part) <= 99999:
            raise ValueError("Input outside the supplied canonical signed integer contract")
    if family == "F010" and all(int(part) == 0 for part in parts):
        raise ValueError("GCD input operands cannot both be zero")


def tool(explicit: str | None, name: str) -> str:
    selected = explicit or shutil.which(name)
    if not selected or not Path(selected).is_file():
        raise ValueError(f"Supply --{name} with the actual compiler/runtime path")
    return str(Path(selected).resolve())


def audit(output: Path, cobc: str, java: str, javac: str) -> dict:
    raw = (Path(__file__).parent / "input-batch.json").read_bytes()
    if sha(raw) != INPUT_SHA256:
        raise ValueError("Refusing to compile or execute changed, unreviewed batch contents")
    batch = json.loads(raw)
    if [family["familyId"] for family in batch["families"]] != ["F009", "F010"]:
        raise ValueError("Unexpected family inventory")
    plan = {"inputSha256": INPUT_SHA256, "familyRevisions": {"F009": "F009-R1", "F010": "F010-R1"}, "sourceReview": "AI-assisted static inspection; not independent human review",
            "suppliedCasesPerFamily": 6, "extraCases": EXTRA_CASES,
            "executionScope": "Pinned source only, no source edits, no original 143-task corpus or training",
            "comparison": "Exact decimal normalization; no tolerance and no float conversion",
            "equivalenceLimit": "Passing executed inputs never establishes universal equivalence"}
    output.mkdir(parents=True, exist_ok=False)
    (output / "audit-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    commands: list[dict] = []
    results = []
    with tempfile.TemporaryDirectory(prefix="sotonship-synthetic-batch05-") as temporary:
        work = Path(temporary)
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C", "LC_ALL": "C"}

        def run(command: list[str], stdin: str = "", timeout: int = 10) -> dict:
            completed = subprocess.run(command, input=stdin, text=True, capture_output=True,
                                       cwd=work, timeout=timeout, env=environment)
            entry = {"command": [part.replace(temporary, "<temporary>") for part in command],
                     "stdin": stdin, "exitCode": completed.returncode,
                     "stdout": completed.stdout, "stderr": completed.stderr}
            commands.append(entry)
            if completed.returncode:
                raise RuntimeError(f"Pinned compiler/runtime failed: {entry}")
            return entry

        versions = {"cobol": run([cobc, "-V"])["stdout"].splitlines()[0],
                    "java": run([java, "-version"])["stderr"].splitlines()[0],
                    "javac": run([javac, "-version"])["stdout"].strip()}
        for family in batch["families"]:
            fid = family["familyId"]
            cobol = "\n".join(family["cobolLines"])
            (work / f"{fid}.cbl").write_text(cobol)
            run([cobc, "-x", "-free", "-Wall", "-o", str(work / fid), f"{fid}.cbl"], timeout=30)
            for variant in family["variants"]:
                class_name = re.search(r"public class (Program)\s*\{", "\n".join(variant["javaLines"]))
                if class_name is None:
                    raise ValueError("Unexpected reviewed Java class declaration")
                folder = work / variant["variantId"]
                folder.mkdir()
                name = folder / (class_name[1] + ".java")
                name.write_text("\n".join(variant["javaLines"]))
                run([javac, "-J-Xmx256m", "-proc:none", "-d", str(folder), str(name)], timeout=45)
        for family in batch["families"]:
            fid = family["familyId"]
            cases = [dict(case, origin="SUPPLIED") for case in family["tests"]]
            cases += [{"testId": fid + "-" + identifier, "stdin": stdin, "origin": "ADDITIONAL_DOMAIN_PROBE", "reason": reason}
                      for identifier, stdin, reason in EXTRA_CASES[fid]]
            for case in cases:
                check_domain(fid, case["stdin"])
                cobol_result = run([str(work / fid)], case["stdin"])
                reference = normalized(cobol_result["stdout"], fid)
                row = {"familyId": fid, "testId": case["testId"], "origin": case["origin"],
                       "stdin": case["stdin"], "reason": case.get("reason", "Unchanged supplied test"),
                       "observedReferenceValue": reference,
                       "proposedReferenceValue": case.get("expectedReferenceValue"),
                       "referencePredictionMatches": reference == case["expectedReferenceValue"] if case["origin"] == "SUPPLIED" else None,
                       "referenceRun": cobol_result, "variants": []}
                for variant in family["variants"]:
                    identifier = variant["variantId"]
                    class_name = "Program"
                    observed = run([java, "-Xmx128m", "-XX:+UseSerialGC", "-cp", str(work / identifier), class_name], case["stdin"])
                    value = normalized(observed["stdout"], fid)
                    proposed = next((p for p in variant["testPredictions"] if p["testId"] == case["testId"]), None)
                    mismatch = value != reference
                    row["variants"].append({"variantId": identifier, "expectedEquivalent": variant["expectedEquivalent"],
                        "observedValue": value, "observedMismatch": mismatch,
                        "proposedValue": proposed["expectedJavaValue"] if proposed else None,
                        "predictionMatches": value == proposed["expectedJavaValue"] if proposed else None,
                        "mismatchFlagMatches": mismatch == proposed["expectedMismatch"] if proposed else None,
                        "run": observed})
                results.append(row)
        summary = []
        for family in batch["families"]:
            for variant in family["variants"]:
                identifier = variant["variantId"]
                observations = [(case, observed) for case in results for observed in case["variants"] if observed["variantId"] == identifier]
                witnesses = [case["testId"] for case, observed in observations if observed["observedMismatch"]]
                assessment = ("REFUTED_BY_EXECUTED_VALID_INPUT" if witnesses else "MATCHES_EXECUTED_INPUTS_ONLY") if variant["expectedEquivalent"] else ("DEFECT_CONFIRMED_BY_RUNTIME_WITNESS" if witnesses else "NO_DEFECT_WITNESS_OBSERVED")
                summary.append({"variantId": identifier, "proposedEquivalent": variant["expectedEquivalent"],
                                "suppliedMismatches": sum(observed["observedMismatch"] and case["origin"] == "SUPPLIED" for case, observed in observations),
                                "additionalMismatches": sum(observed["observedMismatch"] and case["origin"] != "SUPPLIED" for case, observed in observations),
                                "witnessIds": witnesses, "assessment": assessment})
        supplied = [case for case in results if case["origin"] == "SUPPLIED"]
        report = {"schemaVersion": 1, "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
                  "datasetKind": "SYNTHETIC_AI_GENERATED", "inputSha256": INPUT_SHA256,
                  "counts": {"submittedFamilies": 2, "candidatePairs": 8, "suppliedReferenceRuns": len(supplied),
                             "suppliedJavaRuns": len(supplied) * 4, "additionalReferenceRuns": len(results) - len(supplied),
                             "additionalJavaRuns": (len(results) - len(supplied)) * 4,
                             "referencePredictionErrors": sum(not case["referencePredictionMatches"] for case in supplied),
                             "javaPredictionErrors": sum(not observed["predictionMatches"] for case in supplied for observed in case["variants"]),
                             "suppliedMismatchFlagErrors": sum(not observed["mismatchFlagMatches"] for case in supplied for observed in case["variants"])},
                  "toolVersions": versions, "caseOrigins": dict(Counter(case["origin"] for case in results)),
                  "variantSummary": summary, "cases": results, "commands": commands,
                  "modelTrained": False, "trainingAdmission": "QUALITY_CHECKS_RECORDED_SPLIT_GROUP_REVIEW_REQUIRED",
                  "limitations": ["Synthetic feasibility pilot; no production or unseen-data model performance established.",
                                  "Finite runtime checks, not universal equivalence or Z3 proof.",
                                  "Structural alignment annotations remain AI-proposed, not independent localization gold.",
                                  "F009 validation and F010 test sources/supplied labels inspected only for dataset quality; no fitting or model selection.",
                                  "Only the twelve supplied cases were executed; no additional held-out-family probes were generated.",
                                  "No original143-task corpus was compiled or executed by this audit.",
                                  "No model was fitted, tuned, selected or evaluated.",
                                  "Variant IDs/order, split metadata, annotations and expected outputs must not become model features."]}

        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        sources = {family["familyId"]: {"cobol": sha("\n".join(family["cobolLines"])),
                    "java": {variant["variantId"]: sha("\n".join(variant["javaLines"])) for variant in family["variants"]}}
                   for family in batch["families"]}
        (output / "source-hashes.json").write_text(json.dumps(sources, indent=2) + "\n")
        (output / "artifact-hashes.json").write_text(json.dumps({name: sha((output / name).read_bytes()) for name in
                   ("audit-plan.json", "report.json", "source-hashes.json")}, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory; existing paths are refused")
    for name in ("cobc", "java", "javac"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    report = audit(args.output.resolve(), tool(args.cobc, "cobc"), tool(args.java, "java"), tool(args.javac, "javac"))
    print(json.dumps({"counts": report["counts"], "variantSummary": report["variantSummary"],
                      "trainingAdmission": report["trainingAdmission"]}, indent=2))


if __name__ == "__main__":
    main()
