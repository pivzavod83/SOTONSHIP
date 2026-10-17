# Neuro-Symbolic COBOL-to-Java Financial Verifier

## The problem

Banks are modernising decades-old COBOL systems into Java, including software that calculates payments, interest, fees, and foreign-exchange conversions. A migration can compile, pass conventional tests, and still change the financial meaning of the original program.

For example, COBOL `COMP-3` values use fixed-point decimal arithmetic. Translating them into Java `double` values introduces binary floating-point behaviour, where common decimal values such as `0.1` cannot be represented exactly. Differences in scale, rounding order, digit truncation, or control flow can therefore create small discrepancies that are difficult to detect but significant across millions of transactions.

This is a real operational risk, not only a theoretical concern. In 2018, TSB's migration to a new banking platform caused widespread disruption, affected a significant proportion of its 5.2 million customers, led to £32.7 million in customer redress, and resulted in £48.65 million in regulatory fines. The incident was broader than a COBOL-to-Java conversion, but it demonstrates the cost of insufficient assurance during complex banking-system migrations. At the language level, [IBM documents `COMP-3` as fixed-point packed decimal](https://www.ibm.com/docs/en/cobol-linux-x86/1.2.0?topic=arithmetic-formats-numeric-data), while [Oracle documents the exact representation error produced from a Java `double`](https://docs.oracle.com/en/java/javase/18/docs/api/java.base/java/math/BigDecimal.html). These semantic differences cannot be addressed reliably through compilation and ordinary test cases alone.

## Our solution

We are building a verification layer that determines whether a migrated Java module preserves the financial behaviour of its COBOL source. Rather than trusting the translation process, the system combines machine learning with formal verification to identify risky changes and prove—or disprove—financial equivalence.

### How it works

1. **Program modelling:** The COBOL and Java programs are converted into Code Property Graphs that capture syntax, data flow, control flow, types, and financial operations.
2. **Cross-language alignment:** A Graph Neural Network aligns equivalent COBOL paragraphs, variables, and operations with their Java counterparts, even when the code has been renamed or restructured. It assigns risk scores to suspicious mappings such as `COMP-3` to `double`, changed rounding rules, truncation, or altered loop behaviour.
3. **Focused formal verification:** The highest-risk aligned subgraphs are translated into mathematical constraints and checked with the Z3 theorem prover. Relevant Bank of England exchange rates and World Bank remittance-fee data provide realistic financial scenarios.
4. **Proof or counterexample:** If no differing result is possible within the defined model, the module is reported as mathematically equivalent. If a discrepancy exists, the verifier returns the exact input and the differing COBOL and Java outputs—for example, the transaction on which the Java implementation loses one penny.
5. **Verified remediation:** For supported decimal and rounding defects, the system proposes a Java `BigDecimal` correction and reruns the proof. Code that depends on unbounded external state, such as an unstubbed `EXEC CICS` call, is explicitly marked unverifiable and referred for human review.

## Why this solves the problem

Traditional compilers and linters check syntax and local rules; tests examine only selected examples. Our approach checks semantic behaviour across languages. The GNN makes verification practical by locating equivalent and high-risk logic after refactoring, while Z3 provides mathematical evidence and reproducible counterexamples. Together, they give migration teams a clear basis for approving safe modules, correcting unsafe ones, and refusing to make unsupported claims when verification is not possible.

## Evidence

- [FCA: TSB fined £48.65m for operational resilience failings](https://www.fca.org.uk/news/press-releases/tsb-fined-48m-operational-resilience-failings)
- [IBM: COBOL numeric data formats](https://www.ibm.com/docs/en/cobol-linux-x86/1.2.0?topic=arithmetic-formats-numeric-data)
- [Oracle: Java `BigDecimal` documentation](https://docs.oracle.com/en/java/javase/18/docs/api/java.base/java/math/BigDecimal.html)
