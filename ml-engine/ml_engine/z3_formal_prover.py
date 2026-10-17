"""SMT equivalence for a closed scalar subset, with explicit PIC/input bounds.

Z3 checks actual parsed expressions. Floating-point witness search is incomplete;
failure to find a witness returns UNKNOWN, never UNSAT. BigDecimal UNSAT is only
for this bounded model and the fixed reference rate, not arbitrary whole programs.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, localcontext
from fractions import Fraction
from typing import Any

import z3

from .semantics import (CobolProgram, JavaProgram, Picture, UnsupportedSemantics,
                        parse_cobol, parse_java, strip_comments)

SAT = "SAT_COUNTEREXAMPLE_FOUND"
UNSAT = "UNSAT_PROVEN_SAFE"
UNKNOWN = "UNKNOWN_HALTED_LIMIT"


def trunc(value):
    return z3.If(value >= 0, z3.ToInt(value), -z3.ToInt(-value))


def half_up(value):
    return z3.If(value >= 0, z3.ToInt(value + z3.RealVal("1/2")), -z3.ToInt(-value + z3.RealVal("1/2")))


def real(value):
    if z3.is_int(value):
        return z3.ToReal(value)
    return value


def scalar_constant(text: str):
    return z3.RealVal(str(Fraction(text)))


@dataclass
class Value:
    expression: Any
    kind: str = "real"
    defined: tuple = ()


def _fp(value: Value):
    if value.kind == "fp":
        return value.expression
    return z3.fpRealToFP(z3.RNE(), real(value.expression), z3.Float64())


def _real(value: Value):
    return z3.fpToReal(value.expression) if value.kind == "fp" else real(value.expression)


def evaluate(node, environment: dict[str, Value], java_type: str = "BigDecimal") -> Value:
    kind = node[0]
    if kind == "decimal_from_double":
        value = evaluate(node[1], environment, java_type)
        if value.kind != "fp":
            raise UnsupportedSemantics("Only the exact BigDecimal(double) constructor is supported besides strings")
        return Value(z3.fpToReal(value.expression), "decimal")
    if kind in ("number", "decimal"):
        literal = node[1].rstrip("dD")
        value = scalar_constant(literal)
        if java_type == "cobol":
            return Value(value)
        if kind == "decimal":
            return Value(value, "decimal")
        if "." in node[1] or node[1].endswith(("d", "D")):
            numeric = float(literal)
            if not math.isfinite(numeric) or (numeric == 0.0 and Fraction(literal) != 0):
                raise UnsupportedSemantics("Nonfinite or underflowed Java literals are outside the supported grammar")
            return Value(z3.FPVal(float(literal), z3.Float64()), "fp")
        if int(literal) > 2147483647:
            raise UnsupportedSemantics("Java integer literals must fit signed int")
        return Value(z3.IntVal(literal), "int")
    if kind == "var":
        if node[1] not in environment:
            raise UnsupportedSemantics(f"Unknown scalar variable {node[1]}")
        return environment[node[1]]
    if kind == "neg":
        value = evaluate(node[1], environment, java_type)
        if value.kind in ("decimal", "long", "bool"):
            raise UnsupportedSemantics("Unary minus on BigDecimal, boolean or Java long is outside the supported arithmetic subset")
        return Value(-value.expression, value.kind)
    if kind == "member":
        if node[1] == ("var", "BigDecimal") and node[2] in ("ZERO", "ONE", "TEN"):
            return Value(scalar_constant({"ZERO": "0", "ONE": "1", "TEN": "10"}[node[2]]), "decimal")
        raise UnsupportedSemantics("Unsupported Java field access")
    if kind == "binary":
        operator = node[1]
        first, second = evaluate(node[2], environment, java_type), evaluate(node[3], environment, java_type)
        # Java forbids native operators on BigDecimal, while COBOL permits rational arithmetic.
        if java_type != "cobol" and (first.kind == "decimal" or second.kind == "decimal"):
            raise UnsupportedSemantics("BigDecimal native operators/reference comparisons are outside the arithmetic subset")
        if first.kind == "bool" or second.kind == "bool":
            raise UnsupportedSemantics("Boolean arithmetic is unsupported")
        floating = first.kind == "fp" or second.kind == "fp"
        a, b = (_fp(first), _fp(second)) if floating else (_real(first), _real(second))
        if operator in ("<=", ">=", "<", ">", "==", "!="):
            if floating and operator in ("==", "!="):
                equal = z3.fpEQ(a, b)
                return Value(equal if operator == "==" else z3.Not(equal), "bool")
            return Value({"<=": lambda: a <= b, ">=": lambda: a >= b, "<": lambda: a < b,
                          ">": lambda: a > b, "==": lambda: a == b, "!=": lambda: a != b}[operator](), "bool")
        if java_type != "cobol" and not floating:
            raise UnsupportedSemantics("Primitive integral arithmetic, division and overflow require a separate Java model")
        if operator == "/":
            # Only nonzero literal denominators are supported: no hidden totalized division.
            if node[3][0] != "number" or Fraction(node[3][1]) == 0:
                raise UnsupportedSemantics("Division requires a nonzero literal denominator")
        if floating:
            expression = {"+": z3.fpAdd, "-": z3.fpSub, "*": z3.fpMul, "/": z3.fpDiv}[operator](z3.RNE(), a, b)
        else:
            expression = {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "/": lambda: a / b}[operator]()
        return Value(expression, "fp" if floating else "real")
    if kind == "call":
        receiver, method, arguments = node[1:]
        if receiver == ("var", "Math") and method == "round" and len(arguments) == 1:
            value = evaluate(arguments[0], environment, java_type)
            if value.kind != "fp":
                raise UnsupportedSemantics("Only Math.round(double) is supported")
            # Java round uses nearest integer, ties toward positive infinity.
            rounded = z3.ToInt(z3.fpToReal(value.expression) + z3.RealVal("1/2"))
            saturated = z3.If(rounded >= 2 ** 63, z3.IntVal(2 ** 63 - 1), z3.If(rounded < -(2 ** 63), z3.IntVal(-(2 ** 63)), rounded))
            return Value(z3.If(z3.fpIsNaN(value.expression), z3.IntVal(0), saturated), "long")
        value = evaluate(receiver, environment, java_type)
        if value.kind != "decimal" or java_type != "BigDecimal":
            raise UnsupportedSemantics(f"Unsupported method {method} on non-BigDecimal")
        if method in ("multiply", "add", "subtract", "remainder", "compareTo") and len(arguments) == 1:
            operand = evaluate(arguments[0], environment, java_type)
            if operand.kind != "decimal":
                raise UnsupportedSemantics("Mixed decimal/IEEE754 calls are unsupported")
            a, b = value.expression, operand.expression
            if method == "remainder":
                if arguments[0][0] not in ("number", "decimal", "member") or not z3.is_rational_value(z3.simplify(b)) or z3.simplify(b).as_fraction() == 0:
                    raise UnsupportedSemantics("Remainder requires a nonzero decimal constant")
                return Value(a - real(trunc(a / b)) * b, "decimal")
            if method == "compareTo":
                return Value(z3.If(a < b, z3.IntVal(-1), z3.If(a > b, z3.IntVal(1), z3.IntVal(0))), "int")
            return Value({"multiply": lambda: a * b, "add": lambda: a + b, "subtract": lambda: a - b}[method](), "decimal")
        if method == "setScale" and len(arguments) == 2:
            if arguments[0][0] != "number" or not re.fullmatch(r"[0-8]", arguments[0][1]):
                raise UnsupportedSemantics("Scale must be a literal integer from 0 to 8")
            mode = arguments[1]
            if mode[0] != "member" or mode[1] != ("var", "RoundingMode") or mode[2] not in ("HALF_UP", "DOWN"):
                raise UnsupportedSemantics("Only explicit HALF_UP and DOWN rounding are supported")
            factor = 10 ** int(arguments[0][1])
            rounded = half_up(value.expression * factor) if mode[2] == "HALF_UP" else trunc(value.expression * factor)
            return Value(real(rounded) / factor, "decimal")
        raise UnsupportedSemantics(f"Unsupported BigDecimal operation {method}")
    raise UnsupportedSemantics(f"Unsupported expression type {kind}")


def store_picture(value, picture: Picture, rounded: bool):
    scaled = half_up(value * 10 ** picture.scale) if rounded else trunc(value * 10 ** picture.scale)
    magnitude = z3.If(scaled >= 0, scaled, -scaled) % picture.capacity
    signed = z3.If(scaled < 0, -magnitude, magnitude) if picture.signed else magnitude
    return real(signed) / 10 ** picture.scale


def execute_cobol(program: CobolProgram, amount, rate):
    fields = {field.name: field for field in program.fields}
    environment = {name: Value(z3.RealVal(0)) for name in fields}
    environment[program.fields[0].name] = Value(amount)
    environment[program.fields[1].name] = Value(rate)
    names = list(program.paragraphs)

    def statements(items, env, stack):
        halted = False
        for statement in items:
            kind = statement[0]
            if halted:
                raise UnsupportedSemantics("Unreachable COBOL statements are outside the supported grammar")
            if kind == "store":
                name, expression, rounded = statement[1:]
                if name not in fields or name in (program.fields[0].name, program.fields[1].name):
                    raise UnsupportedSemantics("Storage target must be a declared non-input field")
                env[name] = Value(store_picture(evaluate(expression, env, "cobol").expression, fields[name], rounded))
            elif kind == "if":
                condition = evaluate(statement[1], env, "cobol")
                if condition.kind != "bool":
                    raise UnsupportedSemantics("IF requires a scalar comparison")
                yes, no = dict(env), dict(env)
                if statements(statement[2], yes, stack) or statements(statement[3], no, stack):
                    raise UnsupportedSemantics("Branch-local GOBACK is unsupported")
                for name in env:
                    env[name] = Value(z3.If(condition.expression, yes[name].expression, no[name].expression))
            elif kind == "perform":
                start, stop = statement[1:]
                if start not in names or stop not in names or names.index(start) > names.index(stop):
                    raise UnsupportedSemantics("Invalid PERFORM THRU range")
                for name in names[names.index(start):names.index(stop) + 1]:
                    if name in stack:
                        raise UnsupportedSemantics("Recursive or cyclic PERFORM is unsupported")
                    if statements(program.paragraphs[name], env, stack + [name]):
                        raise UnsupportedSemantics("GOBACK within performed range is unsupported")
            elif kind == "halt":
                halted = True
            elif kind != "exit":
                raise UnsupportedSemantics("Unknown COBOL operation")
        return halted

    stopped = False
    for name in names:
        if statements(program.paragraphs[name], environment, [name]):
            stopped = True
            break
    if not stopped:
        raise UnsupportedSemantics("Require explicit GOBACK / STOP RUN")
    return environment[program.fields[-1].name].expression


def execute_java(program: JavaProgram, amount, rate):
    environment = {name: Value(z3.fpRealToFP(z3.RNE(), value, z3.Float64()), "fp") if kind == "double" else Value(value, "decimal")
                   for (kind, name), value in zip(program.parameters, (amount, rate), strict=True)}
    required_finite = []

    def record_defined(value):
        # BigDecimal(double) throws for NaN/infinity. fpToReal on such values is
        # otherwise underspecified in SMT; never accept a witness from it.
        seen = set()
        def visit(term):
            key = term.get_id()
            if key in seen:
                return
            seen.add(key)
            if z3.is_app(term) and term.decl().kind() == z3.Z3_OP_FPA_TO_REAL:
                operand = term.arg(0)
                required_finite.append(z3.And(z3.Not(z3.fpIsNaN(operand)), z3.Not(z3.fpIsInf(operand))))
            for child in term.children():
                visit(child)
        visit(value.expression)
        if value.kind == "fp":
            required_finite.append(z3.And(z3.Not(z3.fpIsNaN(value.expression)), z3.Not(z3.fpIsInf(value.expression))))

    def statements(items, env):
        returned = None
        for statement in items:
            if returned is not None:
                raise UnsupportedSemantics("Unreachable Java code is outside the supported grammar")
            if statement[0] == "let":
                _, name, expression, declared = statement
                if name in env or declared != program.return_type:
                    raise UnsupportedSemantics("Shadowing and mixed local types are unsupported")
                value = evaluate(expression, env, program.return_type)
                record_defined(value)
                if declared == "BigDecimal" and value.kind != "decimal":
                    raise UnsupportedSemantics("BigDecimal assignment type mismatch")
                if declared == "double" and value.kind not in ("fp", "int", "long"):
                    raise UnsupportedSemantics("Invalid implicit conversion to Java double")
                env[name] = Value(_fp(value), "fp") if declared == "double" else value
            elif statement[0] == "return":
                returned = evaluate(statement[1], env, program.return_type)
                record_defined(returned)
            elif statement[0] == "if":
                condition = evaluate(statement[1], env, program.return_type)
                record_defined(condition)
                if condition.kind != "bool":
                    raise UnsupportedSemantics("IF requires a scalar comparison")
                yes, no = statements(statement[2], dict(env)), statements(statement[3], dict(env))
                if yes is None or no is None or yes.kind != no.kind:
                    raise UnsupportedSemantics("Both Java branches must return the same scalar type")
                returned = Value(z3.If(condition.expression, yes.expression, no.expression), yes.kind)
            else:
                raise UnsupportedSemantics("Unknown Java statement")
        return returned

    result = statements(program.statements, environment)
    if result is None:
        raise UnsupportedSemantics("Java method must return on every path")
    if program.return_type == "BigDecimal" and result.kind != "decimal":
        raise UnsupportedSemantics("Java return type mismatch")
    if program.return_type == "double" and result.kind not in ("fp", "int", "long"):
        raise UnsupportedSemantics("Java return type mismatch")
    result = Value(_fp(result), "fp") if program.return_type == "double" else result
    result.defined = tuple(required_finite)
    return result


def _money(cents: int) -> str:
    return format(Decimal(cents) / 100, ".2f")


def _candidate_cents(rate: str, lower: int, upper: int):
    # Search exact half-cent products first; signed Math.round differs at negative ties.
    fraction = Fraction(rate)
    modulus = fraction.denominator
    candidates = [1045033, 0, 1, -1]
    for cents in range(1, min(200000, upper) + 1):
        if (cents * fraction.numerator * 2) % (2 * modulus) == modulus:
            candidates.extend([cents, -cents])
    for cents in sorted(set(candidates), key=lambda value: (value < 0, abs(value))):
        if lower <= cents <= upper:
            yield cents


def prove(cobol_source: str, java_source: str, reference_rate: dict, timeout_ms: int = 5000) -> dict:
    scope = {"supported": False, "bounded": True, "inputUnit": "integer cents",
             "inputAmountCents": {"min": -999999999, "max": 999999999},
             "rate": reference_rate, "semantics": "restricted COBOL/Java scalar arithmetic v1",
             "outputObservation": "monetary values rounded HALF_UP to integer cents",
             "sourceSha256": {"cobol": hashlib.sha256(cobol_source.encode()).hexdigest(),
                              "java": hashlib.sha256(java_source.encode()).hexdigest()},
             "limitations": ["One exact fixed reference rate; acyclic scalar arithmetic only.",
                             "PIC overflow discards high-order digits; no ON SIZE ERROR, runtime or I/O semantics.",
                             "UNSAT covers only the explicit finite input domain, never arbitrary whole programs.",
                             "GNN alignments guide inspection and do not authorize a proof."]}

    def unknown(reason: str, category: str = "UNSUPPORTED_SEMANTICS"):
        scope["reason"] = reason
        return {"formalProofStatus": UNKNOWN, "bugCategory": category, "counterexamplesJson": [],
                "isFailureLimitCase": True, "proofScope": scope}

    code = strip_comments(cobol_source, "cobol")
    if re.search(r"\bEXEC\s+CICS\b|\bJCL\b|\bREDEFINES\b", code, re.I):
        return unknown("External CICS/JCL state or aliased REDEFINES storage cannot be modeled soundly.", "UNBOUNDED_CICS_LIMIT")
    try:
        cobol, java = parse_cobol(cobol_source), parse_java(java_source)
        lower, upper = cobol.min_cents, cobol.max_cents
        # Keep all scalar proofs bounded to the advertised 7-integer-digit amount limit.
        lower, upper = max(lower, -999999999), min(upper, 999999999)
        scope["inputAmountCents"] = {"min": lower, "max": upper}
        rate = Fraction(str(reference_rate["rate"]))
        rate_picture = cobol.fields[1]
        if abs(rate) >= 10 ** rate_picture.integral or (rate * 10 ** rate_picture.scale).denominator != 1 or (rate < 0 and not rate_picture.signed):
            return unknown("Reference rate cannot be represented by the declared COBOL rate PIC.")
        amount_cents = z3.Int("input_amount_cents")
        amount = z3.ToReal(amount_cents) / 100
        exact_rate = scalar_constant(str(rate))
        cobol_result = execute_cobol(cobol, amount, exact_rate)
        java_result = execute_java(java, amount, exact_rate)
        uses_floating_point = any(kind == "double" for kind, _ in java.parameters) or java_result.kind == "fp" or bool(java_result.defined)
        cobol_cents = half_up(cobol_result * 100)
        java_cents = half_up(_real(java_result) * 100)
        scope["supported"] = True
        solver = z3.Solver()
        solver.set(timeout=timeout_ms)
        solver.add(amount_cents >= lower, amount_cents <= upper, cobol_cents != java_cents)
        solver.add(*java_result.defined)
        if uses_floating_point:
            # Finite candidate search is a witness strategy, not an equivalence proof.
            scope["floatingPointSearch"] = "Exact half-cent candidates up to 200000 cents; each candidate checked by Z3 Float64. Incomplete."
            found = None
            for candidate in _candidate_cents(str(rate), lower, upper):
                defined = z3.simplify(z3.substitute(z3.And(*java_result.defined), (amount_cents, z3.IntVal(candidate))))
                if not z3.is_true(defined):
                    continue
                if java_result.kind == "fp":
                    finite = z3.simplify(z3.substitute(z3.Or(z3.fpIsNaN(java_result.expression), z3.fpIsInf(java_result.expression)), (amount_cents, z3.IntVal(candidate))))
                    if not z3.is_false(finite):
                        continue
                concrete = z3.simplify(z3.substitute(cobol_cents != java_cents, (amount_cents, z3.IntVal(candidate))))
                if z3.is_true(concrete):
                    found = candidate
                    break
            if found is None:
                return unknown("No IEEE754 witness found in the incomplete candidate search; equivalence is unproved.")
            solver.add(amount_cents == found)
        result = solver.check()
        scope["solver"] = {"name": "Z3", "version": z3.get_version_string(), "result": str(result), "timeoutMs": timeout_ms}
        if result == z3.unknown:
            return unknown(f"Z3 halted: {solver.reason_unknown()}")
        if result == z3.unsat:
            return {"formalProofStatus": UNSAT, "bugCategory": "NONE", "counterexamplesJson": [],
                    "isFailureLimitCase": False, "proofScope": scope}
        model = solver.model()
        input_cents = model.eval(amount_cents).as_long()
        expected, actual = model.eval(cobol_cents).as_long(), model.eval(java_cents).as_long()
        category = "IEEE754_PENNY_DRIFT" if uses_floating_point else "PERFORM_THRU_FALLTHROUGH" if re.search(r"PERFORM.*THRU", code) else "PIC_SILENT_TRUNCATION"
        counterexample = {"inputAmountGbp": _money(input_cents), "boeFxRate": str(reference_rate["rate"]),
                          "cobolOutput": _money(expected), "javaOutput": _money(actual),
                          "pennyDrift": _money(actual - expected), "dataSource": reference_rate["source"],
                          "collectedDate": reference_rate["collectedDate"],
                          "observationDate": reference_rate.get("observationDate"),
                          "solverGenerated": True, "witnessStrategy": "Z3 Float64 checked finite candidate" if uses_floating_point else "unconstrained bounded Z3 model"}
        if reference_rate.get("currencyPair") == "GBP/EUR":
            counterexample.update(cobolOutputEur=_money(expected), javaOutputEur=_money(actual))
        return {"formalProofStatus": SAT, "bugCategory": category, "counterexamplesJson": [counterexample],
                "isFailureLimitCase": False, "proofScope": scope}
    except (UnsupportedSemantics, ValueError, TypeError, KeyError, z3.Z3Exception) as error:
        return unknown(str(error))
