"""Independent stage accounting and fail-closed boundaries for compiler frontends."""
from __future__ import annotations

import io
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from ml_engine import parser_frontends_v3 as frontends
from scripts import benchmark_parser_v3 as benchmark


def java_result(syntax="PARSED", resolution="RESOLVED", **binding):
    return {"language": "Java", "syntax": {"status": syntax, "diagnostics": []},
            "resolution": {"status": resolution, "bindingComplete": True, "diagnostics": [], **binding}, "structure": {}}


def cobol_result(**resolution):
    return {"language": "COBOL", "syntax": {"status": "PARSED", "diagnostics": []},
            "resolution": {"status": "UNKNOWN", "asgAnalysisCompleted": True,
                           "unresolvedReferences": 0, "countsComplete": True,
                           "typeChecking": "NOT_PROVIDED_BY_PROLEAP", "diagnostics": [], **resolution},
            "structure": {}}


@pytest.mark.parametrize("ir", ["PARTIAL", "UNSUPPORTED"])
def test_complete_java_syntax_and_types_do_not_promote_partial_semantic_ir(ir):
    assert frontends.phase_outcomes(java_result(), ir, "Java") == {
        "syntaxParsed": "PASS", "namesTypesResolved": "PASS", "semanticsModeled": "FAIL"}


@pytest.mark.parametrize("syntax,expected", [("ERROR", "FAIL"), ("UNKNOWN", "UNKNOWN")])
def test_downstream_success_requires_syntax_even_if_other_fields_claim_success(syntax, expected):
    outcomes = frontends.phase_outcomes(java_result(syntax=syntax), "COMPLETE", "Java")
    assert outcomes["syntaxParsed"] == expected
    assert outcomes["namesTypesResolved"] != "PASS"
    assert outcomes["semanticsModeled"] != "PASS"


def test_unresolved_java_names_are_distinct_from_successful_syntax():
    outcomes = frontends.phase_outcomes(java_result(resolution="ERROR"), "COMPLETE", "Java")
    assert outcomes["syntaxParsed"] == "PASS"
    assert outcomes["namesTypesResolved"] == "FAIL"
    assert outcomes["semanticsModeled"] != "PASS"


def test_incomplete_java_bindings_cannot_count_as_resolved():
    outcomes = frontends.phase_outcomes(java_result(bindingComplete=False), "COMPLETE", "Java")
    assert outcomes["syntaxParsed"] == "PASS"
    assert outcomes["namesTypesResolved"] == "UNKNOWN"
    assert outcomes["semanticsModeled"] == "UNKNOWN"


@pytest.mark.parametrize("static", [None, {"status": "UNKNOWN"}, {"status": "REJECTED"}])
def test_proleap_asg_alone_never_counts_as_complete_name_and_type_validation(static):
    outcomes = frontends.phase_outcomes(cobol_result(), "COMPLETE", "COBOL", static)
    assert outcomes["syntaxParsed"] == "PASS"
    assert outcomes["namesTypesResolved"] == ("FAIL" if static and static["status"] == "REJECTED" else "UNKNOWN")
    assert outcomes["semanticsModeled"] != "PASS"


def test_completed_cobol_bindings_plus_static_compiler_evidence_can_pass_second_stage():
    outcomes = frontends.phase_outcomes(cobol_result(), "PARTIAL", "COBOL", {"status": "ACCEPTED"})
    assert outcomes == {"syntaxParsed": "PASS", "namesTypesResolved": "PASS", "semanticsModeled": "FAIL"}


@pytest.mark.parametrize("binding", [{"asgAnalysisCompleted": False}, {"unresolvedReferences": 1, "status": "ERROR"},
                                     {"countsComplete": False}, {"status": "ERROR"}])
def test_static_compiler_acceptance_cannot_replace_missing_or_failed_asg_bindings(binding):
    outcomes = frontends.phase_outcomes(cobol_result(**binding), "COMPLETE", "COBOL", {"status": "ACCEPTED"})
    assert outcomes["syntaxParsed"] == "PASS"
    assert outcomes["namesTypesResolved"] != "PASS"
    assert outcomes["semanticsModeled"] != "PASS"


def test_stage_aggregates_keep_unknowns_in_denominator_and_successes_nested():
    results = [
        frontends.phase_outcomes(java_result(), "COMPLETE", "Java"),
        frontends.phase_outcomes(java_result(), "PARTIAL", "Java"),
        frontends.phase_outcomes(java_result(resolution="UNKNOWN"), "COMPLETE", "Java"),
        frontends.phase_outcomes(java_result(syntax="ERROR", resolution="NOT_ATTEMPTED"), "UNSUPPORTED", "Java"),
        frontends.phase_outcomes(frontends.unknown_result("TIMEOUT"), "UNKNOWN", "Java"),
    ]
    metrics = frontends.aggregate([{"outcomes": outcome} for outcome in results])
    assert [metrics[stage]["count"] for stage in frontends.STAGES] == [3, 2, 1]
    for metric in metrics.values():
        assert metric["denominator"] == 5
        assert metric["count"] + metric["unknown"] + metric["failed"] == 5
        assert metric["status"] == "MEASURED"


def test_empty_cohort_has_zero_denominator_without_invented_accuracy():
    metrics = frontends.aggregate([])
    assert all(metric["denominator"] == 0 and metric["count"] == 0 for metric in metrics.values())
    assert not any("accuracy" in metric for metric in metrics.values())


def test_pair_results_require_both_members_and_failures_take_precedence_over_unknown():
    complete = {stage: "PASS" for stage in frontends.STAGES}
    unresolved = {"syntaxParsed": "PASS", "namesTypesResolved": "UNKNOWN", "semanticsModeled": "FAIL"}
    unknown = {stage: "UNKNOWN" for stage in frontends.STAGES}
    assert benchmark.combined([{"outcomes": complete}, {"outcomes": unresolved}]) == unresolved
    assert benchmark.combined([{"outcomes": unknown}, {"outcomes": unresolved}]) == {
        "syntaxParsed": "UNKNOWN", "namesTypesResolved": "UNKNOWN", "semanticsModeled": "FAIL"}


def frozen_source(folder, raw=b"class Main {}", relative="data/p00001/Java/s1.java"):
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": relative, "problemId": "p00001", "language": "Java",
            "sha256": hashlib.sha256(raw).hexdigest()}


def test_frozen_source_hash_is_checked_before_source_is_returned(tmp_path):
    record = frozen_source(tmp_path)
    assert benchmark.read_source(tmp_path, record) == "class Main {}"
    (tmp_path / record["path"]).write_bytes(b"class Changed {}")
    with pytest.raises(ValueError, match="hash changed"):
        benchmark.read_source(tmp_path, record)


@pytest.mark.parametrize("relative", ["../outside.java", "/tmp/outside.java", "data\\p00001\\Java\\s1.java",
                                      "data/p00002/Java/s1.java", "data/p00001/COBOL/s1.java"])
def test_frozen_source_identity_rejects_unsafe_paths_and_wrong_problem_language(tmp_path, relative):
    record = frozen_source(tmp_path)
    record["path"] = relative
    with pytest.raises(ValueError):
        benchmark.read_source(tmp_path, record)


def test_frozen_source_symlink_is_rejected_even_if_bytes_and_hash_match(tmp_path):
    record = frozen_source(tmp_path)
    source = tmp_path / record["path"]
    moved = tmp_path / "same-bytes.java"
    source.rename(moved)
    source.symlink_to(moved)
    with pytest.raises(ValueError, match="symlink"):
        benchmark.read_source(tmp_path, record)


def test_invalid_utf8_and_source_budget_preserve_quarantine_instead_of_decoding_lossily(tmp_path):
    record = frozen_source(tmp_path, b"\xff\xfe")
    assert benchmark.read_source(tmp_path, record) is None
    record = frozen_source(tmp_path, b"x" * (benchmark.MAX_SOURCE_BYTES + 1))
    assert benchmark.read_source(tmp_path, record) is None


class PipeProcess:
    """Selectable pipe with deterministic bytes, not a downloaded program."""
    def __init__(self, payload: bytes):
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.stdin = io.BytesIO()
        self.killed = False
        os.write(self.write_fd, payload)

    def poll(self):
        return 0 if self.killed else None

    def kill(self):
        self.killed = True
        os.close(self.write_fd)

    def wait(self, timeout):
        return 0


def install_pipe_worker(monkeypatch, payload: bytes, timeout=0.1):
    worker = frontends.FrontendWorker(timeout=timeout)
    process = PipeProcess(payload)
    monkeypatch.setattr(worker, "_start", lambda: setattr(worker, "process", process))
    return worker, process


@pytest.mark.parametrize("payload,code", [
    (b"not-json\n", None),
    (b"[]\n", "FRONTEND_REPORTED_FAILURE"),
    (b'{"error":"failed"}\n', "FRONTEND_REPORTED_FAILURE"),
    (json.dumps({**java_result(), "language": "COBOL"}).encode() + b"\n", "FRONTEND_LANGUAGE_MISMATCH"),
    (json.dumps(java_result(syntax="COMPLETE")).encode() + b"\n", "INVALID_FRONTEND_STATUS"),
    (json.dumps({**java_result(), "syntax": []}).encode() + b"\n", "INVALID_FRONTEND_PHASE"),
    (json.dumps({**java_result(), "resolution": None}).encode() + b"\n", "INVALID_FRONTEND_PHASE"),
    (json.dumps(java_result(resolution="ASSUMED_GOOD")).encode() + b"\n", "INVALID_RESOLUTION_STATUS"),
])
def test_malformed_or_mismatched_worker_results_abstain_and_close_process(monkeypatch, payload, code):
    worker, process = install_pipe_worker(monkeypatch, payload)
    result = worker.inspect("class Main {}", "Java", "JAVA", "Main.java")
    assert result["syntax"]["status"] == "UNKNOWN"
    assert result["resolution"]["status"] == "NOT_ATTEMPTED"
    if code:
        assert result["syntax"]["diagnostics"][0]["code"] == code
    assert process.killed and worker.process is None


def test_hung_worker_returns_unknown_and_is_killed_before_reuse(monkeypatch):
    worker, process = install_pipe_worker(monkeypatch, b"", timeout=0.01)
    result = worker.inspect("class Main {}", "Java", "JAVA", "Main.java")
    assert result["syntax"]["diagnostics"][0]["code"] == "FRONTEND_TIMEOUT"
    assert process.killed and worker.pending == b""


def test_response_budget_abstains_before_deserializing_oversized_payload(monkeypatch):
    monkeypatch.setattr(frontends, "MAX_RESPONSE_BYTES", 16)
    worker, process = install_pipe_worker(monkeypatch, b"x" * 32 + b"\n")
    result = worker.inspect("class Main {}", "Java", "JAVA", "Main.java")
    assert result["syntax"]["diagnostics"][0]["code"] == "FRONTEND_RESPONSE_BUDGET"
    assert process.killed


def test_source_byte_budget_is_checked_before_starting_worker(monkeypatch):
    worker = frontends.FrontendWorker()
    monkeypatch.setattr(worker, "_start", lambda: pytest.fail("Oversized source reached JVM"))
    # UTF-8 byte budget must also catch fewer than MAX_SOURCE_BYTES characters.
    result = worker.inspect("€" * (frontends.MAX_SOURCE_BYTES // 3 + 1), "Java", "JAVA", "Main.java")
    assert result["syntax"]["diagnostics"][0]["code"] == "SOURCE_BYTE_BUDGET"


def test_report_compaction_excludes_ast_payload_but_retains_failure_evidence():
    source = java_result()
    source["syntax"]["diagnostics"] = [{"code": "SOURCE_ERROR", "message": "x" * 5000}] * 20
    source["structure"] = {"nodes": ["large AST"], "symbols": ["bindings"], "references": ["calls"],
                           "nodeCounts": {"method": 2}, "sourceMapping": "PREPROCESSED_ONLY"}
    compact = frontends.compact_frontend(source)
    assert compact["structure"] == {"nodeCounts": {"method": 2}, "sourceMapping": "PREPROCESSED_ONLY"}
    assert len(compact["syntax"]["diagnostics"]) == 4
    assert compact["syntax"]["diagnostics"][0]["code"] == "SOURCE_ERROR"
    assert len(compact["syntax"]["diagnostics"][0]["message"]) <= 1200


def test_unconfigured_compiler_and_external_preprocessing_remain_unknown_without_execution(monkeypatch):
    monkeypatch.setattr(frontends.subprocess, "run", lambda *args, **kwargs: pytest.fail("Compiler must not run"))
    assert frontends.compiler_check("source", "FREE", None)["status"] == "UNKNOWN"
    assert frontends.compiler_check("COPY '/etc/passwd'.", "FREE", "cobc")["reason"] == "EXTERNAL_PREPROCESSING_CONTRACT_REQUIRED"


@pytest.fixture(scope="module")
def compiler_path():
    path = shutil.which("cobc") or "/tmp/sotonship-cobol-toolchain/install/bin/cobc"
    if not Path(path).is_file():
        pytest.skip("GnuCOBOL static checker is not installed")
    return path


@pytest.fixture(scope="module")
def real_worker():
    if not frontends.DEFAULT_JAR.is_file() or not shutil.which("java"):
        pytest.skip("Build experimental parser frontend JAR to run integration tests")
    with frontends.FrontendWorker(timeout=15) as worker:
        yield worker


COBOL_FIXTURE = """identification division.
program-id. table-demo.
data division.
working-storage section.
01 items-table.
   05 item-value occurs 3 times pic 9(4) value 0.
01 item-index pic 9 value 1.
procedure division.
    perform varying item-index from 1 by 1 until item-index > 3
        move item-index to item-value(item-index)
    end-perform
    display item-value(1)
    stop run.
"""


def test_real_cobol_group_and_table_syntax_and_compiler_check_still_do_not_complete_semantics(real_worker, compiler_path):
    parsed = real_worker.inspect(COBOL_FIXTURE, "COBOL", "FREE", "table.cob")
    assert parsed["syntax"]["status"] == "PARSED", parsed
    assert parsed["resolution"]["typeChecking"] == "NOT_PROVIDED_BY_PROLEAP"
    assert parsed["resolution"]["asgAnalysisCompleted"]
    assert parsed["resolution"]["unresolvedReferences"] == 0
    assert parsed["resolution"]["status"] == "UNKNOWN"
    static = frontends.compiler_check(COBOL_FIXTURE, "FREE", compiler_path)
    assert static["status"] == "ACCEPTED", static
    assert frontends.phase_outcomes(parsed, "PARTIAL", "COBOL", static) == {
        "syntaxParsed": "PASS", "namesTypesResolved": "PASS", "semanticsModeled": "FAIL"}


def test_real_java_resolves_jdk_array_and_io_syntax_separately_from_behavior(real_worker):
    source = """import java.util.Arrays;
class Main { public static void main(String[] args) {
    int[] values = {3, 1, 2}; Arrays.sort(values); System.out.println(values[0]);
} }
"""
    parsed = real_worker.inspect(source, "Java", "JAVA", "Main.java")
    assert parsed["syntax"]["status"] == "PARSED", parsed
    assert parsed["resolution"]["status"] == "RESOLVED", parsed
    assert frontends.phase_outcomes(parsed, "UNSUPPORTED", "Java")["semanticsModeled"] == "FAIL"


def test_real_cobol_undefined_name_is_rejected_without_confusing_syntax_with_types(real_worker, compiler_path):
    source = "identification division.\nprogram-id. broken.\nprocedure division.\n    display missing-value.\n    stop run.\n"
    parsed = real_worker.inspect(source, "COBOL", "FREE", "broken.cob")
    static = frontends.compiler_check(source, "FREE", compiler_path)
    assert parsed["syntax"]["status"] == "PARSED", parsed
    assert static["status"] == "REJECTED", static
    outcomes = frontends.phase_outcomes(parsed, "UNKNOWN", "COBOL", static)
    assert outcomes["syntaxParsed"] == "PASS" and outcomes["namesTypesResolved"] == "FAIL"
