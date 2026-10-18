"""Closed arithmetic grammar, rather than a claim to parse either whole language.

Any unconsumed token or unknown operation is rejected. The first two declared
COBOL fields / Java parameters are the amount and reference-rate input contract.
Only scalar arithmetic, acyclic paragraphs and structured IF are supported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any


class UnsupportedSemantics(ValueError):
    pass


JAVA_RESERVED = set("abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while true false null record sealed permits var yield".split())


def java_identifier(tokens) -> str:
    name = tokens.take()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) or name in JAVA_RESERVED or name in ("Math", "BigDecimal", "RoundingMode"):
        raise UnsupportedSemantics(f"Invalid Java identifier {name}")
    return name


def strip_comments(source: str, language: str) -> str:
    if language == "cobol":
        return "\n".join(line.split("*>")[0] for line in source.splitlines())
    # Keep strings verbatim: comment markers inside decimal constructors are data.
    return re.sub(r'"(?:[^"\\]|\\.)*"|//[^\n]*|/\*.*?\*/',
                  lambda match: match[0] if match[0].startswith('"') else " ", source, flags=re.S)


@dataclass(frozen=True)
class Picture:
    name: str
    integral: int
    scale: int
    signed: bool

    @property
    def capacity(self) -> int:
        return 10 ** (self.integral + self.scale)


@dataclass
class CobolProgram:
    fields: list[Picture]
    paragraphs: dict[str, list]

    @property
    def min_cents(self) -> int:
        return -(10 ** (self.fields[0].integral + 2) - 1) if self.fields[0].signed else 0

    @property
    def max_cents(self) -> int:
        return 10 ** (self.fields[0].integral + 2) - 1


@dataclass
class JavaProgram:
    parameters: list[tuple[str, str]]
    statements: list
    return_type: str


TOKEN = re.compile(r'\s*(?:(\d+(?:\.\d+)?(?:[dD])?)|("[^"\\]*")|([A-Za-z_][A-Za-z_0-9]*)|(<=|>=|==|!=|[+*/.,(){};=<>-]))')


class Tokens:
    def __init__(self, text: str, cobol: bool = False):
        # COBOL hyphenated identifiers are preserved through a reversible alias.
        if cobol:
            if "_" in text:
                raise UnsupportedSemantics("Underscores are outside the COBOL identifier grammar")
            text = re.sub(r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+\b", lambda m: m[0].replace("-", "__"), text)
        self.items: list[str] = []
        cursor = 0
        while cursor < len(text):
            if not text[cursor:].strip():
                break
            match = TOKEN.match(text, cursor)
            if not match:
                raise UnsupportedSemantics(f"Unrecognized token near {text[cursor:cursor + 32]!r}")
            self.items.append(next(group for group in match.groups() if group is not None))
            cursor = match.end()
        self.pos = 0

    def peek(self) -> str:
        return self.items[self.pos] if self.pos < len(self.items) else ""

    def take(self, expected: str | None = None) -> str:
        result = self.peek()
        if not result or (expected is not None and result != expected):
            raise UnsupportedSemantics(f"Expected {expected or 'token'}, got {result or 'end of source'}")
        self.pos += 1
        return result

    def done(self):
        if self.peek():
            raise UnsupportedSemantics(f"Unsupported trailing token {self.peek()}")


def expression(tokens: Tokens, minimum: int = 0) -> Any:
    token = tokens.take()
    if token == "(":
        left = expression(tokens)
        tokens.take(")")
    elif token == "-":
        left = ("neg", expression(tokens, 30))
    elif re.fullmatch(r"\d+(?:\.\d+)?[dD]?", token):
        left = ("number", token)
    elif token.startswith('"'):
        left = ("string", token[1:-1])
    elif token == "new":
        tokens.take("BigDecimal")
        tokens.take("(")
        value = expression(tokens)
        tokens.take(")")
        if value[0] == "string":
            if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value[1]):
                raise UnsupportedSemantics("BigDecimal string must be a plain finite decimal literal")
            Fraction(value[1])
            left = ("decimal", value[1])
        else:
            left = ("decimal_from_double", value)
    elif re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", token):
        left = ("var", token)
    else:
        raise UnsupportedSemantics(f"Invalid expression atom {token}")
    while True:
        if tokens.peek() == ".":
            tokens.take(".")
            name = tokens.take()
            if tokens.peek() == "(":
                tokens.take("(")
                args = []
                if tokens.peek() != ")":
                    args.append(expression(tokens))
                    while tokens.peek() == ",":
                        tokens.take(",")
                        args.append(expression(tokens))
                tokens.take(")")
                left = ("call", left, name, args)
            else:
                left = ("member", left, name)
            continue
        operator = tokens.peek()
        precedence = {"<=": 5, ">=": 5, "<": 5, ">": 5, "==": 5, "!=": 5, "+": 10, "-": 10, "*": 20, "/": 20}.get(operator, -1)
        if precedence < minimum:
            break
        tokens.take()
        left = ("binary", operator, left, expression(tokens, precedence + 1))
    return left


def parse_expression(text: str, cobol: bool = False):
    tokens = Tokens(text, cobol)
    result = expression(tokens)
    tokens.done()
    return result


def _cobol_statements(lines: list[str], index: int = 0, nested: bool = False):
    result = []
    while index < len(lines):
        line = lines[index].rstrip(".").strip()
        if line in ("ELSE", "END-IF"):
            if not nested:
                raise UnsupportedSemantics("Unmatched COBOL IF delimiter")
            return result, index
        if line.startswith("IF "):
            yes, index = _cobol_statements(lines, index + 1, True)
            no = []
            if index < len(lines) and lines[index].rstrip(".") == "ELSE":
                no, index = _cobol_statements(lines, index + 1, True)
            if index >= len(lines) or lines[index].rstrip(".") != "END-IF":
                raise UnsupportedSemantics("Unterminated COBOL IF")
            result.append(("if", parse_expression(line[3:], True), yes, no))
        elif match := re.fullmatch(r"COMPUTE ([A-Z][A-Z0-9-]*)( ROUNDED)? = (.+)", line):
            result.append(("store", match[1].replace("-", "__"), parse_expression(match[3], True), bool(match[2])))
        elif match := re.fullmatch(r"MOVE (.+) TO ([A-Z][A-Z0-9-]*)", line):
            result.append(("store", match[2].replace("-", "__"), parse_expression(match[1], True), False))
        elif match := re.fullmatch(r"ADD (.+) TO ([A-Z][A-Z0-9-]*)( ROUNDED)?", line):
            target = match[2].replace("-", "__")
            value = ("binary", "+", ("var", target), parse_expression(match[1], True))
            result.append(("store", target, value, bool(match[3])))
        elif match := re.fullmatch(r"SUBTRACT (.+) FROM ([A-Z][A-Z0-9-]*)( ROUNDED)?", line):
            target = match[2].replace("-", "__")
            value = ("binary", "-", ("var", target), parse_expression(match[1], True))
            result.append(("store", target, value, bool(match[3])))
        elif match := re.fullmatch(r"PERFORM ([A-Z][A-Z0-9-]*) THRU ([A-Z][A-Z0-9-]*)", line):
            result.append(("perform", match[1], match[2]))
        elif line in ("GOBACK", "STOP RUN"):
            result.append(("halt",))
        elif line == "EXIT":
            result.append(("exit",))
        elif line:
            raise UnsupportedSemantics(f"Unsupported COBOL statement: {line}")
        index += 1
    return result, index


def normalize_cobol_source(source: str, source_format: str = "FREE") -> str:
    if source_format == "FREE":
        return strip_comments(source, "cobol")
    if source_format != "FIXED":
        raise UnsupportedSemantics("COBOL source format must be explicitly FREE or FIXED")
    normalized = []
    for line_number, line in enumerate(source.splitlines(), 1):
        if not line.strip():
            continue
        if len(line) < 7:
            raise UnsupportedSemantics(f"Fixed-format source line {line_number} is shorter than the indicator area")
        indicator = line[6]
        if indicator in ("*", "/"):
            continue
        if indicator == "D":
            raise UnsupportedSemantics("Fixed-format debugging lines require compiler-option semantics")
        if indicator == "-":
            raise UnsupportedSemantics("Fixed-format continuation lines are outside the current parser profile")
        if indicator != " ":
            raise UnsupportedSemantics(f"Unsupported fixed-format indicator {indicator!r} on line {line_number}")
        normalized.append(line[7:72].split("*>", 1)[0])
    return "\n".join(normalized)


def parse_cobol(source: str, source_format: str = "FREE") -> CobolProgram:
    text = normalize_cobol_source(source, source_format).upper()
    pattern = (r"\s*IDENTIFICATION DIVISION\.\s*PROGRAM-ID\.\s*[A-Z0-9-]+\.\s*"
               r"DATA DIVISION\.\s*WORKING-STORAGE SECTION\.\s*(.*?)"
               r"PROCEDURE DIVISION\.\s*(.*?)\s*")
    match = re.fullmatch(pattern, text, re.S)
    if not match:
        raise UnsupportedSemantics("COBOL must use the documented complete scalar program grammar")
    declarations = [line.strip() for line in match[1].splitlines() if line.strip()]
    fields = []
    for line in declarations:
        field = re.fullmatch(r"01 ([A-Z][A-Z0-9-]*) PIC (S?)9\((\d+)\)(?:V(99|9\(\d+\)))?(?: COMP-3)? VALUE 0\.", line)
        if not field:
            raise UnsupportedSemantics(f"Unsupported storage declaration: {line}")
        scale_token = field[4]
        scale = int(scale_token[2:-1]) if scale_token and scale_token.startswith("9(") else len(scale_token or "")
        if int(field[3]) > 12 or scale > 8:
            raise UnsupportedSemantics("Storage capacity exceeds scalar proof limits")
        fields.append(Picture(field[1].replace("-", "__"), int(field[3]), scale, bool(field[2])))
    if len(fields) < 3 or fields[0].scale != 2 or len({field.name for field in fields}) != len(fields):
        raise UnsupportedSemantics("Require unique scalar fields: amount (scale 2), rate, result")
    paragraphs: dict[str, list] = {}
    current: list[str] = []
    name = None
    for line in (line.strip() for line in match[2].splitlines() if line.strip()):
        if re.fullmatch(r"[A-Z][A-Z0-9-]*\.", line) and line not in ("GOBACK.", "EXIT.", "END-IF."):
            if name:
                if name in paragraphs:
                    raise UnsupportedSemantics("Duplicate COBOL paragraph")
                paragraphs[name] = _cobol_statements(current)[0]
            name, current = line[:-1], []
        else:
            if not name:
                raise UnsupportedSemantics("Procedure must begin with a named paragraph")
            current.append(line)
    if name:
        if name in paragraphs:
            raise UnsupportedSemantics("Duplicate COBOL paragraph")
        paragraphs[name] = _cobol_statements(current)[0]
    if not paragraphs:
        raise UnsupportedSemantics("No executable COBOL paragraph")
    declared = {field.name for field in fields}
    def validate_expression(node):
        if node[0] == "var" and node[1] not in declared:
            raise UnsupportedSemantics(f"Undeclared COBOL field {node[1]}")
        if node[0] == "binary":
            validate_expression(node[2])
            validate_expression(node[3])
        elif node[0] == "neg":
            validate_expression(node[1])
        elif node[0] not in ("number", "var"):
            raise UnsupportedSemantics("COBOL expression must use scalar arithmetic only")
    def validate_statements(items):
        for item in items:
            if item[0] == "store":
                if item[1] not in declared:
                    raise UnsupportedSemantics("Undeclared COBOL storage target")
                validate_expression(item[2])
            elif item[0] == "if":
                validate_expression(item[1])
                validate_statements(item[2])
                validate_statements(item[3])
            elif item[0] == "perform" and (item[1] not in paragraphs or item[2] not in paragraphs):
                raise UnsupportedSemantics("Unknown COBOL paragraph")
    for items in paragraphs.values():
        validate_statements(items)
    return CobolProgram(fields, paragraphs)


def _java_statements(tokens: Tokens):
    statements = []
    tokens.take("{")
    while tokens.peek() and tokens.peek() != "}":
        first = tokens.take()
        if first == "return":
            statements.append(("return", expression(tokens)))
            tokens.take(";")
        elif first == "if":
            tokens.take("(")
            condition = expression(tokens)
            tokens.take(")")
            yes = _java_statements(tokens)
            tokens.take("else")
            no = _java_statements(tokens)
            statements.append(("if", condition, yes, no))
        elif first in ("BigDecimal", "double"):
            name = java_identifier(tokens)
            tokens.take("=")
            statements.append(("let", name, expression(tokens), first))
            tokens.take(";")
        else:
            raise UnsupportedSemantics(f"Unsupported Java statement {first}")
    tokens.take("}")
    return statements


def parse_java(source: str) -> JavaProgram:
    text = strip_comments(source, "java")
    # Imports may appear only before the class, never inside string literals.
    text = text.lstrip()
    while (match := re.match(r"import\s+java\.math\.(?:BigDecimal|RoundingMode)\s*;\s*", text)):
        text = text[match.end():]
    tokens = Tokens(text)
    tokens.take("public")
    if tokens.peek() == "final":
        tokens.take()
    tokens.take("class")
    java_identifier(tokens)
    tokens.take("{")
    tokens.take("public")
    if tokens.peek() == "static":
        tokens.take()
    return_type = tokens.take()
    if return_type not in ("BigDecimal", "double"):
        raise UnsupportedSemantics("Only BigDecimal and double scalar methods are supported")
    java_identifier(tokens)  # The method name has no influence on proof or alignment.
    tokens.take("(")
    parameter_type = tokens.take()
    parameters = [(parameter_type, java_identifier(tokens))]
    tokens.take(",")
    parameter_type = tokens.take()
    parameters.append((parameter_type, java_identifier(tokens)))
    if parameters[0][0] != parameters[1][0] or parameters[0][0] not in ("double", "BigDecimal") or parameters[0][1] == parameters[1][1]:
        raise UnsupportedSemantics("Require two distinct parameters of the same supported numeric type")
    tokens.take(")")
    statements = _java_statements(tokens)
    tokens.take("}")
    tokens.done()
    return JavaProgram(parameters, statements, return_type)
