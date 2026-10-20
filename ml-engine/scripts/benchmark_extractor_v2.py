#!/usr/bin/env python3
"""Fixed exploratory benchmark for the typed v2 representation, never deployment.

Prepare the protocol, train/freeze once, then explicitly assess the already-known
eight-pair regression split once. No supplied program is compiled or executed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "evaluation/synthetic-pilot/pilot-10-r3/dataset.json"
PLAN = ROOT / "evaluation/synthetic-pilot/pilot-10-r3/split-plan.json"
DEFAULT_OUTPUT = ROOT / "evaluation/extractor-v2/pilot-r1"
V1_REPORT = ROOT / "evaluation/synthetic-pilot/defect-model-v1/final-test-evaluation.json"
CONTRACT_FIXTURES = ROOT / "evaluation/extractor-v2/contract-fixtures.json"
FOLDS = (("F001", "F006"), ("F002", "F007"), ("F003", "F008"))
REGULARIZATION_C = 0.1
THRESHOLD = 0.25
PROTOCOL_VERSION = "extractor-v2-fixed-pilot-r1"
ARMS = ("v1-refit-control", "typed-v2")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dataset() -> tuple[dict, dict]:
    plan = read(PLAN)
    if digest(DATA) != plan["datasetSha256"]:
        raise ValueError("Dataset does not match the existing split plan")
    data = read(DATA)
    actual = {split: sorted(f["familyId"] for f in data["families"] if f["split"] == split)
              for split in ("train", "validation", "test")}
    if actual != {key: sorted(value) for key, value in plan["assignments"].items()}:
        raise ValueError("Family assignments disagree with the split plan")
    if actual["train"] != sorted(family for fold in FOLDS for family in fold):
        raise ValueError("Predeclared outer folds disagree with training families")
    return data, plan


def protocol() -> dict:
    _, plan = dataset()
    return {
        "protocolVersion": PROTOCOL_VERSION, "datasetSha256": digest(DATA), "splitPlanSha256": digest(PLAN),
        "contractFixturesSha256": digest(CONTRACT_FIXTURES), "historicalV1ReportSha256": digest(V1_REPORT),
        "arms": {"v1-refit-control": "Original heuristic extractor, newly fitted under this identical benchmark protocol; no strict parse-coverage guarantee",
                 "typed-v2": "Typed v2 extractor; incomplete or unsupported parsing always abstains"},
        "assignments": plan["assignments"], "outerHeldOutFamilies": FOLDS,
        "model": {"ranker": "L2 logistic regression", "classifier": "L2 logistic regression",
                  "C": REGULARIZATION_C, "classWeight": "balanced", "randomState": 42,
                  "maxIterations": 3000, "scaling": "StandardScaler fitted separately within each fitting partition"},
        "classifierInputs": "Each arm's source-only global features + ranker max, top-three mean, mean and standard deviation",
        "stacking": "Inner leave-one-fitting-family-out rankers produce every classifier training row. Each outer ranker is then fitted on only its four fitting families.",
        "operatingThreshold": THRESHOLD, "thresholdSelection": "FIXED_BEFORE_V2_RESULTS; no threshold or architecture search",
        "abstention": "Every graph.status != SUPPORTED is excluded from fitting and always requires human review. No low-risk fallback.",
        "deployment": "Benchmark-only mean of three fold checkpoints; no full-training refit; existing deployed models unchanged",
        "safetyAuthority": {"aiIsProof": False, "canApproveCode": False, "canAuthorizePatch": False},
        "validationPolicy": "Fixed-setting diagnostic only; not used to choose settings",
        "testPolicy": "ALREADY_KNOWN_REUSED_REGRESSION_SPLIT; eight pairs/two families previously assessed by v1 and inspected during representation design, not a pristine final holdout",
        "baselines": ["constant no defect", "constant all review", "frozen v1 stored final report; no rerun of its evaluation"],
        "localizationLabels": "AI-generated weak segment annotations, never expert-reviewed ground truth",
        "independenceUnit": "Whole source family; statements and variants are correlated, not additional independent samples",
        "measurement": "Report covered-only classifier metrics separately from review triage including abstentions, workload, coverage and per-family counts",
        "limitations": ["Only six fitting families and two reused test families.",
                        "Always reviewing every pair trivially gives full defect-review recall; that alone establishes no useful detector.",
                        "Passing finite tests does not prove an intended-equivalent label.",
                        "Representation contract fixtures are source-only diagnostics, not additional accuracy data."],
    }


def prepare(output: Path) -> None:
    write_new(output / "protocol.json", protocol())
    print(json.dumps({"status": "PREPARED", "path": str(output), "trainingPerformed": False}))


def spans(items: list[dict], identifiers: list[str]) -> list[tuple[int, int]]:
    return [(item["startLine"], item["endLine"]) for item in items if item["id"] in identifiers]


def examples(families: list[dict], arm: str = "typed-v2") -> list[dict]:
    if arm == "typed-v2":
        from ml_engine.defect_features_v2 import extract_pair, supervision
    elif arm == "v1-refit-control":
        from ml_engine.defect_features import extract_pair, supervision
    else:
        raise ValueError("Unknown benchmark arm")
    rows = []
    for family in families:
        for variant in family["variants"]:
            graph = extract_pair("\n".join(family["cobolLines"]), "\n".join(variant["javaLines"]), "FREE")
            covered = arm == "v1-refit-control" or graph.status == "SUPPORTED"
            if arm == "v1-refit-control":
                # v1 can produce numbers while silently dropping unsupported code.
                # Numeric availability is explicitly not a strict coverage claim.
                graph.coverage = {"strictCoverageProvided": False, "status": "UNCHECKED_HEURISTIC"}
            if covered:
                if (graph.candidate_x.ndim != 2 or graph.global_x.ndim != 1 or not len(graph.candidates)
                        or len(graph.candidate_x) != len(graph.candidates)
                        or not np.isfinite(graph.candidate_x).all() or not np.isfinite(graph.global_x).all()):
                    raise ValueError("SUPPORTED graph has invalid feature arrays")
                line_labels = supervision(graph, spans(family["cobolSegments"], variant["defectCobolSegmentIds"]),
                                          spans(variant["javaSegments"], variant["defectJavaSegmentIds"]))
            else:
                line_labels = np.empty(0, dtype=int)
            rows.append({"family": family["familyId"], "variant": variant["variantId"],
                         "label": int(not variant["expectedEquivalent"]), "graph": graph,
                         "covered": covered, "line_y": line_labels})
    return rows


def fit_linear(x: np.ndarray, y: np.ndarray) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    if set(np.asarray(y).tolist()) != {0, 1}:
        raise ValueError("A fitting partition lacks both labels; no constant or low-risk fallback is permitted")
    scaler = StandardScaler().fit(x)
    model = LogisticRegression(C=REGULARIZATION_C, class_weight="balanced", max_iter=3000,
                               random_state=42).fit(scaler.transform(x), y)
    return {"mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
            "coef": model.coef_[0].tolist(), "intercept": float(model.intercept_[0]), "classes": [0, 1]}


def linear_score(x: np.ndarray, model: dict) -> np.ndarray:
    z = ((np.asarray(x) - model["mean"]) / model["scale"]) @ np.asarray(model["coef"]) + model["intercept"]
    return 1.0 / (1.0 + np.exp(-np.clip(z, -40, 40)))


def classifier_features(graph: Any, local_scores: np.ndarray) -> np.ndarray:
    if not len(local_scores):
        raise ValueError("No localization candidates for a supported graph")
    return np.r_[graph.global_x, float(local_scores.max()), float(np.sort(local_scores)[-3:].mean()),
                 float(local_scores.mean()), float(local_scores.std())]


def fit_ranker(rows: list[dict]) -> dict:
    covered = [row for row in rows if row["covered"]]
    if not covered:
        raise ValueError("No covered rows remain in the ranker fitting partition")
    return fit_linear(np.concatenate([row["graph"].candidate_x for row in covered]),
                      np.concatenate([row["line_y"] for row in covered]))


def fit_fold(rows: list[dict], held_out: tuple[str, ...]) -> dict:
    fitting = [row for row in rows if row["family"] not in held_out]
    families = sorted({row["family"] for row in fitting})
    classifier_x, classifier_y, crossfit_records = [], [], []
    for inner_held in families:
        inner_train = [row for row in fitting if row["family"] != inner_held]
        ranker = fit_ranker(inner_train)
        inner_rows = [row for row in fitting if row["family"] == inner_held and row["covered"]]
        for row in inner_rows:
            local = linear_score(row["graph"].candidate_x, ranker)
            classifier_x.append(classifier_features(row["graph"], local))
            classifier_y.append(row["label"])
        crossfit_records.append({"heldOutFamily": inner_held,
                                 "fittingFamilies": sorted({row["family"] for row in inner_train}),
                                 "coveredFittingFamilies": sorted({row["family"] for row in inner_train if row["covered"]}),
                                 "coveredFittingPairs": sum(row["covered"] for row in inner_train),
                                 "coveredClassifierRows": len(inner_rows)})
    if not classifier_x:
        raise ValueError("No covered rows remain for the pair classifier")
    return {"fittingFamilies": families, "heldOutFamilies": list(held_out),
            "coveredFittingFamilies": sorted({row["family"] for row in fitting if row["covered"]}),
            "fittingFamilyCoverage": {family: {"coveredPairs": sum(row["covered"] for row in fitting if row["family"] == family),
                                               "abstainedPairs": sum(not row["covered"] for row in fitting if row["family"] == family)} for family in families},
            "coveredFittingPairs": sum(row["covered"] for row in fitting),
            "innerCrossfit": crossfit_records, "ranker": fit_ranker(fitting),
            "classifier": fit_linear(np.array(classifier_x), np.array(classifier_y))}


def predict(row: dict, members: list[dict]) -> dict:
    if not row["covered"]:
        return {"score": None, "decision": "REVIEW_REQUIRED", "abstained": True, "lineScores": None}
    pair_scores, locations = [], []
    for member in members:
        local = linear_score(row["graph"].candidate_x, member["ranker"])
        pair_scores.append(float(linear_score(classifier_features(row["graph"], local), member["classifier"])))
        locations.append(local)
    score = float(np.mean(pair_scores))
    return {"score": score, "decision": "REVIEW_REQUIRED" if score >= THRESHOLD else "NO_DEFECT_SIGNAL",
            "abstained": False, "lineScores": np.mean(locations, axis=0)}


def classification_metrics(labels: list[int], predictions: list[bool]) -> dict:
    if len(labels) != len(predictions):
        raise ValueError("Metric labels and decisions have different lengths")
    tp = sum(y == 1 and p for y, p in zip(labels, predictions))
    tn = sum(y == 0 and not p for y, p in zip(labels, predictions))
    fp = sum(y == 0 and p for y, p in zip(labels, predictions))
    fn = sum(y == 1 and not p for y, p in zip(labels, predictions))
    precision, recall = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    return {"pairs": len(labels), "accuracy": (tp + tn) / len(labels) if labels else None,
            "precision": precision, "recall": recall, "f1": 2 * precision * recall / max(precision + recall, 1e-12),
            "confusion": {"truePositive": tp, "trueNegative": tn, "falsePositive": fp, "falseNegative": fn},
            "reviewedPairs": tp + fp, "reviewWorkloadFraction": (tp + fp) / len(labels) if labels else None,
            "nonFlaggedPairs": tn + fn, "nonFlaggedDefects": fn, "autonomousAcceptances": 0}


def summarize(rows: list[dict], predictions: list[dict], arm: str = "typed-v2") -> dict:
    labels = [row["label"] for row in rows]
    reviewed = [prediction["decision"] == "REVIEW_REQUIRED" for prediction in predictions]
    covered = [i for i, prediction in enumerate(predictions) if not prediction["abstained"]]
    details, hit1, hit3, defective = [], 0, 0, sum(labels)
    for row, prediction in zip(rows, predictions):
        ranked = []
        if prediction["lineScores"] is not None:
            order = np.argsort(-prediction["lineScores"], kind="stable")
            if row["label"]:
                hit1 += int(bool(row["line_y"][order[0]]))
                hit3 += int(any(row["line_y"][index] for index in order[:3]))
            for index in order[:3]:
                ci, ji = row["graph"].candidates[int(index)]
                ranked.append({"cobolLines": None if ci is None else {"start": row["graph"].cobol[ci].start, "end": row["graph"].cobol[ci].end},
                               "javaLines": None if ji is None else {"start": row["graph"].java[ji].start, "end": row["graph"].java[ji].end},
                               "score": float(prediction["lineScores"][index]), "matchesWeakAnnotation": bool(row["line_y"][index])})
        details.append({"familyId": row["family"], "variantId": row["variant"], "defectLabel": row["label"],
                        "score": prediction["score"], "decision": prediction["decision"], "abstained": prediction["abstained"],
                        "parseCoverage": row["graph"].coverage, "topLocations": ranked})
    return {"reviewTriageIncludingAbstentions": classification_metrics(labels, reviewed),
            "coveredClassifierOnly": classification_metrics([labels[i] for i in covered], [reviewed[i] for i in covered]),
            "coverage": {"pairs": len(rows), "supportedPairs": len(covered) if arm == "typed-v2" else None,
                         "computedPairs": len(covered), "strictCoverageProvided": arm == "typed-v2", "abstainedPairs": len(rows) - len(covered),
                         "fraction": len(covered) / len(rows) if rows else None},
            "localizationWeakLabels": {"defectivePairs": defective, "hitAt1Count": hit1, "hitAt3Count": hit3,
                                       "hitAt1": hit1 / max(defective, 1), "hitAt3": hit3 / max(defective, 1),
                                       "scope": "All labelled defective pairs, including abstentions and missed classifications; exploratory AI-generated span labels"},
            "perFamily": {family: {"reviewTriageIncludingAbstentions": classification_metrics(
                [row["label"] for row in rows if row["family"] == family],
                [prediction["decision"] == "REVIEW_REQUIRED" for row, prediction in zip(rows, predictions) if row["family"] == family]),
                "computedPairs": sum(row["covered"] for row in rows if row["family"] == family)}
                for family in sorted({row["family"] for row in rows})},
            "constantBaselines": {"alwaysNoDefect": classification_metrics(labels, [False] * len(rows)),
                                  "alwaysReview": classification_metrics(labels, [True] * len(rows))},
            "predictions": details, "aiIsProof": False, "acceptanceAuthority": False}


def implementation_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): digest(path) for path in
            (Path(__file__).resolve(), ROOT / "ml_engine/defect_features.py", ROOT / "ml_engine/defect_features_v2.py",
             ROOT / "ml_engine/semantic_ir.py", ROOT / "ml_engine/java_extractor_v2.py",
             ROOT / "ml_engine/cobol_extractor_v2.py", CONTRACT_FIXTURES)}


def contract_diagnostics() -> dict:
    from ml_engine.defect_features import extract_pair as v1
    from ml_engine.defect_features_v2 import extract_pair as v2
    fixtures = read(CONTRACT_FIXTURES)
    results = []
    def same_arrays(a, b):
        return (a.global_x.shape == b.global_x.shape and a.candidate_x.shape == b.candidate_x.shape
                and np.array_equal(a.global_x, b.global_x) and np.array_equal(a.candidate_x, b.candidate_x))
    for fixture in fixtures["fixtures"]:
        cobol, a, b = fixtures["cobolSource"], fixture["javaA"], fixture["javaB"]
        old_a, old_b, new_a, new_b = v1(cobol, a), v1(cobol, b), v2(cobol, a), v2(cobol, b)
        ir_a, ir_b = new_a.java_ir, new_b.java_ir
        equivalent_structure = bool(ir_a and ir_b and ir_a.fingerprint(ignore_names=True) == ir_b.fingerprint(ignore_names=True))
        complete = new_a.status == new_b.status == "SUPPORTED"
        property_name = fixture["property"]
        tracked = None
        if property_name == "REASSIGNMENT_TRACKED":
            symbol = next((value for name, value in ir_a.symbols.items()
                           if name.split("::")[-1].split("#")[0] == "result"), {}) if ir_a else {}
            latest = symbol.get("latest")
            returns = [node for node in ir_a.nodes if node.op.lower() == "return"] if ir_a else []
            reads = {node.id: node for node in ir_a.nodes if node.op.lower() == "read"} if ir_a else {}
            tracked = bool(symbol.get("version", 0) >= 2 and symbol.get("constant") is None
                           and any(any(value in reads and latest in reads[value].inputs for value in node.inputs) for node in returns))
        passed = ((complete and not equivalent_structure) if property_name == "IR_DIFFERENT" else
                  (complete and equivalent_structure) if property_name == "IR_SAME" else
                  (new_b.status == "ABSTAIN") if property_name == "ABSTAIN_SECOND" else bool(complete and tracked))
        results.append({"fixtureId": fixture["fixtureId"], "property": property_name, "passed": passed,
                        "v1NumericFeaturesIdentical": same_arrays(old_a, old_b), "v2NumericFeaturesIdentical": same_arrays(new_a, new_b),
                        "v2StructuralFingerprintsIdentical": equivalent_structure, "v2Statuses": [new_a.status, new_b.status],
                        "reassignmentTracked": tracked, "v2Coverage": [new_a.coverage, new_b.coverage]})
    return {"artifact": "Source-only contract diagnostics, not accuracy evaluation", "contractFixturesSha256": digest(CONTRACT_FIXTURES),
            "fixtureCount": len(results), "passedContracts": sum(item["passed"] for item in results),
            "failedContracts": sum(not item["passed"] for item in results), "results": results,
            "implementationHashes": implementation_hashes(),
            "codeExecuted": False, "modelTrained": False, "accuracyDatasetChanged": False}


def train(output: Path) -> None:
    if any((output / name).exists() for name in ("model.json", "frozen-artifact.json", "regression-test-evaluation.json")):
        raise ValueError("This benchmark version has already trained or assessed; use a new version and disclose test reuse")
    import sklearn
    from ml_engine.defect_features_v2 import FEATURE_VERSION
    declared = protocol()
    if not (output / "protocol.json").exists():
        raise ValueError("Prepare the protocol before training")
    if read(output / "protocol.json") != json.loads(json.dumps(declared)):
        raise ValueError("Prepared protocol does not match the fixed benchmark")
    audit_path = output / "contract-diagnostics.json"
    if not audit_path.exists():
        raise ValueError("Run the source-only contract audit before fitting")
    audit = read(audit_path)
    if (audit.get("failedContracts") != 0 or audit.get("contractFixturesSha256") != digest(CONTRACT_FIXTURES)
            or audit.get("implementationHashes") != implementation_hashes()):
        raise ValueError("Contract audit failed or does not match the current frozen candidate implementation")
    data, _ = dataset()
    arms, oof_reports, validation_reports = {}, {}, {}
    for arm in ARMS:
        training = examples([family for family in data["families"] if family["split"] == "train"], arm)
        validation = examples([family for family in data["families"] if family["split"] == "validation"], arm)
        members = [fit_fold(training, held) for held in FOLDS]
        oof = [predict(row, [next(member for member in members if row["family"] in member["heldOutFamilies"])]) for row in training]
        arms[arm] = {"foldModels": members, "localizerFeatureCount": len(members[0]["ranker"]["coef"]),
                     "classifierFeatureCount": len(members[0]["classifier"]["coef"]), "strictCoverageProvided": arm == "typed-v2"}
        oof_reports[arm] = summarize(training, oof, arm)
        validation_reports[arm] = summarize(validation, [predict(row, members) for row in validation], arm)
    artifact = {"protocolVersion": PROTOCOL_VERSION, "featureVersion": FEATURE_VERSION,
                "datasetSha256": digest(DATA), "threshold": THRESHOLD, "C": REGULARIZATION_C,
                "arms": arms, "refitOnAllTrainingFamilies": False, "deploymentChanged": False,
                "aiIsProof": False, "acceptanceAuthority": False, "createdUtc": now(),
                "implementationHashes": implementation_hashes(), "numpyVersion": np.__version__, "sklearnVersion": sklearn.__version__}
    write_new(output / "model.json", artifact)
    write_new(output / "grouped-oof-evaluation.json", oof_reports)
    write_new(output / "validation-evaluation.json", validation_reports)
    write_new(output / "frozen-artifact.json", {"modelSha256": digest(output / "model.json"), "datasetSha256": digest(DATA),
                                               "splitPlanSha256": digest(PLAN), "protocolSha256": digest(output / "protocol.json"),
                                               "contractAuditSha256": digest(audit_path),
                                               "implementationHashes": implementation_hashes(), "frozenBeforeRegressionAssessment": True,
                                               "testIsReused": True, "createdUtc": now()})
    print(json.dumps({"status": "TRAINED_AND_FROZEN", "output": str(output), "regressionTestAssessed": False,
                      "modelSha256": digest(output / "model.json"), "deploymentChanged": False}))


def evaluate_regression_test(output: Path) -> None:
    marker = output / "regression-test-evaluation.json"
    if marker.exists():
        raise ValueError("Regression split already assessed or attempted for this version; repeated evaluation is refused")
    frozen = read(output / "frozen-artifact.json")
    if (digest(output / "model.json") != frozen["modelSha256"] or digest(DATA) != frozen["datasetSha256"]
            or digest(PLAN) != frozen["splitPlanSha256"] or digest(output / "protocol.json") != frozen["protocolSha256"]
            or digest(output / "contract-diagnostics.json") != frozen["contractAuditSha256"]
            or implementation_hashes() != frozen["implementationHashes"]):
        raise ValueError("Frozen model, implementation, protocol, dataset or split plan changed")
    write_new(marker, {"status": "STARTED", "modelSha256": frozen["modelSha256"], "createdUtc": now()})
    data, _ = dataset()
    artifact = read(output / "model.json")
    arms = {}
    for arm in ARMS:
        rows = examples([family for family in data["families"] if family["split"] == "test"], arm)
        arms[arm] = summarize(rows, [predict(row, artifact["arms"][arm]["foldModels"]) for row in rows], arm)
        arms[arm]["featureDimensions"] = {key: artifact["arms"][arm][key] for key in ("localizerFeatureCount", "classifierFeatureCount")}
    result = {"arms": arms, "aiIsProof": False, "acceptanceAuthority": False}
    baseline = read(V1_REPORT)
    result.update({"status": "COMPLETED", "modelSha256": frozen["modelSha256"], "datasetSha256": digest(DATA),
                   "protocolSha256": frozen["protocolSha256"], "testIsReused": True,
                   "testScope": "Known eight-pair regression split, not unseen validation of generalization",
                   "frozenV1Baseline": {"reportSha256": digest(V1_REPORT), "modelSha256": baseline["modelSha256"],
                                        "pairs": baseline["pairs"], "accuracy": baseline["accuracy"], "precision": baseline["precision"],
                                        "recall": baseline["recall"], "f1": baseline["f1"], "confusion": baseline["confusion"]},
                   "completedUtc": now(), "deploymentChanged": False})
    # Replacing only our STARTED marker records completion, never a repeated run.
    marker.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "arms": {arm: {key: value[key] for key in ("reviewTriageIncludingAbstentions", "coveredClassifierOnly", "coverage")} for arm, value in arms.items()},
                      "testIsReused": True, "deploymentChanged": False}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--train", action="store_true")
    action.add_argument("--evaluate-regression-test", action="store_true")
    action.add_argument("--audit-contracts", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "evaluation/extractor-v2"):
        parser.error("Output must remain inside the new evaluation/extractor-v2 experiment tree")
    if args.prepare:
        prepare(output)
    elif args.audit_contracts:
        result = contract_diagnostics()
        write_new(output / "contract-diagnostics.json", result)
        print(json.dumps({key: result[key] for key in ("fixtureCount", "passedContracts", "failedContracts", "modelTrained", "codeExecuted")}))
    elif args.train:
        train(output)
    else:
        evaluate_regression_test(output)


if __name__ == "__main__":
    main()
