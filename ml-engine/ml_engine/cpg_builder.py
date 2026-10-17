"""Small source-derived AST/CFG/type-flow CPGs; unsupported syntax stays visible."""
from __future__ import annotations

import re

import networkx as nx
import numpy as np

from .semantics import normalize_cobol_source, strip_comments

FEATURE_NAMES = ["is_fixed_point_comp3", "is_ieee754_float", "is_big_decimal", "decimal_scale",
                 "has_rounding_clause", "is_loop_branch", "is_external_call", "pca_structural_residual"]


def features(text: str, language: str) -> list[float]:
    upper = text.upper()
    picture = re.search(r"V(9\((\d+)\)|9+)", upper)
    scale = int(picture[2]) if picture and picture[2] else len(picture[1]) if picture else 0
    set_scale = re.search(r"setScale\((\d+)", text)
    if set_scale:
        scale = int(set_scale[1])
    return [float("COMP-3" in upper), float(bool(re.search(r"\b(?:double|float)\b", text))),
            float("BigDecimal" in text), min(scale / 8, 1.0),
            float("ROUNDED" in upper or "RoundingMode" in text or "Math.round" in text),
            float(bool(re.search(r"\b(?:IF|PERFORM|IF|WHILE|FOR)\b", upper))),
            float(bool(re.search(r"EXEC\s+CICS|\bJCL\b|REDEFINES|receiveMap", text, re.I))), 0.0]


def build_cpg(source: str, language: str, source_format: str = "FREE") -> nx.DiGraph:
    if language not in ("cobol", "java"):
        raise ValueError("language must be cobol or java")
    graph = nx.MultiDiGraph(language=language, extractor="restricted-source-cpg-v1")
    text = normalize_cobol_source(source, source_format) if language == "cobol" else strip_comments(source, language)
    root = f"{language}:root"
    graph.add_node(root, label=language.upper(), kind="program", language=language,
                   line=1, features=features(text, language), riskScore=0.0)
    parent = root
    previous = None
    declared: dict[str, str] = {}
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        field = re.search(r"\b01\s+([\w-]+)\s+PIC", line, re.I) if language == "cobol" else re.search(r"\b(BigDecimal|double|float)\s+(\w+)\s*(?:=|,|\))", line)
        paragraph = re.fullmatch(r"([A-Z][A-Z0-9-]*)\.", line) if language == "cobol" else None
        method = re.search(r"\b(?:public|private|protected)\s+(?:static\s+)?(?:BigDecimal|double|void)\s+(\w+)\s*\(", line) if language == "java" else None
        kind = "field" if field else "paragraph" if paragraph else "method" if method else "statement"
        node_id = f"{language}:{line_number}"
        label = paragraph[1] if paragraph else method[1] if method else line[:160]
        graph.add_node(node_id, label=label, sourceText=line, kind=kind, language=language,
                       line=line_number, features=features(line, language), riskScore=0.0)
        if kind in ("paragraph", "method"):
            parent = node_id
            graph.add_edge(root, node_id, kind="AST")
        else:
            graph.add_edge(parent, node_id, kind="AST")
        if previous and kind != "field":
            graph.add_edge(previous, node_id, kind="CFG")
        if field:
            declared[field[1] if language == "cobol" else field[2]] = node_id
        for variable, declaration in declared.items():
            if node_id != declaration and re.search(r"(?<![\w-])" + re.escape(variable) + r"(?![\w-])", line):
                graph.add_edge(declaration, node_id, kind="TYPE_FLOW")
        previous = node_id
    # PCA residual of local structural descriptors, calculated rather than invented.
    nodes = list(graph)
    structural = np.array([[graph.in_degree(n), graph.out_degree(n),
                            sum(graph.nodes[m]["kind"] == "statement" for m in graph.successors(n))]
                           for n in nodes], dtype=float)
    centered = structural - structural.mean(axis=0)
    if len(nodes) > 2:
        u, s, vt = np.linalg.svd(centered, full_matrices=False)
        residual = np.linalg.norm(centered - (u[:, :2] * s[:2]) @ vt[:2], axis=1)
        for node, value in zip(nodes, residual / (1 + residual), strict=True):
            graph.nodes[node]["features"][7] = float(value)
    return graph


def combined_graph_json(cobol: nx.DiGraph, java: nx.DiGraph, alignments: list[dict]) -> dict:
    return {"featureNames": FEATURE_NAMES,
            "extractorScope": "Line AST/CFG/type-use approximation; formal parser independently validates all syntax.",
            "nodes": [{"id": node, **attributes} for graph in (cobol, java) for node, attributes in graph.nodes(data=True)],
            "edges": [{"source": a, "target": b, **attributes} for graph in (cobol, java) for a, b, attributes in graph.edges(data=True)] + alignments}


def baseline(cobol_source: str, java_source: str) -> tuple[float, bool]:
    # Intentionally naive name overlap, with a separately explicit dangerous-API rule.
    keywords = {"public", "class", "final", "return", "if", "else", "double", "bigdecimal", "rounded",
                "compute", "pic", "comp", "division", "section", "program", "identification", "data", "procedure"}
    def names(text):
        return {token.lower().replace("-", "") for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text)} - keywords
    first, second = names(cobol_source), names(java_source)
    score = len(first & second) / max(len(first | second), 1)
    caught = bool(re.search(r"new\s+BigDecimal\s*\(\s*\d+\.\d+\s*\)|parseFloat\s*\(", java_source))
    return round(score, 6), caught
