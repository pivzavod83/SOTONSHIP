"""Portable local inference for a trained synthetic-pilot defect detector.

Run ``python -m ml_engine.defect_detection --stdin`` with one JSON object.
Submitted code is parsed as text only and is never compiled or executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np

from .defect_features import FEATURE_VERSION, PairGraph, extract_pair

DEFAULT_MODEL_PATH = Path(__file__).with_name("models") / "defect_model_v1.json"
ENGINE_VERSION = "paired-defect-v1"
LIMITATIONS = [
    "Exploratory model trained on 24 synthetic pairs from six COBOL algorithm families; not validated for production migration.",
    "Risk and span scores are uncalibrated learned signals, not probabilities of correctness or a proof of equivalence.",
    "Statement/dependency graphs are extracted heuristically; unsupported syntax, refactorings and unseen defect types can be missed.",
    "Highlighted locations are model hypotheses supervised by AI-generated annotations, not independently reviewed defect locations.",
    "No supplied code or candidate inputs were executed during this analysis; a low score or an empty finding list does not establish correctness.",
]


def sha256(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data,str) else data).hexdigest()


def linear_probability(x: np.ndarray, state: dict) -> np.ndarray:
    mean, scale = np.array(state["mean"]), np.array(state["scale"])
    z = ((np.asarray(x)-mean)/scale) @ np.array(state["coef"]) + float(state["intercept"])
    return 1/(1+np.exp(-np.clip(z, -40, 40)))


def graph_prediction(graph: PairGraph, artifact: dict) -> tuple[float, np.ndarray]:
    program_scores, line_scores = [], []
    for fold in artifact["foldModels"]:
        local = linear_probability(graph.candidate_x, fold["localizer"])
        top = np.sort(local)[-3:]
        px = classifier_features(graph, local, fold.get("classifierInput","graph-and-localizer"))
        program_scores.append(float(linear_probability(px, fold["classifier"])))
        line_scores.append(local)
    return float(np.mean(program_scores)), np.mean(line_scores, axis=0)


def classifier_features(graph: PairGraph, local: np.ndarray, architecture: str) -> np.ndarray:
    if architecture == "localizer-pooling":
        return np.array([local.max(),np.sort(local)[-3:].mean(),local.mean(),local.std()])
    return np.r_[graph.global_x,float(local.max()),float(np.sort(local)[-3:].mean())]


def load_artifact(path: Path = DEFAULT_MODEL_PATH) -> tuple[dict, dict]:
    raw = path.read_bytes()
    artifact = json.loads(raw)
    if artifact.get("featureVersion") != FEATURE_VERSION or artifact.get("engineVersion") != ENGINE_VERSION:
        raise ValueError("Incompatible defect-model artifact")
    metadata = {"name":artifact["name"], "sha256":sha256(raw), "datasetSha256":artifact["datasetSha256"], "trainingFamilyCount":6}
    if artifact.get("evaluation"):
        metadata["evaluation"] = artifact["evaluation"]
    return artifact, metadata


def model_status(path: Path = DEFAULT_MODEL_PATH) -> dict:
    try:
        _, metadata = load_artifact(path)
        return {"configured":True, "model":metadata, "limitations":LIMITATIONS}
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {"configured":False, "model":None, "limitations":["No compatible local defect-model artifact is available.", *LIMITATIONS]}


def _span(node) -> dict | None:
    return {"start":node.start,"end":node.end} if node is not None else None


def _excerpt(source: str, node) -> str:
    return "\n".join(source.split("\n")[node.start-1:node.end]) if node is not None else ""


def analyze(payload: dict, path: Path = DEFAULT_MODEL_PATH) -> dict:
    if payload.get("action") == "status":
        return model_status(path)
    cobol, java = payload.get("cobolSource"), payload.get("javaSource")
    if not isinstance(cobol,str) or not isinstance(java,str) or not cobol.strip() or not java.strip():
        raise ValueError("Nonempty cobolSource and javaSource strings are required")
    source_format = payload.get("cobolSourceFormat", "FREE")
    if source_format not in ("FREE", "FIXED"):
        raise ValueError("cobolSourceFormat must be FREE or FIXED")
    if len(cobol.encode("utf-8")) > 200_000 or len(java.encode("utf-8")) > 200_000:
        raise ValueError("Each source must be at most 200000 UTF-8 bytes")
    base = {"engineVersion":ENGINE_VERSION, "sourceHashes":{"cobol":sha256(cobol),"java":sha256(java)}, "aiIsProof":False,"counterexamplesExecuted":False,"limitations":LIMITATIONS,"findings":[],"risk":{"score":0.,"threshold":.5,"decision":"NO_DEFECT_SIGNAL","calibrated":False}}
    try:
        artifact, metadata = load_artifact(path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {**base,"status":"NOT_CONFIGURED","model":None,"summary":"The local defect model has not been configured."}
    try:
        graph = extract_pair(cobol,java,source_format)
    except ValueError as exc:
        return {**base,"status":"UNSUPPORTED","model":None,"summary":str(exc)}
    risk, scores = graph_prediction(graph,artifact)
    threshold = float(artifact["threshold"])
    required = risk >= threshold
    findings = []
    if required:
        # Ranking is learned. Do not filter it using hand-written defect rules.
        # Avoid repeating the same Java/Cobol span while showing at most 3 areas.
        seen = set()
        for index in np.argsort(-scores,kind="stable"):
            ci,ji = graph.candidates[int(index)]
            cnode = graph.cobol[ci] if ci is not None else None
            jnode = graph.java[ji] if ji is not None else None
            key = (cnode.start if cnode else None,jnode.start if jnode else None)
            if key in seen:
                continue
            seen.add(key)
            label = "Possible semantic difference" if cnode and jnode else "Possible missing Java operation" if cnode else "Possible extra Java operation"
            explanation = "The learned span ranker prioritised this source correspondence using arithmetic, rounding, numeric storage and dependency graph features. Compare the receiving-field semantics and the highlighted Java transformation; the model does not prove a particular defect."
            findings.append({"findingId":f"F{len(findings)+1}","evidenceStatus":"MODEL_HYPOTHESIS","title":label,"explanation":explanation,
                             "suggestedFix":"Review the highlighted operation against the COBOL reference and confirm any change with an executable counterexample or a supported formal proof.",
                             "cobolLines":_span(cnode),"javaLines":_span(jnode),"cobolExcerpt":_excerpt(cobol,cnode),"javaExcerpt":_excerpt(java,jnode),
                             "score":float(scores[index]),"category":"SEMANTIC_DIFFERENCE","candidateInputs":[]})
            if len(findings) == 3:
                break
    return {**base,"status":"ANALYZED","model":metadata,
            "risk":{"score":risk,"threshold":threshold,"decision":"REVIEW_REQUIRED" if required else "NO_DEFECT_SIGNAL","calibrated":False},
            "summary":"The learned model recommends human review; highlighted spans are hypotheses." if required else "The learned model found no strong defect signal. Equivalence has not been established.",
            "findings":findings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin",action="store_true",required=True)
    parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Input JSON must be at most 1000000 UTF-8 bytes")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload,dict):
            raise ValueError("Input must be a JSON object")
        result = analyze(payload)
        print(json.dumps(result,allow_nan=False))
    except (ValueError,TypeError,KeyError) as exc:
        print(json.dumps({"error":str(exc)}),file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
