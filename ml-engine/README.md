# Paired AI defect review, program matching and bounded verification

The migration workflow includes local learned supplied-pair defect review, optional coding-LLM review, optional whole-program GNN matching and independent bounded Z3 verification. AI hypotheses never become proof. The new local graph-feature classifier/ranker uses a separately frozen ten-family synthetic dataset; it failed held-out evaluation (1/8 correct, 12.5%, below 50% baselines). See the [detector guide](../docs/local-defect-model.md) and [actual experiment](evaluation/synthetic-pilot/defect-model-v1/README.md). No API key is required for local inference.

`python -m ml_engine.defect_detection --stdin` analyzes a source pair with portable NumPy weights and returns source-bound `MODEL_HYPOTHESIS` locations. The browser uses this through the readonly `/api/defect-reviews` CQRS endpoint. Its three fold checkpoints retain separate training subsets, with no full refit. The graph extractor is heuristic; this is not a trained GNN or proof. Test results and failed generalization remain visible in the UI.

From this directory, install and check:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

## Paired AI defect review

`ml_engine.ai_review` uses a configurable OpenAI-compatible Chat Completions endpoint. Set `LLM_MODEL`, `LLM_API_KEY` and optionally `LLM_BASE_URL` on the backend. HTTPS is required for remote providers; plain HTTP without credentials is allowed only for explicit loopback providers. Strict structured output is the default, with explicit JSON-mode/text compatibility settings. No provider SDK or extra Python dependency is required.

```sh
.venv/bin/python -m ml_engine.ai_review --stdin < ai-review-request.json
```

Input contains `moduleName`, `cobolSource`, `javaSource`, optional `cobolSourceFormat` (`AUTO`/`FREE`/`FIXED`) and optional `analysisContext`. Exact sources are limited to 100,000 characters and 1,500 LF-separated lines each. Output includes status, summary, line-anchored findings, exact source hashes and provider model metadata. Each finding is `AI_HYPOTHESIS`, and candidate inputs are `NOT_EXECUTED`. The model cannot run code, apply changes or modify proof status. Standalone CLI configuration comes from exported environment variables; the Nest backend also loads the documented `.env` files.

Missing model/key returns `NOT_CONFIGURED`; provider failures, refusal and invalid output return explicit empty-finding statuses. Empty successful findings do not prove equivalence. Source spans and proposed JSON inputs are locally validated; excerpts are copied from raw source, never trusted from the model. Transport has bounded time/size, no redirects or automatic retries, and errors do not expose provider bodies or credentials. Code/comments are treated as untrusted analysis data.

See [setup and API examples](../docs/ai-defect-review.md). Tests use local mock responses and establish protocol correctness, not model detection accuracy. Existing immutable corpus/model experiments and the 23 reserved families are untouched.

## Dataset and actual fitting

The pinned COBOL-JavaTrans benchmark contains 143 small HumanEval-derived program pairs, not production banking modules. Sources and tests are upstream-created and reviewed according to the authors; we use their program correspondence labels, not a claim of unrestricted equivalence. Raw code remains outside Git in `evaluation/corpora/`. The manifest, licence attribution, split task IDs, model weights and measured report are versioned.

```sh
.venv/bin/python scripts/fetch_paired_dataset.py
.venv/bin/python scripts/partition_paired_dataset.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/train_paired_candidates.py --prepare
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/train_paired_candidates.py --train
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/train_paired_candidates.py --evaluate-final
```

The active v4 experiment compares four fixed improvements with a fresh GNN control: count-sensitive mean/max/scaled-sum readouts, separate COBOL/Java heads, WL graph features with ridge CCA, and fitting-only sequence-edge dropout. Every candidate retains five 96-pair models from the frozen grouped folds (24 validation each). **No final fit on all 120 occurs.** CCA preprocessing is fitted on each training fold only. The shared checkpoint and candidate are chosen by pooled development-only Top-1, then MRR and the frozen tie-breaks. Runtime averages the five member cosine scores.

The selected regularized GNN uses epoch 80 and scores **9/23 Top-1 (39.13%)**, **15/23 Top-3 (65.22%)**, **17/23 Top-5 (73.91%)**, **MRR 0.563294**. The original control scores 7/23 Top-1; separate heads score 11/23 but were not selected by CV, so the final ranking does not change deployment. CV selected the regularized GNN at 51/120 Top-1 (42.50%, tied control), with higher MRR 0.5658 vs 0.5583. Name matching still scores 22/23.

All candidates and the CV winner were frozen before the one-shot final comparison. The 23 were previously assessed in v1/v2/v3, and this protocol follows those results: they are excluded from all new fitting and selection, but are not genuinely unforeseen data. A development query's CV score comes only from the member that excluded it; these are selection statistics for individual held-out members, not unbiased five-member ensemble validation.

See [the evaluation guide](evaluation/README.md), [papers and frozen settings](evaluation/paired-code/cv-v4-candidates/run-plan.json), and [complete results](evaluation/paired-code/cv-v4-candidates/final-evaluation-report.json). These changes adapt ideas from GIN, paired-view learning, WL kernels and GraphCL; they do not reproduce those full architectures. The regularizer modifies graph views of original training pairs, not labels or source-program counts. Completed default stages are immutable: use a new output directory and model path for an explicitly declared reproduction.

The four financial fixtures are excluded from matching training. This matching model has no Java generation, defect-risk probability or localization head; the separate synthetic detector above is a different experiment with uncalibrated learned scores. The fixed human-review gate remains unchanged; Z3 independently checks its supported financial contract. Historical v1/v2/v3 models and reports remain intact. The old v2 refit instruction is superseded by v4's no-refit plan without changing assignments.

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

The optional `verify --id UUID` CLI reads PostgreSQL with `DATABASE_URL`; `--persist` additionally updates analysis with version/source checks. The verification CLI does not send sources or database credentials to a model provider. The separate AI review action sends selected source text and context to the configured provider; it never receives database credentials.

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
