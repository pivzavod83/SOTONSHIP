# CodeNet acquisition and source-coverage audit

This separate experiment prepares IBM Project CodeNet for future COBOL/Java
research. It does not retrain the deployed detector, run downloaded programs, or
turn judge outcomes into migration-defect labels. Raw source stays in ignored
`evaluation/corpora/`; small versioned inventory and coverage reports belong here.

## Why the previous test reports contain eight pairs

The synthetic defect pilot has **40 pairs across ten source families**: 24
training examples measured with grouped out-of-fold predictions, eight validation
examples, and eight already-known regression-test examples. These assessments
have different roles and must remain separate. Adding training examples to the
eight test examples would not produce a larger independent test. See the
[typed-extractor benchmark](../extractor-v2/README.md).

CodeNet offers new problem families, but independently written COBOL and Java
solutions to one problem are **not established translations**. A Java Wrong
Answer followed by an Accepted submission is a candidate repair history. Neither
status establishes a COBOL-to-Java translation defect. Accepted means acceptance
by the original judge, not a proof of equivalence for every input. Compilation,
runtime, resource and adapter failures must remain distinct from semantic errors.

## Acquisition and provenance

The [official IBM repository](https://github.com/IBM/Project_CodeNet) links the
full compressed archive. The importer retains COBOL sources and matching Java
families, filtered metadata, descriptions, available sample I/O and relevant
duplicate-problem information. Sample tests are not the complete hidden judge
suite. The official documentation currently says standalone metadata is no longer
available; language selection saves extraction space, not archive download bytes.

The **dataset licence is CDLA-Permissive-2.0**, while IBM's supporting repository
uses Apache-2.0. Preserve the source licence notices and the
[CDLA agreement](https://cdla.dev/permissive-2-0/). The authors document this
distinction in Appendix A.6 of the
[peer-reviewed CodeNet paper](https://datasets-benchmarks-proceedings.neurips.cc/paper_files/paper/2021/hash/a5bfc9e07964f8dddeb95fc584cd965d-Abstract-round2.html).
Collection date, source/archive hashes and file identities are recorded in the
import manifests. Local preparation scripts and tests were AI-generated.

The archive was collected on **20 October 2026**: 8,343,137,473 compressed bytes,
SHA-256 `7e96620307f874269a62cc0225f2a5a13d2de2b3c368cf61319c87ec276620fb`.
This matches the checksum in the [IBM repository contributor's
comment](https://github.com/IBM/Project_CodeNet/issues/66#issuecomment-3534450983).
The multipart HTTP ETag is not an MD5 checksum. See the
[download receipt](import-v1/download-receipt.json) for the exact working URL,
source vintage and checksum provenance. The older `dax-cdn` URL failed DNS
resolution during collection.

After downloading that archive to the ignored corpus cache, reproduce the
selection from `ml-engine/` using a new output/report version if one exists:

```sh
.venv/bin/python scripts/prepare_codenet.py \
  --archive evaluation/corpora/codenet/source/Project_CodeNet.tar.gz \
  --output evaluation/corpora/codenet/import-v1 \
  --report evaluation/codenet/import-v1/inventory.json \
  --stage all --collection-date 2026-10-20 \
  --archive-sha256 7e96620307f874269a62cc0225f2a5a13d2de2b3c368cf61319c87ec276620fb
```

The two streaming passes avoid extracting unrelated languages. A bounded
`derivedLayoutCensus` records the archive's actual derived-data categories;
the retained contracts and duplicate metadata must be checked against it.
The accepted-only Hugging Face mirror loses the rejected submission histories
needed here, so it is not a replacement for this archive.

## Collected corpus and measured results

The completed [inventory](import-v1/inventory.json) contains:

| Item | Count |
| --- | ---: |
| COBOL source files | 1,277 |
| Java source files for COBOL-containing problems | 251,052 |
| Distinct COBOL problem IDs | 340 |
| Problems with UTF-8 Accepted COBOL and Accepted Java candidates | 325 |
| Same-user Java Wrong Answer → Accepted history candidates | 23,225 |
| Source files missing metadata, or metadata rows missing sources | 0 |

COBOL judge outcomes include 727 Accepted, 345 Wrong Answer, 133 Compile Error,
25 Runtime Error and 47 Time Limit Exceeded. Java includes 148,665 Accepted and
57,321 Wrong Answer submissions; all remaining statuses are retained separately.
The selected archive payload is 364,097,739 bytes, excluding generated manifests
and filesystem allocation overhead. Raw files and histories remain outside Git.

The [coverage audit](import-v1/extractor-coverage.json) selected **650 pairs across
325 problem IDs**: one Accepted and one Wrong Answer Java submission against an
Accepted COBOL anchor per problem, chosen before parsing. Every audited source
hash verified. These are independently authored same-problem combinations.

| Explicit COBOL probe | COBOL sources with complete frontend extraction | Selected pairs with both frontends complete | Pair abstentions |
| --- | ---: | ---: | ---: |
| FREE | 41 / 1,277 | 0 / 650 | 650 / 650 |
| FIXED | 2 / 1,277 | 0 / 650 | 650 / 650 |

The 650 selected Java programs yield 346 PARTIAL and 304 UNSUPPORTED results;
none is COMPLETE. Frequent blockers include imports, library calls, arrays and
unsupported control/statement forms. COBOL also exceeds the bounded scalar
statement/declaration grammar. Counts of issue occurrences in the raw report are
not counts of distinct defective programs. FIXED/FREE discrepancies do not tell
us which compiler profile is valid for a source.

**This measures parser coverage, not 0% classifier accuracy.** No classifier was
run, no code was compiled/executed, and no defect labels were assigned. Accuracy
and recall remain null. The next implementation priority is compiler-backed
frontends and explicit I/O/array contracts, followed by behavior-backed curation;
simply feeding these programs into model training would not address that gap.

## Supporting metadata supplement

The first selective import captured problem samples and root duplicate metadata,
but missed global sample caveats and deeper Java clone records. Its evidence is
preserved unchanged. A separate ignored `metadata-supplement-v1/` retains the
complete small input/output tree and Java/global non-token duplicate metadata:
**11,800 files, 46,306,566 bytes**. The [supporting-metadata report](import-v1/supporting-metadata.json)
binds the full raw file manifest and records exact selection/postfilter steps.
Bulk token files and C/C++/Python duplicate trees were removed from this new cache.

To reproduce its final file selection with BSD tar, use a new empty output:

```sh
tar -xzf evaluation/corpora/codenet/source/Project_CodeNet.tar.gz \
  -C evaluation/corpora/codenet/metadata-supplement-v1 --strip-components 1 \
  --include 'Project_CodeNet/derived/input_output/*' \
  --include 'Project_CodeNet/derived/duplicates/*' \
  --exclude '*tokens*' --exclude '*/C++/*' \
  --exclude '*/C/*' --exclude '*/Python/*'
```

All 340 retained problem IDs have sample input/output files, but six appear on
the upstream **unverified sample** list. Upstream provides only the first sample,
and its replay checks covered C/C++/Python/Java rather than COBOL. Samples must
not be treated as complete or infallible oracles. The 153 published identical
problem clusters connect the 340 IDs into 331 upstream groups. Java clone data,
COBOL clones and cross-corpus overlap still require review; **331 is not a claim
of independently validated defect families**. No training split was assigned.

## Source-only coverage measurement

From `ml-engine/`, after the importer finishes both archive passes:

```sh
.venv/bin/python scripts/audit_codenet_coverage.py \
  --corpus evaluation/corpora/codenet/import-v1 \
  --output evaluation/codenet/import-v1/extractor-coverage.json
```

The audit refuses to overwrite completed evidence. It verifies selected source
identities against the import manifest, decodes UTF-8 strictly, and quarantines
unsupported encoding or exceeded budgets. Oversized sources are not read and
explicitly retain `sourceHashVerified: false`. It parses **all retained COBOL files**
and selects the first Accepted COBOL plus the first Accepted and first Wrong
Answer Java source by submission ID per problem. Selection occurs before parsing;
unsupported selected files stay in the denominator. Compilation-error judge
statuses are counted separately and never executed.

COBOL **FREE and FIXED are separate explicit analysis probes**. Success in one
does not choose a compiler profile or establish the source format automatically.
The report records complete/partial/unsupported/quarantined counts, issue-code
distributions, selected-pair coverage and distinct problem IDs. Duplicate-problem
clusters and overlap with existing corpora still need resolution before claiming
independent families or assigning training splits.

No model is loaded or scored. No source is compiled or executed. Every semantic
label remains `UNKNOWN`, `trainingEligible` remains false, and accuracy/recall
are null. Even complete frontend coverage requires review: it is not compiler
validity, behavioral equivalence or permission to accept a migration.

## Next evidence needed

Target at least ten independently grouped new problem families, preferably
twenty. Freeze common input/output contracts and evaluation selection before
model predictions. Confirm candidate-origin discrepancies with compatible source
and control executions, preserve witnesses, and independently adjudicate labels.
Call independently authored CodeNet pairs an **auxiliary cross-language
task-consistency benchmark**. Obtain actual translation attempts separately for
claims about migration-defect detection. Compare frozen models without tuning on
the new assessment, reporting abstentions and review workload alongside any
eligible classifier metrics.
