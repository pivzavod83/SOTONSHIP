"""Two-layer GCN with saved synthetic-demo weights and calibrated XGBoost risk.

Portable JSON tree inference avoids importing libomp/XGBoost in the request path.
Scores are exploratory synthetic-demo model outputs, never proof obligations.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from time import perf_counter

from .cpg_builder import deterministic_diagnostics

import networkx as nx
import numpy as np

MODEL_DIR = Path(__file__).parent / "models"


@lru_cache(maxsize=1)
def load_model():
    return json.loads((MODEL_DIR / "cobol_java_gnn_v1.json").read_text())


def embeddings(graph: nx.DiGraph, model: dict) -> tuple[list[str], np.ndarray]:
    """Sparse normalized message passing; memory grows with nodes and edges."""
    nodes = list(graph)
    positions = {node: index for index, node in enumerate(nodes)}
    directed = {}
    for a, b in graph.edges():
        pair = (positions[a], positions[b])
        directed[pair] = directed.get(pair, 0) + 1
    weights = {}
    for (a, b), count in directed.items():
        value = max(count, directed.get((b, a), 0))
        weights[a,b] = value
        weights[b,a] = value
    for index in range(len(nodes)):
        weights[index,index] = weights.get((index,index),0) + 1
    rows = np.asarray([a for a,b in weights],dtype=int)
    cols = np.asarray([b for a,b in weights],dtype=int)
    weight = np.asarray(list(weights.values()),dtype=float)
    degree = np.bincount(rows,weights=weight,minlength=len(nodes))
    normal = weight / np.sqrt(degree[rows] * degree[cols])
    def aggregate(values):
        result = np.zeros_like(values,dtype=float)
        np.add.at(result, rows, normal[:,None] * values[cols])
        return result
    values = np.asarray([graph.nodes[node]["features"] for node in nodes])
    first = np.maximum(aggregate(values) @ np.asarray(model["W1"]),0)
    second = aggregate(first) @ np.asarray(model["W2"])
    second /= np.maximum(np.linalg.norm(second,axis=1,keepdims=True),1e-12)
    return nodes, second


def _tree_value(tree: dict, values: list[float]) -> float:
    while "leaf" not in tree:
        feature = tree["split"]
        index = int(feature[1:]) if feature.startswith("f") else int(feature)
        target = tree["yes"] if values[index] < tree["split_condition"] else tree["no"]
        tree = next(child for child in tree["children"] if child["nodeid"] == target)
    return float(tree["leaf"])


def node_risk(features: list[float], embedding: np.ndarray, model: dict) -> float:
    classifier = model["riskClassifier"]
    values = features + embedding.tolist()
    margin = classifier["baseMargin"] + sum(_tree_value(tree, values) for tree in classifier["trees"])
    calibration = classifier["calibration"]
    score = 1 / (1 + math.exp(-max(-50, min(50, calibration["slope"] * margin + calibration["intercept"]))))
    return round(score, 6)


def align(cobol: nx.DiGraph, java: nx.DiGraph) -> dict:
    started = perf_counter()
    model = load_model()
    c_nodes, c_vectors = embeddings(cobol, model)
    j_nodes, j_vectors = embeddings(java, model)
    for graph, nodes, vectors in ((cobol, c_nodes, c_vectors), (java, j_nodes, j_vectors)):
        for node, vector in zip(nodes, vectors, strict=True):
            graph.nodes[node]["riskScore"] = node_risk(graph.nodes[node]["features"], vector, model)
    source = [index for index, node in enumerate(c_nodes) if cobol.nodes[node]["kind"] == "paragraph"]
    target = [index for index, node in enumerate(j_nodes) if java.nodes[node]["kind"] == "method"]
    alignment_status = "ALIGNED" if source and target else "MISSING_BOTH" if not source and not target else "MISSING_SOURCE" if not source else "MISSING_TARGET"
    if not target:
        source = []
    links = []
    for index in source:
        candidate = max(target, key=lambda other: float(c_vectors[index] @ j_vectors[other]))
        score = max(0.0, min(1.0, float(c_vectors[index] @ j_vectors[candidate])))
        links.append({"source": c_nodes[index], "target": j_nodes[candidate], "kind": "GNN_ALIGNMENT",
                      "confidence": round(score, 6)})
    maximum_risk = max(graph.nodes[node]["riskScore"] for graph in (cobol, java) for node in graph)
    factors = []
    all_features = [attributes["features"] for graph in (cobol, java) for _, attributes in graph.nodes(data=True)]
    if any(item[0] for item in all_features) and any(item[1] for item in all_features):
        factors.append("packed fixed-point to IEEE754 type boundary")
    if any(item[5] for item in all_features):
        factors.append("branch or PERFORM range control flow")
    if any(item[6] for item in all_features):
        factors.append("external state or aliased storage")
    if not factors:
        factors.append("explicit decimal scale and rounding")
    return {"alignmentScore": round(sum(link["confidence"] for link in links) / len(links), 6) if links else 0.0,
            "bugRiskScore": maximum_risk, "links": links, "riskFactors": factors,
            "inferenceMs": round((perf_counter() - started) * 1000, 3),
            "modelProvenance": model["provenance"], "alignmentStatus": alignment_status,
            "diagnostics": deterministic_diagnostics(cobol,java),
            "modelScope": "Experimental synthetic-trained GCN ranking over actual function/paragraph nodes; deterministic type/operation diagnostics are reported separately; proof does not depend on cosine confidence."}
