"""AI-authored, executable demonstration fixtures, not vendor source extracts."""
from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5


def cobol(name: str, body: str, *, integer_result: bool = False, unsigned: bool = False) -> str:
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 INPUT-AMOUNT PIC {'' if unsigned else 'S'}9(7)V99 COMP-3 VALUE 0.
       01 REFERENCE-RATE PIC 9(2)V9(4) COMP-3 VALUE 0.
       01 SETTLEMENT-RESULT PIC {'9(5)' if integer_result else 'S9(7)V99'} COMP-3 VALUE 0.
       PROCEDURE DIVISION.
{body}
"""


FX_COBOL = cobol("FX-WIRE-CALC", """       MAIN.
           COMPUTE SETTLEMENT-RESULT ROUNDED = INPUT-AMOUNT * REFERENCE-RATE.
           GOBACK.""")
FX_JAVA = """import java.math.BigDecimal;
import java.math.RoundingMode;
public final class FxWireService {
    public BigDecimal calculate(double principal, double quote) {
        return new BigDecimal(principal * quote).setScale(2, RoundingMode.HALF_UP);
    }
}
"""
FX_PATCH = """import java.math.BigDecimal;
import java.math.RoundingMode;
public final class FxWireService {
    public BigDecimal calculate(BigDecimal principal, BigDecimal quote) {
        return principal.multiply(quote).setScale(2, RoundingMode.HALF_UP).remainder(new BigDecimal("10000000"));
    }
}
"""
MORTGAGE_COBOL = cobol("MORTGAGE-INT-CALC", """       MAIN.
           PERFORM CALC-TIER THRU CALC-EXIT.
           GOBACK.
       CALC-TIER.
           COMPUTE SETTLEMENT-RESULT = INPUT-AMOUNT * 0.05.
       APPLY-PREMIUM.
           COMPUTE SETTLEMENT-RESULT = SETTLEMENT-RESULT + 1.
       CALC-EXIT.
           EXIT.""", integer_result=True, unsigned=True)
MORTGAGE_JAVA = """import java.math.BigDecimal;
import java.math.RoundingMode;
public final class MortgageInterestCalculator {
    public BigDecimal calculate(BigDecimal balance, BigDecimal unusedReference) {
        return balance.multiply(new BigDecimal("0.05"));
    }
}
"""
MORTGAGE_PATCH = """import java.math.BigDecimal;
import java.math.RoundingMode;
public final class MortgageInterestCalculator {
    public BigDecimal calculate(BigDecimal balance, BigDecimal unusedReference) {
        BigDecimal tier = balance.multiply(new BigDecimal("0.05")).setScale(0, RoundingMode.DOWN).remainder(new BigDecimal("100000"));
        return tier.add(BigDecimal.ONE).setScale(0, RoundingMode.DOWN).remainder(new BigDecimal("100000"));
    }
}
"""
# The 1.89 fee at GBP120 comes from one documented historical World Bank row.
# The higher tier is an invented demo policy, not a statement of Wise's tariff.
REMIT_COBOL = cobol("REMIT-TIER-FEE", """       MAIN.
           IF INPUT-AMOUNT <= 120
               COMPUTE SETTLEMENT-RESULT ROUNDED = 1.89 * REFERENCE-RATE
           ELSE
               COMPUTE SETTLEMENT-RESULT ROUNDED = INPUT-AMOUNT * 0.01 * REFERENCE-RATE
           END-IF.
           GOBACK.""")
REMIT_JAVA = """import java.math.BigDecimal;
import java.math.RoundingMode;
public final class RemittanceFeeEngine {
    public BigDecimal calculate(BigDecimal transfer, BigDecimal bahtQuote) {
        if (transfer.compareTo(new BigDecimal("120")) <= 0) {
            return new BigDecimal("1.89").multiply(bahtQuote).setScale(2, RoundingMode.HALF_UP).remainder(new BigDecimal("10000000"));
        } else {
            return transfer.multiply(new BigDecimal("0.01")).multiply(bahtQuote).setScale(2, RoundingMode.HALF_UP).remainder(new BigDecimal("10000000"));
        }
    }
}
"""
CICS_COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICS-TERMINAL-IO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TERMINAL-BUFFER PIC X(80).
       01 ACCOUNT-VIEW REDEFINES TERMINAL-BUFFER.
           05 ACCOUNT-ID PIC 9(10).
       PROCEDURE DIVISION.
       MAIN.
           EXEC CICS RECEIVE MAP('WIREMAP')
               INTO(TERMINAL-BUFFER) END-EXEC.
           GOBACK.
"""
CICS_JAVA = """public final class TerminalSessionHandler {
    public void receiveMap(TerminalGateway gateway) {
        gateway.receiveMap("WIREMAP");
    }
}
"""


def demo_requests() -> list[dict]:
    rows = [("FX-WIRE-CALC.cbl", "FX_CONVERSION", FX_COBOL, FX_JAVA, FX_PATCH),
            ("MORTGAGE-INT-CALC.cbl", "INTEREST_CALC", MORTGAGE_COBOL, MORTGAGE_JAVA, MORTGAGE_PATCH),
            ("REMIT-TIER-FEE.cbl", "REMITTANCE_FEE", REMIT_COBOL, REMIT_JAVA, REMIT_JAVA),
            ("CICS-TERMINAL-IO.cbl", "EXTERNAL_LIMIT_CASE", CICS_COBOL, CICS_JAVA, CICS_JAVA)]
    mappings = {
        "FX_CONVERSION": ("INPUT-AMOUNT", "REFERENCE-RATE", "SETTLEMENT-RESULT", "principal", "quote", -999999999,
                          "GBP/EUR", "Bank of England Daily Spot Rate", "2026-10-17"),
        "INTEREST_CALC": ("INPUT-AMOUNT", "REFERENCE-RATE", "SETTLEMENT-RESULT", "balance", "unusedReference", 0,
                          "GBP/EUR", "Bank of England Daily Spot Rate", "2026-10-17"),
        "REMITTANCE_FEE": ("INPUT-AMOUNT", "REFERENCE-RATE", "SETTLEMENT-RESULT", "transfer", "bahtQuote", -999999999,
                           "GBP/THB", "World Bank Remittance Prices Worldwide", "2026-10-17"),
        "EXTERNAL_LIMIT_CASE": ("INPUT-AMOUNT", "REFERENCE-RATE", "SETTLEMENT-RESULT", "amount", "rate", 0,
                                "GBP/EUR", "Bank of England Daily Spot Rate", "2026-10-17"),
    }
    requests = []
    for name, category, old, new, patch in rows:
        (amount_field, rate_field, result_field, amount_parameter, rate_parameter, min_cents,
         pair, source, collected) = mappings[category]
        requests.append({"id": str(uuid5(NAMESPACE_URL, "sotonship:verification:" + name)), "moduleName": name,
                         "category": category, "cobolSource": old, "javaSource": new, "patchedJavaSource": patch,
                         "proofInputs": {"cobolDialectProfile": "IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1",
                             "cobolSourceFormat": "FREE", "amountField": amount_field,
                             "rateField": rate_field, "resultField": result_field,
                             "javaAmountParameter": amount_parameter, "javaRateParameter": rate_parameter,
                             "amountMinCents": min_cents, "amountMaxCents": 999999999,
                             "referenceCurrencyPair": pair, "referenceSource": source,
                             "referenceCollectedDate": collected}})
    return requests
