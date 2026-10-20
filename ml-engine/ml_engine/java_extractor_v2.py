"""Strict, non-executing Java frontend for a bounded scalar migration profile.

This is not javac and never certifies Java validity or equivalence. A lexer and
Pratt expression parser preserve logical statements, typed calls and source
spans. Unrecognised syntax, symbols and overloads become explicit errors; no
unsupported line is silently discarded. Source and old v1 artifacts are untouched.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
import json
import re
from typing import Any

from .semantic_ir import IRBuilder, NumericType, ProgramIR, SourceSpan

PROFILE = "java-scalar-ast-v2"
MAX_SOURCE = 150_000
MAX_TOKENS = 20_000
MAX_DEPTH = 100
_TYPES = {"int", "long", "float", "double", "boolean", "String", "BigDecimal", "BigInteger", "Scanner", "void"}
_NUMERIC = {"int", "long", "float", "double", "BigDecimal", "BigInteger"}
_PRIMITIVE = {"int", "long", "float", "double"}
_IMPORTS = {"java.math.BigDecimal", "java.math.BigInteger", "java.math.RoundingMode", "java.util.Scanner"}
_ROUNDING = {"UP", "DOWN", "CEILING", "FLOOR", "HALF_UP", "HALF_DOWN", "HALF_EVEN", "UNNECESSARY"}
_LEX = re.compile(r'(?P<WS>\s+)|(?P<LINE>//[^\r\n]*)|(?P<BLOCK>/\*.*?\*/)|(?P<STRING>"(?:\\.|[^"\\\r\n])*")|(?P<CHAR>\'(?:\\.|[^\'\\\r\n])*\')|(?P<NUMBER>(?:\d[\d_]*(?:\.[\d_]*)?|\.[\d_]+)(?:[eE][+-]?[\d_]+)?[fFdDlL]?)|(?P<ID>[A-Za-z_$][A-Za-z_0-9$]*)|(?P<OP>>>>=|>>>=|<<=|>>=|>>>|==|!=|<=|>=|&&|\|\||\+=|-=|\*=|/=|%=|\+\+|--|<<|>>|->|::|[{}()\[\];,.?:+*/%<>=!&|^~\-])|(?P<BAD>.)', re.S)


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    start: int
    end: int


@dataclass
class _Expr:
    op: str
    type_name: str
    start: int
    end: int
    args: list['_Expr'] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Stmt:
    kind: str
    start: int
    end: int
    expr: _Expr | None = None
    target: str | None = None
    type_name: str | None = None
    body: list['_Stmt'] = field(default_factory=list)
    otherwise: list['_Stmt'] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Method:
    name: str
    return_type: str
    parameters: list[tuple[str, str, _Token]]
    body: list[_Stmt]
    start: int
    end: int


class _ParseError(Exception):
    def __init__(self, code: str, message: str, token: _Token):
        self.code, self.message, self.token = code, message, token
        super().__init__(message)


def _numeric_type(name: str) -> NumericType:
    attrs: dict[str, Any] = {"java_type": name}
    if name in ("int", "long"):
        return NumericType("integer", signed=True, bit_width=32 if name == "int" else 64, attrs={**attrs, "overflow": "TWOS_COMPLEMENT_WRAP"})
    if name in ("float", "double"):
        return NumericType("binary_float", signed=True, bit_width=32 if name == "float" else 64, attrs={**attrs, "representation": "IEEE_754", "non_finite_possible": True})
    if name in ("BigDecimal", "BigInteger"):
        return NumericType("decimal" if name == "BigDecimal" else "integer", signed=True, attrs={**attrs, "arbitrary_precision": True})
    return NumericType({"String": "string", "String[]": "string_array", "Scanner": "scanner", "RoundingMode": "rounding_mode"}.get(name, name.lower()), attrs=attrs)


class _Parser:
    def __init__(self, source: str, builder: IRBuilder):
        self.source, self.builder = source, builder
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", source)]
        self.tokens: list[_Token] = []
        for match in _LEX.finditer(source):
            kind = match.lastgroup
            if kind not in ("WS", "LINE", "BLOCK"):
                self.tokens.append(_Token(kind, match.group(), match.start(), match.end()))
        self.tokens.append(_Token("EOF", "<eof>", len(source), len(source)))
        self.pos, self.depth, self.scope = 0, 0, 0
        self.env: dict[str, tuple[str, str]] = {}
        self.context = ""
        self.return_type = "void"
        self.imported: set[str] = set()

    def span(self, start: int, end: int) -> SourceSpan:
        first = bisect_right(self.line_starts, start) - 1
        last = bisect_right(self.line_starts, max(start, end - 1)) - 1
        return SourceSpan(first + 1, last + 1, start - self.line_starts[first] + 1, end - self.line_starts[last] + 1)

    def problem(self, code: str, message: str, token: _Token | None = None) -> None:
        token = token or self.peek()
        self.builder.issue(code, message, self.span(token.start, token.end))

    def peek(self, offset: int = 0) -> _Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def take(self, text: str | None = None) -> _Token:
        token = self.peek()
        if text is not None and token.text != text:
            raise _ParseError("JAVA_EXPECTED_TOKEN", f"Expected {text!r}, received {token.text!r}.", token)
        if token.kind != "EOF": self.pos += 1
        return token

    def accept(self, text: str) -> _Token | None:
        return self.take() if self.peek().text == text else None

    def identifier(self) -> _Token:
        token = self.take()
        if token.kind != "ID": raise _ParseError("JAVA_EXPECTED_IDENTIFIER", "Expected a Java identifier.", token)
        return token

    def program(self) -> list[_Method]:
        for token in self.tokens:
            if token.kind == "BAD": self.problem("JAVA_UNRECOGNISED_CHARACTER", f"Unrecognised character {token.text!r}.", token)
        if len(self.tokens) > MAX_TOKENS:
            raise _ParseError("JAVA_TOKEN_BUDGET", f"Profile accepts at most {MAX_TOKENS} tokens.", self.peek())
        if self.accept("package"):
            parts = [self.identifier().text]
            while self.accept("."): parts.append(self.identifier().text)
            self.take(";")
            self.builder.program.attrs["package"] = ".".join(parts)
        imports = []
        while self.accept("import"):
            start = self.tokens[self.pos - 1]
            parts = [self.identifier().text]
            while self.accept("."): parts.append(self.identifier().text)
            self.take(";")
            path = ".".join(parts); imports.append(path)
            if path not in _IMPORTS: self.problem("JAVA_UNSUPPORTED_IMPORT", f"Import {path!r} is outside the scalar profile.", start)
        self.builder.program.attrs["imports"] = imports
        self.imported = {path.rsplit(".", 1)[-1] for path in imports if path in _IMPORTS}
        while self.peek().text in ("public", "final", "abstract"): self.take()
        self.take("class"); name = self.identifier()
        self.builder.program.attrs["class_name"] = name.text
        self.take("{")
        methods = []
        while self.peek().text not in ("}", "<eof>"):
            try:
                methods.append(self.method())
            except _ParseError as exc:
                self.problem(exc.code, exc.message, exc.token)
                self.recover_member()
        self.take("}")
        if self.peek().kind != "EOF":
            self.problem("JAVA_TRAILING_SOURCE", "Additional classes or trailing syntax are outside the single-class profile.")
            while self.peek().kind != "EOF": self.take()
        if not methods: self.problem("JAVA_NO_SUPPORTED_METHOD", "No supported scalar method was parsed.", name)
        if len({method.name for method in methods}) != len(methods): self.problem("JAVA_UNSUPPORTED_OVERLOAD", "Overloaded method namespaces are outside this profile.", name)
        return methods

    def recover_member(self) -> None:
        depth = 0
        while self.peek().kind != "EOF":
            token = self.peek().text
            if token == "}" and depth == 0: return
            self.take()
            if token == "{": depth += 1
            elif token == "}":
                depth -= 1
                if depth == 0: return
            elif token == ";" and depth == 0: return

    def type_name(self, allow_void: bool = False) -> str:
        token = self.identifier()
        if token.text not in _TYPES or (token.text == "void" and not allow_void):
            raise _ParseError("JAVA_UNSUPPORTED_TYPE", f"Unsupported type {token.text!r}.", token)
        name = token.text
        if name in ("BigDecimal", "BigInteger", "Scanner") and name not in self.imported:
            self.problem("JAVA_UNRESOLVED_TYPE", f"Type {name} requires its explicit supported import.", token)
        if self.accept("["):
            self.take("]"); name += "[]"
            if name != "String[]": self.problem("JAVA_UNSUPPORTED_ARRAY", "Only unused main String[] arguments are supported.", token)
        return name

    def method(self) -> _Method:
        start = self.peek().start
        modifiers = []
        while self.peek().text in ("public", "private", "protected", "static", "final", "synchronized", "native", "abstract"):
            modifiers.append(self.take().text)
        result_type = self.type_name(allow_void=True)
        name = self.identifier(); self.take("(")
        parameters = []
        self.env = {}; self.scope = 0
        self.context = name.text; self.return_type = result_type
        while self.peek().text != ")":
            self.accept("final")
            typ = self.type_name(); parameter = self.identifier()
            key = f"{name.text}::{parameter.text}"
            if parameter.text in self.env: self.problem("JAVA_DUPLICATE_PARAMETER", "Duplicate parameter name.", parameter)
            self.env[parameter.text] = (typ, key)
            parameters.append((key, typ, parameter))
            if not self.accept(","): break
        self.take(")")
        if self.accept("throws"):
            token = self.identifier()
            self.problem("JAVA_UNSUPPORTED_THROWS", "Declared exception contracts are outside the supported method profile.", token)
            while self.accept(","): self.identifier()
        if any(modifier in ("synchronized", "native", "abstract") for modifier in modifiers): self.problem("JAVA_UNSUPPORTED_METHOD_MODIFIER", "Concurrency/native/abstract methods are unsupported.", name)
        if result_type == "String[]": self.problem("JAVA_UNSUPPORTED_RETURN_TYPE", "Array returns are unsupported.", name)
        body, end = self.block()
        self.check_return_profile(body)
        if result_type != "void" and not self.returns(body):
            self.problem("JAVA_UNVERIFIED_RETURN_PATHS", "A scalar method requires a top-level return; total branch-return analysis is outside this profile.", name)
        return _Method(name.text, result_type, parameters, body, start, end)

    @staticmethod
    def returns(statements: list[_Stmt]) -> bool:
        for statement in statements:
            if statement.kind == "return": return True
            if statement.kind == "block" and _Parser.returns(statement.body): return True
            if statement.kind == "if" and _Parser.returns(statement.body) and _Parser.returns(statement.otherwise): return True
        return False

    @staticmethod
    def contains_return(statements: list[_Stmt]) -> bool:
        return any(statement.kind == "return" or _Parser.contains_return(statement.body) or _Parser.contains_return(statement.otherwise) for statement in statements)

    def check_return_profile(self, statements: list[_Stmt]) -> None:
        for statement in statements:
            nested = [statement.body, statement.otherwise] if statement.kind == "if" else [statement.body] if statement.kind in ("block", "while") else []
            for arm in nested:
                if self.contains_return(arm) and (statement.kind == "while" or not self.returns(arm)):
                    self.builder.issue("JAVA_UNSUPPORTED_NESTED_EARLY_RETURN", "Partially returning nested blocks and returns inside loops require a broader path-sensitive frontend; this profile does not mark them complete.", self.span(statement.start, statement.end))
                self.check_return_profile(arm)

    def block(self) -> tuple[list[_Stmt], int]:
        self.take("{"); previous = dict(self.env); self.scope += 1
        statements = []
        while self.peek().text not in ("}", "<eof>"):
            begin = self.pos
            try: statements.append(self.statement())
            except _ParseError as exc:
                self.problem(exc.code, exc.message, exc.token); self.recover_statement()
            if self.pos == begin: self.take()
        end = self.take("}").end
        self.env = previous
        return statements, end

    def recover_statement(self) -> None:
        nesting = 0
        while self.peek().kind != "EOF":
            text = self.peek().text
            if text == "}" and nesting == 0: return
            self.take()
            if text == "{": nesting += 1
            elif text == "}":
                nesting -= 1
                if nesting == 0: return
            elif text == ";" and nesting == 0: return

    def child(self) -> tuple[list[_Stmt], int]:
        if self.peek().text == "{": return self.block()
        statement = self.statement()
        if statement.kind == "declare":
            self.builder.issue("JAVA_INVALID_EMBEDDED_DECLARATION", "A local declaration cannot be an unbraced Java control-flow body.", self.span(statement.start, statement.end))
        return [statement], statement.end

    def statement(self) -> _Stmt:
        start = self.peek().start
        if self.accept(";"): return _Stmt("empty", start, self.tokens[self.pos - 1].end)
        if self.peek().text == "{":
            body, end = self.block(); return _Stmt("block", start, end, body=body)
        if self.peek().text in ("if", "while"):
            kind = self.take().text; self.take("("); condition = self.expression(); self.take(")")
            if condition.type_name != "boolean": self.problem("JAVA_NON_BOOLEAN_CONDITION", "Control predicates must be boolean.")
            body, end = self.child(); otherwise = []
            if kind == "if" and self.accept("else"): otherwise, end = self.child()
            return _Stmt(kind, start, end, condition, body=body, otherwise=otherwise)
        if self.peek().text in ("for", "do", "switch", "try", "throw", "break", "continue", "assert", "synchronized"):
            token = self.take(); raise _ParseError("JAVA_UNSUPPORTED_CONTROL", f"{token.text} is outside the bounded if/while scalar profile.", token)
        if self.accept("return"):
            expression = None if self.peek().text == ";" else self.expression()
            end = self.take(";").end
            if (expression is None) != (self.return_type == "void"): self.problem("JAVA_RETURN_TYPE_MISMATCH", "Return value disagrees with the declared method type.")
            elif expression and not self.assignable(self.return_type, expression.type_name): self.problem("JAVA_RETURN_TYPE_MISMATCH", "Unsupported return conversion.")
            return _Stmt("return", start, end, expression)
        final = bool(self.accept("final"))
        if self.peek().text in _TYPES and (self.peek(1).kind == "ID" or self.peek(1).text == "["):
            typ = self.type_name(); target = self.identifier(); self.take("=")
            expression = self.expression(); end = self.take(";").end
            if target.text in self.env: self.problem("JAVA_DUPLICATE_LOCAL", "Shadowing an existing local/parameter is not supported.", target)
            key = f"{self.context}::{target.text}#{self.scope}"
            self.env[target.text] = (typ, key)
            if not self.assignable(typ, expression.type_name): self.problem("JAVA_ASSIGNMENT_TYPE_MISMATCH", f"Cannot assign {expression.type_name} to {typ}.", target)
            return _Stmt("declare", start, end, expression, key, typ, attrs={"final": final})
        if final: raise _ParseError("JAVA_UNSUPPORTED_DECLARATION", "Expected a typed local after final.", self.peek())
        if self.peek().kind == "ID" and self.peek(1).text in ("=", "+=", "-=", "*=", "/=", "%="):
            target = self.take(); operator = self.take()
            if target.text not in self.env:
                self.problem("JAVA_UNRESOLVED_TARGET", f"Undeclared target {target.text!r}.", target); typ, key = "unknown", f"{self.context}::{target.text}"
            else: typ, key = self.env[target.text]
            expression = self.expression(); end = self.take(";").end
            if operator.text != "=":
                left = _Expr("read", typ, target.start, target.end, attrs={"symbol": key})
                expression = self.binary(operator.text[0], left, expression)
                expression.attrs["compound_assignment_conversion"] = typ
            elif not self.assignable(typ, expression.type_name): self.problem("JAVA_ASSIGNMENT_TYPE_MISMATCH", f"Cannot assign {expression.type_name} to {typ}.", target)
            return _Stmt("assign", start, end, expression, key, typ)
        expression = self.expression(); end = self.take(";").end
        if expression.op != "output": self.problem("JAVA_UNSUPPORTED_EXPRESSION_STATEMENT", "Only println is supported as a stand-alone call.", self.tokens[self.pos - 1])
        return _Stmt("expression", start, end, expression)

    @staticmethod
    def assignable(target: str, value: str) -> bool:
        if target == value: return True
        widen = {"long": {"int"}, "float": {"int", "long"}, "double": {"int", "long", "float"}}
        return value in widen.get(target, set())

    def expression(self, minimum: int = 0) -> _Expr:
        self.depth += 1
        if self.depth > MAX_DEPTH: raise _ParseError("JAVA_NESTING_BUDGET", "Expression nesting exceeds the profile budget.", self.peek())
        try:
            value = self.prefix()
            precedence = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, ">": 4, "<=": 4, ">=": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}
            while True:
                token = self.peek()
                if token.text == "?" and minimum == 0:
                    self.take(); yes = self.expression(); self.take(":"); no = self.expression()
                    if value.type_name != "boolean": self.problem("JAVA_NON_BOOLEAN_TERNARY", "Ternary predicate must be boolean.", token)
                    typ = yes.type_name if yes.type_name == no.type_name else self.promote(yes.type_name, no.type_name)
                    if typ == "unknown": self.problem("JAVA_TERNARY_TYPE_MISMATCH", "Unsupported conditional expression type combination.", token)
                    value = _Expr("conditional", typ, value.start, no.end, [value, yes, no]); continue
                level = precedence.get(token.text, -1)
                if level < minimum: break
                self.take(); right = self.expression(level + 1); value = self.binary(token.text, value, right)
            return value
        finally: self.depth -= 1

    def prefix(self) -> _Expr:
        token = self.take()
        if token.text in ("-", "+", "!"):
            value = self.expression(7)
            if token.text == "!" and value.type_name != "boolean": self.problem("JAVA_UNARY_TYPE", "Logical negation requires boolean.", token)
            if token.text != "!" and value.type_name not in _PRIMITIVE: self.problem("JAVA_UNARY_TYPE", "Numeric unary operations require primitive scalar operands.", token)
            return _Expr({"-": "negate", "+": "positive", "!": "not"}[token.text], value.type_name, token.start, value.end, [value])
        if token.text == "(":
            if self.peek().text in _PRIMITIVE and self.peek(1).text == ")":
                typ = self.take().text; self.take(")"); value = self.expression(7)
                if value.type_name not in _PRIMITIVE: self.problem("JAVA_UNSUPPORTED_CAST", "Only primitive numeric casts are supported.", token)
                value = _Expr("convert", typ, token.start, value.end, [value], {"conversion": "EXPLICIT_JAVA_CAST", "from_type": value.type_name, "to_type": typ})
            else:
                value = self.expression(); end = self.take(")"); value.start, value.end = token.start, end.end
        elif token.kind == "NUMBER":
            raw = token.text; clean = raw.replace("_", "")
            typ = "long" if clean[-1:] in ("l", "L") else "float" if clean[-1:] in ("f", "F") else "double" if clean[-1:] in ("d", "D") or any(c in clean for c in ".eE") else "int"
            number = clean[:-1] if clean[-1:] in "lLfFdD" else clean
            if typ in ("int", "long"):
                if len(number) > 1 and number.startswith("0"): self.problem("JAVA_UNSUPPORTED_NUMERIC_BASE", "Octal/binary/hex integer literals are outside this decimal-only profile.", token)
                if "." in number or "e" in number.lower(): self.problem("JAVA_INVALID_INTEGER_LITERAL", "Integer literals cannot contain a decimal point/exponent.", token)
            value = _Expr("literal", typ, token.start, token.end, attrs={"value": number, "raw": raw, "literal_kind": "BINARY_FLOAT" if typ in ("float", "double") else "INTEGER", "java_type": typ})
            if typ in ("int", "long") and number.isdigit():
                boundary = 2 ** (31 if typ == "int" else 63)
                if int(number) > boundary: self.problem("JAVA_INTEGER_LITERAL_RANGE", "Decimal integer literal exceeds its declared Java width.", token)
                elif int(number) == boundary: value.attrs["requires_unary_minus"] = True
        elif token.kind == "STRING":
            try: decoded = json.loads(token.text)
            except (ValueError, json.JSONDecodeError):
                decoded = token.text[1:-1]; self.problem("JAVA_UNSUPPORTED_STRING_ESCAPE", "This string uses a Java escape outside the supported JSON-compatible subset.", token)
            value = _Expr("literal", "String", token.start, token.end, attrs={"value": decoded, "raw": token.text, "literal_kind": "STRING"})
        elif token.kind == "CHAR":
            self.problem("JAVA_UNSUPPORTED_CHAR_LITERAL", "Character arithmetic is outside the bounded scalar profile.", token)
            value = _Expr("unsupported", "unknown", token.start, token.end)
        elif token.text in ("true", "false"):
            value = _Expr("literal", "boolean", token.start, token.end, attrs={"value": token.text, "literal_kind": "BOOLEAN"})
        elif token.text == "new":
            typ = self.identifier(); self.take("("); args, end = self.arguments()
            value = self.construct(typ.text, args, token.start, end)
        elif token.kind == "ID":
            if token.text in self.env:
                typ, key = self.env[token.text]; value = _Expr("read", typ, token.start, token.end, attrs={"symbol": key})
            elif token.text in ("Math", "BigDecimal", "Integer", "Long", "RoundingMode", "System"):
                if token.text in ("BigDecimal", "RoundingMode") and token.text not in self.imported:
                    self.problem("JAVA_UNRESOLVED_TYPE", f"Type {token.text} requires its explicit supported import.", token)
                value = _Expr("namespace", "class:" + token.text, token.start, token.end, attrs={"class": token.text})
            else:
                self.problem("JAVA_UNRESOLVED_SYMBOL", f"Unresolved scalar identifier {token.text!r}.", token)
                value = _Expr("unsupported", "unknown", token.start, token.end, attrs={"unresolved": token.text})
        else: raise _ParseError("JAVA_UNSUPPORTED_EXPRESSION", f"Unexpected expression token {token.text!r}.", token)
        while self.accept("."):
            member = self.identifier()
            if self.accept("("):
                args, end = self.arguments(); value = self.call(value, member, args, end)
            else: value = self.field(value, member)
        if self.peek().text in ("(", "["):
            raise _ParseError("JAVA_UNSUPPORTED_INVOCATION", "Unqualified calls, array indexing and custom method dispatch are unsupported.", self.peek())
        return value

    def arguments(self) -> tuple[list[_Expr], int]:
        values = []
        if self.peek().text != ")":
            values.append(self.expression())
            while self.accept(","): values.append(self.expression())
        return values, self.take(")").end

    @staticmethod
    def promote(left: str, right: str) -> str:
        if left not in _PRIMITIVE or right not in _PRIMITIVE: return "unknown"
        return max((left, right), key=("int", "long", "float", "double").index)

    def binary(self, operator: str, left: _Expr, right: _Expr) -> _Expr:
        typ = self.promote(left.type_name, right.type_name)
        attrs: dict[str, Any] = {"operator": operator}
        if operator in ("&&", "||"):
            if left.type_name != "boolean" or right.type_name != "boolean": self.problem("JAVA_BINARY_TYPE", "Short-circuit boolean operators require boolean operands.")
            op, typ = ("and" if operator == "&&" else "or"), "boolean"
            attrs["short_circuit"] = True
        elif operator in ("==", "!=", "<", ">", "<=", ">="):
            if typ == "unknown" and not (operator in ("==", "!=") and left.type_name == right.type_name == "boolean"): self.problem("JAVA_BINARY_TYPE", "Comparison operands are outside primitive numeric/boolean comparison support.")
            op, typ = "compare", "boolean"
        else:
            op = {"+": "add", "-": "subtract", "*": "multiply", "/": "divide", "%": "modulo"}[operator]
            if typ == "unknown": self.problem("JAVA_BINARY_TYPE", "Arithmetic operators require primitive numeric values; decimal arithmetic must use supported methods.")
            if operator in ("/", "%"):
                attrs.update({"division_by_zero_possible": True, "rounding_mode": "TRUNCATE_TOWARD_ZERO" if typ in ("int", "long") else "TRUNCATE_QUOTIENT_TOWARD_ZERO" if operator == "%" else "IEEE_754", "remainder_sign": "DIVIDEND" if operator == "%" else None})
                if typ in ("int", "long"): attrs["overflow"] = "TWOS_COMPLEMENT_WRAP"
        return _Expr(op, typ, left.start, right.end, [left, right], attrs)

    def construct(self, typ: str, args: list[_Expr], start: int, end: int) -> _Expr:
        attrs: dict[str, Any] = {"java_constructor": typ}
        if typ in ("BigDecimal", "Scanner") and typ not in self.imported:
            self.problem("JAVA_UNRESOLVED_TYPE", f"Constructor type {typ} requires its explicit supported import.")
        if typ == "Scanner" and len(args) == 1 and args[0].type_name == "InputStream":
            return _Expr("resource", "Scanner", start, end, args, {**attrs, "stream": "STDIN"})
        if typ == "BigDecimal" and len(args) == 1 and args[0].type_name in ("String", "double", "int", "long"):
            attrs.update({"constructor_input_type": args[0].type_name, "decimal_construction": "EXACT_BINARY_FLOAT_VALUE" if args[0].type_name == "double" else "DECIMAL_STRING" if args[0].type_name == "String" else "EXACT_INTEGER", "invalid_number_exception_possible": args[0].type_name in ("String", "double")})
            return _Expr("convert", typ, start, end, args, attrs)
        self.problem("JAVA_UNSUPPORTED_CONSTRUCTOR", f"Unsupported {typ} constructor signature ({', '.join(a.type_name for a in args)}).")
        return _Expr("unsupported", typ if typ in _TYPES else "unknown", start, end, args, attrs)

    def field(self, receiver: _Expr, member: _Token) -> _Expr:
        if receiver.type_name == "class:System" and member.text in ("in", "out"):
            return _Expr("resource", "InputStream" if member.text == "in" else "PrintStream", receiver.start, member.end, attrs={"stream": "STDIN" if member.text == "in" else "STDOUT"})
        if receiver.type_name == "class:RoundingMode" and member.text in _ROUNDING:
            return _Expr("literal", "RoundingMode", receiver.start, member.end, attrs={"value": member.text, "literal_kind": "ROUNDING_MODE"})
        if receiver.type_name == "class:BigDecimal" and member.text in ("ZERO", "ONE", "TEN"):
            return _Expr("literal", "BigDecimal", receiver.start, member.end, attrs={"value": {"ZERO": "0", "ONE": "1", "TEN": "10"}[member.text], "literal_kind": "DECIMAL", "constant_field": member.text})
        self.problem("JAVA_UNSUPPORTED_FIELD", f"Unsupported field {member.text!r} on {receiver.type_name}.", member)
        return _Expr("unsupported", "unknown", receiver.start, member.end, [receiver])

    def call(self, receiver: _Expr, member: _Token, args: list[_Expr], end: int) -> _Expr:
        name, typ = member.text, receiver.type_name
        attrs: dict[str, Any] = {"java_method": name, "receiver_type": typ}
        result, op, operands = "unknown", "unsupported", [receiver, *args]
        numeric = lambda arg: arg.type_name in _PRIMITIVE
        if typ == "Scanner" and name == "nextLine" and not args:
            result, op = "String", "input"; attrs["format"] = "LINE"
        elif typ == "String" and name == "trim" and not args:
            result, op = "String", "convert"; attrs["conversion"] = "JAVA_STRING_TRIM"
        elif typ == "PrintStream" and name == "println" and len(args) == 1 and args[0].type_name in _NUMERIC | {"String", "boolean"}:
            result, op, operands = "void", "output", args; attrs["stream"] = "STDOUT"
        elif typ in ("class:Integer", "class:Long") and name == ("parseInt" if typ == "class:Integer" else "parseLong") and len(args) == 1 and args[0].type_name == "String":
            result, op, operands = ("int" if typ == "class:Integer" else "long"), "convert", args
            attrs.update({"conversion": "PARSE_DECIMAL_INTEGER", "invalid_number_exception_possible": True, "radix": 10})
        elif typ == "class:Math" and name in ("abs", "min", "max") and len(args) == (1 if name == "abs" else 2) and all(numeric(arg) for arg in args):
            result = args[0].type_name if name == "abs" else self.promote(args[0].type_name, args[1].type_name)
            op, operands = {"abs": "absolute", "min": "minimum", "max": "maximum"}[name], args
            attrs["minimum_integer_overflow_possible"] = name == "abs" and result in ("int", "long")
        elif typ == "class:BigDecimal" and name == "valueOf" and len(args) in (1, 2) and numeric(args[0]) and (len(args) == 1 or args[0].type_name in ("int", "long") and args[1].type_name == "int"):
            result, op, operands = "BigDecimal", "convert", args
            attrs["decimal_construction"] = "DOUBLE_TO_STRING_DECIMAL" if args[0].type_name in ("double", "float") else "SCALED_INTEGER" if len(args) == 2 else "EXACT_INTEGER"
            if len(args) == 2: attrs["scale"] = self.constant_int(args[1])
        elif typ == "BigDecimal":
            if name in ("add", "subtract", "multiply", "remainder", "min", "max", "divideToIntegralValue", "compareTo") and len(args) == 1 and args[0].type_name == "BigDecimal":
                result = "int" if name == "compareTo" else "BigDecimal"
                op = {"add": "add", "subtract": "subtract", "multiply": "multiply", "remainder": "modulo", "min": "minimum", "max": "maximum", "divideToIntegralValue": "divide", "compareTo": "compare"}[name]
                if name in ("remainder", "divideToIntegralValue"): attrs.update({"division_by_zero_possible": True, "rounding_mode": "TRUNCATE_TOWARD_ZERO"})
                if name == "compareTo": attrs["comparison_result"] = "NEGATIVE_ZERO_POSITIVE_INTEGER"
            elif name == "divide" and len(args) in (1, 2, 3) and args[0].type_name == "BigDecimal" and (len(args) == 1 or len(args) == 2 and args[1].type_name == "RoundingMode" or len(args) == 3 and args[1].type_name == "int" and args[2].type_name == "RoundingMode"):
                result, op = "BigDecimal", "divide"; attrs["division_by_zero_possible"] = True
                attrs["rounding_mode"] = args[-1].attrs.get("value") if len(args) > 1 else "EXACT_OR_ARITHMETIC_EXCEPTION"
                attrs["nonterminating_decimal_exception_possible"] = len(args) == 1
                if len(args) == 3: attrs["scale"] = self.constant_int(args[1])
                elif len(args) == 2: attrs["scale_source"] = "RECEIVER"
            elif name == "setScale" and len(args) in (1, 2) and args[0].type_name == "int" and (len(args) == 1 or args[1].type_name == "RoundingMode"):
                result, op = "BigDecimal", "quantize"; attrs.update({"scale": self.constant_int(args[0]), "rounding_mode": args[1].attrs.get("value") if len(args) == 2 else "UNNECESSARY", "inexact_exception_possible": len(args) == 1 or args[1].attrs.get("value") == "UNNECESSARY"})
            elif name in ("abs", "signum", "longValue", "longValueExact", "intValue", "intValueExact", "toBigInteger", "toBigIntegerExact", "toPlainString", "toString") and not args:
                result = "BigDecimal" if name == "abs" else "int" if name in ("signum", "intValue", "intValueExact") else "long" if name in ("longValue", "longValueExact") else "BigInteger" if name.startswith("toBigInteger") else "String"
                op = "absolute" if name == "abs" else "compare" if name == "signum" else "format" if result == "String" else "convert"
                if "Value" in name or "BigInteger" in name: attrs.update({"rounding_mode": "EXACT_OR_ARITHMETIC_EXCEPTION" if name.endswith("Exact") else "TRUNCATE_TOWARD_ZERO", "overflow": "ARITHMETIC_EXCEPTION" if name.endswith("Exact") else "DISCARD_HIGH_ORDER_BITS" if result in ("int", "long") else "ARBITRARY_PRECISION"})
                if name == "signum": attrs["comparison_result"] = "SIGNUM"
            elif name in ("movePointRight", "movePointLeft") and len(args) == 1 and args[0].type_name == "int":
                result, op = "BigDecimal", "convert"; attrs.update({"conversion": "DECIMAL_POINT_SHIFT", "shift_direction": "RIGHT" if name.endswith("Right") else "LEFT", "decimal_places": self.constant_int(args[0])})
        elif typ in ("BigInteger", "String") and name == "toString" and not args:
            result, op = "String", "format"
        if op == "unsupported": self.problem("JAVA_UNSUPPORTED_CALL", f"Unsupported call {typ}.{name}({', '.join(a.type_name for a in args)}).", member)
        return _Expr(op, result, receiver.start, end, operands, attrs)

    @staticmethod
    def constant_int(expression: _Expr) -> int | None:
        if expression.op == "literal" and expression.type_name == "int":
            try: return int(expression.attrs["value"])
            except (ValueError, KeyError): pass
        if expression.op == "negate" and expression.args:
            value = _Parser.constant_int(expression.args[0]); return -value if value is not None else None
        return None


class _Emitter:
    def __init__(self, parser: _Parser):
        self.parser, self.builder = parser, parser.builder
        self.context = ""
        self.input_index = self.output_index = 0
        self.final_symbols: set[str] = set()

    def span(self, value: _Expr | _Stmt | _Method) -> SourceSpan:
        return self.parser.span(value.start, value.end)

    def add(self, op: str, value: _Expr | _Stmt | _Method, inputs=(), attrs=None, typ: str | None = None) -> str:
        return self.builder.add_node(op, self.span(value), inputs, {"method": self.context, **(attrs or {})}, _numeric_type(typ) if typ else None)

    def expression(self, expression: _Expr, unary_minus: bool = False) -> str:
        op = expression.op
        if op == "read": return self.builder.read(expression.attrs["symbol"], self.span(expression))
        if op == "conditional":
            predicate = self.expression(expression.args[0]); branch = self.add("branch", expression, [predicate], {"expression": "TERNARY"})
            self.builder.active_controls.append(branch)
            yes = self.expression(expression.args[1]); self.builder.edge(branch, yes, "control", {"arm": "TRUE"})
            no = self.expression(expression.args[2]); self.builder.edge(branch, no, "control", {"arm": "FALSE"})
            self.builder.active_controls.pop()
            return self.add("merge", expression, [predicate, yes, no], {"selection": "TERNARY", "lazy_branches": True}, expression.type_name)
        if op in ("and", "or"):
            left = self.expression(expression.args[0]); branch = self.add("branch", expression, [left], {"expression": "SHORT_CIRCUIT", "operator": op})
            self.builder.active_controls.append(branch); right = self.expression(expression.args[1]); self.builder.active_controls.pop()
            self.builder.edge(branch, right, "control", {"arm": "TRUE" if op == "and" else "FALSE"})
            return self.add(op, expression, [left, right], expression.attrs, expression.type_name)
        values = [self.expression(arg, unary_minus=op == "negate") for arg in expression.args]
        attrs = dict(expression.attrs)
        if op == "literal" and attrs.get("requires_unary_minus") and not unary_minus:
            self.builder.issue("JAVA_INTEGER_LITERAL_RANGE", "The boundary integer magnitude is supported only directly under unary minus.", self.span(expression))
        if op == "input": attrs["input_index"] = self.input_index; attrs["input_index_semantics"] = "STATIC_SOURCE_OCCURRENCE"; self.input_index += 1
        if op == "output": attrs["output_index"] = self.output_index; self.output_index += 1
        if op in ("add", "subtract", "multiply", "negate", "positive") and expression.type_name in ("int", "long"):
            attrs["overflow"] = "TWOS_COMPLEMENT_WRAP"
        if op == "convert" and attrs.get("conversion") == "EXPLICIT_JAVA_CAST":
            attrs.update({"rounding_mode": "TRUNCATE_TOWARD_ZERO" if expression.type_name in ("int", "long") else "IEEE_754", "narrowing_possible": True})
        return self.add(op, expression, values, attrs, expression.type_name)

    def declare(self, statement: _Stmt) -> None:
        self.builder.declare(statement.target, _numeric_type(statement.type_name), self.span(statement), {"method": self.context, **statement.attrs})
        if statement.attrs.get("final"): self.final_symbols.add(statement.target)
        self.store(statement)

    def store(self, statement: _Stmt) -> None:
        if statement.expr is None: return
        value = self.expression(statement.expr)
        if statement.type_name != statement.expr.type_name and self.parser.assignable(statement.type_name, statement.expr.type_name):
            value = self.add("convert", statement, [value], {"conversion": "JAVA_ASSIGNMENT_WIDENING", "from_type": statement.expr.type_name, "to_type": statement.type_name}, statement.type_name)
        self.builder.store(statement.target, value, self.span(statement), attrs={"method": self.context, "receiving_type": statement.type_name, "storage": "JAVA_LOCAL", "overflow": "TWOS_COMPLEMENT_WRAP" if statement.type_name in ("int", "long") else "IEEE_754" if statement.type_name in ("float", "double") else "ARBITRARY_PRECISION" if statement.type_name in ("BigDecimal", "BigInteger") else "NOT_NUMERIC"})

    def body(self, statements: list[_Stmt]) -> bool:
        terminated = False
        continuation_controls = 0
        for statement in statements:
            if terminated:
                self.builder.issue("JAVA_UNREACHABLE_STATEMENT", "Statements after an unconditional return are outside the supported reachable method body.", self.span(statement)); break
            kind = statement.kind
            if kind == "empty": continue
            if kind == "declare": self.declare(statement)
            elif kind == "assign":
                if statement.target in self.final_symbols: self.builder.issue("JAVA_FINAL_REASSIGNMENT", "A final local is reassigned.", self.span(statement))
                self.store(statement)
            elif kind == "expression": self.expression(statement.expr)
            elif kind == "return":
                values = [self.expression(statement.expr)] if statement.expr else []
                self.add("return", statement, values, {"observable": True, "terminates_method": True}, statement.expr.type_name if statement.expr else "void")
                terminated = True
            elif kind == "block": terminated = self.body(statement.body)
            elif kind == "if":
                predicate = self.expression(statement.expr); branch = self.add("branch", statement, [predicate], {"condition": "IF"})
                before = self.builder.snapshot()
                self.builder.active_controls.append(branch); then_start = len(self.builder.program.nodes)
                then_terminates = self.body(statement.body); then_state = self.builder.snapshot()
                for node in self.builder.program.nodes[then_start:]: self.builder.edge(branch, node.id, "control", {"arm": "TRUE"})
                self.builder.restore(before); else_start = len(self.builder.program.nodes)
                else_terminates = self.body(statement.otherwise); else_state = self.builder.snapshot()
                for node in self.builder.program.nodes[else_start:]: self.builder.edge(branch, node.id, "control", {"arm": "FALSE"})
                self.builder.active_controls.pop()
                states = [state for state, ended in ((then_state, then_terminates), (else_state, else_terminates)) if not ended]
                if states: self.builder.merge(states, self.span(statement))
                else: self.builder.restore(before)
                terminated = then_terminates and else_terminates
                if then_terminates != else_terminates:
                    # Only the non-returning arm can reach subsequent statements.
                    # A lexical sequence edge is deliberately not treated as CFG.
                    continuation = self.add("branch", statement, [predicate], {"condition": "RETURN_CONTINUATION", "required_arm": "FALSE" if then_terminates else "TRUE", "excludes_terminated_arm": True})
                    self.builder.active_controls.append(continuation); continuation_controls += 1
            elif kind == "while": self.loop(statement)
        for _ in range(continuation_controls): self.builder.active_controls.pop()
        return terminated

    @staticmethod
    def assigned(statements: list[_Stmt]) -> set[str]:
        result = set()
        for statement in statements:
            if statement.kind == "assign": result.add(statement.target)
            result.update(_Emitter.assigned(statement.body)); result.update(_Emitter.assigned(statement.otherwise))
        return result

    def loop(self, statement: _Stmt) -> None:
        before = self.builder.snapshot(); header_state = dict(before); phis = {}
        assigned = self.assigned(statement.body)
        for name in before:
            if name not in assigned: continue
            if name not in before: continue
            symbol = self.builder.program.symbols[name]; symbol["version"] += 1
            phi = self.builder.add_node("merge", self.span(statement), [before[name]], {"method": self.context, "symbol": name, "version": symbol["version"], "loop_header": True, "constantStateKilled": True}, NumericType(**symbol["numericType"]))
            symbol["versions"].append(phi); symbol["latest"] = phi; symbol["constant"] = None
            header_state[name] = phi; phis[name] = phi
        self.builder.restore(header_state)
        predicate = self.expression(statement.expr); loop = self.add("loop", statement, [predicate], {"test_position": "BEFORE", "zero_iterations_possible": True})
        self.builder.active_controls.append(loop); begin = len(self.builder.program.nodes)
        terminates = self.body(statement.body); after = self.builder.snapshot()
        self.builder.active_controls.pop()
        if not terminates:
            for name, phi in phis.items():
                back = after.get(name, phi)
                self.builder.node(phi).inputs.append(back)
                self.builder.edge(back, phi, "data", {"loop_carried": True, "operand_index": len(self.builder.node(phi).inputs) - 1})
                self.builder.edge(back, phi, "loop", {"symbol": name})
            if len(self.builder.program.nodes) > begin: self.builder.edge(self.builder.program.nodes[-1].id, loop, "loop", {"reevaluate_condition": True})
        self.builder.restore(header_state)
        self.add("merge", statement, [loop], {"control_join": "WHILE_EXIT", "zero_iteration_path": True})

    def methods(self, methods: list[_Method]) -> None:
        contexts = []
        for method in methods:
            self.context = method.name; self.final_symbols = set()
            self.builder.restore({})
            context = self.add("structure", method, attrs={"kind": "METHOD", "name": method.name, "return_type": method.return_type})
            contexts.append({"name": method.name, "returnType": method.return_type, "node": context, "span": self.span(method).to_dict()})
            self.builder.active_controls.append(context)
            for key, typ, token in method.parameters:
                span = self.parser.span(token.start, token.end)
                self.builder.declare(key, _numeric_type(typ), span, {"method": method.name, "parameter": True})
                attrs: dict[str, Any] = {"method": method.name, "parameter": key, "kind": "METHOD_PARAMETER"}
                if method.name == "main" and typ == "String[]": attrs["framework_argument"] = True
                else: attrs["input_index"] = self.input_index; self.input_index += 1
                value = self.builder.add_node("input", span, attrs=attrs, numeric_type=_numeric_type(typ))
                self.builder.store(key, value, span, attrs={"method": method.name, "parameter": True})
            self.body(method.body)
            self.builder.active_controls.pop()
        self.builder.program.attrs["methods"] = contexts
        self.builder.program.attrs["inputCount"] = self.input_index
        self.builder.program.attrs["outputCount"] = self.output_index


def extract_java(source: str) -> ProgramIR:
    """Extract source-only typed/flow IR; COMPLETE means this bounded profile only."""
    if not isinstance(source, str): raise TypeError("Java source must be text.")
    builder = IRBuilder(source, "java", "JAVA")
    builder.program.attrs.update({"extractor": PROFILE, "profile": "single class, scalar methods, typed locals, supported arithmetic/library calls, if/else and while", "fullJavaCompiler": False, "codeExecuted": False})
    if len(source) > MAX_SOURCE:
        builder.issue("JAVA_SOURCE_BUDGET", f"Source exceeds the {MAX_SOURCE}-character profile limit.", SourceSpan(1, 1)); return builder.program
    parser = _Parser(source, builder)
    for match in re.finditer(r"\\u+[0-9a-fA-F]{4}", source):
        builder.issue("JAVA_UNSUPPORTED_UNICODE_ESCAPE", "Java pre-lexical Unicode translation is outside this source-preserving profile.", parser.span(match.start(), match.end()))
    try:
        methods = parser.program(); _Emitter(parser).methods(methods)
    except _ParseError as exc:
        parser.problem(exc.code, exc.message, exc.token)
    except (RecursionError, ValueError) as exc:
        builder.issue("JAVA_PROFILE_BUDGET_OR_LITERAL", f"Profile extraction halted: {exc}.", parser.span(parser.peek().start, parser.peek().end))
    return builder.program
