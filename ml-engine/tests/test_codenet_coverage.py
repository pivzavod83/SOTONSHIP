"""Source-only coverage invariants; no corpus execution, model fitting or scoring."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import audit_codenet_coverage as coverage


def record(folder, problem, language, identifier, status="Accepted", raw=b"fixture"):
    extension = "cob" if language == "COBOL" else "java"
    relative = f"data/{problem}/{language}/{identifier}.{extension}"
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": relative, "problemId": problem, "language": language,
            "submissionId": identifier, "upstreamJudgeStatus": status,
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "encoding": "UTF-8"}


def manifest(folder, records):
    (folder / "inventory.json").write_text(json.dumps({"stage": "INVENTORIED", "sourceFiles": records}), encoding="utf-8")


def stub(source, language, profile):
    return SimpleNamespace(status="COMPLETE", nodes=[1], edges=[], issues=[])


def test_at_least_ten_problem_selection_is_deterministic_and_keeps_labels_unknown(tmp_path, monkeypatch):
    rows = []
    for i in range(12):
        problem = f"p{i:05d}"
        rows.extend([record(tmp_path, problem, "COBOL", "s2"),
                     record(tmp_path, problem, "COBOL", "s1"),
                     record(tmp_path, problem, "Java", "s9", "Wrong Answer"),
                     record(tmp_path, problem, "Java", "s4", "Accepted"),
                     record(tmp_path, problem, "Java", "s3", "Accepted"),
                     record(tmp_path, problem, "Java", "s0", "Compile Error")])
    monkeypatch.setattr(coverage, "_extract", stub)
    manifest(tmp_path, rows[::-1])
    result = coverage.audit(tmp_path)
    assert result["selectedPairs"] == 24
    assert result["selectedPairProblemCount"] == 12
    assert result["atLeastTenPairs"]
    for profile in coverage.PROFILES:
        assert result["profileResults"][profile]["bothFrontendsComplete"] == 24
        assert result["profileResults"][profile]["cobolSources"]["sources"] == 24
    assert all(pair["cobolSource"].endswith("s1.cob") for pair in result["pairs"])
    assert not any(pair["javaSource"].endswith(("s0.java", "s4.java")) for pair in result["pairs"])
    assert result["upstreamJudgeStatusDistribution"]["Java"]["Compile Error"] == 12
    assert all(pair["semanticLabel"] == "UNKNOWN" and pair["requiresReview"] and not pair["trainingEligible"] for pair in result["pairs"])
    assert result["accuracy"] is result["recall"] is None
    assert not result["modelInferencePerformed"] and not result["sourcesExecuted"]
    manifest(tmp_path, rows)
    assert coverage.audit(tmp_path)["pairs"] == result["pairs"]


def test_free_fixed_are_distinct_probes_and_never_auto_resolve_contract(tmp_path, monkeypatch):
    rows = [record(tmp_path, "p00001", "COBOL", "s1"), record(tmp_path, "p00001", "Java", "s2")]
    manifest(tmp_path, rows)
    def extractor(source, language, profile):
        return SimpleNamespace(status="PARTIAL" if profile == "FIXED" else "COMPLETE", nodes=[], edges=[],
                               issues=[SimpleNamespace(code="FIXED_UNSUPPORTED")] if profile == "FIXED" else [])
    monkeypatch.setattr(coverage, "_extract", extractor)
    result = coverage.audit(tmp_path)
    assert result["profileResults"]["FREE"]["bothFrontendsComplete"] == 1
    assert result["profileResults"]["FIXED"]["abstainedPairs"] == 1
    assert result["pairs"][0]["compilerContract"] == "UNKNOWN"
    assert result["pairs"][0]["requiresReview"]
    assert result["profileResults"]["FIXED"]["cobolSources"]["issueCounts"] == {"FIXED_UNSUPPORTED": 1}


def test_non_utf8_anchor_is_quarantined_without_falling_back_to_next_parseable_source(tmp_path, monkeypatch):
    rows = [record(tmp_path, "p00001", "COBOL", "s1", raw=b"\xff"),
            record(tmp_path, "p00001", "COBOL", "s2"), record(tmp_path, "p00001", "Java", "s3")]
    manifest(tmp_path, rows)
    monkeypatch.setattr(coverage, "_extract", stub)
    result = coverage.audit(tmp_path)
    assert result["selectedPairs"] == 1
    assert result["pairs"][0]["cobolSource"].endswith("s1.cob")
    for profile in coverage.PROFILES:
        assert result["profileResults"][profile]["abstainedPairs"] == 1
        assert result["profileResults"][profile]["cobolSources"]["issueCounts"] == {"NON_UTF8_REQUIRES_REVIEW": 1}


def test_source_budget_abstains_before_parser_and_retains_pair_denominator(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage, "MAX_SOURCE_BYTES", 5)
    monkeypatch.setattr(coverage, "_extract", lambda *args: pytest.fail("Oversized source was parsed"))
    manifest(tmp_path, [record(tmp_path, "p00001", "COBOL", "s1"), record(tmp_path, "p00001", "Java", "s2")])
    result = coverage.audit(tmp_path)
    assert result["profileResults"]["FREE"]["pairs"] == 1
    assert result["profileResults"]["FREE"]["abstainedPairs"] == 1
    assert result["selectedJavaSources"]["issueCounts"] == {"SOURCE_BYTE_BUDGET": 1}
    assert not result["sourceProbes"]["Java"][0]["sourceHashVerified"]


@pytest.mark.parametrize("change", ["bytes", "hash", "traversal", "symlink", "duplicate"])
def test_changed_or_unsafe_source_identity_is_rejected(tmp_path, monkeypatch, change):
    row = record(tmp_path, "p00001", "COBOL", "s1")
    if change == "bytes":
        (tmp_path / row["path"]).write_bytes(b"different-length")
    elif change == "hash":
        (tmp_path / row["path"]).write_bytes(b"changed")
    elif change == "traversal":
        row["path"] = "../outside.cob"
    elif change == "symlink":
        target = tmp_path / "outside.cob"
        target.write_bytes(b"fixture")
        path = tmp_path / row["path"]
        path.unlink()
        path.symlink_to(target)
    manifest(tmp_path, [row, row] if change == "duplicate" else [row])
    monkeypatch.setattr(coverage, "_extract", stub)
    with pytest.raises(ValueError):
        coverage.audit(tmp_path)


def test_real_frontends_extract_source_text_without_executing_it(tmp_path):
    cobol = b""">>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. ADDER.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 A PIC S9(4) VALUE 1.
01 B PIC S9(4) VALUE 2.
01 RESULT PIC S9(4).
PROCEDURE DIVISION.
COMPUTE RESULT = A + B
DISPLAY RESULT
STOP RUN.
"""
    java = b"class Main { public static int add(int a, int b) { int result = a + b; return result; } }"
    manifest(tmp_path, [record(tmp_path, "p00001", "COBOL", "s1", raw=cobol),
                        record(tmp_path, "p00001", "Java", "s2", raw=java)])
    result = coverage.audit(tmp_path)
    assert result["profileResults"]["FREE"]["bothFrontendsComplete"] == 1
    assert not result["modelsLoaded"] and not result["sourcesCompiled"]
    assert result["semanticLabelStatus"] == "UNKNOWN"


def test_incomplete_inventory_is_refused(tmp_path):
    (tmp_path / "inventory.json").write_text('{"stage":"COBOL_READY","sourceFiles":[]}')
    with pytest.raises(ValueError, match="INVENTORIED"):
        coverage.audit(tmp_path)


def test_unmatched_cobol_is_in_census_but_never_used_as_accepted_anchor(tmp_path, monkeypatch):
    row = record(tmp_path, "p00001", "COBOL", "s1")
    row.pop("upstreamJudgeStatus")
    (tmp_path / "inventory.json").write_text(json.dumps({"stage": "INVENTORIED", "sourceFiles": [], "unmatchedSourceFiles": [row]}))
    monkeypatch.setattr(coverage, "_extract", stub)
    result = coverage.audit(tmp_path)
    assert result["profileResults"]["FREE"]["cobolSources"]["sources"] == 1
    assert result["selectedPairs"] == 0
    assert result["upstreamJudgeStatusDistribution"]["COBOL"] == {"UNKNOWN_MISSING_METADATA": 1}


def test_cli_refuses_to_overwrite_report_before_opening_corpus(tmp_path, monkeypatch):
    output = tmp_path / "evidence.json"
    output.write_text("preserved")
    monkeypatch.setattr("sys.argv", ["audit", "--corpus", str(tmp_path / "missing"), "--output", str(output)])
    with pytest.raises(SystemExit):
        coverage.main()
    assert output.read_text() == "preserved"
