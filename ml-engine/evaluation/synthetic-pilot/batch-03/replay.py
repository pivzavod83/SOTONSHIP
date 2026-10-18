#!/usr/bin/env python3
"""Offline execution audit of inspected, hash-pinned synthetic batch 03.

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


INPUT_SHA256 = "87e181c46ba306d75373f36f37698a3de33b7dee836b8067839b922cd17ff502"
EXTRA_CASES = {
    "F005": [],
    "F006": [
        ("A1", "0\n-40000\n5000\n", "Maximum negative intermediate magnitude with positive fee."),
        ("A2", "0\n0\n5000\n", "Minimum signed final output with zero intermediate balance."),
        ("A3", "40000\n-40000\n-5000\n", "Zero intermediate sum followed by negative fee."),
        ("A4", "1\n-2\n1\n", "Sign-removal boundary and exactly zero final result."),
    ],
}


def sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def normalized(raw: str, family: str) -> str:
    text = raw.strip()
    if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", text):
        raise ValueError("Program did not print exactly one numeric value")
    value = Decimal(text)
    scale = 0 if family == "F006" else 2
    quantized = value.quantize(Decimal(1).scaleb(-scale))
    if value != quantized:
        raise ValueError("Program printed a value outside the family output scale")
    return format(abs(quantized) if quantized == 0 else quantized, f".{scale}f")


def check_domain(family: str, stdin: str) -> None:
    parts = stdin.splitlines()
    if len(parts) != 3 or any(not 1 <= len(part) <= 20 for part in parts):
        raise ValueError("Input does not fit the declared three-line canonical interface")
    if family == "F005":
        if not all(re.fullmatch(r"(?:0|[1-9][0-9]*)\.[0-9]{2}", part) for part in parts):
            raise ValueError("F005 requires canonical ASCII decimals with exactly two fractional digits")
        minima, maxima = ["0", "0", "0"], ["50000", "25", "25"]
    elif family == "F006":
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)", parts[0]) or not all(
                re.fullmatch(r"-?(?:0|[1-9][0-9]*)", part) for part in parts[1:]):
            raise ValueError("F006 requires canonical integer spelling, signed only for adjustment and fee")
        minima, maxima = ["0", "-40000", "-5000"], ["40000", "40000", "5000"]
    else:
        raise ValueError("Unexpected inspected family")
    values = [Decimal(part) for part in parts]
    if not all(Decimal(minimum) <= value <= Decimal(maximum)
               for value, minimum, maximum in zip(values, minima, maxima)):
        raise ValueError("Case lies outside the supplied numeric domain")


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
    if [family["familyId"] for family in batch["families"]] != ["F005", "F006"]:
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
    with tempfile.TemporaryDirectory(prefix="sotonship-synthetic-batch03-") as temporary:
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
                  "counts": {"independentFamilies": 2, "candidatePairs": 8, "suppliedReferenceRuns": len(supplied),
                             "suppliedJavaRuns": len(supplied) * 4, "additionalReferenceRuns": len(results) - len(supplied),
                             "additionalJavaRuns": (len(results) - len(supplied)) * 4,
                             "referencePredictionErrors": sum(not case["referencePredictionMatches"] for case in supplied),
                             "javaPredictionErrors": sum(not observed["predictionMatches"] for case in supplied for observed in case["variants"]),
                             "suppliedMismatchFlagErrors": sum(not observed["mismatchFlagMatches"] for case in supplied for observed in case["variants"])},
                  "toolVersions": versions, "caseOrigins": dict(Counter(case["origin"] for case in results)),
                  "variantSummary": summary, "cases": results, "commands": commands,
                  "modelTrained": False, "trainingAdmission": "QUALITY_CHECKS_RECORDED_SPLIT_GROUP_REVIEW_REQUIRED",
                  "limitations": ["Synthetic pilot; no production or unseen-data model performance established.",
                                  "Finite runtime checks, not universal equivalence or Z3 proof.",
                                  "Structural alignment annotations remain AI-proposed; spans and plausible mappings are not independent localization gold.",
                                  "F005 is labelled test and F006 training. Test source/labels are inspected for data quality, not model tuning; no model has been trained.",
                                  "No additional test-family cases were generated; extra domain probes target only F006 training data.",
                                  "F005 has a closely related four-stage truncate/combine/round/combine structure to F001 training data; split grouping requires review before any independent test claim.",
                                  "Overall 20-family plan and complete clone-aware split inventory remain absent.",
                                  "Class names are neutral; variant IDs/order and other supervision metadata must remain excluded from model inputs."]}
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
