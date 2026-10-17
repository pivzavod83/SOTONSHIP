"""Independent JVM replay of financial witnesses and patched boundary cases.

Optional when JDK tools are absent. Submitted user programs are never executed by
the API; this test compiles only the repository's generated demo fixtures.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    not shutil.which("javac") or not shutil.which("java"), reason="JDK required for independent JVM replay"
)
DATA = Path(__file__).resolve().parents[1] / "data" / "seed-verifications.json"


def _runner(source: str, folder: Path):
    name = re.search(r"public\s+(?:final\s+)?class\s+(\w+)", source)[1]
    method = re.search(r"public\s+(?:static\s+)?(BigDecimal|double)\s+(\w+)\(([^)]*)\)", source)
    result_type, method_name, parameters = method.groups()
    types = [argument.strip().split()[0] for argument in parameters.split(",")]
    assert len(types) == 2
    arguments = [f"new java.math.BigDecimal(args[{i}])" if kind == "BigDecimal"
                 else f"Double.parseDouble(args[{i}])" for i, kind in enumerate(types)]
    call = f"new {name}().{method_name}({', '.join(arguments)})"
    observed = f"{call}.toPlainString()" if result_type == "BigDecimal" else f"new java.math.BigDecimal({call}).toPlainString()"
    (folder / f"{name}.java").write_text(source)
    (folder / "Replay.java").write_text(
        "public final class Replay { public static void main(String[] args) { "
        f"System.out.print({observed});"
        " } }"
    )
    subprocess.run(["javac", f"{name}.java", "Replay.java"], cwd=folder, check=True, capture_output=True, timeout=30)

    def invoke(amount: str, rate: str) -> Decimal:
        output = subprocess.run(["java", "-cp", str(folder), "Replay", amount, rate],
                                check=True, capture_output=True, text=True, timeout=15).stdout
        return Decimal(output).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return invoke


def _rows():
    return json.loads(DATA.read_text())["verifications"]


def test_z3_sat_witnesses_match_actual_java(tmp_path):
    witnesses = 0
    for index, row in enumerate(_rows()):
        if row["formalProofStatus"] != "SAT_COUNTEREXAMPLE_FOUND":
            continue
        folder = tmp_path / str(index)
        folder.mkdir()
        invoke = _runner(row["javaSource"], folder)
        for witness in row["counterexamplesJson"]:
            observed = invoke(witness["inputAmountGbp"], witness["boeFxRate"])
            assert observed == Decimal(witness["javaOutput"])
            expected = Decimal(witness["cobolOutput"])
            assert observed != expected
            assert observed - expected == Decimal(witness["pennyDrift"])
            witnesses += 1
    assert witnesses >= 2, "Both buggy fixtures must carry replayable solver witnesses"


def test_patched_java_matches_financial_boundary_cases(tmp_path):
    checked = 0
    for index, row in enumerate(_rows()):
        if row["isFailureLimitCase"]:
            continue
        folder = tmp_path / str(index)
        folder.mkdir()
        invoke = _runner(row["patchedJavaSource"], folder)
        rate = Decimal(str(row["proofScope"]["rate"]["rate"]))
        for text in ("-9999999.99", "-65.00", "0.00", "65.00", "120.00", "120.01", "2000000.00", "9999999.99"):
            amount = Decimal(text)
            if row["category"] == "INTEREST_CALC":
                if amount < 0:
                    continue
                tier = (amount * Decimal("0.05")).to_integral_value(rounding=ROUND_DOWN) % 100000
                expected = (tier + 1) % 100000
            elif row["category"] == "FX_CONVERSION":
                expected = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) % 10000000
            else:
                fee = Decimal("1.89") if amount <= 120 else amount * Decimal("0.01")
                expected = (fee * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) % 10000000
            assert invoke(text, str(rate)) == expected, (row["moduleName"], text)
            checked += 1
    assert checked >= 20
