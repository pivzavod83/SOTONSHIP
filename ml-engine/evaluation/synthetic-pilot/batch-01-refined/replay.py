#!/usr/bin/env python3
"""Offline execution audit of the REFINED inspected, hash-pinned synthetic batch.

This is not a generic uploaded-code runner or a training/evaluation benchmark.
Original programs, labels and supplied tests are preserved without correction.
Additional cases probe the declared bounds and are explicitly separate.
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


INPUT_SHA256 = "640b04fcd1c4e2368aa37994826d6d4fa625b52cf1dae34a50af70fc6adaab9d"
EXTRA_CASES = {
    "F001": [
        ("A1", "99999.99\n0.00\n99.99\n", "Maximum subtotal and tax; no discount."),
        ("A2", "99999.99\n99.99\n99.99\n", "Maximum values in all three declared fields."),
        ("A3", "1.00\n99.99\n99.99\n", "Discount truncation and tax rounding at a one-cent net amount."),
        ("A4", "0.01\n0.00\n50.00\n", "Exact half-cent tax at the smallest positive subtotal."),
    ],
    "F002": [
        ("A1", "99999.98\n365\n0.00\n", "Adjacent fee below the supplied maximum-fee storage regression."),
        ("A2", "99999.99\n365\n9999.99\n", "Maximum fee/days and credit after gross storage assignment."),
        ("A3", "0.00\n365\n9999.99\n", "Zero fee with maximum days and credit."),
        ("A4", "99999.99\n364\n0.00\n", "Adjacent day boundary without rounded gross overflow."),
        ("A5", "100.00\n365\n0.00\n", "Retain the original batch annual-division rounding regression."),
    ],
}


def sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def normalized(raw: str) -> str:
    text = raw.strip()
    if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", text):
        raise ValueError("Program did not print exactly one decimal value")
    value = Decimal(text)
    cents = value.quantize(Decimal("0.01"))
    if value != cents:
        raise ValueError("Program printed a value outside the stated two-decimal output scale")
    return format(abs(cents) if cents == 0 else cents, ".2f")


def check_domain(family: str, stdin: str) -> None:
    parts = stdin.splitlines()
    if len(parts) != 3 or any(len(part) > 20 for part in parts):
        raise ValueError("Input does not fit the reviewed three-line PIC X(20) interface")
    values = [Decimal(part) for part in parts]
    maxima = ["99999.99", "99.99", "99.99"] if family == "F001" else ["99999.99", "365", "9999.99"]
    if not all(Decimal(0) <= value <= Decimal(maximum) for value, maximum in zip(values, maxima)):
        raise ValueError("Case lies outside the supplied valid input domain")
    if family == "F002" and values[1] != values[1].to_integral_value():
        raise ValueError("Day count is not an integer")
    if any(value != value.quantize(Decimal("0.01")) for value in values):
        raise ValueError("Input exceeds the declared decimal scale")


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
    if [family["familyId"] for family in batch["families"]] != ["F001", "F002"]:
        raise ValueError("Unexpected family inventory")
    plan = {"inputSha256": INPUT_SHA256, "sourceReview": "AI-assisted static inspection; not independent human review",
            "suppliedCasesPerFamily": 6, "extraCases": EXTRA_CASES,
            "executionScope": "Pinned source only, no source edits, no original 143-task corpus or training",
            "comparison": "Exact decimal normalization; no tolerance and no float conversion",
            "equivalenceLimit": "Passing executed inputs never establishes universal equivalence"}
    output.mkdir(parents=True, exist_ok=False)
    (output / "audit-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    commands: list[dict] = []
    results = []
    with tempfile.TemporaryDirectory(prefix="sotonship-synthetic-batch01-") as temporary:
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
                reference = normalized(cobol_result["stdout"])
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
                    value = normalized(observed["stdout"])
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
                  "counts": {"independentFamilies": 2, "candidatePairs": 8, "suppliedReferenceRuns": len(supplied),
                             "suppliedJavaRuns": len(supplied) * 4, "additionalReferenceRuns": len(results) - len(supplied),
                             "additionalJavaRuns": (len(results) - len(supplied)) * 4,
                             "referencePredictionErrors": sum(not case["referencePredictionMatches"] for case in supplied),
                             "javaPredictionErrors": sum(not observed["predictionMatches"] for case in supplied for observed in case["variants"]),
                             "suppliedMismatchFlagErrors": sum(not observed["mismatchFlagMatches"] for case in supplied for observed in case["variants"])},
                  "toolVersions": versions, "caseOrigins": dict(Counter(case["origin"] for case in results)),
                  "variantSummary": summary, "cases": results, "commands": commands,
                  "modelTrained": False, "trainingAdmission": "PILOT_GENERATION_MAY_CONTINUE_NO_TRAINING_AUTHORIZED",
                  "limitations": ["Synthetic pilot; no production or unseen-data accuracy established.",
                                  "Finite runtime checks, not universal equivalence or Z3 proof.",
                                  "Structural alignment labels remain AI-proposed; existence of spans is not semantic localization ground truth.",
                                  "All present families are training-only and share one focus category.",
                                  "Class names are neutral; variant IDs/order and other supervision metadata must remain excluded from model inputs.",
                                  "Only supplied and explicitly listed additional canonical inputs were executed; the lexical input contract needs an explicit line-length limit.",
                                  "Overall 20-family plan, cross-family similarity grouping and complete validation/test inventory remain to be checked."]}
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
