"""Contract adapters must preserve source storage and reject ambiguous labels."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adjudicate_c2j_numeric_arrays_b.py"
SPEC = importlib.util.spec_from_file_location("numeric_b", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def row_fixture(number, fields, moves, output_pic, result_decl):
    linkage = "       01 LINKED-ITEMS.\n" + fields + result_decl
    source = (f"       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TEST-PROGRAM.\n"
              "       DATA DIVISION.\n       LINKAGE SECTION.\n" + linkage
              + "       PROCEDURE DIVISION USING LINKED-ITEMS.\n       GOBACK.\n")
    output = ("       PERFORM VARYING NJ FROM 1 BY 1 UNTIL NJ > 100\n"
              "           MOVE RESULT (NJ) TO OUTPUT-RECORD\n           WRITE OUTPUT-RECORD\n       END-PERFORM\n"
              if number in {113, 120} else "       MOVE RESULT TO OUTPUT-RECORD\n       WRITE OUTPUT-RECORD\n")
    driver = ('       SELECT OUTPUT-FILE ASSIGN TO "TEST-PROGRAM.TXT".\n'
              f"       01 OUTPUT-RECORD PIC {output_pic}.\n" + linkage
              + "       PROCEDURE DIVISION.\n" + moves
              + '       CALL "TEST-PROGRAM" USING LINKED-ITEMS\n' + output)
    return {"task_id": f"HumanEval/{number}", "COBOL_canonical_solution": source, "tests": [{"test": driver}]}


def test_comp2_uses_homogeneous_double_not_integer_literal_kind():
    row = row_fixture(92, "           05 L-X COMP-2.\n           05 L-Y COMP-2.\n           05 L-Z COMP-2.\n",
                      "       MOVE 3.0 TO L-X\n       MOVE 4 TO L-Y\n       MOVE 7 TO L-Z\n", "9", "           05 RESULT PIC 9.\n")
    result = module.extract_case(row, 0)
    assert result["arguments"] == [3.0, 4.0, 7.0]
    assert all(type(v) is float for v in result["arguments"])
    assert module.java_probe(92).count("Double.valueOf") == 3


def test_fixed_string_input_truncation_is_explicit_and_not_expected_driven():
    row = row_fixture(113, "           05 L-LST OCCURS 2 TIMES INDEXED BY NI PIC X(2).\n",
                      "       MOVE '3' TO L-LST(1)\n       MOVE \"1111111\" TO L-LST(2)\n", "X(100)",
                      "           05 RESULT OCCURS 100 TIMES INDEXED BY NJ PIC X(100).\n")
    result = module.extract_case(row, 0)
    assert result["arguments"] == [["3", "11"]]
    assert result["cobolStoredInputs"] == [["3 ", "11"]]
    assert result["logicalResultLength"] == 2
    assert result["sourceDefinedInputTruncations"][0]["originalLiteral"] == "1111111"


def test_full_native_string_cell_preserves_internal_padding_and_checks_tail():
    records = [b"prefix    0001 suffix", b"other    0002"] + [b""] * 98
    result, metadata = module.decode_cobol(113, b"\n".join(records) + b"\n", {"logicalResultLength": 2})
    assert result == [line.decode().ljust(100) for line in records[:2]]
    assert metadata["unusedStorageRecordsChecked"] == 98
    assert metadata["expectedAnswerLengthUsed"] is False
    assert result != module.map_java_output(113, ["prefix 1 suffix", "other 2"], {"logicalResultLength": 2})
    records[-1] = b"unexpected"
    with pytest.raises(ValueError, match="Unused"):
        module.decode_cobol(113, b"\n".join(records) + b"\n", {"logicalResultLength": 2})


def test_source_input_k_defines_list_length_and_java_extra_values_fail():
    raw = b"0000000004\n0000000004\n" + b"0000000000\n" * 98
    result, metadata = module.decode_cobol(120, raw, {"logicalResultLength": 2})
    assert result == [4, 4]
    assert metadata["sourceDerivedLogicalResultLength"] == 2
    with pytest.raises(ValueError, match="length"):
        module.map_java_output(120, [4, 4, 0], {"logicalResultLength": 2})


def test_boolean_and_optional_absence_are_not_silently_healthy():
    with pytest.raises(ValueError):
        module.decode_cobol(92, b"2\n", {})
    with pytest.raises(ValueError, match="absent"):
        module.map_java_output(128, None, {})


def test_reference_disagreement_does_not_gate_source_fidelity_comparison():
    observed = {"status": "OBSERVED", "mappedResult": True}
    assert module.comparison(observed, False, False) == "SOURCE_DIVERGENCE_WITH_REFERENCE_POLICY_CONFLICT"
    assert module.comparison(observed, True, False) == "SOURCE_AGREEMENT_WITH_REFERENCE_POLICY_CONFLICT"


def test_solution_exception_is_distinguished_from_adapter_failure():
    source = 'Exception in thread "main" java.lang.StringIndexOutOfBoundsException: Index 3 out of bounds\n\tat Solution.matchParens(Solution.java:14)\n\tat NumericBReplay.main(NumericBReplay.java:20)\n'
    evidence = module.exception_evidence(source)
    assert evidence["status"] == "CANDIDATE_PROGRAM_EXCEPTION"
    assert evidence["exceptionType"] == "java.lang.StringIndexOutOfBoundsException"
    adapter = source.replace("Solution.matchParens(Solution.java:14)", "NumericBReplay.main(NumericBReplay.java:20)")
    assert module.exception_evidence(adapter)["status"] == "RUNTIME_FAILURE_UNRESOLVED"


def test_task_outside_assigned_development_contract_cannot_be_mapped():
    with pytest.raises(ValueError, match="outside"):
        module.extract_case({"task_id": "HumanEval/1"}, 0)


def test_java_probe_encoder_round_trips_quotes_backslash_and_newline(tmp_path):
    jdk = Path("/Users/volodymyrsydorenko/Developer/jdk-21.0.10.jdk/Contents/Home/bin")
    if not (jdk / "javac").exists():
        pytest.skip("JDK21 local integration toolchain unavailable")
    (tmp_path / "NumericBReplay.java").write_text(module.java_probe(103))
    (tmp_path / "Solution.java").write_text('class Solution { public Object roundedAvg(int a,int b) { return "a\\\"b\\\\c\\n"; } }')
    compiled = subprocess.run([str(jdk / "javac"), "-proc:none", "NumericBReplay.java", "Solution.java"], cwd=tmp_path, capture_output=True, timeout=15)
    assert compiled.returncode == 0, compiled.stderr.decode()
    run = subprocess.run([str(jdk / "java"), "-cp", str(tmp_path), "NumericBReplay", "1", "2"], cwd=tmp_path, capture_output=True, timeout=5)
    assert run.returncode == 0, run.stderr.decode()
    assert json.loads(run.stdout) == 'a"b\\c\n'
