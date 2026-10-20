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

The **Parser experiments** tab compares the frozen bounded V2 extractor with
the experimental V3 compiler frontends. It reports **syntax parsed**, **complete
name/type resolution**, and **complete shared semantic representation** as
separate counts with explicit denominators, failures and unknown outcomes.
FREE and FIXED COBOL source-format probes remain separate. Individual-language
source counts differ from the pair-level cohort. V3 retains the bounded typed
IR lowerer; an AST does not count as modeled semantics. These are coverage
measurements, not classifier accuracy, and the eleven trained model versions
remain unchanged. Diagnostic examples can be filtered by language. The page
reads the frozen offline run and cannot run a parser or submitted code.

The defect pilot contains **40 pairs across ten source families**: 24 grouped
out-of-fold predictions, eight validation pairs and eight reused regression
pairs. Use **View 24-pair cross-validation** to inspect the larger development
assessment. These partitions remain separate; none is presented as a new blind
test. The branch link follows the checked-out Git branch unless the catalog
caller supplies an explicit branch override. Detached or unavailable branch
information stays unavailable rather than showing a stale branch.

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
