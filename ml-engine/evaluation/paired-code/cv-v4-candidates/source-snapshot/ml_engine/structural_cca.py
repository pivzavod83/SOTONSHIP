"""Fixed relation-aware WL features with a paired, regularized linear CCA map.

The feature map uses numeric graph semantics only, with no fitted vocabulary,
identifier spelling, task labels, comments, or source text. Its fixed hashed
subtree counts are inspired by Shervashidze et al. (JMLR 2011). The two-view
learning objective is classical ridge-regularized CCA, related to the linear
CCA objective discussed by Andrew et al. (ICML 2013); this is not deep CCA.

All fitted centering, scaling and projections come exclusively from the two
matrices supplied to ``fit_cca``. The experiment caller owns split integrity.
"""
from __future__ import annotations

import hashlib
import numbers

import numpy as np

from .code_graph import CodeGraph, FEATURE_NAMES, RELATIONS


HASH_BINS = 512
WL_ROUNDS = 2
FEAT_DIM = HASH_BINS + 2 * len(FEATURE_NAMES) + 1 + 2 * len(RELATIONS)
FEATURE_VERSION = "relation-aware-hashed-wl-cca-v1"


def _digest(value: bytes) -> bytes:
    return hashlib.blake2b(value, digest_size=16, person=b"paired-wl-cca-v1").digest()


def _graph_arrays(graph: CodeGraph):
    x = np.asarray(graph.x, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != len(FEATURE_NAMES) or x.shape[0] < 1:
        raise ValueError("graph.x must have nodes and the declared semantic features")
    if not np.all(np.isfinite(x)):
        raise ValueError("graph.x must be finite")
    if not isinstance(graph.edges, dict) or set(graph.edges) != set(RELATIONS):
        raise ValueError("graph edges must contain exactly the declared relations")
    edges = {}
    for relation in RELATIONS:
        raw = np.asarray(graph.edges[relation])
        if raw.ndim != 2 or raw.shape[1] != 2:
            raise ValueError("each relation must have an edge matrix with two columns")
        if not np.issubdtype(raw.dtype, np.integer):
            raise ValueError("graph edge endpoints must be integers")
        if raw.size and (raw.min() < 0 or raw.max() >= len(x)):
            raise ValueError("graph edge endpoint is outside the node matrix")
        # Graph topology is a set: duplicate edge order must not affect features.
        edges[relation] = np.unique(raw.astype(np.int64), axis=0)
    return x, edges


def graph_features(graph: CodeGraph) -> np.ndarray:
    """Return one deterministic, fixed-size semantic/structural feature vector.

    WL colors refine quantized numeric node labels using relation-labelled
    incoming/outgoing neighbor multisets. Square-root normalized counts retain
    rounds 0, 1 and 2 in fixed hash bins. Separate semantic means/log counts and
    relation-size statistics retain smooth information that discrete colors
    would lose. Node indices and graph.stats never enter the representation.
    """
    x, edges = _graph_arrays(graph)
    adjacency = {relation: ([[] for _ in x], [[] for _ in x]) for relation in RELATIONS}
    for relation, endpoints in edges.items():
        outgoing, incoming = adjacency[relation]
        for left, right in endpoints:
            outgoing[left].append(int(right))
            incoming[right].append(int(left))

    # Coarse quantization avoids floating byte-format instability in WL labels;
    # unquantized semantic statistics below retain continuous numeric features.
    quantized = np.rint(np.clip(x, -1e6, 1e6) * 10).astype("<i8")
    labels = [_digest(row.tobytes()) for row in quantized]
    histogram = np.zeros(HASH_BINS, dtype=np.float64)
    for depth in range(WL_ROUNDS + 1):
        for label in labels:
            token = _digest(bytes([depth]) + label)
            histogram[int.from_bytes(token[:8], "little") % HASH_BINS] += 1
        if depth == WL_ROUNDS:
            break
        refined = []
        for node in range(len(x)):
            pieces = [labels[node]]
            for relation in RELATIONS:
                outgoing, incoming = adjacency[relation]
                for direction, neighbors in ((b"out", outgoing[node]), (b"in", incoming[node])):
                    pieces.append(relation.encode() + b":" + direction)
                    pieces.append(len(neighbors).to_bytes(8, "little"))
                    pieces.extend(sorted(labels[neighbor] for neighbor in neighbors))
            refined.append(_digest(b"".join(pieces)))
        labels = refined
    histogram = np.sqrt(histogram / (len(x) * (WL_ROUNDS + 1)))
    # The extractor emits nonnegative semantics; signed log also handles custom
    # finite unit graphs without silently clipping their semantic statistics.
    sums = x.sum(axis=0)
    semantic_counts = np.sign(sums) * np.log1p(np.abs(sums))
    sizes = [np.log1p(len(x))]
    for relation in RELATIONS:
        sizes.extend((np.log1p(len(edges[relation])), len(edges[relation]) / len(x)))
    result = np.concatenate((histogram, x.mean(axis=0), semantic_counts, sizes))
    if result.shape != (FEAT_DIM,) or not np.all(np.isfinite(result)):
        raise ValueError("non-finite or incorrectly shaped structural graph features")
    return result


def _matrix(value, *, name: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 1:
        raise ValueError(f"{name} must have at least two rows and one feature")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must contain only finite values")
    return matrix


def _standardize(matrix: np.ndarray):
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0, ddof=1)
    # Constant columns remain zero after centering and must not amplify noise.
    scale = np.where(scale > 1e-8, scale, 1.0)
    return (matrix - mean) / scale, mean, scale


def fit_cca(cobolFeatures, javaFeatures, regularization: float = 0.1, output: int = 24) -> dict:
    """Fit paired ridge CCA using only the supplied training rows.

    Thin SVD restricts whitening to the data span, avoiding large singular
    feature-space inverses when graphs have more features than paired samples.
    Covariances use n-1 normalization. Missing low-rank output directions are
    zero-padded, so every fold has exactly the requested output width.
    """
    cobol = _matrix(cobolFeatures, name="cobolFeatures")
    java = _matrix(javaFeatures, name="javaFeatures")
    if cobol.shape[0] != java.shape[0]:
        raise ValueError("paired views must have the same training row count")
    if (not isinstance(regularization, numbers.Real) or isinstance(regularization, bool)
            or not np.isfinite(regularization) or regularization <= 0):
        raise ValueError("regularization must be finite and positive")
    if not isinstance(output, numbers.Integral) or isinstance(output, bool) or output < 1:
        raise ValueError("output must be a positive integer")
    a, mean_a, scale_a = _standardize(cobol)
    b, mean_b, scale_b = _standardize(java)
    n = len(a)

    def whiten(matrix):
        _, singular, vt = np.linalg.svd(matrix, full_matrices=False)
        tolerance = np.finfo(float).eps * max(matrix.shape) * (singular[0] if len(singular) else 0)
        present = singular > max(tolerance, 1e-12)
        singular, vt = singular[present], vt[present]
        return vt.T / np.sqrt(singular * singular / (n - 1) + regularization)

    whitening_a, whitening_b = whiten(a), whiten(b)
    cross = (a @ whitening_a).T @ (b @ whitening_b) / (n - 1)
    left, correlations, right_t = np.linalg.svd(cross, full_matrices=False)
    width = min(int(output), len(correlations))
    projection_a = np.zeros((a.shape[1], int(output)))
    projection_b = np.zeros((b.shape[1], int(output)))
    projection_a[:, :width] = whitening_a @ left[:, :width]
    projection_b[:, :width] = whitening_b @ right_t[:width].T
    return {
        "kind": "STRUCTURAL_CCA",
        "featureVersion": FEATURE_VERSION,
        "regularization": float(regularization),
        "output": int(output),
        "trainingRows": n,
        "canonicalCorrelations": correlations[:width].tolist(),
        "cobol": {"mean": mean_a.tolist(), "scale": scale_a.tolist(), "projection": projection_a.tolist()},
        "java": {"mean": mean_b.tolist(), "scale": scale_b.tolist(), "projection": projection_b.tolist()},
    }


def validate_cca(model: dict) -> None:
    """Validate the fixed runtime feature/projection schema without fitting.

    The experiment's fold wrapper separately verifies that trainingRows is 96
    and binds its original task membership; this module also supports tiny
    arrays for numerical unit checks and does not encode corpus policy.
    """
    if not isinstance(model, dict) or model.get("kind") != "STRUCTURAL_CCA":
        raise ValueError("model must be a structural CCA artifact")
    if (model.get("featureVersion") != FEATURE_VERSION or model.get("output") != 24
            or not isinstance(model.get("output"), int)):
        raise ValueError("CCA model feature version or output width does not match runtime")
    if isinstance(model.get("output"), bool):
        raise ValueError("CCA output must be an integer")
    regularization = model.get("regularization")
    if (not isinstance(regularization, numbers.Real) or isinstance(regularization, bool)
            or not np.isfinite(regularization) or regularization <= 0):
        raise ValueError("CCA regularization must be finite and positive")
    rows = model.get("trainingRows")
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 2:
        raise ValueError("CCA trainingRows must be an integer of at least two")
    correlations = np.asarray(model.get("canonicalCorrelations"), dtype=float)
    if (correlations.ndim != 1 or len(correlations) > 24 or not np.all(np.isfinite(correlations))
            or np.any(correlations < 0) or np.any(correlations > 1 + 1e-8)):
        raise ValueError("CCA canonical correlations must be finite and between zero and one")
    for language in ("cobol", "java"):
        state = model.get(language)
        if not isinstance(state, dict) or set(state) != {"mean", "scale", "projection"}:
            raise ValueError("CCA view must contain mean, scale, and projection only")
        mean, scale, projection = (np.asarray(state[key], dtype=float)
                                   for key in ("mean", "scale", "projection"))
        if (mean.shape != (FEAT_DIM,) or scale.shape != (FEAT_DIM,)
                or projection.shape != (FEAT_DIM, 24)
                or not all(np.all(np.isfinite(value)) for value in (mean, scale, projection))
                or np.any(scale <= 0)):
            raise ValueError("CCA runtime state has invalid dimensions, values, or scales")


def encode_cca(features, model: dict, language: str) -> np.ndarray:
    """Transform one vector or a row matrix; return finite unit-length rows.

    A zero projection stays zero, since an empty/constant representation has
    no justified direction. No parameters are fitted or changed at inference.
    """
    if language not in ("cobol", "java"):
        raise ValueError("language must be cobol or java")
    if not isinstance(model, dict) or model.get("kind") != "STRUCTURAL_CCA":
        raise ValueError("model must be a structural CCA artifact")
    output = model.get("output")
    if not isinstance(output, int) or isinstance(output, bool) or output < 1:
        raise ValueError("model output must be a positive integer")
    state = model.get(language)
    if not isinstance(state, dict):
        raise ValueError("CCA model is missing view state")
    try:
        mean = np.asarray(state["mean"], dtype=float)
        scale = np.asarray(state["scale"], dtype=float)
        projection = np.asarray(state["projection"], dtype=float)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid CCA view state") from error
    if (mean.ndim != 1 or mean.size < 1 or scale.shape != mean.shape
            or projection.shape != (len(mean), output)
            or not all(np.all(np.isfinite(item)) for item in (mean, scale, projection))
            or np.any(scale <= 0)):
        raise ValueError("CCA view state must have compatible finite arrays and positive scales")
    values = np.asarray(features, dtype=float)
    if values.ndim not in (1, 2) or values.shape[-1] != len(mean) or not np.all(np.isfinite(values)):
        raise ValueError("features must be finite vectors with the fitted view width")
    embedded = ((values - mean) / scale) @ projection
    if not np.all(np.isfinite(embedded)):
        raise ValueError("CCA projection produced non-finite output")
    norm = np.linalg.norm(embedded, axis=-1, keepdims=True)
    return np.divide(embedded, norm, out=np.zeros_like(embedded), where=norm > 1e-12)
