"""Representation regression tests only; no model inference, fit or execution."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from ml_engine.cobol_extractor_v2 import extract_cobol
from ml_engine.semantic_ir import IRBuilder,NumericType,SourceSpan


def program(body,fields=None):
    fields=fields or ["01 IN-TEXT PIC X(20).","01 A PIC S9(5)V99 VALUE 0.","01 B PIC S9(5)V99 VALUE 0.","01 Q PIC S9(5) VALUE 0.","01 R PIC S9(5) VALUE 0.","01 OUT-VAL PIC -9(6).99."]
    return "\n".join(["IDENTIFICATION DIVISION.","PROGRAM-ID. DEMO.","DATA DIVISION.","WORKING-STORAGE SECTION.",*fields,"PROCEDURE DIVISION.",*body.split("\n"),"STOP RUN."])


def nodes(ir,op):return [n for n in ir.nodes if n.op==op]


def test_abs_mod_unary_input_output_exact_literals():
    source=program("ACCEPT IN-TEXT\nCOMPUTE A = FUNCTION NUMVAL(IN-TEXT)\nCOMPUTE B = FUNCTION ABS(-A)\nCOMPUTE R = FUNCTION MOD(-7, 3)\nMOVE B TO OUT-VAL\nDISPLAY FUNCTION TRIM(OUT-VAL)")
    ir=extract_cobol(source)
    assert ir.status=="COMPLETE",ir.to_dict()["issues"]
    for op in ["input","output","convert","absolute","negate","modulo","format"]:assert nodes(ir,op)
    assert nodes(ir,"input")[0].attrs["input_index"]==0
    assert nodes(ir,"output")[0].attrs["output_index"]==0
    assert nodes(ir,"modulo")[0].attrs["remainder_sign"]=="divisor"
    assert ir.source_hash==hashlib.sha256(source.encode()).hexdigest()
    assert ir.to_dict()["isProof"] is False and ir.to_dict()["codeExecuted"] is False


def test_multiline_divide_captures_both_receivers_and_span():
    source=program("DIVIDE A BY B GIVING Q\n    REMAINDER R\nDISPLAY R")
    ir=extract_cobol(source)
    assert ir.status=="COMPLETE"
    divide=nodes(ir,"divide")[0]
    assert divide.span.end_line==divide.span.start_line+1
    assert divide.source=="DIVIDE A BY B GIVING Q\n    REMAINDER R"
    stores=[n for n in nodes(ir,"store") if n.span==divide.span]
    assert {n.attrs["symbol"] for n in stores}=={"Q","R"}
    assert nodes(ir,"modulo")[0].attrs["quotient_rounding"]=="TRUNCATE_TOWARD_ZERO"


@pytest.mark.parametrize("statement,receivers,op",[
    ("SUBTRACT 1 FROM A B",{"A","B"},"subtract"),
    ("SUBTRACT 1 FROM A GIVING B",{"B"},"subtract"),
    ("ADD 1 2 TO A B",{"A","B"},"add"),
    ("ADD 1 TO A GIVING B",{"B"},"add"),
    ("MULTIPLY 2 BY A B",{"A","B"},"multiply"),
    ("MULTIPLY 2 BY A GIVING B",{"B"},"multiply"),
    ("DIVIDE 2 INTO A B",{"A","B"},"divide"),
    ("COMPUTE A ROUNDED B = 1 / 3",{"A","B"},"divide"),
])
def test_receiving_targets_all_supported_arithmetic_forms(statement,receivers,op):
    ir=extract_cobol(program(statement+"\nDISPLAY A"))
    assert ir.status=="COMPLETE",ir.to_dict()["issues"]
    line=next(n.span.start_line for n in nodes(ir,op))
    assert {n.attrs["symbol"] for n in nodes(ir,"store") if n.span.start_line==line}==receivers


def test_rounding_sign_overflow_precision_and_edited_format_are_separate():
    source=program("COMPUTE A ROUNDED = 1 / 3\nCOMPUTE B = A\nMOVE A TO OUT-VAL\nDISPLAY OUT-VAL",
                   ["01 A PIC 9(4)V99.","01 B PIC S9(5)V9(4).","01 OUT-VAL PIC -(5)9."])
    ir=extract_cobol(source);assert ir.status=="COMPLETE"
    stores={n.attrs["symbol"]:n for n in nodes(ir,"store")}
    assert stores["A"].attrs["rounding_mode"]=="HALF_UP"
    assert stores["B"].attrs["rounding_mode"]=="TRUNCATE_TOWARD_ZERO"
    assert stores["A"].attrs["unsignedSignRemoval"] is True
    assert stores["B"].attrs["unsignedSignRemoval"] is False
    assert stores["B"].numeric_type.precision==9 and stores["B"].numeric_type.scale==4
    assert stores["A"].numeric_type.bit_width is None
    assert stores["A"].attrs["overflow"]=="DISCARD_HIGH_ORDER_DECIMAL_DIGITS"
    assert nodes(ir,"format")[0].attrs["format_picture"]=="-(5)9"


@pytest.mark.parametrize("usage",["COMP-3","PACKED-DECIMAL","USAGE IS COMP-3"])
def test_packed_decimal_is_supported_without_binary_width_guess(usage):
    ir=extract_cobol(program("COMPUTE A = 1.25\nDISPLAY A",[f"01 A PIC S9(5)V99 {usage}."]))
    assert ir.status=="COMPLETE",ir.to_dict()["issues"]
    assert nodes(ir,"store")[0].numeric_type.attrs["storage"]=="packed_decimal"
    assert nodes(ir,"store")[0].attrs["storage"]=="packed_decimal"
    assert nodes(ir,"store")[0].numeric_type.bit_width is None


def test_versioned_reassignment_uses_latest_value_and_retains_type():
    ir=extract_cobol(program("MOVE 3 TO A\nMOVE B TO A\nCOMPUTE Q = A\nDISPLAY Q"))
    assert ir.status=="COMPLETE"
    a_stores=[n for n in nodes(ir,"store") if n.attrs["symbol"]=="A"]
    final_read=[n for n in nodes(ir,"read") if n.attrs["symbol"]=="A"][-1]
    assert final_read.inputs==[a_stores[-1].id]
    assert final_read.numeric_type.scale==2
    assert final_read.attrs["version"]==a_stores[-1].attrs["version"]
    assert ir.symbols["A"]["constant"] is None
    assert all(n.attrs["constantStateKilled"] for n in a_stores)


def test_if_else_guards_branch_merge_and_read_versions():
    ir=extract_cobol(program("IF A < B\nMOVE 1 TO Q\nELSE\nMOVE 2 TO Q\nEND-IF\nDISPLAY Q"))
    assert ir.status=="COMPLETE"
    assert {n.attrs["expected"] for n in nodes(ir,"guard")}=={True,False}
    merge=next(n for n in nodes(ir,"merge") if n.attrs.get("symbol")=="Q")
    assert len(merge.inputs)==2
    read=[n for n in nodes(ir,"read") if n.attrs["symbol"]=="Q"][-1]
    assert read.inputs==[merge.id]
    assert any(e.kind=="control" for e in ir.edges)


def test_loop_phis_control_backedge_and_exit_are_present():
    ir=extract_cobol(program("PERFORM UNTIL Q = 0\nSUBTRACT 1 FROM Q\nEND-PERFORM\nDISPLAY Q"))
    assert ir.status=="COMPLETE"
    loop=nodes(ir,"loop")[0]
    assert loop.attrs["test_position"]=="BEFORE"
    phi=next(n for n in nodes(ir,"merge") if n.attrs.get("loop_phi") and n.attrs["symbol"]=="Q")
    assert len(phi.inputs)==2
    assert any(e.kind=="loop" and e.target==phi.id for e in ir.edges)
    assert any(e.kind=="loop" and e.target==loop.id and e.attrs["meaning"]=="control_backedge" for e in ir.edges)
    assert [n for n in nodes(ir,"read") if n.attrs["symbol"]=="Q"][-1].inputs==[phi.id]


def test_constants_are_exact_and_changed_output_remains_visible():
    ir=extract_cobol(program("MOVE 0.10000000000000000000000000000000001 TO A\nDISPLAY A"))
    literal=next(n for n in nodes(ir,"literal") if n.attrs["value"].startswith("0.1"))
    assert literal.attrs["value"]=="0.10000000000000000000000000000000001"
    assert literal.attrs["exact_denominator"]=="100000000000000000000000000000000000"
    assert extract_cobol(program("DISPLAY A")).fingerprint()!=extract_cobol(program("DISPLAY B")).fingerprint()


def test_source_spans_crlf_fixed_and_renaming_fingerprint():
    source=program("MAIN.\nCOMPUTE Q =\n    A - B\nDISPLAY Q")
    free=extract_cobol(source);crlf=extract_cobol(source.replace("\n","\r\n"))
    fixed=extract_cobol("\n".join(f"{i:06d} {line}" for i,line in enumerate(source.split("\n"),1)),"FIXED")
    assert free.status==crlf.status==fixed.status=="COMPLETE"
    assert free.source_hash!=crlf.source_hash
    assert free.fingerprint()==crlf.fingerprint()==fixed.fingerprint()
    assert nodes(crlf,"subtract")[0].source.endswith("\r")
    assert nodes(fixed,"subtract")[0].span.start_column==8
    renamed_source=re.sub(r"(?<![\w-])A(?![\w-])","ALPHA",source)
    renamed_source=re.sub(r"(?<![\w-])B(?![\w-])","BETA",renamed_source)
    renamed=extract_cobol(renamed_source)
    # Explicit source identity always changes; ignore_names is a structural aid,
    # not a promise that arbitrary graph rewrites are equivalent.
    assert renamed.source_hash!=free.source_hash
    assert renamed.status=="COMPLETE"
    assert free.fingerprint()==renamed.fingerprint()
    assert free.fingerprint(ignore_names=False)!=renamed.fingerprint(ignore_names=False)


@pytest.mark.parametrize("body",[
    'CALL "OTHER"',"EXEC CICS LINK END-EXEC","COPY MISSING","COMPUTE A = FUNCTION UNKNOWN(B)",
    "COMPUTE A = UNKNOWN","MOVE 1 TO UNKNOWN","IF A + 1\nMOVE 1 TO B\nEND-IF",
    'COMPUTE A = FUNCTION ABS("text")',"COMPUTE A = FUNCTION NUMVAL(B)",
    'COMPUTE A = "text"',"COMPUTE A = 1 ON SIZE ERROR MOVE 0 TO A", "DISPLAY A UPON PRINTER",
])
def test_unknown_or_unsupported_behavior_abstains_with_source_issue(body):
    ir=extract_cobol(program(body))
    assert ir.status in {"PARTIAL","UNSUPPORTED"}
    assert ir.issues and all(i.span.start_line>=1 for i in ir.issues)


def test_unknown_declaration_header_and_fixed_literal_continuation_are_not_silent():
    for fields in [["01 A PIC 9(4) COMP."],["01 A REDEFINES B PIC 9(4)."],["01 A PIC 9(4) UNKNOWN."]]:
        ir=extract_cobol(program("DISPLAY A",fields));assert ir.status!="COMPLETE" and ir.issues
    ir=extract_cobol(program("DISPLAY A").replace("DATA DIVISION.","ENVIRONMENT DIVISION.\nDATA DIVISION."))
    assert any(i.code=="DECLARATION_OR_HEADER_UNSUPPORTED" for i in ir.issues)
    source=program('DISPLAY "abc"');fixed="\n".join("       "+l for l in source.split("\n"))
    fixed=fixed.replace('       DISPLAY "abc"','      -DISPLAY "abc"')
    assert any(i.code=="FIXED_CONTINUATION_UNSUPPORTED" for i in extract_cobol(fixed,"FIXED").issues)


def test_operand_roles_and_serialization_are_preserved():
    ir=extract_cobol(program("COMPUTE Q = A - B\nDISPLAY Q"))
    subtract=nodes(ir,"subtract")[0]
    assert [e.attrs["operand_index"] for e in ir.edges if e.kind=="data" and e.target==subtract.id]==[0,1]
    assert all(e.attrs["meaning"]=="lexical_emission_order" for e in ir.edges if e.kind=="sequence")
    assert json.loads(json.dumps(ir.to_dict()))["status"]=="COMPLETE"


def test_current_pilot_cobol_sources_have_explicit_complete_coverage():
    # Source extraction coverage, not model or behavioral accuracy evaluation.
    path=Path(__file__).resolve().parents[1]/"evaluation/synthetic-pilot/pilot-10-r3/dataset.json"
    dataset=json.loads(path.read_text())
    for family in dataset["families"]:
        ir=extract_cobol("\n".join(family["cobolLines"]))
        assert ir.status=="COMPLETE",(family["familyId"],ir.to_dict()["issues"])
        coverage=ir.attrs["coverage"]
        assert coverage["logical_statements"]==coverage["consumed_statements"]


def test_budgets_are_source_bound_abstentions():
    ir=extract_cobol("X"*200001)
    assert ir.status=="UNSUPPORTED" and ir.issues[0].code=="SOURCE_BUDGET"
    source=program("COMPUTE A = "+"("*70+"1"+")"*70)
    ir=extract_cobol(source);assert ir.status!="COMPLETE" and any("nesting" in i.message for i in ir.issues)


@pytest.mark.parametrize("body",["STOP RUN\nDISPLAY A","IF A < B\nGOBACK\nEND-IF","PERFORM UNTIL A = 0\nSTOP RUN\nEND-PERFORM"])
def test_early_or_nested_termination_abstains(body):
    ir=extract_cobol(program(body))
    assert ir.status!="COMPLETE"
    assert any("terminal-path" in i.message for i in ir.issues)


@pytest.mark.parametrize("body",['ADD "text" TO A','SUBTRACT "text" FROM A','MULTIPLY A BY IN-TEXT','DIVIDE A INTO IN-TEXT','MULTIPLY "text" BY A GIVING B','DIVIDE A BY IN-TEXT GIVING Q'])
def test_non_numeric_arithmetic_statement_operands_abstain(body):
    ir=extract_cobol(program(body))
    assert ir.status!="COMPLETE"
    assert any("numeric operands" in i.message for i in ir.issues)
