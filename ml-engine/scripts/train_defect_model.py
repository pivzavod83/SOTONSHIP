#!/usr/bin/env python3
"""Reproducible grouped-CV synthetic defect pilot; never refit on all 24 pairs.

Default trains and freezes the artifact. --evaluate-frozen-test performs the
separate once-only final assessment, refusing an already existing marker.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ml_engine.defect_features import FEATURE_VERSION, NODE_NAMES,PAIR_NAMES,extract_pair,supervision
from ml_engine.defect_detection import ENGINE_VERSION,graph_prediction,sha256

DATA=ROOT/"evaluation/synthetic-pilot/pilot-10-r3/dataset.json"
PLAN=ROOT/"evaluation/synthetic-pilot/pilot-10-r3/split-plan.json"
OUT=ROOT/"evaluation/synthetic-pilot/defect-model-v1"
MODEL=ROOT/"ml_engine/models/defect_model_v1.json"
FOLDS=[ ["F001","F006"], ["F002","F007"], ["F003","F008"] ]
CS=[0.1,1.0,10.0]
ARCHITECTURES=["graph-and-localizer","localizer-pooling"]
THRESHOLDS=[.25,.5,.75]


def implementation_hashes():
    return {str(path.relative_to(ROOT)):sha256(path.read_bytes()) for path in [Path(__file__).resolve(),ROOT/"ml_engine/defect_features.py",ROOT/"ml_engine/defect_detection.py"]}


def write(path:Path,value:dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n")


def dataset():
    raw=DATA.read_bytes();plan=json.loads(PLAN.read_text())
    if sha256(raw)!=plan["datasetSha256"]:
        raise ValueError("Dataset hash disagrees with frozen split plan")
    return json.loads(raw),plan,sha256(raw)


def spans(items,ids):
    return [(a["startLine"],a["endLine"]) for a in items if a["id"] in ids]


def examples(families):
    result=[]
    for f in families:
        for v in f["variants"]:
            g=extract_pair("\n".join(f["cobolLines"]),"\n".join(v["javaLines"]))
            result.append({"family":f["familyId"],"variant":v["variantId"],"label":int(not v["expectedEquivalent"]),"graph":g,
                           "line_y":supervision(g,spans(f["cobolSegments"],v["defectCobolSegmentIds"]),spans(v["javaSegments"],v["defectJavaSegmentIds"]))})
    return result


def fit_linear(x,y,c):
    scaler=StandardScaler().fit(x)
    model=LogisticRegression(C=c,class_weight="balanced",max_iter=3000,random_state=42).fit(scaler.transform(x),y)
    return {"mean":scaler.mean_.tolist(),"scale":scaler.scale_.tolist(),"coef":model.coef_[0].tolist(),"intercept":float(model.intercept_[0])}


def fit_fold(rows,c,architecture):
    from ml_engine.defect_detection import linear_probability,classifier_features
    lx=np.concatenate([r["graph"].candidate_x for r in rows]);ly=np.concatenate([r["line_y"] for r in rows])
    loc=fit_linear(lx,ly,c)
    px=[]
    for r in rows:
        local=linear_probability(r["graph"].candidate_x,loc)
        px.append(classifier_features(r["graph"],local,architecture))
    return {"localizer":loc,"classifier":fit_linear(np.array(px),[r["label"] for r in rows],c),"classifierInput":architecture}


def metrics(rows,scores,threshold):
    labels=np.array([r["label"] for r in rows]);pred=np.asarray(scores)>=threshold
    tp=int(((labels==1)&pred).sum());tn=int(((labels==0)&~pred).sum());fp=int(((labels==0)&pred).sum());fn=int(((labels==1)&~pred).sum())
    precision=tp/max(tp+fp,1);recall=tp/max(tp+fn,1)
    return {"pairs":len(rows),"correct":tp+tn,"accuracy":(tp+tn)/len(rows),"precision":precision,"recall":recall,"f1":2*precision*recall/max(precision+recall,1e-12),"balancedAccuracy":.5*(tp/max(tp+fn,1)+tn/max(tn+fp,1)),"confusion":{"truePositive":tp,"trueNegative":tn,"falsePositive":fp,"falseNegative":fn}}


def assess(rows,artifact):
    scores=[];details=[];hits1=hits3=eligible=0
    for r in rows:
        score,local=graph_prediction(r["graph"],artifact)
        scores.append(score)
        ranking=np.argsort(-local,kind="stable")
        if r["label"]:
            eligible+=1
            hits1+=int(r["line_y"][ranking[0]]==1)
            hits3+=int(any(r["line_y"][i]==1 for i in ranking[:3]))
        top=[]
        for i in ranking[:3]:
            ci,ji=r["graph"].candidates[int(i)]
            top.append({"cobolLine":r["graph"].cobol[ci].start if ci is not None else None,"javaLine":r["graph"].java[ji].start if ji is not None else None,"score":float(local[i]),"matchesWeakAnnotation":bool(r["line_y"][i])})
        details.append({"familyId":r["family"],"variantId":r["variant"],"defectLabel":r["label"],"score":score,"predictedDefect":score>=artifact["threshold"],"topLocations":top})
    per={}
    for family in sorted(set(r["family"] for r in rows)):
        idx=[i for i,r in enumerate(rows) if r["family"]==family]
        per[family]=metrics([rows[i] for i in idx],[scores[i] for i in idx],artifact["threshold"])
    return {**metrics(rows,scores,artifact["threshold"]),"perFamily":per,"localization":{"scope":"All labelled defective pairs, including missed classifications; AI-generated weak span annotations, exploratory only","defectivePairs":eligible,"hitAt1Count":hits1,"hitAt1":hits1/max(eligible,1),"hitAt3Count":hits3,"hitAt3":hits3/max(eligible,1)},"predictions":details}


def train():
    if (OUT/"final-test-evaluation.json").exists():
        raise ValueError("Final test was already assessed. Use a new version and disclose test reuse; cannot retrain this version.")
    data,plan,data_hash=dataset()
    train_families=[f for f in data["families"] if f["split"]=="train"]
    validation_families=[f for f in data["families"] if f["split"]=="validation"]
    if set(f["familyId"] for f in train_families)!=set(sum(FOLDS,[])):
        raise ValueError("Training assignments disagree with predeclared folds")
    protocol={"engineVersion":ENGINE_VERSION,"datasetSha256":data_hash,"splitPlanSha256":sha256(PLAN.read_bytes()),"trainingFamilies":plan["assignments"]["train"],"validationFamilies":plan["assignments"]["validation"],"finalTestFamilies":plan["assignments"]["test"],"foldHeldOutFamilies":FOLDS,"candidates":[{"C":c,"architecture":a,"classifier":"balanced L2 logistic regression","localizer":"balanced L2 logistic regression"} for a in ARCHITECTURES for c in CS],"candidateSelection":"Highest grouped OOF balanced accuracy at 0.5, then F1, then smaller C; exact ties prefer fewer classifier features","thresholdSelection":"Validation balanced accuracy, then F1, then closest to 0.5; coarse predeclared thresholds only","thresholdCandidates":THRESHOLDS,"pretestExploration":"Initial graph-only experiment and unrestricted threshold results are preserved in pretest-exploration-initial. Compact learned pooling and coarse thresholds were added before any final test assessment. Validation was inspected during this development and is not a blind estimate.","deployment":"Mean probability of three fold checkpoints; no full-training refit","features":"Source-only heuristic statement graphs with def/use edges, operator/type/storage/rounding comparisons; no labels, IDs, test outcomes, provided alignments, rationale or variant order","localizationSupervision":"Training-only synthetic defect segment annotations; candidate correspondence source-derived","testPolicy":"Freeze artifact and SHA256 first; separate explicit command; final-test marker refuses repeated assessment","baseline":"Constant no-defect and training-only selected source graph distance threshold","dataQualityDisclosure":plan["inspectionDisclosure"],"createdUtc":datetime.now(timezone.utc).isoformat(),"sklearnVersion":sklearn.__version__,"numpyVersion":np.__version__}
    write(OUT/"protocol.json",protocol)
    tr=examples(train_families);va=examples(validation_families)
    candidates=[]
    for architecture,c in [(a,c) for a in ARCHITECTURES for c in CS]:
        scores=[None]*len(tr);loc_hits=0;folds=[]
        for held in FOLDS:
            fitting=[r for r in tr if r["family"] not in held];fold=fit_fold(fitting,c,architecture)
            fold["trainingFamilies"]=sorted(set(r["family"] for r in fitting));fold["heldOutFamilies"]=held
            folds.append(fold)
            for i,r in enumerate(tr):
                if r["family"] in held:
                    score,local=graph_prediction(r["graph"],{"foldModels":[fold]})
                    scores[i]=score
                    if r["label"]:loc_hits+=int(r["line_y"][np.argmax(local)]==1)
        result=metrics(tr,scores,.5)
        candidates.append({"C":c,"architecture":architecture,"metrics":result,"oofPredictions":[{"familyId":r["family"],"variantId":r["variant"],"label":r["label"],"score":float(p)} for r,p in zip(tr,scores)],"oofLocalizationHitAt1":{"hits":loc_hits,"defectivePairs":12},"foldModels":folds})
        print(f"{architecture} C={c}: grouped OOF accuracy={result['accuracy']:.3f} F1={result['f1']:.3f}",flush=True)
    chosen=max(candidates,key=lambda a:(a["metrics"]["balancedAccuracy"],a["metrics"]["f1"],-a["C"],a["architecture"]=="localizer-pooling"))
    artifact={"engineVersion":ENGINE_VERSION,"featureVersion":FEATURE_VERSION,"name":"Synthetic graph-feature defect ensemble v1","datasetSha256":data_hash,"implementationHashes":implementation_hashes(),"trainingFamilyCount":6,"foldModels":chosen["foldModels"],"selectedC":chosen["C"],"selectedArchitecture":chosen["architecture"],"threshold":.5,"runtimeDependencies":["numpy"],"architecture":"Heuristic source statement/dependency graph features + trained regularized logistic classifiers and span rankers; not a trained GNN","refitOnAllTrainingFamilies":False,"createdUtc":datetime.now(timezone.utc).isoformat(),"nodeFeatureNames":NODE_NAMES,"candidateFeatureNames":PAIR_NAMES}
    val_scores=[graph_prediction(r["graph"],artifact)[0] for r in va]
    thresholds=THRESHOLDS
    selected=max(thresholds,key=lambda t:(metrics(va,val_scores,t)["balancedAccuracy"],metrics(va,val_scores,t)["f1"],-abs(t-.5)))
    artifact["threshold"]=float(selected)
    val=assess(va,artifact)
    artifact["evaluation"]={"scope":"Synthetic pilot; validation used for threshold selection; test results in frozen external report","groupedOof":chosen["metrics"],"validation":{k:v for k,v in val.items() if k not in ("predictions",)},"testReportPath":"evaluation/synthetic-pilot/defect-model-v1/final-test-evaluation.json"}
    write(MODEL,artifact)
    write(OUT/"candidate-selection.json",{"selectedC":chosen["C"],"selectedArchitecture":chosen["architecture"],"selectionUsedFinalTest":False,"candidates":[{k:v for k,v in item.items() if k!="foldModels"} for item in candidates]})
    write(OUT/"validation-evaluation.json",val)
    for i,fold in enumerate(artifact["foldModels"]):write(OUT/f"fold-{i+1}.json",fold)
    # A descriptive source graph distance baseline threshold is chosen using
    # training labels only, then kept fixed on validation and final testing.
    def distance(r):
        g=r["graph"];return float(abs(np.array([n.x for n in g.cobol]).mean(0)-np.array([n.x for n in g.java]).mean(0)).mean())
    td=[distance(r) for r in tr]
    bt=max(sorted(set(td)),key=lambda t:(metrics(tr,td,t)["balancedAccuracy"],-t))
    write(OUT/"baseline-settings.json",{"graphDistanceThreshold":bt,"selectionSplit":"train","training":metrics(tr,td,bt),"validation":metrics(va,[distance(r) for r in va],bt),"definition":"Mean absolute distance between mean statement feature vectors"})
    write(OUT/"frozen-artifact.json",{"modelPath":str(MODEL.relative_to(ROOT)),"sha256":sha256(MODEL.read_bytes()),"implementationHashes":implementation_hashes(),"datasetSha256":data_hash,"threshold":artifact["threshold"],"selectedC":chosen["C"],"frozenBeforeFinalTest":True,"createdUtc":datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"selectedC":chosen["C"],"threshold":selected,"validation":{k:v for k,v in val.items() if k not in ("predictions","perFamily")},"modelSha256":sha256(MODEL.read_bytes()),"finalTestAssessed":False},indent=2))


def evaluate_frozen_test():
    marker=OUT/"final-test-evaluation.json"
    if marker.exists():raise ValueError("Final test has already been assessed; repeated evaluation is refused")
    data,plan,data_hash=dataset();frozen=json.loads((OUT/"frozen-artifact.json").read_text());raw=MODEL.read_bytes()
    if sha256(raw)!=frozen["sha256"] or data_hash!=frozen["datasetSha256"]:raise ValueError("Frozen model/data hash changed")
    if implementation_hashes()!=frozen["implementationHashes"]:raise ValueError("Frozen feature/inference/training implementation changed")
    # Claim the once-only assessment before reading final-test examples. A crash
    # is recorded as attempted rather than silently permitting adaptive retries.
    with marker.open("x") as f:json.dump({"status":"STARTED","modelSha256":sha256(raw),"createdUtc":datetime.now(timezone.utc).isoformat()},f)
    artifact=json.loads(raw);te=examples([f for f in data["families"] if f["split"]=="test"])
    result=assess(te,artifact)
    baseline=json.loads((OUT/"baseline-settings.json").read_text())
    distances=[float(abs(np.array([n.x for n in r["graph"].cobol]).mean(0)-np.array([n.x for n in r["graph"].java]).mean(0)).mean()) for r in te]
    result.update({"status":"COMPLETED","modelSha256":sha256(raw),"datasetSha256":data_hash,"threshold":artifact["threshold"],"modelFrozenBeforeAssessment":True,"modelChangedAfterAssessment":False,"testPairs":8,"testFamilies":plan["assignments"]["test"],"baseline":{"constantNoDefect":metrics(te,[0]*len(te),.5),"sourceGraphDistance":metrics(te,distances,baseline["graphDistanceThreshold"])},"limitations":["Only two independent synthetic test algorithm families (8 pairs); no real-world accuracy claim.",plan["inspectionDisclosure"],"Defect witnesses are finite runtime evidence; intended-equivalent labels are not general equivalence proofs.","Span metrics use AI-generated weak annotations and are exploratory, not expert-reviewed localisation accuracy."],"completedUtc":datetime.now(timezone.utc).isoformat()})
    write(marker,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ("predictions",)},indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--evaluate-frozen-test",action="store_true");args=p.parse_args()
    evaluate_frozen_test() if args.evaluate_frozen_test else train()
