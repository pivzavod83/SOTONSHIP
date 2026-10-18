"""Source-only, bounded statement/dependency graph features for a learned pilot.

This is a heuristic graph extractor, not a compiler or a trained GNN. Identifiers
are used only for local def/use edges and cross-language similarity. Labels,
provided alignments, test outputs and family identifiers are never inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import numpy as np

FEATURE_VERSION = "source-graph-v1"
OPS = ("add", "subtract", "multiply", "divide", "modulo", "absolute", "minimum", "maximum", "compare", "branch", "loop", "assign")
NODE_NAMES = (*OPS, "half_up", "down", "floor", "explicit_scale", "scale", "unsigned", "signed", "decimal", "integer", "width", "zero", "one", "two", "literal_count", "literal_magnitude", "power_ten", "round_bias", "input_degree", "output_degree")
PAIR_NAMES = ("cobol_present", "java_present", "target_similarity", "dependency_similarity", "operation_similarity", "position_distance", *["c_"+n for n in NODE_NAMES], *["j_"+n for n in NODE_NAMES], *["difference_"+n for n in NODE_NAMES], *["absolute_difference_"+n for n in NODE_NAMES], "round_mode_disagreement", "scale_disagreement", "signed_abs", "unsigned_no_abs", "storage_width_reduction")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:-[A-Za-z_0-9]+)*")
KEYWORDS = set("compute rounded function numval move to add subtract from giving multiply divide into if else end then perform until varying times accept display stop run and or not integer bigdecimal long int double math roundingmode half_up down floor new setscale divide multiply subtract add remainder abs min max valueof parseint parselong compareto signum tostring true false".split())


@dataclass
class Statement:
    start: int
    end: int
    text: str
    target: str
    uses: set[str]
    x: np.ndarray


@dataclass
class PairGraph:
    cobol: list[Statement]
    java: list[Statement]
    candidates: list[tuple[int | None, int | None]]
    candidate_x: np.ndarray
    global_x: np.ndarray


def _identifier(value: str) -> str:
    value = re.sub(r"[^a-z0-9]", "", value.lower())
    for suffix in ("value", "amount", "cents", "units", "pips", "amt", "bp"):
        if value.endswith(suffix) and len(value) > len(suffix)+1:
            value = value[:-len(suffix)]
    return value


def _clean_lines(source: str, language: str, source_format: str) -> list[str]:
    # Preserve line positions, including blank/comment lines and CRLF inputs.
    if language == "java":
        source = re.sub(r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|/\*.*?\*/|//[^\n]*',
                        lambda m: m.group(1) or "\n"*m.group().count("\n"), source, flags=re.S)
    result = []
    for raw in source.split("\n"):
        line = raw.rstrip("\r")
        if language == "cobol":
            if source_format == "FIXED":
                line = "" if line[6:7] in ("*", "/") else line[7:72]
            line = line.split("*>", 1)[0]
        result.append(line)
    return result


def _picture(value: str) -> tuple[int, int, bool]:
    whole, _, fraction = value.lower().lstrip("s").partition("v")
    def count(part: str) -> int:
        return sum(int(m.group(1) or 1) for m in re.finditer(r"9(?:\((\d+)\))?", part))
    return count(whole), count(fraction), value.lower().startswith("s")


def statements(source: str, language: str, source_format: str = "FREE") -> list[Statement]:
    lines = _clean_lines(source, language, source_format)
    declarations: dict[str, tuple[int, int, bool]] = {}
    constants: dict[str, str] = {}
    result: list[Statement] = []
    if language == "cobol":
        for line in lines:
            match = re.search(r"\b\d+\s+([\w-]+)\s+PIC(?:TURE)?\s+(S?9[9V()0-9]*)", line, re.I)
            if match:
                declarations[match.group(1).lower()] = _picture(match.group(2))
    for line_no, raw in enumerate(lines, 1):
        text = raw.strip()
        lower = text.lower()
        if not text:
            continue
        if language == "cobol":
            if not re.match(r"(?:compute|move|add|subtract|multiply|divide|if|perform)\b", lower) or "numval" in lower:
                continue
            if re.search(r"\bto\s+out[\w-]*", lower):
                continue
            target_match = re.search(r"^compute\s+([\w-]+)|\bto\s+([\w-]+)|\bgiving\s+([\w-]+)", lower)
        else:
            if any(token in lower for token in ("nextline(", "system.out", "scanner ")):
                continue
            if re.match(r"(?:import|package|public|private|class)\b", lower) or lower in ("}", "};", "{"):
                continue
            target_match = re.search(r"(?:^|\s)([A-Za-z_]\w*)\s*(?:[+\-*/%]?=)(?!=)", text)
            if not target_match and not re.match(r"(?:if|while|for)\s*\(", lower):
                continue
            if target_match and re.fullmatch(r'\s*(?:BigDecimal|long|int|double)\s+\w+\s*=\s*(?:new BigDecimal\("[\d.]+"\)|[\d.]+[Ll]?)\s*;\s*', text):
                value = re.search(r'"([\d.]+)"|=\s*([\d.]+)', text)
                constants[target_match.group(1)] = next(g for g in value.groups() if g is not None)
        target = next((g for g in target_match.groups() if g), "") if target_match else ""
        x = np.zeros(len(NODE_NAMES), dtype=float)
        def put(name: str, value: float = 1.0):
            x[NODE_NAMES.index(name)] = value
        expr = re.sub(r'"([\d.]+)"', r"\1", text)
        for key, value in constants.items():
            expr = re.sub(r"\b"+re.escape(key)+r"\b", value, expr)
        arithmetic = re.sub(r"[A-Za-z_][A-Za-z_0-9]*(?:-[A-Za-z_0-9]+)*", " V ", expr) if language == "cobol" else expr
        patterns = {"add":r"\+|\badd\b|\.add\s*\(", "subtract":r"(?<![A-Za-z0-9])-(?![A-Za-z])|\bsubtract\b|\.subtract\s*\(", "multiply":r"\*|\.multiply\s*\(", "divide":r"/|\.divide(?:ToIntegralValue)?\s*\(", "modulo":r"%|\.remainder\s*\(|\bmod\s*\(", "absolute":r"\.abs\s*\(|\babs\s*\(|<\s*0\w*\s*\?\s*-", "minimum":r"\.min\s*\(", "maximum":r"\.max\s*\(", "compare":r"<|>|==|!=|compareTo", "branch":r"\bif\b|\?", "loop":r"\bperform\b|\bwhile\b|\bfor\b", "assign":r"(?<![<>=!])=(?!=)|\bmove\b|\bto\b"}
        for op, pattern in patterns.items():
            keyword = language == "cobol" and bool(re.search(r"\b"+op+r"\b",lower))
            put(op, float(keyword or bool(re.search(pattern, arithmetic, re.I))))
        if language == "cobol":
            put("assign",float(bool(re.search(r"\b(?:move|compute|to|giving)\b|=",lower))))
            put("branch",float(bool(re.match(r"if\b",lower))))
            put("loop",float(bool(re.match(r"perform\b",lower))))
        if language == "cobol":
            width, scale, signed = declarations.get(target.lower(), (0, 0, False))
            put("width", min(width, 18)/18)
            put("scale", min(scale, 8)/8)
            put("unsigned", float(bool(width) and not signed))
            put("signed", float(signed))
            put("decimal", float(scale > 0))
            put("integer", float(bool(width) and scale == 0))
            put("explicit_scale", float(bool(width)))
            put("half_up", float("rounded" in lower))
            put("down", float(bool(width) and "rounded" not in lower))
        else:
            put("decimal", float("bigdecimal" in lower))
            put("integer", float(bool(re.search(r"\b(?:long|int)\b", lower))))
            put("signed", float(bool(re.search(r"\b(?:long|int)\b", lower))))
            put("width", 64/128 if "long " in lower else 32/128 if "int " in lower else 0)
            put("half_up", float("half_up" in lower))
            put("down", float("roundingmode.down" in lower or bool(re.search(r"\b(?:long|int)\b.* / ", lower))))
            put("floor", float("roundingmode.floor" in lower or "floordiv" in lower))
            scale_match = re.search(r"\.setScale\(\s*(\d+)|\.divide\([^;]*?,\s*(\d+)\s*,\s*RoundingMode", text)
            if scale_match:
                put("explicit_scale")
                put("scale", min(int(next(g for g in scale_match.groups() if g is not None)), 8)/8)
            # A positive bias before fixed-point integer division is a source
            # feature, not a verdict that it implements the correct rounding.
            if re.search(r"\+\s*\d+[Ll]?\s*\)*\s*/", expr):
                put("round_bias")
                put("half_up")
                put("down", 0)
        numbers = [float(v) for v in re.findall(r"(?<![A-Za-z_\d])\d+(?:\.\d+)?", expr)]
        for value, name in ((0, "zero"), (1, "one"), (2, "two")):
            put(name, float(value in numbers))
        put("literal_count", min(len(numbers), 12)/12)
        put("literal_magnitude", min(np.log1p(max(numbers, default=0)), 20)/20)
        put("power_ten", float(any(v >= 10 and abs(np.log10(v)-round(np.log10(v))) < 1e-9 for v in numbers)))
        uses = {v.lower() for v in IDENTIFIER.findall(text) if v.lower() not in KEYWORDS and v.lower() != target.lower()}
        result.append(Statement(line_no, line_no, text, target.lower(), uses, x))
        if len(result) > 160:
            raise ValueError("Source exceeds the pilot's 160-statement graph budget")
    # Directed def/use edges, pooled into local in/out degrees.
    latest: dict[str, int] = {}
    for i, node in enumerate(result):
        parents = {latest[v] for v in node.uses if v in latest}
        node.x[NODE_NAMES.index("input_degree")] = min(len(parents), 8)/8
        for j in parents:
            result[j].x[NODE_NAMES.index("output_degree")] += 1/8
        if node.target:
            latest[node.target] = i
    return result


def _similarity(c: Statement, j: Statement) -> tuple[float, float, float]:
    a, b = _identifier(c.target), _identifier(j.target)
    name = SequenceMatcher(None, a, b).ratio() if a and b else 0
    ca, ja = {_identifier(v) for v in c.uses}, {_identifier(v) for v in j.uses}
    dep = sum(max((SequenceMatcher(None, v, w).ratio() for w in ja), default=0) for v in ca)/max(len(ca), 1)
    cop, jop = c.x[:len(OPS)], j.x[:len(OPS)]
    operation = float(np.minimum(cop, jop).sum()/max(np.maximum(cop, jop).sum(), 1))
    return name, dep, operation


def pair_features(c: Statement | None, j: Statement | None, nc: int, nj: int) -> np.ndarray:
    cx = c.x if c else np.zeros(len(NODE_NAMES))
    jx = j.x if j else np.zeros(len(NODE_NAMES))
    sim = _similarity(c, j) if c and j else (0., 0., 0.)
    position = abs(c.start/max(nc, 1)-j.start/max(nj, 1)) if c and j else 1
    get = lambda vector, name: vector[NODE_NAMES.index(name)]
    round_diff = abs(get(cx,"half_up")-get(jx,"half_up")) + abs(get(cx,"down")-get(jx,"down"))
    scale_diff = abs(get(cx,"scale")-get(jx,"scale"))*get(jx,"explicit_scale")
    return np.r_[float(c is not None), float(j is not None), sim, position, cx, jx, cx-jx, abs(cx-jx), round_diff, scale_diff,
                 get(cx,"signed")*get(jx,"absolute"), get(cx,"unsigned")*(1-get(jx,"absolute")), max(get(cx,"width")-get(jx,"width"), 0)]


def extract_pair(cobol: str, java: str, source_format: str = "FREE") -> PairGraph:
    c, j = statements(cobol, "cobol", source_format), statements(java, "java")
    if not c or not j:
        raise ValueError("No supported computational statements found in one or both sources")
    # Candidate correspondence is inferred from sources, never read from labels.
    scores = np.array([[sum(w*s for w,s in zip((.6,.2,.2), _similarity(a,b))) for b in j] for a in c])
    pairs: set[tuple[int | None,int | None]] = set()
    for ci in range(len(c)):
        for ji in np.argsort(-scores[ci], kind="stable")[:2]:
            pairs.add((ci, int(ji)))
    for ji in range(len(j)):
        ci = int(np.argmax(scores[:,ji]))
        pairs.add((ci, ji))
    pairs.update((ci, None) for ci in range(len(c)))
    pairs.update((None, ji) for ji in range(len(j)))
    ordered = sorted(pairs, key=lambda p: (-1 if p[0] is None else p[0], -1 if p[1] is None else p[1]))
    px = np.array([pair_features(c[ci] if ci is not None else None, j[ji] if ji is not None else None, len(cobol.split("\n")),len(java.split("\n"))) for ci,ji in ordered])
    cx, jx = np.array([n.x for n in c]), np.array([n.x for n in j])
    # Compare nearest source-derived correspondences rather than arbitrary
    # Cartesian products. Extra and missing statements remain ranker candidates.
    nearest = np.array([pair_features(c[int(np.argmax(scores[:,ji]))], node, len(cobol.split("\n")),len(java.split("\n"))) for ji,node in enumerate(j)])
    global_x = np.r_[cx.mean(0), jx.mean(0), abs(cx.mean(0)-jx.mean(0)), cx.sum(0)-jx.sum(0), nearest.mean(0), nearest.max(0), len(c)/20, len(j)/20]
    return PairGraph(c, j, ordered, px, global_x)


def supervision(graph: PairGraph, cobol_spans: list[tuple[int,int]], java_spans: list[tuple[int,int]]) -> np.ndarray:
    """Training-only weak span supervision; annotations are not semantic gold."""
    def hit(node: Statement | None, spans: list[tuple[int,int]]) -> bool:
        return bool(node and any(node.start <= end and node.end >= start for start,end in spans))
    labels = []
    for ci, ji in graph.candidates:
        cn, jn = graph.cobol[ci] if ci is not None else None, graph.java[ji] if ji is not None else None
        if cobol_spans and java_spans:
            yes = hit(cn,cobol_spans) and hit(jn,java_spans)
        elif cobol_spans:
            yes = ji is None and hit(cn,cobol_spans)
        elif java_spans:
            yes = ci is None and hit(jn,java_spans)
        else:
            yes = False
        labels.append(int(yes))
    return np.asarray(labels)
