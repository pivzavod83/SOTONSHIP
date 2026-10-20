"""Source-pair contracts; these are not a new independent accuracy dataset."""
import hashlib

import numpy as np

from ml_engine.defect_features_v2 import GLOBAL_NAMES, PAIR_NAMES, extract_pair, supervision


COBOL = """>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. EXTRACT-V2.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 AMOUNT PIC S9(5)V99.
01 FEE PIC S9(5)V99.
01 RESULT-VALUE PIC S9(6)V99.
PROCEDURE DIVISION.
ACCEPT AMOUNT
ACCEPT FEE
COMPUTE RESULT-VALUE = AMOUNT - FEE
DISPLAY RESULT-VALUE
STOP RUN.
"""
JAVA = """import java.math.BigDecimal;
public class Review {
public BigDecimal calculate(BigDecimal amount, BigDecimal fee) {
BigDecimal result = amount.subtract(fee);
return result;
}
}
"""


def test_return_transformation_survives_to_model_features():
    a = extract_pair(COBOL, JAVA)
    b = extract_pair(COBOL, JAVA.replace("return result;", "return result.abs();"))
    assert a.status == b.status == "SUPPORTED", (a.coverage, b.coverage)
    assert a.global_x.shape == b.global_x.shape == (len(GLOBAL_NAMES),)
    assert a.candidate_x.shape[1] == len(PAIR_NAMES)
    assert not np.array_equal(a.global_x, b.global_x)
    assert any(n.op == "absolute" for n in b.java_ir.nodes)
    assert any(n.op == "return" for n in b.java_ir.nodes)


def test_ordered_operands_and_observable_selection_reach_model_features():
    original = extract_pair(COBOL, JAVA)
    swapped = extract_pair(COBOL, JAVA.replace("amount.subtract(fee)", "fee.subtract(amount)"))
    output = extract_pair(COBOL, JAVA.replace("return result;", "return amount;"))
    assert original.status == swapped.status == output.status == "SUPPORTED"
    assert not np.array_equal(original.global_x, swapped.global_x)
    assert not np.array_equal(original.global_x, output.global_x)


def test_decimal_rounding_policy_reaches_model_features():
    source = JAVA.replace("import java.math.BigDecimal;", "import java.math.BigDecimal;\nimport java.math.RoundingMode;")
    a = extract_pair(COBOL, source.replace("return result;", "return result.setScale(2, RoundingMode.DOWN);"))
    b = extract_pair(COBOL, source.replace("return result;", "return result.setScale(2, RoundingMode.HALF_EVEN);"))
    assert a.status == b.status == "SUPPORTED", (a.coverage, b.coverage)
    assert not np.array_equal(a.global_x, b.global_x)


def test_formatting_and_renaming_are_not_classifier_features():
    original = extract_pair(COBOL, JAVA)
    formatted = extract_pair(COBOL.replace(" = AMOUNT - FEE", " =\n    AMOUNT - FEE"),
                             JAVA.replace("amount.subtract(fee)", "amount\n .subtract(\n fee\n )"))
    renamed = extract_pair(COBOL.replace("AMOUNT", "SOURCE-AMOUNT").replace("FEE", "SOURCE-FEE"),
                           JAVA.replace("amount", "principal").replace("fee", "charge").replace("Review", "Other"))
    assert original.status == formatted.status == renamed.status == "SUPPORTED", (formatted.coverage, renamed.coverage)
    np.testing.assert_array_equal(original.global_x, formatted.global_x)
    np.testing.assert_array_equal(original.global_x, renamed.global_x)


def test_unknown_operations_cannot_produce_supported_classification_features():
    graph = extract_pair(COBOL, JAVA.replace("return result;", "return External.adjust(result);"))
    assert graph.status == "ABSTAIN"
    assert graph.coverage["java"]["status"] != "COMPLETE"
    assert graph.coverage["java"]["issues"]
    graph = extract_pair(COBOL.replace("DISPLAY RESULT-VALUE", 'CALL "EXTERNAL" USING RESULT-VALUE'), JAVA)
    assert graph.status == "ABSTAIN"
    assert graph.coverage["cobol"]["issues"]


def test_all_candidate_excerpts_bind_to_raw_sources_and_allow_clusters():
    c, j = COBOL.replace("\n", "\r\n"), JAVA.replace("\n", "\r\n")
    graph = extract_pair(c, j)
    assert graph.status == "SUPPORTED", graph.coverage
    assert graph.java_ir.source_hash == hashlib.sha256(j.encode()).hexdigest()
    assert graph.cobol_ir.source_hash == hashlib.sha256(c.encode()).hexdigest()
    for source, regions in ((c, graph.cobol), (j, graph.java)):
        assert all(r.text == "\n".join(source.split("\n")[r.start-1:r.end]) for r in regions)
    assert any(a is None for a, _ in graph.candidates)
    assert any(b is None for _, b in graph.candidates)
    labels = supervision(graph, [(12, 12)], [(4, 4)])
    assert labels.shape == (len(graph.candidates),)
    assert set(labels) <= {0, 1}


def test_source_budget_abstains_without_low_risk_fallback():
    graph = extract_pair(COBOL, "//" + "x" * 200_001)
    assert graph.status == "ABSTAIN"
    assert graph.coverage["extractionError"]["requiresReview"]
    assert graph.candidate_x.shape == (0, len(PAIR_NAMES))
