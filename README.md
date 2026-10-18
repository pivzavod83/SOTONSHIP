# Omul

Banks modernising older systems must preserve how money is calculated. **COBOL** is a long-established programming language used in banking; **Java** is widely used for newer applications. Converting between them requires preserving different rules for rounding, storing numbers and following instructions. Code can run successfully while producing a different financial result.

The consequences of migration failures are real. TSB’s 2018 IT migration disrupted banking services and led to **£32.7 million in customer redress** and **£48.65 million in regulatory fines**. This was a broader systems migration, not a documented COBOL-to-Java rounding failure. [FCA report](https://www.fca.org.uk/news/press-releases/tsb-fined-48m-operational-resilience-failings).

Our demonstration uses the [Bank of England’s published rate](https://www.bankofengland.co.uk/boeapps/database/Rates.asp?into=GBP) of **€1.183 per £1**, observed on **15 October 2026**. Independently recorded execution of our AI-generated example converts £45 into **€53.24 in COBOL but €53.23 in Java**. This is a reproducible educational example, not a discovered production-bank defect.

**Omul is a review workbench for COBOL-to-Java migrations.** Engineers supply the original and translated code. A locally trained AI model flags suspected differences and highlights the relevant lines. A separate mathematical checker looks for inputs that produce different results within supported calculations and declared limits. The interface distinguishes AI suggestions, recorded execution evidence and mathematical results. Engineers can inspect a reviewed correction and check again; unsupported code is marked inconclusive.

This gives reviewers concrete differences to investigate before approving a migration. Omul aims to reduce repetitive comparison and make financial behaviour easier to inspect. It reviews supplied translations; it does not automatically translate or repair programs.

**Current limitation:** the experimental detector correctly classified only **1 of 8 held-out examples**. Its findings require human review; this prototype does not certify production safety.

Financial reference data includes Bank of England rates and historical World Bank remittance costs, collected **17 October 2026**. [Source dates and licences](data-sources/README.md) distinguish these observations from synthetic training examples. [Setup, architecture, evaluation and AI-generated work](TECHNICAL.md) are documented separately.

**Target customers:** bank modernisation teams, financial-software engineers and migration consultancies.

**Ethics:** Omul is designed to assist bank employees, not replace their jobs or expertise. Engineers retain responsibility for reviewing findings, approving changes and protecting customers. Supporting their work is the product’s purpose.
