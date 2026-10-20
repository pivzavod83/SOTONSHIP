# Parser V3: compiler frontend experiment

This source-only experiment broadens parsing and records three independent
coverage stages. It is a parser component, not a newly trained ML model. The
deployed detector, matcher weights, formal prover and all V1/V2 evidence remain
unchanged. No submitted programs run and no equivalence labels are inferred.

## What changed

- Java uses the JDK's public `javac` parsing/analysis APIs with Java 17 language
  rules, an empty external class/source path and annotation processing disabled.
  Source declarations, references, types and bounded AST summaries retain source
  locations. Public-class filenames come from the AST, avoiding artificial errors
  from CodeNet submission filenames.
- COBOL uses the real ProLeap 4.0.0 preprocessor, ANTLR grammar and semantic graph,
  pinned to upstream commit `d1bfe75bdd6d480f70c74c6345bcc02610ac30d3`.
  GnuCOBOL 3.2 provides independent static checks under its explicit default
  dialect; `-fsyntax-only` produces no executable. FREE and FIXED are separate
  probes, not automatic source-format inference. The documented FREE adapter
  uses ProLeap TANDEM with an inserted blank indicator column.
- The existing bounded typed IR lowerer remains a separate stage. Its recorded
  coverage is reused only for identical source hashes and verified unchanged
  implementation hashes, then gated by the new syntax and resolution results.
  A large AST does not count as complete behavior modeling.

## Three measurements

1. **Syntax parsed:** lexer and parser accept the full source without errors.
2. **Names/types resolved:** Java compiler analysis succeeds with complete
   recorded bindings. COBOL requires completed ProLeap ASG analysis, zero
   undefined references and an accepted GnuCOBOL static check. These are scoped
   compiler checks, not universal statements about runtime behavior.
3. **Semantics modeled:** the earlier two stages pass and the unchanged bounded
   typed IR lowerer reports complete representation coverage for the same source.
   This does not prove that the graph faithfully models every runtime behavior
   or that two programs are equivalent.

Unknown and failed cases remain in every denominator. Pair success requires both
programs to complete that stage. Historical V2 syntax and name/type metrics stay
unavailable because the previous audit did not measure them separately.

## Measured CodeNet results: `codenet-r1`

The cohort is the same exposed 650 same-problem COBOL/Java combinations across
325 problem IDs. All 1,277 COBOL files are additionally inspected under both
formats, giving 3,204 source/profile probes. Selection precedes new outcomes.

| Assessment | Syntax parsed | Names/types resolved | Semantics modeled |
| --- | ---: | ---: | ---: |
| Java sources | 650 / 650 | 648 / 650 | 0 / 650 |
| COBOL sources, FREE | 745 / 1,277 | 716 / 1,277 | 30 / 1,277 |
| COBOL sources, FIXED | 219 / 1,277 | 192 / 1,277 | 2 / 1,277 |
| Supplied pairs, FREE | 346 / 650 | 345 / 650 | 0 / 650 |
| Supplied pairs, FIXED | 64 / 650 | 64 / 650 | 0 / 650 |

Java resolution has one compiler failure and one incomplete binding inspection;
both remain outside the 648 completed cases. GnuCOBOL accepts 1,124 FREE probes,
but ProLeap syntax is incomplete on 402 of those accepted files. This exposes a
real grammar/dialect gap rather than a defect in the submitted programs. FIXED
results often reflect applying the wrong format to free-format code; do not
interpret the difference as a model-performance comparison.

The frozen V2 audit's pair representation coverage remains **0/650** under both
formats. Its syntax/resolution results were never separately measured, so no
invented before/after syntax percentage is presented. The new result establishes
broad Java syntax coverage and considerably broader language structure access;
the semantic lowerer still prevents complete pair analysis. **Classifier accuracy
and recall remain null**, and nothing in this experiment authorizes a migration.

Detailed evidence: [report](codenet-r1/report.json),
[pre-run protocol](codenet-r1/protocol.json),
[artifact bindings](codenet-r1/artifact-hashes.json), and
[build/dependency provenance](build-provenance.json).
Full AST responses remain in the ignored corpus cache with a hash in the report.

## Reproduce

Build the parser worker using the [module instructions](../../parser-frontends/README.md).
The bootstrap checks out pinned ProLeap source because its current coordinate
is not published on Maven Central. Jars, Maven caches and generated files stay
outside Git. A full JDK 17+ and Maven are required; recorded build/runtime JDK
is 21.0.10 with the Java 17 source profile.

From `ml-engine/`, after preparing the CodeNet corpus:

```sh
.venv/bin/python scripts/benchmark_parser_v3.py \
  --corpus evaluation/corpora/codenet/import-v1 \
  --output evaluation/parser-v3/codenet-r2 \
  --cobc /path/to/gnucobol/bin/cobc
```

Use a new output name: completed evidence and raw outputs cannot be overwritten.
Omitting `--cobc` leaves COBOL type-validation evidence unknown. This is a reused
coverage cohort, not a fresh classifier holdout. The dashboard on loopback port
3010 reads recorded evidence; it cannot compile, run, train or accept source.

## Remaining limitations and next work

ProLeap does not accept every GNU/IBM extension. For example, valid GnuCOBOL
`REPOSITORY. FUNCTION ALL INTRINSIC.` and some `EXIT PERFORM` forms remain visible
failures. Missing copybooks require an explicit dependency contract; no implicit
filesystem lookup is permitted. Rewritten COBOL positions are marked as
preprocessed coordinates unless original alignment is verified.

The next priorities are broader COBOL dialect coverage and lifting compiler ASTs
into a richer shared representation for arrays, strings, libraries, control flow
and numeric/storage semantics. No unsupported construct should be silently
discarded. Changes need a new version, targeted semantic contracts and comparisons
that preserve historical reports.

## Sources and disclosure

The Java compiler APIs are documented by [OpenJDK/Oracle](https://docs.oracle.com/en/java/javase/21/docs/api/jdk.compiler/com/sun/source/util/JavacTask.html).
[ProLeap](https://github.com/uwol/proleap-cobol-parser) is MIT licensed; its source
is pinned in the build receipt. [GnuCOBOL](https://gnucobol.sourceforge.io/doc/gnucobol.html)
is used as an installed compiler, not redistributed here. Other dependencies
retain their own licences and recorded identities. CodeNet was collected on
20 October 2026 under CDLA-Permissive-2.0; see its [acquisition record](../codenet/README.md).
Same-problem programs and judge outcomes are not reviewed migration-defect labels.
New adapters, benchmark code, tests, dashboard changes and documentation were
AI-generated and require human review; upstream tools and source retain attribution.
