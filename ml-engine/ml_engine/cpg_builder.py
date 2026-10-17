"""Typed graphs from the supported AST; unsupported syntax remains an explicit approximation."""
from __future__ import annotations

import re
from collections import Counter

import networkx as nx
import numpy as np

from .policy import MAX_GRAPH_NODES
from .semantics import UnsupportedSemantics, parse_cobol, parse_java, strip_comments

FEATURE_NAMES = ["is_fixed_point_comp3", "is_ieee754_float", "is_big_decimal", "decimal_scale",
                 "has_rounding_clause", "is_loop_branch", "is_external_call", "pca_structural_residual"]
METHOD = re.compile(r"\b(?:public|private|protected)\s+(?:static\s+)?(BigDecimal|double|void)\s+(\w+)\s*\(")
KEYWORDS = {"GOBACK", "EXIT", "END-IF", "ELSE", "STOP RUN"}
OPERATORS = {"multiply": "*", "add": "+", "subtract": "-", "compareTo": "compare", "remainder": "%"}


def features(text: str, language: str) -> list[float]:
    upper = text.upper()
    picture = re.search(r"V(9\((\d+)\)|9+)", upper)
    scale = int(picture[2]) if picture and picture[2] else len(picture[1]) if picture else 0
    set_scale = re.search(r"setScale\(\s*(\d+)", text)
    if set_scale:
        scale = int(set_scale[1])
    return [float("COMP-3" in upper), float(bool(re.search(r"\b(?:double|float)\b", text))),
            float("BigDecimal" in text), min(scale / 8, 1.0),
            float("ROUNDED" in upper or "RoundingMode" in text or "Math.round" in text),
            float(bool(re.search(r"\b(?:IF|PERFORM|WHILE|FOR)\b", upper))),
            float(bool(re.search(r"EXEC\s+CICS|\bJCL\b|REDEFINES|receiveMap", text, re.I))), 0.0]


def expression_semantics(node) -> dict:
    operators, constants, variables, rounding, scales = [], [], [], [], []
    def visit(item):
        kind = item[0]
        if kind in ("number", "decimal", "string"):
            constants.append(item[1])
        elif kind == "var":
            variables.append(item[1])
        elif kind == "binary":
            operators.append(item[1]); visit(item[2]); visit(item[3])
        elif kind in ("neg", "decimal_from_double"):
            operators.append("negate" if kind == "neg" else "BigDecimal(double)"); visit(item[1])
        elif kind == "member":
            visit(item[1])
            if item[1] == ("var", "RoundingMode"):
                rounding.append(item[2])
        elif kind == "call":
            operators.append(OPERATORS.get(item[2], item[2])); visit(item[1])
            for arg in item[3]: visit(arg)
            if item[2] == "setScale" and item[3] and item[3][0][0] == "number":
                scales.append(item[3][0][1])
    visit(node)
    return {"operators": operators, "constants": constants, "variables": sorted(set(variables)),
            "rounding": rounding, "scales": scales}


def build_cpg(source: str, language: str) -> nx.MultiDiGraph:
    if language not in ("cobol", "java"):
        raise ValueError("language must be cobol or java")
    graph = nx.MultiDiGraph(language=language, extractor="bounded-typed-ast-v2")
    text = strip_comments(source, language)
    root = f"{language}:root"
    graph.add_node(root, label=language.upper(), kind="program", language=language,
                   line=1, features=features(text, language), riskScore=0.0)
    counter = 0
    declarations = {}
    def add(kind, label, source_text="", line=None, **metadata):
        nonlocal counter
        if len(graph) >= MAX_GRAPH_NODES:
            raise UnsupportedSemantics("Graph node budget exceeded", "limit.graph_nodes")
        counter += 1
        node_id = f"{language}:node:{counter}"
        graph.add_node(node_id, label=label, kind=kind, language=language, sourceText=source_text,
                       line=line, features=features(source_text, language), riskScore=0.0, **metadata)
        return node_id
    def source_line(pattern):
        return next((i for i, line in enumerate(text.splitlines(), 1) if re.search(pattern, line)), None)
    def edge(a, b, kind, **attrs): graph.add_edge(a, b, kind=kind, **attrs)
    def read_edges(expression, target):
        for variable in expression_semantics(expression)["variables"]:
            if variable in declarations:
                field = declarations[variable]
                attrs = {"variable": variable.replace("__", "-"), "declaredType": graph.nodes[field].get("declaredType"),
                         "decimalScale": graph.nodes[field].get("decimalScale")}
                edge(field, target, "READS", **attrs)
                edge(field, target, "TYPE_FLOW", **attrs)
                edge(field, target, "DATA_FLOW", **attrs)
    def expression_node(expression, owner, line=None):
        sem = expression_semantics(expression)
        semantic_text = " ".join(sem["operators"] + sem["rounding"])
        if sem["scales"]: semantic_text += " setScale(" + sem["scales"][0]
        node = add("expression", expression[0], semantic_text, line=line, semantics=sem)
        inherited = [graph.nodes[declarations[name]]["features"] for name in sem["variables"] if name in declarations]
        if inherited:
            graph.nodes[node]["features"] = np.maximum(graph.nodes[node]["features"],np.max(inherited,axis=0)).tolist()
        edge(owner, node, "AST"); read_edges(expression, node)
        # Expression children retain actual operator tree structure.
        children = []
        if expression[0] == "binary": children = [expression[2], expression[3]]
        elif expression[0] in ("neg", "decimal_from_double", "member"): children = [expression[1]]
        elif expression[0] == "call": children = [expression[1], *expression[3]]
        for child in children: expression_node(child, node, line)
        return node
    def statements(items, owner, previous=None):
        exits = [previous or owner]
        for item in items:
            kind = item[0]
            if kind == "store":
                name, expr, rounded = item[1:]
                line = source_line(r"\b(?:COMPUTE|MOVE)\b.*" + re.escape(name.replace("__", "-")))
                node = add("statement", "COMPUTE/MOVE", "ROUNDED" if rounded else "", line, operation="store", target=name)
                expression_node(expr, node, line)
                if name in declarations:
                    field = declarations[name]
                    edge(node, field, "WRITES", declaredType=graph.nodes[field].get("declaredType"), decimalScale=graph.nodes[field].get("decimalScale"))
                    edge(node, field, "DATA_FLOW", variable=name.replace("__", "-"))
            elif kind in ("let", "return"):
                expr = item[2] if kind == "let" else item[1]
                line = source_line(r"\breturn\b" if kind == "return" else re.escape(item[1]) + r"\s*=")
                node = add("statement", kind, line=line, operation=kind)
                expression_node(expr, node, line)
                if kind == "let":
                    name, declared = item[1], item[3]
                    field = add("field", name, declared, line, declaredType=declared, typeFamily=declared, decimalScale=None)
                    declarations[name] = field
                    edge(owner, field, "AST"); edge(node, field, "WRITES", declaredType=declared); edge(node, field, "DATA_FLOW", variable=name)
            elif kind == "if":
                node = add("branch", "IF", "IF", source_line(r"\b(?:IF|if)\b"), operation="branch")
                expression_node(item[1], node)
            elif kind == "perform":
                node = add("statement", f"PERFORM {item[1]} THRU {item[2]}", "PERFORM", operation="perform", start=item[1], stop=item[2])
            else:
                node = add("statement", kind.upper(), operation=kind)
            edge(owner, node, "AST")
            for prior in exits: edge(prior, node, "CFG")
            if kind == "if":
                yes = add("block", "true branch"); no = add("block", "false branch")
                edge(node, yes, "CFG", branch=True); edge(node, no, "CFG", branch=False)
                edge(node, yes, "AST"); edge(node, no, "AST")
                exits = statements(item[2], yes) + statements(item[3], no)
            else:
                exits = [] if kind in ("halt", "return") else [node]
        return exits
    try:
        if language == "cobol":
            program = parse_cobol(source)
            for index, field in enumerate(program.fields):
                name = field.name.replace("__", "-")
                line = source_line(r"\b01\s+" + re.escape(name) + r"\s+PIC")
                storage = next((raw for raw in text.splitlines() if re.search(r"\b01\s+" + re.escape(name) + r"\s+PIC", raw, re.I)), "")
                node = add("field", name, storage, line, declaredType="COMP-3" if "COMP-3" in storage.upper() else "DISPLAY_DECIMAL",
                           typeFamily="fixed_point", decimalScale=field.scale, integralDigits=field.integral, signed=field.signed,
                           role="amount" if index == 0 else "rate" if index == 1 else "result" if index == len(program.fields)-1 else "local")
                declarations[field.name] = node; edge(root, node, "AST")
            paragraphs = {}
            for name in program.paragraphs:
                node = add("paragraph", name, line=source_line(r"^\s*"+re.escape(name)+r"\.\s*$"))
                paragraphs[name] = node; edge(root, node, "AST")
            last_exits = []
            for name, items in program.paragraphs.items():
                for prior in last_exits: edge(prior, paragraphs[name], "CFG", flow="fallthrough")
                last_exits = statements(items, paragraphs[name])
            order = list(paragraphs)
            for node, attrs in list(graph.nodes(data=True)):
                if attrs.get("operation") == "perform":
                    start, stop = attrs["start"], attrs["stop"]
                    if start in order and stop in order:
                        for name in order[order.index(start):order.index(stop)+1]: edge(node, paragraphs[name], "CALL", rangeStart=start, rangeEnd=stop)
        else:
            program = parse_java(source)
            signature = METHOD.search(text)
            name = signature[2] if signature else "calculation"
            method = add("method", name, f"public {program.return_type}", source_line(r"\b"+re.escape(name)+r"\s*\("), declaredType=program.return_type)
            edge(root, method, "AST")
            for index, (declared, name) in enumerate(program.parameters):
                field = add("parameter", name, declared, graph.nodes[method]["line"], declaredType=declared, typeFamily=declared,
                            decimalScale=None, role="amount" if index == 0 else "rate")
                declarations[name] = field; edge(method, field, "AST"); edge(field, method, "PARAMETER", position=index, declaredType=declared)
            statements(program.statements, method)
        graph.graph["semanticExtraction"] = {"status": "SUPPORTED_AST", "scope": "closed scalar grammar; typed use/definition and structured control edges"}
    except (UnsupportedSemantics, ValueError, RecursionError) as error:
        # Approximation is visible, and never used to authorize formal proof.
        graph = nx.MultiDiGraph(language=language, extractor="bounded-source-approximation-v2")
        graph.add_node(root, label=language.upper(), kind="program", language=language, line=1, features=features(text, language), riskScore=0.0)
        graph.graph["semanticExtraction"] = {"status": "LIMIT_EXCEEDED" if str(getattr(error, "code", "")).startswith("limit.") else "SOURCE_APPROXIMATION", "reason": str(error), "reasonCode": getattr(error, "code", "semantics.unsupported")}
        parent = root
        for number, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line or len(graph) >= MAX_GRAPH_NODES: continue
            method = METHOD.search(line) if language == "java" else None
            paragraph = re.fullmatch(r"([A-Z][A-Z0-9-]*)\.", line) if language == "cobol" else None
            if paragraph and paragraph[1] in KEYWORDS: paragraph = None
            field = re.search(r"\b01\s+([\w-]+)\s+PIC", line, re.I) if language == "cobol" else None
            kind = "method" if method else "paragraph" if paragraph else "field" if field else "statement"
            node = add(kind, method[2] if method else paragraph[1] if paragraph else line[:120], line, number)
            edge(parent if kind not in ("method", "paragraph") else root, node, "AST")
            if kind in ("method", "paragraph"): parent = node
    # Pool source-derived node semantics for inspectable function-level comparison.
    ast_graph = nx.DiGraph()
    ast_graph.add_nodes_from(graph)
    ast_graph.add_edges_from((a,b) for a,b,d in graph.edges(data=True) if d['kind'] == 'AST')
    for node, attributes in list(graph.nodes(data=True)):
        if attributes["kind"] not in ("method", "paragraph"): continue
        children = nx.descendants(ast_graph, node)
        semantics = {key: [] for key in ("operators", "constants", "rounding", "scales")}
        for child in children:
            for key in semantics: semantics[key].extend(graph.nodes[child].get("semantics", {}).get(key, []))
        attributes["semantics"] = {key: sorted(set(values)) for key, values in semantics.items()}
        local = [graph.nodes[child]["features"] for child in children]
        if local: attributes["features"] = np.maximum(attributes["features"], np.max(local,axis=0)).tolist()
    nodes = list(graph)
    structural = np.array([[graph.in_degree(n), graph.out_degree(n), sum(graph.nodes[m]["kind"] == "statement" for m in graph.successors(n))] for n in nodes], dtype=float)
    centered = structural - structural.mean(axis=0)
    if len(nodes) > 2:
        u, s, vt = np.linalg.svd(centered, full_matrices=False)
        residual = np.linalg.norm(centered - (u[:, :2] * s[:2]) @ vt[:2], axis=1)
        for node, value in zip(nodes, residual/(1+residual), strict=True): graph.nodes[node]["features"][7] = float(value)
    return graph


def deterministic_diagnostics(cobol, java):
    result = []
    if any(a.get("typeFamily") == "fixed_point" for _,a in cobol.nodes(data=True)) and any(a.get("declaredType") == "double" for _,a in java.nodes(data=True)):
        result.append({"code":"types.fixed_point_to_ieee754", "severity":"warning", "origin":"deterministic_type_rule", "message":"COBOL fixed-point storage crosses a Java double boundary; binary conversion and rounding require inspection."})
    c_ops = {op for _,a in cobol.nodes(data=True) for op in a.get("semantics",{}).get("operators",[]) if op in ("*","+","-","/")}
    j_ops = {op for _,a in java.nodes(data=True) for op in a.get("semantics",{}).get("operators",[]) if op in ("*","+","-","/")}
    if c_ops - j_ops:
        result.append({"code":"logic.operator_difference", "severity":"warning", "origin":"deterministic_ast_rule", "message":"Arithmetic operators differ between the parsed source graphs; Z3 determines whether this changes the result.", "cobolOperators":sorted(c_ops),"javaOperators":sorted(j_ops)})
    return result


def combined_graph_json(cobol, java, alignments):
    return {"featureNames":FEATURE_NAMES, "extractorScope":"Typed AST/use-definition/structured control graph for the supported scalar grammar; unsupported syntax is labelled as an approximation.",
            "semanticExtraction": {"cobol":cobol.graph["semanticExtraction"],"java":java.graph["semanticExtraction"]},
            "deterministicDiagnostics":deterministic_diagnostics(cobol,java),
            "nodes":[{"id":node,**attrs} for g in (cobol,java) for node,attrs in g.nodes(data=True)],
            "edges":[{"source":a,"target":b,**attrs} for g in (cobol,java) for a,b,attrs in g.edges(data=True)]+alignments}


def baseline(cobol_source, java_source):
    keywords={"public","class","final","return","if","else","double","bigdecimal","rounded","compute","pic","comp","division","section","program","identification","data","procedure"}
    def names(text): return {token.lower().replace("-","") for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]*",text)}-keywords
    first,second=names(cobol_source),names(java_source)
    caught=bool(re.search(r"new\s+BigDecimal\s*\(\s*\d+\.\d+\s*\)|parseFloat\s*\(",java_source))
    return round(len(first&second)/max(len(first|second),1),6),caught
