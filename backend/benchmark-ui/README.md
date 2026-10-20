# Parity benchmark lab

A separate, read-only localhost dashboard for the project's recorded model
versions, evaluation results, failure cases and paper-backed next experiments.
It runs independently of the Nest API, PostgreSQL and the migration workbench.
`frontend/` remains empty except for `.gitkeep`.

Requires Node.js 22 or newer. From `backend/`:

```sh
npm run benchmarks
```

Open **http://127.0.0.1:3010**. Set `BENCHMARK_PORT` to use another port. The
existing workbench remains at http://127.0.0.1:3000. The new dashboard binds to
loopback and serves only its static assets and explicit evidence routes.

Use the task and assessment controls to inspect defect-detection classification
separately from program-matching retrieval. Select a version for its changes,
recorded metrics, problems, source report, GitHub branch and immutable artifact
commit. Research entries link to peer-reviewed papers and clearly distinguish
proposed experiments from trained models. The failure inspector shows a stored,
source-bound runtime discrepancy, not a newly executed program.

Metrics are read from committed JSON reports, never invented or recomputed by
training. Refresh reloads evidence; downloading a snapshot exports the catalog.
The dashboard cannot train models, execute submitted source, approve a
translation, modify a proof or apply a patch. Missing metrics remain unavailable
instead of becoming zero. Historical and reused evaluations retain their scope
and denominators; different tasks, splits and galleries are not interchangeable.

`catalog.mjs` builds the version inventory and validates available frozen
evidence. A computed report SHA-256 identifies the bytes; it is not by itself
proof of an independently frozen evaluation. Inspect each record's integrity
details and links. GitHub artifact links use exact commits where available;
branch links show the current artifact branch, not a fabricated historical
development branch.

The research inventory is `research.json`; its methodology and applicability
limits are documented in [benchmark research](../../docs/benchmark-research.md).
This dashboard, its explanations and research summaries were AI-generated and
require human review. Published papers and upstream data retain their original
attribution. No provider API key is needed.

Run the catalog and server checks with:

```sh
npm run test:benchmarks
```

Adding an experiment requires a separately versioned report and an explicit
catalog adapter. Preserve completed model/data/protocol/evaluation artifacts.
Do not tune against known regression outcomes or promote a matcher score to a
defect-detection metric.
