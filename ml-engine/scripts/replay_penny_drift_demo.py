#!/usr/bin/env python3
"""Replay the pinned, repository-authored penny-drift example with real runtimes.

This is an offline fixture tool, never an endpoint for running submitted code.
The COBOL input/output harness is explicitly recorded; Java sources are copied
byte-for-byte and invoked by a separate driver. No LLM response is fabricated.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "ml-engine"
FIXTURES = ENGINE / "data" / "fixtures"
PINNED = {
    "cobol": ("FX-WIRE-CALC.cbl", "c9bd04358c7ee83cd2c61530262e6d55ee880ab846a854467491d5138ee5f395"),
    "java": ("FX-WIRE-CALC.java.txt", "211340a44236a811b8eaff6ec6d0d3007130cabfd0cd092832ce87699e1e4561"),
    "patchedJava": ("FX-WIRE-CALC.patched.java.txt", "57649c44b80daa20f15a7daead24d30d3749cd145f07665c4f73aaf06ff96123"),
}
AMOUNT, RATE = "45.00", "1.1830"


def sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def run(command: list[str], cwd: Path, log: dict, name: str) -> str:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=45)
    log[name] = {"command": command, "exitCode": completed.returncode,
                 "stdout": completed.stdout, "stderr": completed.stderr}
    if completed.returncode:
        raise RuntimeError(f"{name} failed: {completed.stderr[:2000]}")
    return completed.stdout


def required_tool(explicit: str | None, name: str, fallback: Path) -> str:
    selected = explicit or shutil.which(name) or (str(fallback) if fallback.is_file() else None)
    if not selected or not Path(selected).is_file():
        raise RuntimeError(f"{name} is required; supply its explicit command-line path")
    return str(Path(selected).resolve())


def cobol_harness(source: str) -> str:
    marker, stop = "       MAIN.\n", "           GOBACK.\n"
    if source.count(marker) != 1 or source.count(stop) != 1:
        raise ValueError("Pinned COBOL fixture no longer has the reviewed harness insertion points")
    # Keep original declarations and arithmetic statement unchanged. The original
    # fixture initializes both inputs to zero and has no input or output I/O.
    return source.replace(marker, marker +
                          f"           MOVE {AMOUNT} TO INPUT-AMOUNT.\n"
                          f"           MOVE {RATE} TO REFERENCE-RATE.\n").replace(
                              stop, "           DISPLAY SETTLEMENT-RESULT.\n" + stop)


def java_driver(patched: bool) -> str:
    values = [f"new java.math.BigDecimal(args[{index}])" if patched else
              f"Double.parseDouble(args[{index}])" for index in range(2)]
    return ("public final class Replay {\n"
            "    public static void main(String[] args) {\n"
            "        System.out.print(new FxWireService().calculate(" + ", ".join(values) +
            ").toPlainString());\n    }\n}\n")


def generate(output: Path, cobc: str, java: str, javac: str) -> dict:
    sources = {key: (FIXTURES / filename).read_text(encoding="utf-8")
               for key, (filename, _) in PINNED.items()}
    for key, source in sources.items():
        if sha(source) != PINNED[key][1]:
            raise ValueError(f"Refusing to execute changed, unreviewed {key} fixture")
    example = json.loads((ROOT / "vscode-extension/examples/penny-drift.json").read_text())
    for key, request_key in (("cobol", "cobolSource"), ("java", "javaSource"),
                             ("patchedJava", "patchedJavaSource")):
        if sources[key] != example[request_key]:
            raise ValueError(f"UI example {request_key} does not match the pinned runtime fixture")

    log: dict = {}
    artifacts: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="sotonship-penny-replay-") as temporary:
        work = Path(temporary)
        tool_versions = {
            "cobol": run([cobc, "-V"], work, log, "cobol-version").splitlines()[0],
        }
        run([java, "-version"], work, log, "java-version")
        tool_versions["java"] = log["java-version"]["stderr"].splitlines()[0]
        for key, source in sources.items():
            artifacts["original-" + PINNED[key][0]] = source
        harness = cobol_harness(sources["cobol"])
        artifacts["cobol-replay.cbl"] = harness
        (work / "cobol-replay.cbl").write_text(harness, encoding="utf-8")
        run([cobc, "-x", "-free", "-o", "cobol-replay", "cobol-replay.cbl"], work, log, "cobol-compile")
        observed = {"cobol": str(Decimal(run([str(work / "cobol-replay")], work, log,
                                                 "cobol-run").strip()).quantize(Decimal("0.01")))}
        for key in ("java", "patchedJava"):
            folder = work / key
            folder.mkdir()
            (folder / "FxWireService.java").write_text(sources[key], encoding="utf-8")
            driver = java_driver(key == "patchedJava")
            artifacts[f"{key}-Replay.java"] = driver
            (folder / "Replay.java").write_text(driver, encoding="utf-8")
            run([javac, "-proc:none", "FxWireService.java", "Replay.java"], folder, log, key + "-compile")
            observed[key] = str(Decimal(run([java, "-cp", ".", "Replay", AMOUNT, RATE], folder,
                                             log, key + "-run").strip()).quantize(Decimal("0.01")))
        if observed != {"cobol": "53.24", "java": "53.23", "patchedJava": "53.24"}:
            raise AssertionError(f"Expected penny-drift witness did not reproduce: {observed}")

        sys.path.insert(0, str(ENGINE))
        from ml_engine.z3_formal_prover import prove
        reference = {"currencyPair": "GBP/EUR", "rate": RATE,
                     "source": "Bank of England Daily Spot Rate", "collectedDate": "2026-10-17",
                     "observationDate": "2026-10-15"}
        original = prove(sources["cobol"], sources["java"], reference,
                         proof_inputs=example["proofInputs"])
        patched = prove(sources["cobol"], sources["patchedJava"], reference,
                        proof_inputs=example["proofInputs"])
        if original["formalProofStatus"] != "SAT_COUNTEREXAMPLE_FOUND":
            raise AssertionError("The supplied original pair did not produce a Z3 counterexample")
        if not any(Decimal(row["inputAmountGbp"]) == Decimal(AMOUNT)
                   and Decimal(row["referenceRate"]) == Decimal(RATE)
                   and row["cobolOutput"] == observed["cobol"]
                   and row["javaOutput"] == observed["java"] for row in original["counterexamplesJson"]):
            raise AssertionError("Z3 did not independently produce the replayed runtime witness")
        if patched["formalProofStatus"] != "UNSAT_PROVEN_SAFE":
            raise AssertionError("Patched source did not pass the existing explicit bounded proof contract")
        # Temporary paths are irrelevant and would make this record unreproducible.
        log = json.loads(json.dumps(log).replace(temporary, "<temporary-replay-directory>"))
        artifacts["runtime-log.json"] = json.dumps(log, indent=2) + "\n"
        artifacts["z3-original.json"] = json.dumps(original, indent=2) + "\n"
        artifacts["z3-patched.json"] = json.dumps(patched, indent=2) + "\n"

    evidence = {
        "schemaVersion": 1, "status": "CONFIRMED_REPLAY",
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "title": "A real one-cent rounding discrepancy in the repository demo pair",
        "provenance": "AI-authored educational repository fixture; not a discovered production-bank defect.",
        "sourceHashes": {key: sha(value) for key, value in sources.items()},
        "finding": {
            "title": "Binary floating-point changes COBOL decimal rounding",
            "cobolLines": {"start": 10, "end": 10},
            "javaLines": {"start": 4, "end": 5},
            "patchedJavaLines": {"start": 4, "end": 5},
            "explanation": "COBOL packed-decimal arithmetic computes 45.00 × 1.1830 = 53.235 and ROUNDED stores 53.24. Java multiplies binary double values first; new BigDecimal(double) preserves that slightly smaller binary result and HALF_UP produces 53.23. This exact difference was independently observed by running both implementations.",
            "suggestedFix": "Accept decimal inputs as BigDecimal and multiply before rounding; construct the values from decimal strings, not doubles. The supplied patch also models the declared COBOL result field's high-order digit truncation.",
        },
        "witness": {"inputs": {"amount": AMOUNT, "rate": RATE}, "outputs": observed,
                    "difference": "-0.01", "status": "EXECUTED", "executedByLlm": False},
        "proofStatus": original["formalProofStatus"],
        "patchedProofStatus": patched["formalProofStatus"],
        "toolVersions": tool_versions,
        "harnessTransformations": [
            "COBOL: insert MOVE 45.00 TO INPUT-AMOUNT and MOVE 1.1830 TO REFERENCE-RATE immediately after MAIN.; preserve original declarations and calculation body.",
            "COBOL: insert DISPLAY SETTLEMENT-RESULT immediately before original GOBACK.; compile the recorded derivative with GnuCOBOL -free.",
            "Java: copy the pinned fixture byte-for-byte to FxWireService.java; compile it with a separate Replay.java that only constructs inputs, invokes calculate and prints its result.",
        ],
        "limitations": [
            "This is one executed input witness, not exhaustive runtime testing or whole-program equivalence.",
            "The original COBOL fixture has VALUE 0 inputs and no I/O; execution uses the fully recorded input/output harness derivative, not the original zero-input program unchanged.",
            "GnuCOBOL runtime replay is an independent corroboration for this arithmetic case, not an IBM Enterprise COBOL certification.",
            "The patched Z3 UNSAT result covers only the recorded finite amount range, exact fixed rate and supported scalar subset; it does not prove arbitrary programs safe.",
            "This fixture's rate carries the existing example's provenance; no live external FX data was fetched during replay.",
            "Runtime evidence and Z3 output are separate from any AI analysis; this report is not an LLM finding.",
        ],
        "evidenceDirectory": "penny-drift-replay",
        "artifactHashes": {name: sha(value) for name, value in artifacts.items()},
        "reproduction": "ml-engine/.venv/bin/python ml-engine/scripts/replay_penny_drift_demo.py",
    }
    output.mkdir(parents=True, exist_ok=True)
    raw = output / "penny-drift-replay"
    raw.mkdir(exist_ok=True)
    for name, value in artifacts.items():
        (raw / name).write_text(value, encoding="utf-8")
    (output / "penny-drift-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "backend/dev-ui/data")
    parser.add_argument("--cobc")
    parser.add_argument("--java")
    parser.add_argument("--javac")
    options = parser.parse_args()
    jdk = Path.home() / "Developer/jdk-21.0.10.jdk/Contents/Home/bin"
    cobc = required_tool(options.cobc, "cobc", Path("/tmp/sotonship-cobol-toolchain/install/bin/cobc"))
    java = required_tool(options.java, "java", jdk / "java")
    javac = required_tool(options.javac, "javac", jdk / "javac")
    evidence = generate(options.output.resolve(), cobc, java, javac)
    print(json.dumps({"status": evidence["status"], "witness": evidence["witness"],
                      "proofStatus": evidence["proofStatus"],
                      "patchedProofStatus": evidence["patchedProofStatus"]}, indent=2))


if __name__ == "__main__":
    main()
