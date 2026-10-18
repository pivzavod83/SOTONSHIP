"""Keep the UI's confirmed defect tied to exact sources and runtime evidence."""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend/dev-ui/data"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ui_evidence_covers_exact_sources_and_valid_semantic_spans():
    evidence = json.loads((DATA / "penny-drift-evidence.json").read_text())
    example = json.loads((ROOT / "vscode-extension/examples/penny-drift.json").read_text())
    assert evidence["status"] == "CONFIRMED_REPLAY"
    for key, request_key in (("cobol", "cobolSource"), ("java", "javaSource"),
                             ("patchedJava", "patchedJavaSource")):
        source = example[request_key]
        assert hashlib.sha256(source.encode()).hexdigest() == evidence["sourceHashes"][key]
        span = evidence["finding"][key + "Lines"]
        assert 1 <= span["start"] <= span["end"] <= len(source.splitlines())
    assert "COMPUTE SETTLEMENT-RESULT ROUNDED" in example["cobolSource"].splitlines()[9]
    assert "new BigDecimal(principal * quote)" in example["javaSource"].splitlines()[4]
    for filename, expected_hash in evidence["artifactHashes"].items():
        assert digest(DATA / "penny-drift-replay" / filename) == expected_hash


def test_replay_discloses_instrumentation_and_records_successful_runtimes():
    raw = DATA / "penny-drift-replay"
    source = (raw / "original-FX-WIRE-CALC.cbl").read_text()
    harness = (raw / "cobol-replay.cbl").read_text()
    instrumentation = ("           MOVE 45.00 TO INPUT-AMOUNT.\n",
                       "           MOVE 1.1830 TO REFERENCE-RATE.\n",
                       "           DISPLAY SETTLEMENT-RESULT.\n")
    assert all(harness.count(line) == 1 for line in instrumentation)
    for line in instrumentation:
        harness = harness.replace(line, "")
    assert harness == source, "The harness must not silently change the arithmetic or storage layout"
    log = json.loads((raw / "runtime-log.json").read_text())
    assert all(row["exitCode"] == 0 for row in log.values())
    assert Decimal(log["cobol-run"]["stdout"].strip()) == Decimal("53.24")
    assert Decimal(log["java-run"]["stdout"].strip()) == Decimal("53.23")
    assert Decimal(log["patchedJava-run"]["stdout"].strip()) == Decimal("53.24")


def test_recorded_solver_witness_agrees_with_observed_runtimes_and_scope():
    evidence = json.loads((DATA / "penny-drift-evidence.json").read_text())
    raw = DATA / "penny-drift-replay"
    original = json.loads((raw / "z3-original.json").read_text())
    patched = json.loads((raw / "z3-patched.json").read_text())
    assert original["formalProofStatus"] == "SAT_COUNTEREXAMPLE_FOUND"
    assert patched["formalProofStatus"] == "UNSAT_PROVEN_SAFE"
    witness = original["counterexamplesJson"][0]
    assert Decimal(witness["inputAmountGbp"]) == Decimal(evidence["witness"]["inputs"]["amount"])
    assert Decimal(witness["referenceRate"]) == Decimal(evidence["witness"]["inputs"]["rate"])
    assert witness["cobolOutput"] == evidence["witness"]["outputs"]["cobol"]
    assert witness["javaOutput"] == evidence["witness"]["outputs"]["java"]
    for row, source_key in ((original, "java"), (patched, "patchedJava")):
        scope = row["proofScope"]
        assert scope["supported"] and scope["bounded"]
        assert scope["sourceSha256"]["cobol"] == evidence["sourceHashes"]["cobol"]
        assert scope["sourceSha256"]["java"] == evidence["sourceHashes"][source_key]
        assert scope["inputAmountCents"] == {"min": -999999999, "max": 999999999}
