# Repository instructions

This project is an ML-led COBOL-to-Java program-matching workbench with independent bounded financial verification. Work in `backend/`, `ml-engine/` and the optional `vscode-extension/` client, plus root documentation/configuration and provenance records in `data-sources/`. Keep `frontend/` empty except for `.gitkeep`.

## Required architecture

The API is NestJS + **Layered DDD + CQRS + MikroORM + PostgreSQL**. Never introduce TypeORM or replace CQRS with a controller/service/repository chain.

```
HTTP -> presentation/controllers (validated DTO)
     -> CommandBus / QueryBus -> application handler
     -> domain repository interface -> infrastructure repository
     -> infrastructure mapper -> module-root MikroORM persistence entity -> PostgreSQL
application handler -> presentation RTO -> HTTP
```

Apply this layout to `backend/src/modules/verification/` and `fx-rates/`:

| Location | Responsibility |
| --- | --- |
| `presentation/controllers`, `dto`, `rto` | HTTP, validation, Swagger, DTO input and RTO output; dispatch commands/queries. |
| `application/commands/handlers`, `queries/handlers`, `services` | Use cases; mutations are commands, reads are queries. Handlers orchestrate aggregates, repository ports and the ML bridge, publish events, and construct RTOs. |
| `domain/entities`, `value-objects`, `repositories`, `events`, `enums` | Pure TypeScript business model. No NestJS, MikroORM, database, subprocess or HTTP imports. |
| `infrastructure/repositories`, `mappers`, `ml-bridge` | MikroORM adapters, persistence/domain conversion and Python subprocess integration. |
| module-root `entities/*.entity.ts` | MikroORM PostgreSQL table declarations, separate from domain entities. |
| `backend/src/common/` | Exceptions/filter, translations, shared values/RTOs/pipes, migrations and seeders. |

Inject repository interfaces with explicit tokens such as `'IVerificationRepository'`. The infrastructure mapper is the conversion boundary between persistence and domain models. Discover compiled persistence models with `dist/**/entities/*.entity.js`, and use the matching TypeScript pattern during development. Preserve numeric FX rates as decimal strings. Never return persistence or domain entities directly from controllers.

`VerificationRun` holds sources, alignment/risk scores, baseline, proof status, graph, witnesses, scope and provenance. Commands run verification or apply a proposed patch. A patch can be saved only after fresh Z3 verification returns `UNSAT_PROVEN_SAFE`; preserve the original row on failed verification. Publishing a completion event does not imply that a run was proved safe.

Use explicit migrations and the idempotent initial seeder. Four precomputed rows make the list API useful immediately after setup; do not overwrite subsequently patched runs when reseeding.

## Engine and proof integrity

`code_graph.py` produces bounded heuristic operation/type/literal graphs with data/control/sequence relations. `paired_gnn.py` contains portable NumPy relation-aware message passing, whole-program pooling and a paired-source contrastive objective. The saved model is fitted on actual source pairs from the pinned 143-task COBOL-JavaTrans benchmark. It does not use the deleted random-feature trainer or XGBoost risk classifier. Whole tasks/near-duplicate groups are split before fitting; checkpoint/gate decisions use validation. Never tune on test metrics or hide a baseline that wins. The report discloses prior test exposure before code-review fixes; do not describe it as a pristine external validation.

`POST /api/matches` runs a read-only QueryBus use case through a domain-validated application port and the shared bounded Python worker. It returns ranked program candidates tied to exact source hashes and model provenance. Scores are cosine similarities, not probabilities. A trained-model result can remain `REVIEW_REQUIRED` when validation does not support automatic suggestions. An engineer explicitly confirms a Java candidate and supplies proof inputs before verification. A matching result never authorizes an edit or supplies proof premises. Keep the new matching module layered even though no matching table is persisted.

The 143 upstream program pairs label whole-task correspondence, not equivalent statements, defect locations or production banking correctness. The current model has no risk or repair head. `gnnBugRiskScore=0` is a deprecated compatibility field with `riskAssessment.status=NOT_ESTIMATED`; do not display it as low risk. `gnn_aligner.py` provides a program-level compatibility link in the verification inspection graph, not predicted paragraph/method ground truth. The old node-risk evaluator refuses to evaluate this incompatible task.

`cpg_builder.py` retains a separate line-oriented inspection graph. `z3_formal_prover.py` uses its own closed parser and recognized source semantics for every mathematical claim. Neural matching never prunes inputs, narrows bounds, substitutes a rate or changes proof status. Never infer successful verification from filenames, model confidence or the presence of BigDecimal. Unsupported statements/side effects and external CICS/JCL state remain UNKNOWN.

External stdin/API verification requires explicit `proofInputs`: COBOL source format, amount/rate/result field names, Java parameter names, cent bounds, and exact reference-rate pair/source/collection date. Missing or mismatched inputs must return `UNKNOWN_HALTED_LIMIT`; never substitute another rate. `FREE` and a restricted fixed-reference normalizer are supported; continuation/debug lines and other compiler features remain unsupported. Seed proof scopes retain the explicit input contract.

API routes are available without credentials or role checks. Analysis uses a bounded in-process asynchronous queue; it is not durable. List reads are paginated. Do not describe the queue as restart-safe until durable job persistence is implemented.

`UNSAT_PROVEN_SAFE` means equivalence **only for the recorded `proofScope`**, including input bounds, arithmetic/rounding semantics, supported operations and fixed reference rates. It does not establish full COBOL/Java language equivalence or production banking safety. `SAT_COUNTEREXAMPLE_FOUND` requires a concrete reproducible witness. `UNKNOWN_HALTED_LIMIT` is a normal honest result. Proposed fixes must preserve the modeled COBOL behavior, including width truncation and paragraph fall-through when present.

Report actual retrieval metrics and denominators from the versioned training/stress reports. A controlled anonymized-name stress test is not a new independent holdout. Financial-domain reliability, exact localization, and production safety remain unvalidated. Do not advertise unmeasured accuracy or latency. Keep model, dataset, split and report hashes visible.

## Data, licences and AI disclosure

The paired-training manifest, source/licence notices, split IDs and measured reports live in `ml-engine/evaluation/paired-code/`; raw benchmark sources stay in the ignored corpus cache and are fetched by commit-pinned URL. Actual runtime GNN weights are versioned. Do not fabricate reviewer votes or relabel upstream correspondence as formal correctness.

The authoritative financial-reference inventory is `data-sources/` (source URLs, observation and collection dates, licence notices and snapshot hashes); the reproducible four-case fixture and computed results are in `ml-engine/data/`. Consult the root README's source table before changing fixture rates or corridor values.

Use Bank of England published daily FX data with its actual observation date; do not label the illustrative `1.2941` as a BoE observation on `2026-10-16` unless the provider confirms it. World Bank Remittance Prices Worldwide describes corridor/provider costs and quoted FX data; total remittance cost is not a central-bank spot rate. Open-source COBOL reference samples retain their upstream licences. Generated demo COBOL/Java is not authentic production bank code.

Record newly collected external data with its real collection date and source vintage. Preserve the distinction between the user/client date `2026-10-17` and a provider's available observations. Never invent future data or licences. Do not copy upstream code without preserving its licence and provenance. All application code, demo banking source pairs, model construction/training code, tests, precomputed proof explanations and documentation introduced in this task were AI-generated and require human review; upstream source/data retain their separate attribution.

## Validation

The VS Code extension is a thin desktop client for the existing local API. It reads only explicitly selected editor documents, including unsaved text; sends code only on a requested verification; and never starts an LLM or executes submitted source. Keep its webview passive, use a strict CSP, and render response/source text as text. Proof-input mappings and source SHA-256 hashes bind a result to a precise question. Editing source, mappings or the endpoint invalidates previous results and diagnostics. Candidate ranking reads only explicitly selected unsaved documents; confirmation rechecks hashes, text, endpoint and source format and selects only a URI. It does not apply Java edits or silently infer the proof contract. Applying a candidate requires a fresh supported, bounded UNSAT result for the exact current documents, followed by a version-aware native editor edit. Leave the edit unsaved and undoable. Diagnostics identify program-level findings; do not claim that a first-line report anchor identifies the defect location. The extension has its own unit and native-host tests; the server architecture rules remain unchanged.

From `vscode-extension/`: run `npm ci`, `npm test`, and `npm run package` to build the local VSIX. With the backend running, `npm run test:host` runs native VS Code integration checks in a separate temporary profile. `LIVE_VERIFIER_URL` selects the local API for these checks. Keep generated VSIX files, dependency installs, extension-host profiles and compiled output out of Git. The extension package is not a Marketplace publication.

From `backend/`: install with `npm ci`, run `npm run build` and `npm test`. With PostgreSQL running, run migrations, seed and `node test/api.smoke.mjs` against a disposable database. From `ml-engine/`: create a Python 3.11–3.13 virtualenv, install `requirements.txt`, and run `python -m pytest`. Regenerate seed results with the documented precompute command after changing supported source semantics or reference data. Check actual solver results and witnesses, patch re-verification, unsupported-code rejection and import boundaries. Keep secrets, virtualenvs, installed dependencies and generated build output out of Git.

## Reproduce paired learning

From `ml-engine/`, fetch the pinned public dataset with `.venv/bin/python scripts/fetch_paired_dataset.py`, train with `OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/train_paired_gnn.py`, and evaluate the frozen model under controlled declaration renaming with `.venv/bin/python scripts/evaluate_paired_gnn.py`. Keep derivatives in the same original-task split. Preserve both original-name and renamed-baseline results. Training and inference require only the runtime NumPy dependencies. Model metadata must bind to the exact loaded weight bytes; write artifacts atomically. The financial regression fixtures remain separate and are never training examples.
