# Synthetic pilot: batch 03 audit

The submitted batch is preserved byte-for-byte as `input-batch.json`, SHA-256
`87e181c46ba306d75373f36f37698a3de33b7dee836b8067839b922cd17ff502`.
It contains F005 (two-period compounded interest, proposed test split) and F006
(signed adjustment through an unsigned intermediate, proposed training split),
with four Java variants per reference. This is synthetic feasibility data,
separate from the original 143-pair matching corpus. No model was trained,
selected or evaluated during this audit.

## Executed checks

After inspecting the sources, `replay.py` compiled the two unchanged COBOL
references and eight unchanged Java candidates using GnuCOBOL 3.2 and Java 21.
All ten programs compiled successfully. The replay recorded **80 program
executions**: 12 supplied reference executions, 48 supplied Java executions,
four additional reference executions and 16 additional Java executions.

All proposed numeric outputs and mismatch flags agreed with execution. The four
nominally equivalent variants agreed with their references on every executed
input. Each of the four defective variants produced two supplied mismatch
witnesses. Additional probes found further witnesses for F006-V3 and F006-V4.
Passing these finite inputs does not prove universal equivalence.

Examples of actual observed values:

| Input / test | COBOL | Java candidate | Result |
| --- | --- | --- | --- |
| F005-T5: principal 100.10, rates 5.50 / 5.50 | 111.41 | V3: 111.42 | First interest incorrectly rounded instead of truncated |
| F005-T5: same input | 111.41 | V4: 111.40 | Second interest incorrectly truncated instead of rounded |
| F006-T5: start 500, adjustment -800, fee 400 | -100 | V3: -700 | Unsigned intermediate storage semantics omitted |
| F006-T5: same input | -100 | V4: 100 | Final signed balance incorrectly made absolute |

For F006, execution confirms that the negative intermediate sum is stored as its
absolute magnitude in the unsigned COBOL field, while the signed final field
preserves a negative result. The extra boundary probes target only F006,
the proposed training family. No additional test-family probes were generated.

The evidence directory `runtime-audit-2026-10-18/` retains the frozen probe plan,
source hashes, compiler versions, commands, raw stdin/stdout/stderr, exit codes,
normalized comparisons and artifact hashes. Compiled temporary files were
removed. The replay refuses changed input bytes or an existing output directory.
It is a pinned local audit, not a submitted-source execution API.

## Annotation improvements

All 31 source spans and 22 alignment records are structurally valid. The mappings
include 17 one-to-one, two many-to-one and three one-to-many records. F006-V1
also reorders an independent fee negation and maps noncontiguous Java segments.
These are meaningful improvements over purely positional mappings. Structural
checks and plausible mappings do not establish independently reviewed alignment
gold labels.

Both implementation styles now occur under both labels: each of integer and
BigDecimal arithmetic has two nominally correct and two defective candidates in
this batch. Contracts now specify canonical ASCII numeric inputs and a
20-character line limit. Classes remain neutrally named `Program`.

Across the six submitted families, the style-only rule "integer means correct;
BigDecimal means defective" still agrees with 16 of 24 proposed labels (66.7%).
This is a descriptive shortcut diagnostic, not measured model accuracy. Continue
balancing styles in subsequent batches. Exclude variant IDs, ordering, split
metadata, defect annotations, explanations and test outputs from model features.

## Split issue requiring a versioned correction

**F005 must not currently support a claim of independent test generalization.**
It is structurally close to F001 in the training split. Both use the sequence:

1. Truncate principal times a first percentage rate.
2. Combine principal with that intermediate amount.
3. Round the updated amount times a second percentage rate.
4. Add the second amount to the intermediate balance.

F001 subtracts at step 2 while F005 adds; names, domains and some field widths
also differ. They are not identical programs, but their dependency structure,
candidate implementations and defect positions are sufficiently similar to
require clone-group review before a split is accepted. Different business names
alone do not establish algorithm independence. The runtime report's inherited
`independentFamilies` count denotes the two submitted family records; this audit
does not certify their independence from the rest of the corpus.

Prefer replacing proposed test family F005 with a materially different algorithm.
Alternatively, assign F001 and F005 to the same clone group and split and revise
the full allocation explicitly. Keep this original upload and runtime evidence;
produce replacements as a separately versioned dataset. Do not silently relabel
or move a held-out family.

The requested complete 20-family algorithm/category/split manifest is still
missing. Obtain that plan before generating the rest of the corpus. It should
declare clone groups and preserve the intended per-category split allocation.
Earlier batch-02 metadata repair requests also remain separate from this upload.

Test sources and supplied labels were inspected for data quality. They have not
been used to tune a model. That inspection is disclosed and is not an unseen
model evaluation. Original model weights, the 143-pair corpus and its reserved
23 evaluation samples remain untouched.

## Reproduction

Use a fresh evidence directory and the actual installed compiler paths:

```sh
python3 ml-engine/evaluation/synthetic-pilot/batch-03/replay.py \
  --output /tmp/sotonship-batch03-new-audit \
  --cobc /path/to/cobc \
  --java /path/to/java \
  --javac /path/to/javac
```

The audit code, documentation and annotation assessment are AI-assisted. The
original upload retains its honest `PROPOSED` / `NOT_EXECUTED` annotations; actual
execution evidence is recorded separately. No production reliability, human
reviewer votes or model performance are claimed.
