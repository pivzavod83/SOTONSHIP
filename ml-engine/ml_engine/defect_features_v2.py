"""Compact source-pair features from the bounded, typed v2 semantic IR.

The complete IR retains ordered operands, source maps and dependency/control
edges. These deliberately lossy statistical features are ML inputs, not a proof
representation. Unknown syntax or exhausted budgets must abstain before scoring.
The frozen v1 extractor and its weights are never modified or reused here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math

import numpy as np

from .semantic_ir import ProgramIR

FEATURE_VERSION = "typed-semantic-v2"
OPS = ("input", "output", "return", "read", "store", "add", "subtract", "multiply",
       "divide", "modulo", "absolute", "negate", "minimum", "maximum", "compare",
       "branch", "loop", "merge", "quantize", "convert", "format", "call", "stop",
       "power", "not", "and", "or", "floor", "concatenate", "select")
ATTRS = ("decimal", "integer", "float", "string", "boolean", "signed", "unsigned",
         "precision", "scale", "binary_width", "round_half_up", "round_down", "round_floor",
         "round_other", "unsigned_store", "overflow_store", "negative_literal", "literal_magnitude",
         "compare_lt", "compare_le", "compare_eq", "compare_ne", "compare_gt", "compare_ge")
# Small fixed hashing spaces retain operand roles and semantic attributes without
# fitting a vocabulary on validation/test sources. Collisions remain possible;
# the full, unhashed IR is the representation to inspect, never these ML inputs.
HASH_BINS = 32
HASH_NAMES = (*(f"semantic_attr_{i}" for i in range(HASH_BINS)),
              *(f"ordered_operand_{i}" for i in range(HASH_BINS)))
NODE_NAMES = (*OPS, *ATTRS, *HASH_NAMES)
EXTRA_NAMES = ("operation_overlap", "literal_overlap", "literal_count_delta", "literal_value_difference",
               "data_edge_delta", "control_edge_delta", "loop_edge_delta", "operand_role_delta",
               "region_size_delta", "output_reach_delta")
PAIR_NAMES = (*("delta_" + n for n in NODE_NAMES), *EXTRA_NAMES)
GLOBAL_NAMES = (*("delta_" + n for n in NODE_NAMES), *EXTRA_NAMES,
                "nearest_mean_distance", "nearest_max_distance", "nearest_min_distance")
MAX_SOURCE_BYTES = 200_000
MAX_REGIONS = 180


@dataclass
class Region:
    start: int
    end: int
    text: str
    target: str
    uses: set[str]
    x: np.ndarray
    node_ids: frozenset[str]
    literals: frozenset[str] = frozenset()
    edge_counts: dict[str, int] = field(default_factory=dict)
    output_reach: float = 0.0


@dataclass
class PairGraph:
    cobol: list[Region]
    java: list[Region]
    candidates: list[tuple[int | None, int | None]]
    candidate_x: np.ndarray
    global_x: np.ndarray
    status: str
    coverage: dict
    cobol_ir: ProgramIR | None = None
    java_ir: ProgramIR | None = None
    feature_names: tuple[str, ...] = GLOBAL_NAMES
    candidate_feature_names: tuple[str, ...] = PAIR_NAMES


def _op(value: str) -> str:
    value = value.lower()
    return {"abs": "absolute", "remainder": "modulo", "neg": "negate", "unary_minus": "negate",
            "round": "quantize", "cast": "convert", "conversion": "convert", "phi": "merge",
            "while": "loop", "if": "branch", "print": "output", "display": "output",
            "assign": "store", "terminate": "stop"}.get(value, value)


def _number(value) -> Decimal | None:
    try:
        result = Decimal(str(value).rstrip("LlDdFf"))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _literals(nodes) -> frozenset[str]:
    values = set()
    for node in nodes:
        if _op(node.op) != "literal":
            continue
        value = node.attrs.get("value", node.attrs.get("literal"))
        numeric = _number(value)
        # Include representation: a binary literal is not an exact decimal string.
        kind = node.numeric_type.kind if node.numeric_type else "unknown"
        values.add(f"{kind}:{numeric.normalize() if numeric is not None else str(value)}")
    return frozenset(values)


def _vector(nodes, ir: ProgramIR) -> np.ndarray:
    values = Counter()
    by_id = {n.id: n for n in ir.nodes}
    symbols = {name: i for i, name in enumerate(ir.symbols)}
    ignored_attrs = {"method", "name", "symbol", "parameter", "version", "raw", "java_method",
                     "java_constructor", "receiver_type", "java_type", "constantStateKilled",
                     "loop_header", "branch", "loop", "source", "sourceHash"}

    def hashed(prefix, token):
        digest = hashlib.sha256(token.encode()).digest()
        values[f"{prefix}_{int.from_bytes(digest[:4], 'big') % HASH_BINS}"] += 1

    def operand(identifier):
        node = by_id.get(identifier)
        if node is None:
            return "unknown"
        if _op(node.op) in {"read", "store", "declare", "merge"} and "symbol" in node.attrs:
            return f"{_op(node.op)}:v{symbols.get(node.attrs['symbol'], -1)}"
        if _op(node.op) == "literal":
            return "literal:" + str(node.attrs.get("value", node.attrs.get("literal")))
        return _op(node.op)

    for node in nodes:
        op = _op(node.op)
        if node.attrs.get("framework_argument"):
            continue
        if op in OPS:
            values[op] += 1
        for index, identifier in enumerate(node.inputs):
            hashed("ordered_operand", f"{op}:{index}:{operand(identifier)}")
        # Includes conversions, overflow/exception policies, modulo sign,
        # formatting and exact rounding modes. Identifier spelling/layout are
        # intentionally absent; numeric types are separate from source names.
        for key, value in node.attrs.items():
            if key not in ignored_attrs and value is not None:
                hashed("semantic_attr", f"{op}:{key}:{json.dumps(value, sort_keys=True)}")
        if node.numeric_type:
            for key, value in node.numeric_type.attrs.items():
                if key != "java_type" and value is not None:
                    hashed("semantic_attr", f"type:{key}:{json.dumps(value, sort_keys=True)}")
        numeric = node.numeric_type
        if numeric:
            kind = numeric.kind.lower()
            if kind in {"decimal", "bigdecimal"}:
                values["decimal"] += 1
            elif kind in {"integer", "int", "long", "short", "byte", "binary_integer"}:
                values["integer"] += 1
            elif kind in {"float", "double", "binary_float"}:
                values["float"] += 1
            elif kind in {"string", "alphanumeric", "edited"}:
                values["string"] += 1
            elif kind in {"bool", "boolean"}:
                values["boolean"] += 1
            values["signed"] += float(numeric.signed is True)
            values["unsigned"] += float(numeric.signed is False)
            # Separate units: decimal precision, decimal scale and binary width.
            values["precision"] += min(numeric.precision or 0, 38) / 38
            values["scale"] += min(abs(numeric.scale or 0), 38) / 38
            values["binary_width"] += min(numeric.bit_width or 0, 128) / 128
        mode = str(node.attrs.get("rounding_mode", node.attrs.get("roundingMode", ""))).upper()
        if mode == "HALF_UP":
            values["round_half_up"] += 1
        elif mode in {"DOWN", "TRUNCATE_TOWARD_ZERO"}:
            values["round_down"] += 1
        elif mode == "FLOOR":
            values["round_floor"] += 1
        elif mode:
            values["round_other"] += 1
        values["unsigned_store"] += float(bool(node.attrs.get("unsignedSignRemoval")))
        values["overflow_store"] += float(bool(node.attrs.get("overflow")))
        operator = str(node.attrs.get("operator", node.attrs.get("comparison", ""))).upper()
        key = {"<": "lt", "<=": "le", "=": "eq", "==": "eq", "!=": "ne", "<>": "ne", ">": "gt", ">=": "ge"}.get(operator)
        if op == "compare" and key:
            values["compare_" + key] += 1
        if op == "literal":
            numeric_value = _number(node.attrs.get("value", node.attrs.get("literal")))
            if numeric_value is not None:
                values["negative_literal"] += float(numeric_value < 0)
                try:
                    magnitude = min(float(abs(numeric_value)), 1e18)
                except (OverflowError, ValueError):
                    magnitude = 1e18
                values["literal_magnitude"] += math.log1p(magnitude) / math.log1p(1e18)
    # No fitted normalization here. Training-only scaling belongs to each fold.
    return np.asarray([values[name] for name in NODE_NAMES], dtype=float)


def _region(ir: ProgramIR, source: str, ids: frozenset[str]) -> Region:
    nodes = [n for n in ir.nodes if n.id in ids]
    start = min(n.span.start_line for n in nodes)
    end = max(n.span.end_line for n in nodes)
    counts = Counter(e.kind for e in ir.edges if e.source in ids and e.target in ids)
    counts["operand_roles"] = sum("operand_index" in e.attrs for e in ir.edges if e.source in ids and e.target in ids)
    # Preserve actual data reachability in the IR; expose a local summary here.
    reverse = defaultdict(set)
    for edge in ir.edges:
        if edge.kind == "data":
            reverse[edge.target].add(edge.source)
    reaching = {n.id for n in ir.nodes if _op(n.op) in {"output", "return"}}
    pending = list(reaching)
    while pending:
        for predecessor in reverse[pending.pop()]:
            if predecessor not in reaching:
                reaching.add(predecessor)
                pending.append(predecessor)
    return Region(start, end, "\n".join(source.split("\n")[start-1:end]), "", set(), _vector(nodes, ir), ids,
                  _literals(nodes), dict(counts), len(ids & reaching) / max(len(ids), 1))


def _regions(ir: ProgramIR, source: str) -> list[Region]:
    # Logical receiver/control/sink roots, not physical lines. A multiline
    # expression and its single-line rendering must have the same ML regions.
    by_id = {node.id: node for node in ir.nodes}
    roots = [node for node in ir.nodes if _op(node.op) in
             {"store", "output", "return", "branch", "loop", "merge", "stop"}]
    ordered = []
    covered = set()
    for root in roots:
        ids = {root.id}
        pending = list(root.inputs)
        while pending:
            identifier = pending.pop()
            if identifier in ids or identifier not in by_id:
                continue
            node = by_id[identifier]
            # Reads retain their explicit definition edge in the full IR, but
            # that predecessor statement is a separate matching region.
            if _op(node.op) in {"declare", "store", "merge", "resource", "structure"}:
                continue
            ids.add(identifier)
            if _op(node.op) != "read":
                pending.extend(node.inputs)
        ordered.append(frozenset(ids))
        covered.update(ids)
    for node in ir.nodes:
        if node.id not in covered and _op(node.op) not in {"declare", "resource", "structure"}:
            ordered.append(frozenset({node.id}))
    # Source-derived dependency clusters allow one-to-many correspondence.
    membership = {node: i for i, ids in enumerate(ordered) for node in ids}
    clusters = set(ordered)
    for edge in ir.edges:
        if edge.kind not in {"data", "control"} or edge.source not in membership or edge.target not in membership:
            continue
        a, b = membership[edge.source], membership[edge.target]
        if a == b:
            continue
        ids = ordered[a] | ordered[b]
        if abs(a-b) <= 3:
            clusters.add(ids)
    if len(clusters) > MAX_REGIONS:
        raise ValueError(f"Source exceeds the {MAX_REGIONS}-region extraction budget")
    result = [_region(ir, source, ids) for ids in clusters]
    return sorted(result, key=lambda r: (r.start, r.end, len(r.node_ids), tuple(sorted(r.node_ids))))


def _extras(c: Region | None, j: Region | None) -> np.ndarray:
    zero = np.zeros(len(NODE_NAMES))
    a, b = c.x if c else zero, j.x if j else zero
    op_a, op_b = a[:len(OPS)], b[:len(OPS)]
    overlap = float(np.minimum(op_a, op_b).sum() / max(np.maximum(op_a, op_b).sum(), 1))
    la, lb = c.literals if c else frozenset(), j.literals if j else frozenset()
    literal_overlap = len(la & lb) / max(len(la | lb), 1)
    ca, cb = c.edge_counts if c else {}, j.edge_counts if j else {}
    return np.asarray([overlap, literal_overlap, (len(la)-len(lb))/10, len(la ^ lb)/max(len(la | lb), 1),
                       (ca.get("data", 0)-cb.get("data", 0))/20,
                       (ca.get("control", 0)-cb.get("control", 0))/20,
                       (ca.get("loop", 0)+ca.get("loop_back", 0)-cb.get("loop", 0)-cb.get("loop_back", 0))/10,
                       (ca.get("operand_roles", 0)-cb.get("operand_roles", 0))/20,
                       ((len(c.node_ids) if c else 0)-(len(j.node_ids) if j else 0))/20,
                       (c.output_reach if c else 0)-(j.output_reach if j else 0)], dtype=float)


def pair_features(c: Region | None, j: Region | None) -> np.ndarray:
    zero = np.zeros(len(NODE_NAMES))
    return np.r_[(c.x if c else zero)-(j.x if j else zero), _extras(c, j)]


def _coverage(ir: ProgramIR) -> dict:
    return {"status": ir.status, "nodes": len(ir.nodes), "edges": len(ir.edges),
            "issues": [issue.to_dict() for issue in ir.issues], "details": ir.attrs,
            "isProof": False, "codeExecuted": False}


def extract_pair(cobol: str, java: str, source_format: str = "FREE") -> PairGraph:
    from .cobol_extractor_v2 import extract_cobol
    from .java_extractor_v2 import extract_java
    for source in (cobol, java):
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Nonempty source strings are required")
    if source_format not in {"FREE", "FIXED"}:
        raise ValueError("Source format must be FREE or FIXED")
    coverage = {}
    ci = ji = None
    try:
        if max(len(cobol.encode()), len(java.encode())) > MAX_SOURCE_BYTES:
            raise ValueError("Source exceeds the 200000-byte extraction budget")
        ci, ji = extract_cobol(cobol, source_format), extract_java(java)
        coverage = {"cobol": _coverage(ci), "java": _coverage(ji)}
        c, j = _regions(ci, cobol), _regions(ji, java)
    except (ValueError, RecursionError) as exc:
        coverage["extractionError"] = {"message": str(exc), "requiresReview": True}
        return PairGraph([], [], [], np.empty((0, len(PAIR_NAMES))), np.zeros(len(GLOBAL_NAMES)), "ABSTAIN", coverage, ci, ji)
    status = "SUPPORTED" if ci.status == ji.status == "COMPLETE" and c and j else "ABSTAIN"
    if not c or not j:
        return PairGraph(c, j, [], np.empty((0, len(PAIR_NAMES))), np.zeros(len(GLOBAL_NAMES)), "ABSTAIN", coverage, ci, ji)
    similarities = np.asarray([[float(_extras(a, b)[0]) for b in j] for a in c])
    pairs: set[tuple[int | None, int | None]] = set()
    for a in range(len(c)):
        pairs.update((a, int(b)) for b in np.argsort(-similarities[a], kind="stable")[:3])
    for b in range(len(j)):
        pairs.update((int(a), b) for a in np.argsort(-similarities[:, b], kind="stable")[:3])
    pairs.update((a, None) for a in range(len(c)))
    pairs.update((None, b) for b in range(len(j)))
    candidates = sorted(pairs, key=lambda p: (-1 if p[0] is None else p[0], -1 if p[1] is None else p[1]))
    px = np.asarray([pair_features(c[a] if a is not None else None, j[b] if b is not None else None) for a, b in candidates])
    whole_c = _region(ci, cobol, frozenset(n.id for n in ci.nodes if _op(n.op) not in {"declare", "resource", "structure"}))
    whole_j = _region(ji, java, frozenset(n.id for n in ji.nodes if _op(n.op) not in {"declare", "resource", "structure"}))
    nearest = [pair_features(c[a], j[int(np.argmax(similarities[a]))]) for a in range(len(c))]
    distances = np.asarray([np.mean(np.abs(x[:len(NODE_NAMES)])) for x in nearest])
    gx = np.r_[pair_features(whole_c, whole_j), distances.mean(), distances.max(), distances.min()]
    assert px.shape[1] == len(PAIR_NAMES) and gx.shape == (len(GLOBAL_NAMES),)
    return PairGraph(c, j, candidates, px, gx, status, coverage, ci, ji)


def supervision(graph: PairGraph, cobol_spans: list[tuple[int, int]], java_spans: list[tuple[int, int]]) -> np.ndarray:
    """Training-only weak spans; retained as weak labels, never proof or inputs."""
    def hit(region, spans):
        return region is not None and any(region.start <= end and region.end >= start for start, end in spans)
    labels = []
    for ci, ji in graph.candidates:
        c = graph.cobol[ci] if ci is not None else None
        j = graph.java[ji] if ji is not None else None
        labels.append(bool(hit(c, cobol_spans) and hit(j, java_spans)) if cobol_spans and java_spans
                      else bool(ji is None and hit(c, cobol_spans)) if cobol_spans
                      else bool(ci is None and hit(j, java_spans)) if java_spans else False)
    return np.asarray(labels, dtype=int)
