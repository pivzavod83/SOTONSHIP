# Financial verification engine

This engine produces source-derived structural graphs, runs a small two-layer GCN and synthetic-calibrated XGBoost classifier, and asks Z3 to compare a deliberately restricted scalar COBOL/Java model. The graph model is a demonstration trained on generated examples. It does not establish real-corpus alignment accuracy or financial defect probabilities.

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ml_engine.precompute
.venv/bin/pytest -q
```

Run these commands from `ml-engine/`. Source data and attribution live in `../data-sources/`; precomputation reads those checked-in snapshots without making network requests. It writes `data/seed-verifications.json` and readable source pairs under `data/fixtures/`. The backend's MikroORM seeder loads this artifact.

The four seeded outcomes are two genuine solver-checked counterexamples, one bounded equivalence proof, and one explicit external-state limit. All three arithmetic patches are independently reverified before seed generation succeeds. The CICS example has no certified patch.

## CLI protocol

```sh
.venv/bin/python -m ml_engine.verify --stdin < request.json
.venv/bin/python -m ml_engine.verify --id 529f05c9-2783-53b1-a89f-0aacc1b5a3fe
.venv/bin/python -m ml_engine.verify --id 529f05c9-2783-53b1-a89f-0aacc1b5a3fe --persist
```

`--stdin` consumes one JSON object with `moduleName`, `category`, `cobolSource`, `javaSource`, optional `patchedJavaSource`, and optional `referenceFxRates`. Rates contain `currencyPair`, a decimal-string `rate`, `source`, `collectedDate`, optional `observationDate`, and optional `provenanceJson`. If rates are omitted, the engine loads the checked-in reference data. Analysis uses the current `javaSource`; supplying a patch does not imply its correctness.

Stdout contains exactly one JSON analysis object. Protocol/input failures exit 2 and write a JSON error to stderr. Valid unsupported programs return `UNKNOWN_HALTED_LIMIT`. Requests are limited to 1 MiB and each source to 100,000 characters / 1,500 lines.

The result includes alignment/risk/baseline scores, `formalProofStatus`, `bugCategory`, an English summary, graph JSON, witnesses, `isFailureLimitCase`, `proofScope`, and `provenanceJson`. `proofScope` retains input bounds, the exact rate and vintage, source SHA-256 hashes, solver version/result, the observation contract, and limitations. There is no compiler execution of submitted code.

`--id` reads the same PostgreSQL tables as NestJS, using `DATABASE_URL` from the environment or root `.env`. It is read-only unless `--persist` is passed. Persistence checks the loaded version and source strings before updating analysis, rejecting stale writes after concurrent edits. `--persist` requires `--id`.

## Formal scope

The closed parser rejects unknown or unconsumed syntax. It accepts complete scalar programs in the exact style shown by `data/fixtures/`, rather than claiming support for arbitrary COBOL or Java:

- COBOL: explicit `VALUE 0` numeric `PIC [S]9(n)[V99|V9(n)] [COMP-3]` fields; named paragraphs; `COMPUTE`, `MOVE`, structured `IF/ELSE/END-IF`, acyclic `PERFORM start THRU end`, `EXIT` and explicit `GOBACK` / `STOP RUN`. The first two fields are amount and rate inputs, the last field is the observed result. Unreferenced fields are explicitly initialized. Output assignment applies the declared scale, `ROUNDED` ties away from zero, truncation toward zero otherwise, and high-order digit discard on overflow. `ON SIZE ERROR`, binary storage, aliasing and compiler-specific runtime behavior are outside scope.
- Java: one public scalar method with two distinct same-type parameters (`BigDecimal` or `double`), local declarations, returns and structured branches. The first two parameters are amount and rate, independent of variable names. Decimal operations include `multiply`, `add`, `subtract`, constant `remainder`, `compareTo` and explicit `setScale(0..8, HALF_UP|DOWN)`. Plain decimal-string constructors and exact `BigDecimal(double)` are supported. Native BigDecimal comparisons and implicit primitive/decimal conversion are rejected. Primitive integral arithmetic is rejected; IEEE754 operations and `Math.round(double)` are modeled separately. Unsupported APIs, exponents in decimal strings, loops and additional methods halt analysis.
- The amount is an integer number of cents within the declared input picture, capped at `-999999999..999999999` cents; unsigned pictures constrain it to nonnegative cents. The proof uses one exact reference rate that must fit the COBOL rate picture. Output comparison observes monetary values rounded HALF_UP to cents; it does not claim equivalence of object identity, exceptions, decimal scale metadata or unobserved state.

`UNSAT_PROVEN_SAFE` means no differing outputs exist within this exact bounded model, rate and observation contract. It never means all arbitrary programs or all real-world inputs are equivalent. Full symbolic integer/rational constraints cover every cent amount in that domain for supported BigDecimal programs; no representative sampling is used to certify them.

For floating-point programs, the engine searches exact half-cent candidate amounts up to GBP2,000 (plus a few diagnostic amounts), validates each expression using Z3 Float64 and finiteness obligations, and checks the selected concrete witness with Z3. Failure to find a witness yields `UNKNOWN`, even when the tested candidates agree. No floating-point program is certified safe by this incomplete search. `EXEC CICS`, JCL and `REDEFINES` halt proof immediately.

The FX witness at the collected BoE GBP/EUR rate `1.1830` is **GBP 45.00 → COBOL 53.24 / Java 53.23**, caused by `new BigDecimal(principal * quote)` preserving an inexact binary product. The originally proposed GBP 10,450.33 at rate 1.2941 yields 13523.77 under both decimal and binary cent rounding; it is not a valid penny-drift witness. Mortgage witnesses expose both the included `PERFORM THRU` intermediate paragraph and the five-digit result capacity. The fixed remittance example uses the historical World Bank provider rate 43.98 and fee 1.89 at GBP 120; its higher fee tier is an invented demo policy, with this limitation recorded in provenance. The generated COBOL uses free source format (`cobc -free` when compiling separately).

## Graph model and reproducibility

`cpg_builder.py` uses NetworkX `MultiDiGraph` to retain separate AST, CFG and type-use edges. It is a line-based structural approximation; its eight features include arithmetic/storage type, normalized scale, rounding, branches, external calls and a calculated PCA structural residual. The independent formal parser validates the complete source before any proof.

`gnn_aligner.py` applies normalized adjacency message passing through saved `8→12→8` GCN weights. Cosine similarity links paragraph and method embeddings without name features. Saved XGBoost trees produce node scores, followed by Platt calibration fitted on held-out synthetic rows. Portable JSON inference requires NumPy and NetworkX, and does not import the native XGBoost runtime.

Training is reproducible with a fixed seed:

```sh
.venv/bin/pip install -r requirements-training.txt
.venv/bin/python scripts/train_demo_models.py
.venv/bin/python -m ml_engine.precompute
```

On macOS, XGBoost training additionally needs the OpenMP runtime (`brew install libomp`); normal inference and tests do not. Artifacts include the source training script, GCN arrays, portable tree dump, original XGBoost JSON and synthetic train/calibration/test split plus metrics. These metrics apply only to generated feature rows. No measured 94% vs 18% alignment claim, real financial benchmark, production probability calibration or mathematical need for AI is asserted. An explicit mapping supplied by a human could also drive formal verification.

The deterministic baseline actually computes normalized name overlap and one obvious unsafe-constructor regex rule. Its scores are not ground-truth alignment accuracy, so the API reports observational comparisons rather than claiming a proven model advantage. Model inference time is recorded for each run, not guaranteed to remain below 200 ms for arbitrary inputs.

The test suite checks source mutations, rounding signs/ties, overflow-compatible patches, external limits, invalid syntax and Java types, comments/string semantics, rate capacity, graph edges/message passing, name invariance, baseline behavior and CLI output. When a JDK is installed, independent JVM tests compile only the repository's generated fixtures and replay witnesses and patched boundary cases.
