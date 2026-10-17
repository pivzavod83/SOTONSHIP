from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from ml_engine.cpg_builder import build_cpg, deterministic_diagnostics
from ml_engine.fixtures import FX_COBOL, FX_JAVA, FX_PATCH, MORTGAGE_COBOL, REMIT_JAVA, cobol, demo_requests
from ml_engine.gnn_aligner import align
from ml_engine.policy import ENGINE_VERSION, InputValidationError, MAX_SOURCE_LINES, validate_source
from ml_engine.verify import verify_request
from ml_engine.z3_formal_prover import UNKNOWN, UNSAT, prove

RATE = {"currencyPair":"GBP/EUR","rate":"1.183","source":"Bank of England Daily Spot Rate","collectedDate":"2026-10-17"}


def test_octal_regression_never_claims_safe():
    java = '''import java.math.BigDecimal; public class OctalCase {
      public BigDecimal calculate(BigDecimal a, BigDecimal r) {
        if (010 == 8) { return BigDecimal.ONE; } else { return BigDecimal.ZERO; }
      }}'''
    result = prove(FX_COBOL.replace('INPUT-AMOUNT * REFERENCE-RATE','0'), java, RATE)
    assert result['formalProofStatus'] == UNKNOWN
    assert result['proofScope']['reasonCode'] == 'semantics.java_integer_literal'


@pytest.mark.parametrize('literal',['00','010','08','000001'])
def test_leading_zero_integer_literals_rejected(literal):
    java=FX_PATCH.replace('principal.multiply(quote)',f'principal.multiply(new BigDecimal("1")).setScale({literal}, RoundingMode.HALF_UP)')
    assert prove(FX_COBOL,java,RATE)['formalProofStatus'] != UNSAT


def test_unicode_preprocessing_cannot_hide_java_statements():
    java=FX_PATCH.replace('return principal', r'//\u000aif (1 == 1) { return BigDecimal.ONE; } else { return BigDecimal.ZERO; }'+'\nreturn principal')
    assert prove(FX_COBOL,java,RATE)['formalProofStatus'] == UNKNOWN


def test_nested_perform_expansion_has_a_work_budget():
    body=['       MAIN.','           PERFORM P0 THRU P0.','           GOBACK.']
    for i in range(20):
        body += [f'       P{i}.',f'           PERFORM P{i+1} THRU P{i+1}.',f'           PERFORM P{i+1} THRU P{i+1}.']
    body += ['       P20.','           COMPUTE SETTLEMENT-RESULT = 0.']
    started=time.monotonic()
    result=prove(cobol('EXPANSION', '\n'.join(body)),FX_PATCH,RATE)
    assert result['formalProofStatus']==UNKNOWN
    assert result['proofScope']['reasonCode']=='limit.execution_steps'
    assert time.monotonic()-started < 5


def test_complete_grammar_rejects_extra_sentence_punctuation():
    source=FX_COBOL.replace('REFERENCE-RATE.','REFERENCE-RATE..')
    assert prove(source,FX_PATCH,RATE)['formalProofStatus']==UNKNOWN


def test_deep_expressions_halt_before_python_stack_overflow():
    source=FX_PATCH.replace('principal.multiply(quote)', '(' * 100 + 'principal.multiply(quote)' + ')' * 100)
    result=prove(FX_COBOL,source,RATE)
    assert result['formalProofStatus']==UNKNOWN
    assert result['proofScope']['reasonCode']=='limit.ast_nesting'


def test_implicit_cobol_scope_termination_is_not_silently_ignored():
    from ml_engine.fixtures import REMIT_COBOL
    source=REMIT_COBOL.replace('= 1.89 * REFERENCE-RATE\n','= 1.89 * REFERENCE-RATE.\n')
    assert prove(source, REMIT_JAVA, RATE)['formalProofStatus']==UNKNOWN


def test_java_rounding_type_must_be_imported():
    java=FX_PATCH.replace('import java.math.RoundingMode;', '')
    assert prove(FX_COBOL, java, RATE)['formalProofStatus']==UNKNOWN


def test_flat_expression_chains_have_an_ast_depth_budget():
    source=FX_COBOL.replace('INPUT-AMOUNT * REFERENCE-RATE', ' + '.join(['INPUT-AMOUNT'] * 100))
    result=prove(source,FX_PATCH,RATE)
    assert result['formalProofStatus']==UNKNOWN
    assert result['proofScope']['reasonCode']=='limit.ast_nesting'


def test_graph_budget_halts_before_symbolic_expansion():
    with patch('ml_engine.cpg_builder.MAX_GRAPH_NODES', 5), patch('ml_engine.verify.prove', side_effect=AssertionError('must not expand')):
        result=verify_request(demo_requests()[0])
    assert result['formalProofStatus']==UNKNOWN
    assert result['proofScope']['reasonCode']=='limit.graph_nodes'


@pytest.mark.parametrize('java',[FX_JAVA,FX_PATCH,REMIT_JAVA])
def test_real_methods_and_typed_parameters(java):
    graph=build_cpg(java,'java')
    methods=[n for n,a in graph.nodes(data=True) if a['kind']=='method']
    assert len(methods)==1
    assert graph.nodes[methods[0]]['label']=='calculate'
    assert len([n for n,a in graph.nodes(data=True) if a['kind']=='parameter'])==2
    assert graph.graph['semanticExtraction']['status']=='SUPPORTED_AST'


def test_real_paragraphs_and_call_range_edges():
    graph=build_cpg(MORTGAGE_COBOL,'cobol')
    labels={a['label'] for _,a in graph.nodes(data=True) if a['kind']=='paragraph'}
    assert labels=={'MAIN','CALC-TIER','APPLY-PREMIUM','CALC-EXIT'}
    calls={graph.nodes[b]['label'] for a,b,d in graph.edges(data=True) if d['kind']=='CALL'}
    assert calls=={'CALC-TIER','APPLY-PREMIUM','CALC-EXIT'}
    assert any(d['kind']=='WRITES' and d['declaredType']=='COMP-3' for a,b,d in graph.edges(data=True))
    assert any(d['kind']=='READS' and d['decimalScale']==2 for a,b,d in graph.edges(data=True))


def test_no_fabricated_alignment_when_method_missing():
    c=build_cpg(FX_COBOL,'cobol'); j=build_cpg('public class Empty {}','java')
    result=align(c,j)
    assert result['alignmentStatus']=='MISSING_TARGET'
    assert result['alignmentScore']==0 and result['links']==[]


def test_alignment_targets_methods_and_deterministic_types_are_separate():
    c=build_cpg(FX_COBOL,'cobol'); j=build_cpg(FX_JAVA,'java')
    result=align(c,j)
    assert result['alignmentStatus']=='ALIGNED'
    assert all(c.nodes[link['source']]['kind']=='paragraph' and j.nodes[link['target']]['kind']=='method' for link in result['links'])
    assert any(d['code']=='types.fixed_point_to_ieee754' and d['origin']=='deterministic_type_rule' for d in result['diagnostics'])
    wrong=build_cpg(FX_PATCH.replace('principal.multiply(quote)','principal.add(quote)'),'java')
    assert any(d['code']=='logic.operator_difference' for d in deterministic_diagnostics(c,wrong))


def test_engine_report_and_version_are_evidence_grounded():
    result=verify_request(demo_requests()[0])
    report=result['provenanceJson']['reviewReport']
    assert result['provenanceJson']['engineVersion']==ENGINE_VERSION
    assert report['disposition']=='NEEDS_REVIEW' and report['humanReviewStatus']=='PENDING'
    assert report['witnesses']==result['counterexamplesJson']
    assert report['relevantLocations']
    assert result['proofScope']['inputContract']['outputCobolField']=='SETTLEMENT-RESULT'


def test_shared_source_limits_return_protocol_input_errors():
    with pytest.raises(InputValidationError): validate_source('\n' * (MAX_SOURCE_LINES+1),'cobolSource')
    req=demo_requests()[0]; req['cobolSource']='\n'*(MAX_SOURCE_LINES+1)+req['cobolSource']
    result=subprocess.run([sys.executable,'-m','ml_engine.verify','--stdin'],input=json.dumps(req),text=True,capture_output=True)
    assert result.returncode==2 and not result.stdout
    assert json.loads(result.stderr)['code']=='input.too_many_lines'
