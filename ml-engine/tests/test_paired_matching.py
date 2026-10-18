"""Real-pair GNN contract, source isolation and differentiation regression checks."""
from __future__ import annotations
import copy,hashlib,json
from pathlib import Path
import numpy as np
import pytest
from ml_engine.code_graph import build_graph,FEATURE_NAMES
from ml_engine.paired_gnn import (MODEL_PATH,batch_graphs,initialise,forward,backward,encode_source,load_model,model_metadata)
from ml_engine.matching import match_sources

COBOL='''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ADDITION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 LEFT-VALUE PIC S9(6)V9(2).
       01 RIGHT-VALUE PIC S9(6)V9(2).
       01 ANSWER PIC S9(8)V9(2).
       PROCEDURE DIVISION.
           COMPUTE ANSWER = LEFT-VALUE + RIGHT-VALUE.
           GOBACK.
'''
JAVA='''class Solution {
 public double add(double left, double right) {
  double answer = left + right;
  return answer;
 }
}'''
OTHER=JAVA.replace('left + right','left * right')

def request(**overrides):
    return {'cobolSource':COBOL,'candidates':[
        {'candidateId':'one','moduleName':'RenamedOne','javaSource':JAVA},
        {'candidateId':'two','moduleName':'RenamedTwo','javaSource':OTHER}],**overrides}


def test_graph_names_and_comments_are_not_features():
    renamed=JAVA.replace('Solution','UnrelatedClass').replace('add(', 'calculate(').replace('left','alpha').replace('right','beta').replace('answer','gamma')
    renamed='// multiply subtract overflow task/ID should be invisible\n'+renamed
    a=build_graph(JAVA,'java');b=build_graph(renamed,'java')
    np.testing.assert_array_equal(a.x,b.x)
    for relation in a.edges: np.testing.assert_array_equal(a.edges[relation],b.edges[relation])
    np.testing.assert_allclose(encode_source(JAVA,'java'),encode_source(renamed,'java'))


def test_literal_contents_do_not_invent_operations():
    # Same-length literal, completely different words, identical semantic graph.
    left=build_graph('public String f() { return "sort"; }','java')
    right=build_graph('public String f() { return "abcd"; }','java')
    np.testing.assert_array_equal(left.x,right.x)
    assert not left.x[:,FEATURE_NAMES.index('op_sort')].any()


def test_graph_operations_numeric_contracts_and_edges():
    a=build_graph(JAVA,'java');b=build_graph(OTHER,'java')
    assert a.x[:,FEATURE_NAMES.index('op_add')].sum()==1
    assert b.x[:,FEATURE_NAMES.index('op_multiply')].sum()==1
    assert len(a.edges['data']) and len(a.edges['sequence'])
    decimal=build_graph(COBOL,'cobol')
    assert decimal.x[:,FEATURE_NAMES.index('numeric_scale')].max()>0
    assert decimal.x[:,FEATURE_NAMES.index('numeric_signed')].max()==1
    assert a.x[:,FEATURE_NAMES.index('numeric_width')].max()==.5
    branch=build_graph('public int f(int a) {\n if(a>0) {\n return a+1;\n }\n return a;\n}','java')
    assert len(branch.edges['control'])


def test_message_passing_is_actual_learned_differentiable_computation():
    graph=build_graph(JAVA,'java');params=initialise();batch=batch_graphs([graph])
    output,saved=forward(batch,params,True);gradient=np.arange(output.shape[1],dtype=float)[None,:]/20
    grads=backward(gradient,saved,params)
    name='W1_data';index=np.unravel_index(np.argmax(np.abs(grads[name])),grads[name].shape)
    eps=1e-5;original=params[name][index]
    params[name][index]=original+eps;plus=float(np.sum(forward(batch,params)*gradient))
    params[name][index]=original-eps;minus=float(np.sum(forward(batch,params)*gradient))
    params[name][index]=original
    assert abs(grads[name][index])>1e-8
    assert grads[name][index]==pytest.approx((plus-minus)/(2*eps),rel=1e-4,abs=1e-6)
    assert not np.allclose(forward(batch,params),forward(batch_graphs([graph],False),params))


def test_model_provenance_matches_real_training_artifact_and_grouped_splits():
    model=load_model();meta=model_metadata();root=Path(__file__).resolve().parents[1]
    report=json.loads((root/'evaluation/paired-code/training-report.json').read_text())
    split=json.loads((root/'evaluation/paired-code/task-splits.json').read_text())
    partitions=[set(values) for values in split['splits'].values()]
    assert sum(map(len,partitions))==143 and len(set.union(*partitions))==143
    assert not partitions[0]&partitions[1] and not partitions[0]&partitions[2] and not partitions[1]&partitions[2]
    for group in split['groups']:
        assert sum(bool(set(group)&partition) for partition in partitions)==1
    sha=hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    assert meta['sha256']==report['modelSha256']==sha
    assert model['evaluation']['status']=='BENCHMARK_PILOT'
    assert model['training']['datasetSha256']=='ff1b2e308ea006d905fd979103f32486c57d586c5fdbc0325a23f8ae23a6530d'
    assert report['testExposureAudit']['previousRunObserved'] is True
    assert not np.allclose(np.asarray(model['weights']['W1_data']),initialise()['W1_data'])


def test_matching_is_ranked_source_bound_and_not_proof():
    result=match_sources(request())
    assert result['matchingIsProof'] is False and result['granularity']=='PROGRAM'
    assert result['cobolSourceSha256']==hashlib.sha256(COBOL.encode()).hexdigest()
    assert [c['rank'] for c in result['candidates']]==[1,2]
    assert result['candidates'][0]['similarity']>=result['candidates'][1]['similarity']
    assert all(-1<=c['similarity']<=1 for c in result['candidates'])
    sources={'one':JAVA,'two':OTHER}
    for candidate in result['candidates']:
        assert candidate['javaSourceSha256']==hashlib.sha256(sources[candidate['candidateId']].encode()).hexdigest()
    changed=request();changed['candidates'][0]['moduleName']='CompletelyDifferent'
    assert [c['similarity'] for c in result['candidates']]==[c['similarity'] for c in match_sources(changed)['candidates']]
    assert len(match_sources(request(topK=1))['candidates'])==1


def test_singleton_or_insufficient_structure_requires_review():
    r=request();r['candidates']=r['candidates'][:1]
    assert match_sources(r)['status']=='REVIEW_REQUIRED'
    assert match_sources(request(cobolSource='IDENTIFICATION DIVISION.'))['status']=='REVIEW_REQUIRED'

@pytest.mark.parametrize('change',[
    {'cobolSource':''},{'cobolSource':'a'*100001},{'cobolSource':'x\n'*1501},
    {'cobolSourceFormat':'OTHER'},{'topK':True},{'topK':0},{'topK':21}, {'candidates':[]},
    {'candidates':[{'candidateId':'bad/id','moduleName':'x','javaSource':JAVA}]},
    {'candidates':[{'candidateId':'x','moduleName':'../bad','javaSource':JAVA}]},
    {'candidates':[{'candidateId':'x','moduleName':'x','javaSource':JAVA}]*2},
])
def test_invalid_matching_contract_rejected(change):
    with pytest.raises(ValueError): match_sources(request(**change))


@pytest.mark.parametrize('method', ['sort','add','sqrt'])
@pytest.mark.parametrize('modifier', ['', 'static ', 'final '])
def test_package_private_method_names_are_not_features(method,modifier):
    original=f'class X {{ {modifier}int {method}(int value) {{ return value + 1; }} }}'
    renamed=f'class X {{ {modifier}int unrelated(int value) {{ return value + 1; }} }}'
    a=build_graph(original,'java');b=build_graph(renamed,'java')
    np.testing.assert_array_equal(a.x,b.x)
    for relation in a.edges: np.testing.assert_array_equal(a.edges[relation],b.edges[relation])
    np.testing.assert_array_equal(encode_source(original,'java'),encode_source(renamed,'java'))


def test_unqualified_and_this_helper_names_are_not_standard_api_operations():
    for prefix in ('','this.'):
        a=build_graph(f'class X {{ int f(int value) {{ return {prefix}sort(value); }} }}','java')
        b=build_graph(f'class X {{ int f(int value) {{ return {prefix}helper(value); }} }}','java')
        np.testing.assert_array_equal(a.x,b.x)
        for relation in a.edges: np.testing.assert_array_equal(a.edges[relation],b.edges[relation])
        assert not a.x[:,FEATURE_NAMES.index('op_sort')].any()
    # Expression calls must survive declaration masking as known API operations.
    api=build_graph('class X { double f(double x) { return Math.sqrt(x); } }','java')
    assert api.x[:,FEATURE_NAMES.index('op_sqrt')].sum()==1
    assert api.x[:,FEATURE_NAMES.index('op_return')].sum()==1
