"""Evaluate advisory model outputs against adjudicated, held-out review cases.

Run from ml-engine with: python -m ml_engine.evaluate_review_set CORPUS.json --split test
The private corpus is read-only; this tool never trains or changes a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from .paired_gnn import MODEL_PATH, load_model
from .verify import verify_request


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source(case_dir: Path, descriptor: dict, label: str) -> str:
    path = (case_dir / descriptor["path"]).resolve()
    if not path.is_relative_to(case_dir.resolve()):
        raise ValueError(f"{label} source path must remain within the corpus directory")
    content = path.read_bytes()
    if _sha256(content) != descriptor["sha256"]:
        raise ValueError(f"{label} source hash mismatch: {descriptor['path']}")
    return content.decode("utf-8")


def _canonical_pairs(pairs: list[dict]) -> set[tuple[str, str]]:
    return {(pair["cobolNodeId"], pair["javaNodeId"]) for pair in pairs}


def _node_tokens(label: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", label.lower()))


def _name_baseline(nodes: list[dict]) -> set[tuple[str, str]]:
    cobol = [node for node in nodes if node.get("kind") == "paragraph" and node.get("language") == "cobol"]
    java = [node for node in nodes if node.get("kind") == "method" and node.get("language") == "java"]
    result = set()
    for source in cobol:
        source_tokens = _node_tokens(source.get("label", ""))
        candidates = []
        for target in java:
            target_tokens = _node_tokens(target.get("label", ""))
            overlap = len(source_tokens & target_tokens) / max(1, len(source_tokens | target_tokens))
            candidates.append((overlap, target["id"]))
        if candidates:
            score, target_id = max(candidates, key=lambda item: (item[0], item[1]))
            if score > 0:
                result.add((source["id"], target_id))
    return result


def _confusion(actual: list[bool], predicted: list[bool]) -> dict:
    tp = sum(a and p for a, p in zip(actual, predicted, strict=True))
    fp = sum((not a) and p for a, p in zip(actual, predicted, strict=True))
    fn = sum(a and (not p) for a, p in zip(actual, predicted, strict=True))
    tn = sum((not a) and (not p) for a, p in zip(actual, predicted, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"cases": len(actual), "truePositive": tp, "falsePositive": fp,
            "falseNegative": fn, "trueNegative": tn, "precision": round(precision, 6),
            "recall": round(recall, 6), "falseNegativeRate": round(fn / (tp + fn), 6) if tp + fn else None,
            "f1": round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0}


def _aggregate_pair_metrics(rows: list[dict], prediction_key: str) -> dict:
    actual_count = sum(len(row["expectedPairs"]) for row in rows)
    predicted_count = sum(len(row[prediction_key]) for row in rows)
    true_positive = sum(len(row["expectedPairs"] & row[prediction_key]) for row in rows)
    precision = true_positive / predicted_count if predicted_count else 0.0
    recall = true_positive / actual_count if actual_count else (1.0 if not predicted_count else 0.0)
    return {"reviewedPairs": actual_count, "predictedPairs": predicted_count,
            "truePositivePairs": true_positive, "falsePositivePairs": predicted_count - true_positive,
            "missedPairs": actual_count - true_positive, "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0}


def _case_result(case: dict, base: Path, risk_threshold: float) -> dict:
    adjudication = case.get("adjudication", {})
    if adjudication.get("status") != "ADJUDICATED":
        raise ValueError(f"Case {case.get('caseId')} is not adjudicated")
    if not adjudication.get("adjudicatorId") or not adjudication.get("rationale", "").strip():
        raise ValueError(f"Case {case.get('caseId')} needs a named adjudicator and rationale")
    votes = case.get("reviewVotes", [])
    if len({vote.get("reviewerId") for vote in votes}) < 2:
        raise ValueError(f"Case {case.get('caseId')} needs independent votes from at least two reviewers")
    request = dict(case["request"])
    request["cobolSource"] = _source(base, request.pop("cobolSource"), "COBOL")
    request["javaSource"] = _source(base, request.pop("javaSource"), "Java")
    result = verify_request(request)
    graph = result["cpgGraphJson"]
    predicted_pairs = {(edge["source"], edge["target"]) for edge in graph["edges"]
                       if edge.get("kind") == "GNN_ALIGNMENT"}
    expected_pairs = _canonical_pairs(adjudication.get("mappings", []))
    actual_defect = adjudication["hasDefect"]
    model_defect = result["gnnBugRiskScore"] >= risk_threshold
    baseline_defect = bool(result["baselineCaughtBug"])
    normalized_final = {"hasDefect": actual_defect,
                        "mappings": sorted([list(pair) for pair in expected_pairs])}
    disagreement = 0
    for vote in votes:
        normalized_vote = {"hasDefect": vote.get("hasDefect"),
                           "mappings": sorted([list(pair) for pair in _canonical_pairs(vote.get("mappings", []))])}
        disagreement += normalized_vote != normalized_final
    return {"caseId": case["caseId"], "groupId": case["groupId"],
            "dialectProfile": case["dialectProfile"], "patternTags": case["patternTags"],
            "actualDefect": actual_defect, "modelDefect": model_defect,
            "modelRiskScore": result["gnnBugRiskScore"], "baselineDefect": baseline_defect,
            "modelPairs": predicted_pairs, "baselinePairs": _name_baseline(graph["nodes"]),
            "expectedPairs": expected_pairs, "reviewerDisagreements": disagreement,
            "formalProofStatus": result["formalProofStatus"]}


def evaluate(corpus_path: Path, split: str, risk_threshold: float = 0.5) -> dict:
    if load_model().get("task") != "NODE_ALIGNMENT_AND_DEFECT_RISK":
        raise ValueError(
            "This legacy evaluator needs a node-alignment/defect-risk model. The paired-program GNN "
            "does not predict those labels. Use evaluation/paired-code/training-report.json and "
            "scripts/train_paired_gnn.py for program-retrieval evaluation; do not report zero risk as accuracy."
        )
    if not 0 <= risk_threshold <= 1:
        raise ValueError("Risk threshold must be between 0 and 1")
    if not corpus_path.is_file():
        raise ValueError(
            f"Corpus file not found: {corpus_path}. Replace the example path with the path to your completed, approved corpus JSON."
        )
    raw = corpus_path.read_bytes()
    corpus = json.loads(raw)
    if corpus.get("schemaVersion") != 1 or not corpus.get("datasetId"):
        raise ValueError("Corpus must declare schemaVersion 1 and datasetId")
    cases = corpus.get("cases", [])
    groups: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        if case.get("split") not in ("train", "calibration", "test"):
            raise ValueError(f"Case {case.get('caseId')} must have a train/calibration/test split")
        groups[case["groupId"]].add(case["split"])
    overlap = [group for group, splits in groups.items() if len(splits) != 1]
    if overlap:
        raise ValueError(f"Codebase groups must not cross splits; overlapping groups: {overlap[:5]}")
    selected = [case for case in cases if case["split"] == split]
    if not selected:
        raise ValueError(f"No cases found for split {split}")
    rows = [_case_result(case, corpus_path.parent.resolve(), risk_threshold) for case in selected]
    actual = [row["actualDefect"] for row in rows]
    output = {"datasetId": corpus["datasetId"], "datasetSha256": _sha256(raw),
              "datasetSplit": split, "groupSplitPolicy": "groupId cannot appear in more than one split",
              "reviewedCases": len(rows), "reviewerDisagreementsResolved": sum(row["reviewerDisagreements"] > 0 for row in rows),
              "reviewerDisagreementVotes": sum(row["reviewerDisagreements"] for row in rows),
              "riskThreshold": risk_threshold,
              "model": {"modelId": load_model().get("provenance", {}).get("modelId", "unknown"),
                        "provenance": "advisory only; no training performed",
                        "sha256": _sha256(MODEL_PATH.read_bytes())},
              "risk": {"model": _confusion(actual, [row["modelDefect"] for row in rows]),
                       "baseline": _confusion(actual, [row["baselineDefect"] for row in rows])},
              "alignment": {"model": _aggregate_pair_metrics(rows, "modelPairs"),
                            "exactNameBaseline": _aggregate_pair_metrics(rows, "baselinePairs")},
              "byDialectProfile": {}, "byPatternTag": {},
              "limitations": ["Metrics describe only this adjudicated corpus and split.",
                              "Risk scores and the 0.5 threshold are exploratory; no production calibration is implied.",
                              "Formal proof status is reported per case but does not define the human defect label."]}
    dimensions = {"byDialectProfile": lambda row: [row["dialectProfile"]],
                  "byPatternTag": lambda row: row["patternTags"]}
    for section, keys_for in dimensions.items():
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            for key in keys_for(row):
                grouped[key].append(row)
        for key, members in sorted(grouped.items()):
            truths = [row["actualDefect"] for row in members]
            output[section][key] = {"cases": len(members),
                "riskModel": _confusion(truths, [row["modelDefect"] for row in members]),
                "riskBaseline": _confusion(truths, [row["baselineDefect"] for row in members]),
                "alignmentModel": _aggregate_pair_metrics(members, "modelPairs")}
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--split", choices=("train", "calibration", "test"), default="test")
    parser.add_argument("--risk-threshold", type=float, default=0.5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = json.dumps(evaluate(args.corpus.resolve(), args.split, args.risk_threshold), indent=2, sort_keys=True) + "\n"
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    if args.output:
        args.output.write_text(report)
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
