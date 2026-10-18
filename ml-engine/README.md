# Paired-program matching and bounded financial verification

The migration workflow has two independent engines: a relation-aware GNN learns whole-program COBOL/Java correspondence from actual source pairs; Z3 checks the supported financial arithmetic after an engineer confirms a pair and an explicit input contract. No LLM is connected. No defect-risk classifier or synthetic-feature training dataset is shipped.

From this directory, install and check:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

## Dataset and actual fitting

The pinned COBOL-JavaTrans benchmark contains 143 small HumanEval-derived program pairs, not production banking modules. Sources and tests are upstream-created and reviewed according to the authors; we use their program correspondence labels, not a claim of unrestricted equivalence. Raw code remains outside Git in `evaluation/corpora/`. The manifest, licence attribution, split task IDs, model weights and measured report are versioned.

```sh
.venv/bin/python scripts/fetch_paired_dataset.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/train_paired_gnn.py
```

The task-grouped split contains 85 training, 29 validation and 29 test tasks. Near-duplicates stay together. Training uses a symmetric paired-source contrastive objective, two relation-aware message-passing layers and whole-program pooling. Checkpoint selection and retrieval gates use validation only. A corrected-model report records that an earlier implementation's test results were observed before code-review fixes; it does not claim a pristine unseen research benchmark.

The measured GNN is an experimental pilot, not established as superior to name matching. See [evaluation/README.md](evaluation/README.md) and [the exact training report](evaluation/paired-code/training-report.json). The 143 task pairs do not provide statement correspondence, bug locations or faulty-to-correct patch labels. There is no automatic code generation, exact failure localization or trained risk probability.

## Matching CLI

```sh
.venv/bin/python -m ml_engine.matching --stdin < matching-request.json
```

Input: `{ "cobolSource": "...", "cobolSourceFormat": "AUTO", "candidates": [{ "candidateId": "candidate-1", "moduleName": "Example.java", "javaSource": "..." }], "topK": 5 }`.

Supply 1–20 Java candidates; each source is limited to 100,000 characters and 1,500 lines, the request to 2 MiB. `AUTO`/`FREE`/`FIXED` affects matching extraction only and makes no formal compiler claim. Output is one JSON object with source-bound ranked candidates, cosine similarities, model/dataset/evaluation provenance, `matchingIsProof: false`, `granularity: PROGRAM`, and `MATCH_SUGGESTED` or `REVIEW_REQUIRED`. A single candidate, insufficient graph structure or unsupported validation gate requires review. Even a suggested match needs engineer confirmation.

`code_graph.py` extracts operation/type/literal features and approximate local data, control and sequence relations. This is a bounded heuristic, not a complete compiler AST/CFG. Identifier spelling, comments, declared method/program names and task IDs are excluded from learned numeric features. `paired_gnn.py` fits and evaluates portable NumPy weights; no native ML runtime, GPU, model API or OpenMP is required. Matching never executes submitted programs.

## Verification CLI and fixture regeneration

```sh
.venv/bin/python -m ml_engine.verify --stdin < verification-request.json
.venv/bin/python -m ml_engine.precompute
```

Verification input contains `moduleName`, `category`, `cobolSource`, `javaSource`, optional `patchedJavaSource`, `proofInputs`, and reference-rate records. `proofInputs` declares the supported COBOL profile, source format, exact amount/rate/result fields, Java parameter names, cent bounds and reference-rate pair/source/collection date. Missing or mismatched inputs return `UNKNOWN`; matching does not invent or silently change this contract. Stdout is one JSON object; invalid protocols fail on stderr. Submitted programs are parsed as data, never executed by the API.

The inspection graph in `cpg_builder.py` is separate from the learned matching graph. Verification records contain a program-level learned similarity only. `gnnBugRiskScore=0` is a deprecated numeric compatibility field: `provenanceJson.riskAssessment.status=NOT_ESTIMATED` explicitly says no risk was predicted. Clients must not show that zero as low risk. The legacy node-risk evaluator refuses to apply inappropriate labels to this model.

Four AI-authored financial fixtures remain as independent Z3 regression scenarios, **excluded from GNN training**. Precomputation produces two counterexamples, one bounded match and one external-state limit, and checks proposed arithmetic fixes. Reference rates and licences live in `../data-sources/`. The backend's idempotent MikroORM seeder preserves existing applied patches.

The optional `verify --id UUID` CLI reads PostgreSQL with `DATABASE_URL`; `--persist` additionally updates analysis with version/source checks. Sources and database credentials are never sent to a model provider.

## Formal scope

The closed parser rejects unknown or unconsumed syntax. It accepts complete scalar programs in the exact style shown by `data/fixtures/`, and normalizes a restricted IBM fixed-reference source format when explicitly declared. It does not claim support for arbitrary COBOL or Java:

- COBOL: explicit `VALUE 0` numeric `PIC [S]9(n)[V99|V9(n)] [COMP-3]` fields; named paragraphs; `COMPUTE`, `MOVE`, single-operand `ADD ... TO field [ROUNDED]`, single-operand `SUBTRACT ... FROM field [ROUNDED]`, structured `IF/ELSE/END-IF`, acyclic `PERFORM start THRU end`, `EXIT` and explicit `GOBACK` / `STOP RUN`. The first two fields are amount and rate inputs, the last field is the observed result. Unreferenced fields are explicitly initialized. Output assignment applies the declared scale, `ROUNDED` ties away from zero, truncation toward zero otherwise, and high-order digit discard on overflow. `ON SIZE ERROR`, binary storage, aliasing and compiler-specific runtime behavior are outside scope.
- Java: one public scalar method with two distinct same-type parameters (`BigDecimal` or `double`), local declarations, returns and structured branches. The first two parameters are amount and rate, independent of variable names. Decimal operations include `multiply`, `add`, `subtract`, constant `remainder`, `compareTo` and explicit `setScale(0..8, HALF_UP|DOWN)`. Plain decimal-string constructors and exact `BigDecimal(double)` are supported. Native BigDecimal comparisons and implicit primitive/decimal conversion are rejected. Primitive integral arithmetic is rejected; IEEE754 operations and `Math.round(double)` are modeled separately. Unsupported APIs, exponents in decimal strings, loops and additional methods halt analysis.
- The amount is an integer number of cents within the declared input picture, capped at `-999999999..999999999` cents; unsigned pictures constrain it to nonnegative cents. The proof uses one exact reference rate that must fit the COBOL rate picture. Output comparison observes monetary values rounded HALF_UP to cents; it does not claim equivalence of object identity, exceptions, decimal scale metadata or unobserved state.

`UNSAT_PROVEN_SAFE` means no differing outputs exist within this exact bounded model, rate and observation contract. It never means all arbitrary programs or all real-world inputs are equivalent. Full symbolic integer/rational constraints cover every cent amount in that domain for supported BigDecimal programs; no representative sampling is used to certify them.

For floating-point programs, the engine searches exact half-cent candidate amounts up to GBP2,000 (plus a few diagnostic amounts), validates each expression using Z3 Float64 and finiteness obligations, and checks the selected concrete witness with Z3. Failure to find a witness yields `UNKNOWN`, even when the tested candidates agree. No floating-point program is certified safe by this incomplete search. `EXEC CICS`, JCL and `REDEFINES` halt proof immediately.

The FX witness at the collected BoE GBP/EUR rate `1.1830` is **GBP 45.00 → COBOL 53.24 / Java 53.23**, caused by `new BigDecimal(principal * quote)` preserving an inexact binary product. The originally proposed GBP 10,450.33 at rate 1.2941 yields 13523.77 under both decimal and binary cent rounding; it is not a valid penny-drift witness. Mortgage witnesses expose both the included `PERFORM THRU` intermediate paragraph and the five-digit result capacity. The fixed remittance example uses the historical World Bank provider rate 43.98 and fee 1.89 at GBP 120; its higher fee tier is an invented demo policy, with this limitation recorded in provenance. The generated COBOL uses free source format (`cobc -free` when compiling separately).

## Validation boundaries

Matching quality is measured as retrieval on the versioned paired-task split. It is not the same as proof coverage. Many benchmark programs are outside the financial parser; a retrieval result can coexist with `UNKNOWN` verification.

Tests include real model metadata/source binding, extraction and renaming invariance, message passing and numerical gradients, split isolation, matching contracts, unchanged Z3 counterexamples and bounded proofs. Optional JVM tests execute only repository-owned educational fixtures to replay financial witnesses; they do not execute arbitrary uploaded code.

Implementation, training code, generated financial fixtures and documentation are AI-assisted and require human review. Upstream benchmark code has separate authorship and licence notices.
