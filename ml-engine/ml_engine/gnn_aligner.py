"""Program matching from a model trained on paired source programs.

This adapter preserves the verification response contract. There is no defect
risk model or learned statement correspondence. The independent formal parser,
not this model, defines every proof obligation.
"""
from __future__ import annotations

from time import perf_counter

import networkx as nx
import numpy as np

from .paired_gnn import MODEL_PATH, encode_source, load_model, model_metadata

MODEL_DIR = MODEL_PATH.parent


def align_sources(cobol_source: str, java_source: str, source_format: str = "AUTO") -> dict:
    started = perf_counter()
    model = load_model()
    cobol_vector = encode_source(cobol_source, "cobol", source_format, model=model)
    java_vector = encode_source(java_source, "java", model=model)
    cosine = float(np.clip(cobol_vector @ java_vector, -1.0, 1.0))
    metadata = model_metadata()
    return {
        # Existing verification storage constrains this legacy field to [0, 1].
        # The retrieval API returns the full cosine, including negative values.
        "alignmentScore": round(max(0.0, cosine), 6),
        "cosineSimilarity": round(cosine, 6),
        "bugRiskScore": 0.0,
        "riskAssessment": {
            "status": "NOT_ESTIMATED",
            "reason": "The synthetic risk classifier was removed. Paired-program labels do not identify defects.",
            "legacyNumericField": "gnnBugRiskScore=0 is unused compatibility data, not evidence of low risk.",
        },
        "links": [{"source": "cobol:root", "target": "java:root", "kind": "GNN_ALIGNMENT",
                   "granularity": "PROGRAM", "similarity": round(cosine, 6), "matchingIsProof": False}],
        "riskFactors": [],
        "inferenceMs": round((perf_counter() - started) * 1000, 3),
        "modelProvenance": metadata,
        "modelSha256": metadata["sha256"],
    }


def align(cobol: nx.DiGraph, java: nx.DiGraph) -> dict:
    """Compatibility entry point for inspection graphs, not a node model."""
    if "sourceText" not in cobol.graph or "sourceText" not in java.graph:
        raise ValueError("Program matching needs exact original sources; line labels are insufficient")
    return align_sources(cobol.graph["sourceText"], java.graph["sourceText"],
                         cobol.graph.get("sourceFormat", "AUTO"))
