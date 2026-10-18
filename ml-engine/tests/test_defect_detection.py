import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from ml_engine.defect_detection import analyze,model_status,load_artifact,linear_probability
from ml_engine.defect_features import NODE_NAMES,PAIR_NAMES,extract_pair,statements,supervision

ROOT=Path(__file__).resolve().parents[1]
COBOL="""IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 MID-BAL PIC 9(5).
01 END-BAL PIC S9(6).
PROCEDURE DIVISION.
COMPUTE MID-BAL = START-BAL + ADJ-AMT
COMPUTE END-BAL = MID-BAL - FEE-AMT
STOP RUN."""
JAVA="""public class Program {
public static void main(String[] args) {
BigDecimal midBal = startBal.add(adjAmt).abs();
BigDecimal endBal = midBal.subtract(feeAmt).abs();
}
}"""


def test_graph_numeric_fields_and_keyword_operators():
    c=statements(COBOL,"cobol")
    assert c[0].x[NODE_NAMES.index("unsigned")]==1
    assert c[1].x[NODE_NAMES.index("signed")]==1
    nodes=statements("01 VALUE-A PIC 9(4).\nADD 1 TO VALUE-A\nSUBTRACT 2 FROM VALUE-A\nDIVIDE VALUE-A BY 2 GIVING VALUE-A\nIF VALUE-A < 0\nMOVE 0 TO VALUE-A","cobol")
    for node,op in zip(nodes,["add","subtract","divide","branch","assign"]):
        assert node.x[NODE_NAMES.index(op)]==1


def test_constant_statements_and_integral_division_remain_localizable():
    nodes=statements('long step = 10L;\nBigDecimal quotient = value.divideToIntegralValue(step);',"java")
    assert len(nodes)==2
    assert nodes[0].start==1
    assert nodes[1].x[NODE_NAMES.index("divide")]==1


def test_source_only_features_are_deterministic_and_comments_preserve_lines():
    a=extract_pair(COBOL,JAVA)
    b=extract_pair(COBOL.replace("PROGRAM-ID. TEST.","PROGRAM-ID. OTHER."),JAVA.replace("public class Program","public class Other"))
    np.testing.assert_array_equal(a.global_x,b.global_x)
    np.testing.assert_array_equal(a.candidate_x,b.candidate_x)
    assert a.candidate_x.shape[1]==len(PAIR_NAMES)
    assert all(n.start>0 for n in a.cobol+a.java)
    j=statements('// ignored\n/* multi\nline */\nlong x = y + z;',"java")
    assert j[0].start==4


def test_one_sided_training_supervision():
    g=extract_pair(COBOL,JAVA)
    labels=supervision(g,[(8,8)],[])
    selected=[p for p,y in zip(g.candidates,labels) if y]
    assert selected and all(j is None for c,j in selected)
    labels=supervision(g,[],[(4,4)])
    selected=[p for p,y in zip(g.candidates,labels) if y]
    assert selected and all(c is None for c,j in selected)


def test_missing_artifact_and_unsupported_have_valid_envelope(tmp_path):
    p={"cobolSource":COBOL,"javaSource":JAVA}
    result=analyze(p,tmp_path/"missing.json")
    assert result["status"]=="NOT_CONFIGURED"
    assert result["risk"]["decision"]=="NO_DEFECT_SIGNAL"
    assert result["findings"]==[]
    assert not model_status(tmp_path/"missing.json")["configured"]
    result=analyze({"cobolSource":"hello","javaSource":"world"})
    assert result["status"]=="UNSUPPORTED"
    assert not result["aiIsProof"] and not result["counterexamplesExecuted"]


def test_trained_artifact_is_three_distinct_grouped_checkpoints():
    artifact,_=load_artifact()
    assert not artifact["refitOnAllTrainingFamilies"]
    assert len(artifact["foldModels"])==3
    all_held=[]
    for fold in artifact["foldModels"]:
        assert not set(fold["trainingFamilies"])&set(fold["heldOutFamilies"])
        assert len(fold["trainingFamilies"])==4
        all_held+=fold["heldOutFamilies"]
        for head in ["classifier","localizer"]:
            assert np.isfinite(fold[head]["coef"]).all()
            assert np.linalg.norm(fold[head]["coef"])>0
    assert len(set(all_held))==6


def test_trained_demo_predicts_from_source_and_spans_are_raw_source_bound():
    # This is explicitly a training example, not a held-out accuracy test.
    dataset=json.loads((ROOT/"evaluation/synthetic-pilot/pilot-10-r3/dataset.json").read_text())
    f=next(f for f in dataset["families"] if f["familyId"]=="F006")
    v=next(v for v in f["variants"] if v["variantId"]=="F006-V4")
    cobol="\n".join(f["cobolLines"]);java="\n".join(v["javaLines"])
    result=analyze({"cobolSource":cobol,"javaSource":java,"moduleName":"anything"})
    assert result["status"]=="ANALYZED"
    assert result["risk"]["decision"]=="REVIEW_REQUIRED"
    assert result["findings"][0]["javaLines"]=={"start":10,"end":10}
    assert result["findings"][0]["cobolLines"]=={"start":23,"end":23}
    for i,finding in enumerate(result["findings"],1):
        assert finding["findingId"]==f"F{i}"
        assert finding["evidenceStatus"]=="MODEL_HYPOTHESIS"
        for language,source in [("cobol",cobol),("java",java)]:
            span=finding[language+"Lines"]
            if span:
                assert finding[language+"Excerpt"]=="\n".join(source.split("\n")[span["start"]-1:span["end"]])
    assert result["sourceHashes"]["java"]==hashlib.sha256(java.encode()).hexdigest()
    repeated=analyze({"cobolSource":cobol,"javaSource":java,"moduleName":"F005-V1"})
    assert repeated["risk"]==result["risk"] and repeated["findings"]==result["findings"]
    crlf=analyze({"cobolSource":cobol.replace("\n","\r\n"),"javaSource":java.replace("\n","\r\n")})
    assert crlf["sourceHashes"]!=result["sourceHashes"]
    assert crlf["risk"]==result["risk"]
    assert crlf["findings"][0]["javaExcerpt"].endswith("\r")


def test_cli_status_and_rejection():
    completed=subprocess.run([sys.executable,"-m","ml_engine.defect_detection","--stdin"],input='{"action":"status"}',text=True,capture_output=True,cwd=ROOT)
    assert completed.returncode==0
    assert json.loads(completed.stdout)["configured"]
    completed=subprocess.run([sys.executable,"-m","ml_engine.defect_detection","--stdin"],input='[]',text=True,capture_output=True,cwd=ROOT)
    assert completed.returncode==2
    assert "JSON object" in completed.stderr


def test_source_limits_and_input_validation():
    with pytest.raises(ValueError,match="200000"):
        analyze({"cobolSource":"ü"*100001,"javaSource":JAVA})
    with pytest.raises(ValueError,match="FREE or FIXED"):
        analyze({"cobolSource":COBOL,"javaSource":JAVA,"cobolSourceFormat":"AUTO"})
    with pytest.raises(ValueError,match="Nonempty"):
        analyze({"cobolSource":"","javaSource":JAVA})
