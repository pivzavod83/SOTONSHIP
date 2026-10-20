"""Typed, source-bound IR for bounded extraction, never an equivalence proof.

The v2 frontends opt into explicit support: an unrecognised construct produces
an issue, not an invented zero feature. No submitted program is executed here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json
import re
from typing import Any, Iterable

IR_VERSION = "typed-semantic-ir-v2"


@dataclass(frozen=True)
class SourceSpan:
    start_line: int
    end_line: int
    start_column: int = 1
    end_column: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NumericType:
    kind: str
    precision: int | None = None
    scale: int | None = None
    signed: bool | None = None
    bit_width: int | None = None
    picture: str | None = None
    attrs: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self,"kind",self.kind.lower())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IRNode:
    id: str
    op: str
    inputs: list[str]
    span: SourceSpan
    source: str
    attrs: dict = field(default_factory=dict)
    numeric_type: NumericType | None = None

    def to_dict(self) -> dict:
        return {"id":self.id,"op":self.op,"inputs":self.inputs,"span":self.span.to_dict(),"source":self.source,
                "attrs":self.attrs,"numericType":self.numeric_type.to_dict() if self.numeric_type else None}


@dataclass
class IREdge:
    source: str
    target: str
    kind: str
    attrs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractionIssue:
    code: str
    message: str
    span: SourceSpan
    severity: str = "ERROR"

    def to_dict(self) -> dict:
        return {"code":self.code,"message":self.message,"span":self.span.to_dict(),"severity":self.severity}


@dataclass
class ProgramIR:
    language: str
    source_format: str
    source_hash: str
    nodes: list[IRNode] = field(default_factory=list)
    edges: list[IREdge] = field(default_factory=list)
    issues: list[ExtractionIssue] = field(default_factory=list)
    symbols: dict[str, dict] = field(default_factory=dict)
    attrs: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        errors = any(issue.severity == "ERROR" for issue in self.issues)
        computational = any(n.op not in {"declare","resource","structure","literal"} for n in self.nodes)
        if errors:
            return "PARTIAL" if computational else "UNSUPPORTED"
        return "COMPLETE" if computational else "UNSUPPORTED"

    def to_dict(self) -> dict:
        return {"irVersion":IR_VERSION,"language":self.language,"sourceFormat":self.source_format,"sourceHash":self.source_hash,
                "status":self.status,"nodes":[n.to_dict() for n in self.nodes],"edges":[e.to_dict() for e in self.edges],
                "issues":[i.to_dict() for i in self.issues],"symbols":self.symbols,"attrs":self.attrs,
                "isProof":False,"codeExecuted":False}

    def fingerprint(self, ignore_names: bool = True) -> str:
        """Structural digest, not a semantic-equivalence decision.

        Ignores source layout, hashes and diagnostic prose. Optional renaming
        normalises declared identifiers by declaration order, not source names.
        """
        names = {name:f"v{i}" for i,name in enumerate(self.symbols)} if ignore_names else {}
        def normal(value: Any):
            if isinstance(value,dict):
                return {names.get(k,k):normal(v) for k,v in value.items() if k not in {"source","sourceHash","source_format","declaredSpan","span"} and not (ignore_names and k=="paragraph_label")}
            if isinstance(value,list):
                return [normal(v) for v in value]
            if isinstance(value,str):
                return names.get(value,value)
            return value
        payload={"version":IR_VERSION,"language":self.language,"nodes":[{"id":n.id,"op":n.op,"inputs":n.inputs,"attrs":normal(n.attrs),"type":n.numeric_type.to_dict() if n.numeric_type else None} for n in self.nodes],
                 "edges":[e.to_dict() for e in self.edges],"symbols":normal(self.symbols),"status":self.status,
                 "issueCodes":[i.code for i in self.issues]}
        return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


class IRBuilder:
    """Low-level frontend bridge; expressions are constructed by each parser.

    All inputs are node IDs. ``read`` emits a versioned READ node. ``store``
    emits a new receiver version and kills its previous constant state.
    Branch parsers can snapshot/restore and merge; loop parsers also retain
    explicit loop edges. None of these operations executes user code.
    """
    def __init__(self, source: str, language: str, source_format: str = "FREE"):
        self.source = source
        self.source_lines = source.split("\n")
        self.program = ProgramIR(language,source_format,hashlib.sha256(source.encode("utf-8")).hexdigest())
        self.active_controls: list[str] = []
        self._latest: dict[str,str] = {}
        self._previous: str | None = None
        self._node_map: dict[str,IRNode] = {}

    def excerpt(self, span: SourceSpan) -> str:
        return "\n".join(self.source_lines[max(0,span.start_line-1):span.end_line])

    def add_node(self, op: str, span: SourceSpan, inputs: Iterable[str] = (), attrs: dict | None = None,
                 numeric_type: NumericType | None = None) -> str:
        if len(self.program.nodes) >= 20_000:
            raise ValueError("IR exceeds the 20000-node extraction budget")
        node_id=f"n{len(self.program.nodes)+1}"
        values=list(inputs)
        op={"abs":"absolute","remainder":"modulo","if":"branch","while":"loop","phi":"merge","constant":"literal"}.get(op.lower(),op.lower())
        node=IRNode(node_id,op,values,span,self.excerpt(span),dict(attrs or {}),numeric_type)
        self.program.nodes.append(node);self._node_map[node_id]=node
        for index,source in enumerate(values):
            self.edge(source,node_id,"data",{"operand_index":index})
        if self._previous is not None:
            self.edge(self._previous,node_id,"sequence",{"meaning":"lexical_emission_order"})
        for control in self.active_controls:
            self.edge(control,node_id,"control")
        self._previous=node_id
        return node_id

    def node(self, node_id: str) -> IRNode:
        return self._node_map[node_id]

    def edge(self, source: str, target: str, kind: str, attrs: dict | None = None) -> None:
        self.program.edges.append(IREdge(source,target,kind,dict(attrs or {})))

    def issue(self, code: str, message: str, span: SourceSpan, severity: str = "ERROR") -> None:
        self.program.issues.append(ExtractionIssue(code,message,span,severity))

    def declare(self, name: str, numeric_type: NumericType, span: SourceSpan, attrs: dict | None = None) -> str:
        if name in self.program.symbols:
            self.issue("DUPLICATE_SYMBOL",f"Duplicate declaration: {name}",span)
        node_id=self.add_node("DECLARE",span,attrs={"symbol":name,**(attrs or {})},numeric_type=numeric_type)
        self.program.symbols[name]={"numericType":numeric_type.to_dict(),"declaration":node_id,"latest":node_id,"version":0,"versions":[node_id],"constant":None}
        self._latest[name]=node_id
        return node_id

    def read(self, name: str, span: SourceSpan) -> str:
        symbol=self.program.symbols.get(name)
        if symbol is None:
            self.issue("UNKNOWN_IDENTIFIER",f"Undeclared identifier: {name}",span)
            return self.add_node("UNKNOWN_READ",span,attrs={"symbol":name})
        numeric_type=NumericType(**symbol["numericType"])
        version=self.node(self._latest[name]).attrs.get("version",0)
        return self.add_node("READ",span,[self._latest[name]],{"symbol":name,"version":version},numeric_type)

    def store(self, name: str, value_id: str, span: SourceSpan, rounded: bool = False,
              attrs: dict | None = None) -> str:
        symbol=self.program.symbols.get(name)
        if symbol is None:
            self.issue("UNKNOWN_RECEIVER",f"Undeclared receiving target: {name}",span)
            return self.add_node("UNKNOWN_STORE",span,[value_id],{"symbol":name,**(attrs or {})})
        numeric_type=NumericType(**symbol["numericType"])
        symbol["version"]+=1
        store_attrs={"symbol":name,"version":symbol["version"],"constantStateKilled":True}
        if self.program.language=="cobol" and numeric_type.kind in {"integer","decimal"}:
            store_attrs.update({"receivingPrecision":numeric_type.precision,"receivingScale":numeric_type.scale or 0,
                               "unsignedSignRemoval":numeric_type.signed is False,"overflow":"DISCARD_HIGH_ORDER_DECIMAL_DIGITS",
                               "storageRadix":10,"sizeErrorHandled":False,"storage":numeric_type.attrs.get("storage","cobol_pic_decimal"),
                               "rounding_mode":"HALF_UP" if rounded else "TRUNCATE_TOWARD_ZERO",
                               "scale":numeric_type.scale or 0,"precision":numeric_type.precision,"signed":numeric_type.signed})
        if attrs:
            store_attrs.update(attrs)
        node_id=self.add_node("STORE",span,[value_id],store_attrs,numeric_type)
        symbol["latest"]=node_id;symbol["versions"].append(node_id);symbol["constant"]=None
        self._latest[name]=node_id
        return node_id

    def snapshot(self) -> dict[str,str]:
        return dict(self._latest)

    def restore(self, state: dict[str,str]) -> None:
        self._latest=dict(state)
        for name,node_id in state.items():
            if name in self.program.symbols:
                self.program.symbols[name]["latest"]=node_id

    def merge(self, states: Iterable[dict[str,str]], span: SourceSpan, op: str = "MERGE") -> None:
        states=list(states)
        for name in self.program.symbols:
            values=list(dict.fromkeys(state[name] for state in states if name in state))
            if not values:
                continue
            if len(values)==1:
                self._latest[name]=values[0];self.program.symbols[name]["latest"]=values[0]
            else:
                symbol=self.program.symbols[name];symbol["version"]+=1
                node_id=self.add_node(op,span,values,{"symbol":name,"version":symbol["version"],"constantStateKilled":True},NumericType(**symbol["numericType"]))
                symbol["latest"]=node_id;symbol["versions"].append(node_id);symbol["constant"]=None;self._latest[name]=node_id

    def begin_loop(self, span: SourceSpan, attrs: dict | None = None) -> tuple[str,dict[str,str]]:
        """Create loop-carried definitions before parsing its condition/body."""
        header=self.add_node("loop",span,attrs=attrs)
        phis={}
        for name,value in self.snapshot().items():
            symbol=self.program.symbols[name];symbol["version"]+=1
            node_id=self.add_node("merge",span,[value],{"symbol":name,"version":symbol["version"],"loop_phi":True,"loop_header":header},NumericType(**symbol["numericType"]))
            symbol["latest"]=node_id;symbol["versions"].append(node_id);symbol["constant"]=None
            self._latest[name]=node_id;phis[name]=node_id
        return header,phis

    def end_loop(self, header: str, phis: dict[str,str], span: SourceSpan) -> None:
        body_terminal=self._previous
        for name,phi in phis.items():
            value=self._latest.get(name,phi)
            if value!=phi:
                self.node(phi).inputs.append(value)
                self.edge(value,phi,"loop",{"operand_index":1,"meaning":"loop_carried_definition"})
        exit_id=self.add_node("merge",span,[header],{"loop_exit":True})
        if body_terminal is not None:
            self.edge(body_terminal,header,"loop",{"meaning":"control_backedge"})
        self.edge(header,exit_id,"control",{"meaning":"exit_when_condition_true"})
        self.restore(phis)

