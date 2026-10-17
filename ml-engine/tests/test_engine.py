from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import z3

from ml_engine.cpg_builder import baseline, build_cpg, combined_graph_json, features
from ml_engine.fixtures import (CICS_COBOL, CICS_JAVA, FX_COBOL, FX_JAVA, FX_PATCH,
                                MORTGAGE_COBOL, MORTGAGE_JAVA, MORTGAGE_PATCH,
                                REMIT_COBOL, REMIT_JAVA, cobol, demo_requests)
from ml_engine.gnn_aligner import align, embeddings, load_model
from ml_engine.semantics import parse_cobol, parse_java, strip_comments
from ml_engine.verify import load_reference_rates, verify_request
from ml_engine.z3_formal_prover import SAT, UNKNOWN, UNSAT, half_up, prove, trunc

RATE = {"currencyPair": "GBP/EUR", "rate": "1.183", "source": "Bank of England Daily Spot Rate",
        "collectedDate": "2026-10-17", "observationDate": "2026-10-15"}


@pytest.mark.parametrize("old,new,status", [(FX_COBOL, FX_JAVA, SAT), (FX_COBOL, FX_PATCH, UNSAT),
    (MORTGAGE_COBOL, MORTGAGE_JAVA, SAT), (MORTGAGE_COBOL, MORTGAGE_PATCH, UNSAT),
    (REMIT_COBOL, REMIT_JAVA, UNSAT), (CICS_COBOL, CICS_JAVA, UNKNOWN)])
def test_real_solver_statuses_and_scope(old, new, status):
    result = prove(old, new, RATE)
    assert result["formalProofStatus"] == status, result["proofScope"]
    assert result["proofScope"]["bounded"]
    assert result["proofScope"]["sourceSha256"]["java"]
    assert bool(result["counterexamplesJson"]) == (status == SAT)
    if status == UNSAT:
        assert result["proofScope"]["solver"]["result"] == "unsat"


def test_actual_binary_witness_and_false_requested_example():
    result = prove(FX_COBOL, FX_JAVA, RATE)
    witness = result["counterexamplesJson"][0]
    assert witness["inputAmountGbp"] == "45.00"
    assert witness["cobolOutput"] == "53.24"
    assert witness["javaOutput"] == "53.23"
    from decimal import Decimal, ROUND_HALF_UP
    decimal_output = (Decimal("10450.33") * Decimal("1.2941")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    binary_output = Decimal(10450.33 * 1.2941).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    assert decimal_output == binary_output == Decimal("13523.77")


@pytest.mark.parametrize("value,rounding,expected", [("-1.5",half_up,-2),("-1.5",trunc,-1),
    ("-1.49",half_up,-1),("1.5",half_up,2)])
def test_negative_and_tie_rounding(value, rounding, expected):
    assert z3.simplify(rounding(z3.RealVal(value))).as_long() == expected


def test_changed_patch_is_never_approved_from_category_or_bigdecimal_marker():
    wrong = FX_PATCH.replace('principal.multiply(quote)', 'principal.add(quote)')
    result = prove(FX_COBOL, wrong, RATE)
    assert result["formalProofStatus"] == SAT
    request = {**demo_requests()[0], "javaSource": wrong, "referenceFxRates": [RATE]}
    assert verify_request(request)["formalProofStatus"] == SAT
    mismatched = {**request, "category": "REMITTANCE_FEE"}
    assert verify_request(mismatched)["formalProofStatus"] == UNKNOWN


@pytest.mark.parametrize("source", [
    FX_PATCH.replace("principal.multiply(quote)", "principal.multiply(2)"),
    FX_PATCH.replace('principal.multiply(quote).setScale(2, RoundingMode.HALF_UP).remainder(new BigDecimal("10000000"))', "0"),
    FX_PATCH.replace('principal.multiply(quote).setScale(2, RoundingMode.HALF_UP).remainder(new BigDecimal("10000000"))', 'new BigDecimal("1/2")'),
    FX_PATCH.replace('principal.multiply(quote).setScale(2, RoundingMode.HALF_UP).remainder(new BigDecimal("10000000"))', 'new BigDecimal("1_2")'),
    FX_PATCH.replace('principal.multiply(quote).setScale(2, RoundingMode.HALF_UP).remainder(new BigDecimal("10000000"))', 'new BigDecimal("1/*comment*/2")'),
    FX_PATCH.replace("public final class FxWireService", "public final class int"),
    FX_PATCH.replace("RoundingMode.HALF_UP", "RoundingMode.HALF_EVEN"),
    FX_PATCH.replace("return principal", "while (true) {} return principal"),
])
def test_invalid_or_unsupported_source_halts(source):
    assert prove(FX_COBOL, source, RATE)["formalProofStatus"] == UNKNOWN


def test_bigdecimal_reference_comparisons_and_compare_to_type():
    body = """import java.math.BigDecimal;
    public final class Sample { public BigDecimal calculate(BigDecimal a, BigDecimal r) {
        if (a == r) {return BigDecimal.ONE;} else {return BigDecimal.ZERO;}
    }}"""
    assert prove(FX_COBOL, body, RATE)["formalProofStatus"] == UNKNOWN
    invalid = FX_PATCH.replace("principal.multiply(quote)", "principal.compareTo(quote).multiply(quote)")
    assert prove(FX_COBOL, invalid, RATE)["formalProofStatus"] == UNKNOWN


def test_integral_java_division_is_not_assumed_float():
    integer_division = """public class Example {
      public double calculate(double a,double r) {return Math.round(a*r*100)/100;}
    }"""
    assert prove(FX_COBOL, integer_division, RATE)["formalProofStatus"] == UNKNOWN
    negated_long = integer_division.replace("Math.round(a*r*100)/100", "-Math.round(a*r*100.0)/100.0")
    assert prove(FX_COBOL, negated_long, RATE)["formalProofStatus"] == UNKNOWN


def test_nonfinite_bigdecimal_constructor_cannot_be_a_witness_or_safe_proof():
    huge = "1" + "0" * 200 + ".0"
    expression = f'new BigDecimal({huge} * {huge}).multiply(BigDecimal.ZERO)'
    source = FX_PATCH.replace('principal.multiply(quote).setScale(2, RoundingMode.HALF_UP).remainder(new BigDecimal("10000000"))', expression)
    zero_cobol = FX_COBOL.replace("INPUT-AMOUNT * REFERENCE-RATE", "0")
    result = prove(zero_cobol, source, RATE)
    assert result["formalProofStatus"] == UNKNOWN
    assert not result["counterexamplesJson"]


def test_bigdecimal_cannot_be_implicitly_returned_or_assigned_as_double():
    wrong_return = """import java.math.BigDecimal;
    public class Example { public double calculate(BigDecimal a,BigDecimal r) {return a;} }"""
    assert prove(FX_COBOL, wrong_return, RATE)["formalProofStatus"] == UNKNOWN
    wrong_local = FX_PATCH.replace("return principal", "double x = principal; return principal")
    assert prove(FX_COBOL, wrong_local, RATE)["formalProofStatus"] == UNKNOWN


def test_unsupported_storage_and_uninitialized_fields_halt():
    assert prove(FX_COBOL.replace(" VALUE 0", ""), FX_PATCH, RATE)["formalProofStatus"] == UNKNOWN
    assert prove(FX_COBOL + "BOGUS TOKENS", FX_PATCH, RATE)["formalProofStatus"] == UNKNOWN
    assert prove(FX_COBOL.replace("* REFERENCE-RATE", "* NOT-DECLARED"), FX_PATCH, RATE)["formalProofStatus"] == UNKNOWN


def test_comments_preserve_decimal_string_content():
    assert strip_comments('new BigDecimal("1/*x*/2") /* real */', "java").strip() == 'new BigDecimal("1/*x*/2")'
    result = prove(FX_COBOL + "\n*> EXEC CICS fake comment", FX_PATCH, RATE)
    assert result["formalProofStatus"] == UNSAT


def test_fixed_point_rate_must_fit_declared_picture():
    assert prove(FX_COBOL, FX_PATCH, {**RATE, "rate": "1.18301"})["formalProofStatus"] == UNKNOWN
    assert prove(FX_COBOL, FX_PATCH, {**RATE, "rate": "101.0"})["formalProofStatus"] == UNKNOWN


def test_graph_has_source_derived_features_and_all_edge_types():
    graph = build_cpg(MORTGAGE_COBOL, "cobol")
    kinds = {attributes["kind"] for _, _, attributes in graph.edges(data=True)}
    assert {"AST", "CFG", "TYPE_FLOW"} <= kinds
    assert features("PIC 9(2)V9(4) COMP-3", "cobol")[3] == 0.5
    assert all(len(attributes["features"]) == 8 for _, attributes in graph.nodes(data=True))
    java = build_cpg(MORTGAGE_JAVA, "java")
    result = align(graph, java)
    serialized = combined_graph_json(graph, java, result["links"])
    assert any(edge["kind"] == "GNN_ALIGNMENT" for edge in serialized["edges"])
    assert 0 <= result["bugRiskScore"] <= 1


def test_graph_embedding_is_name_invariant_and_message_passing_sensitive():
    first = build_cpg(FX_JAVA, "java")
    second = build_cpg(FX_JAVA.replace("principal", "zzzz").replace("quote", "aaaa"), "java")
    _, a = embeddings(first, load_model())
    _, b = embeddings(second, load_model())
    np.testing.assert_allclose(a, b)
    first.remove_edges_from(list(first.edges(keys=True)))
    _, changed = embeddings(first, load_model())
    assert not np.allclose(a, changed)


def test_baseline_is_computed_and_can_catch_explicit_bad_api():
    assert not baseline(FX_COBOL, FX_JAVA)[1]
    assert baseline(FX_COBOL, "return new BigDecimal(1.21);")[1]


def test_actual_reference_provenance_and_corridor_vintage():
    rates = load_reference_rates()
    assert len(rates) == 4
    bank = next(rate for rate in rates if "World Bank" in rate["source"])
    assert bank["rate"] == "43.98"
    assert bank["observationDate"] == "2025-08-22"
    request = {**demo_requests()[2], "referenceFxRates": rates}
    result = verify_request(request)
    assert result["proofScope"]["rate"]["source"] == bank["source"]
    assert result["formalProofStatus"] == UNSAT


def test_cli_emits_only_one_json_object_and_rejects_bad_input():
    request = {**demo_requests()[0], "referenceFxRates": [RATE]}
    command = [sys.executable, "-m", "ml_engine.verify", "--stdin"]
    response = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True, check=True)
    assert json.loads(response.stdout)["formalProofStatus"] == SAT
    assert not response.stderr
    invalid = subprocess.run(command, input='{"javaSource": ""}', text=True, capture_output=True)
    assert invalid.returncode == 2 and not invalid.stdout
    assert json.loads(invalid.stderr)["error"] == "ValueError"


def test_optional_patch_is_not_required_for_analysis():
    request = {**demo_requests()[0], "referenceFxRates": [RATE]}
    del request["patchedJavaSource"]
    assert verify_request(request)["formalProofStatus"] == SAT
    request["patchedJavaSource"] = ""
    assert verify_request(request)["formalProofStatus"] == SAT
