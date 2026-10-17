# Repository instructions

This project is a bounded neuro-symbolic COBOL-to-Java financial verification prototype. Work only in `backend/` and `ml-engine/`, plus root documentation/configuration and provenance records in `data-sources/`. Keep `frontend/` empty except for `.gitkeep`.

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

`ml-engine/ml_engine/cpg_builder.py` extracts AST/control/type features into NetworkX graphs. `gnn_aligner.py` performs two rounds of graph message passing, cosine subgraph alignment and node risk scoring from saved demo model assets. `z3_formal_prover.py` encodes the recognized arithmetic subset and searches for output inequality. The Python CLI supports JSON stdin and database-backed UUID lookup against the API's PostgreSQL schema.

Neural alignment guides candidate matching; it is not a proof premise and is not mathematically necessary for every equivalence problem. Formal claims must be backed by Z3 constraints derived from recognized source semantics. Never choose a successful status from a filename, category, source comment, or the mere presence of `BigDecimal`. Reject unsupported statements/side effects rather than omitting them. External CICS/JCL and unsupported memory aliases must return `UNKNOWN_HALTED_LIMIT`.

External stdin/API verification requires explicit `proofInputs`: COBOL source format, amount/rate/result field names, Java parameter names, cent bounds, and exact reference-rate pair/source/collection date. Missing or mismatched inputs must return `UNKNOWN_HALTED_LIMIT`; never substitute another rate. `FREE` and a restricted fixed-reference normalizer are supported; continuation/debug lines and other compiler features remain unsupported. Seed proof scopes retain the explicit input contract.

API routes require configured RS256 Bearer authentication and role claims (`verifications:read` / `verifications:write`). Analysis uses a bounded in-process asynchronous queue; it is not durable. List reads are paginated. Do not describe the queue as restart-safe or access as tenant-isolated until durable job persistence and tenant/portfolio row scoping are implemented.

`UNSAT_PROVEN_SAFE` means equivalence **only for the recorded `proofScope`**, including input bounds, arithmetic/rounding semantics, supported operations and fixed reference rates. It does not establish full COBOL/Java language equivalence or production banking safety. `SAT_COUNTEREXAMPLE_FOUND` requires a concrete reproducible witness. `UNKNOWN_HALTED_LIMIT` is a normal honest result. Proposed fixes must preserve the modeled COBOL behavior, including width truncation and paragraph fall-through when present.

Do not advertise 94%/18% alignment accuracy or sub-200ms performance without a measured and identified dataset/runtime. Synthetic model training or calibration is demo evidence, not independent generalization evidence. Keep model origin and measured timing visible in metadata/documentation.

## Data, licences and AI disclosure

The authoritative source inventory is `data-sources/` (source URLs, observation and collection dates, licence notices and snapshot hashes); the reproducible four-case fixture and computed results are in `ml-engine/data/`. Consult the root README's source table before changing fixture rates or corridor values.

Use Bank of England published daily FX data with its actual observation date; do not label the illustrative `1.2941` as a BoE observation on `2026-10-16` unless the provider confirms it. World Bank Remittance Prices Worldwide describes corridor/provider costs and quoted FX data; total remittance cost is not a central-bank spot rate. Open-source COBOL reference samples retain their upstream licences. Generated demo COBOL/Java is not authentic production bank code.

Record newly collected external data with its real collection date and source vintage. Preserve the distinction between the user/client date `2026-10-17` and a provider's available observations. Never invent future data or licences. Do not copy upstream code without preserving its licence and provenance. All application code, demo banking source pairs, model construction/training code, tests, precomputed proof explanations and documentation introduced in this task were AI-generated and require human review; upstream source/data retain their separate attribution.

## Validation

From `backend/`: install with `npm ci`, run `npm run build` and `npm test`. With PostgreSQL running, run migrations, seed and `node test/api.smoke.mjs` against a disposable database. From `ml-engine/`: create a Python 3.11–3.13 virtualenv, install `requirements.txt`, and run `python -m pytest`. Regenerate seed results with the documented precompute command after changing supported source semantics or reference data. Check actual solver results and witnesses, patch re-verification, unsupported-code rejection and import boundaries. Keep secrets, virtualenvs, installed dependencies and generated build output out of Git.
