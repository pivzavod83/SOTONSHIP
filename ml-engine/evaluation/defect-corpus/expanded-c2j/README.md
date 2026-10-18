# Expanded COBOL-to-Java behavioral adjudication

This follow-up classifies **all 23 previously untriaged development task families** from the initial Java screening. It uses unchanged published programs and original COBOL drivers, with input/output contracts frozen before each new replay. No LLM API, injected bugs, held-out execution or model fitting is involved.

## Results

| Outcome among the 23 families | Count | Families |
| --- | ---: | --- |
| Reproduced discrepancy with agreeing COBOL/canonical controls | 4 | 17, 47, 119, 143 |
| No mismatch within the tested shared contract | 11 | 35, 43, 70, 73, 85, 88, 105, 110, 120, 128, 145 |
| Reference-policy or representation conflict | 6 | 92, 103, 113, 126, 134, 151 |
| Unsupported mapping | 2 | 74, 99 |

Together with the earlier tasks 94 and 98, the [consolidated review queue](consolidated-2026-10-18/review-queue.json) contains **six discrepant candidate programs in six source tasks**, supported by **25 input witnesses**. Nine witnesses return a different value/list; sixteen throw a deterministic exception inside the translated program. Multiple witnesses from one program are not independent faulty programs.

| Source task / candidate | Representative original input | Actual source/control | Actual candidate | AI-inspected cause |
| --- | --- | --- | --- | --- |
| 17 / 14B | `"o o o o"` | `[4,4,4,4]` | `[4,4,4]` | Final unpadded whole note is omitted. |
| 47 / 7B | `[3,1,2,4,5]` | `3` | `4` | One-based third element became Java's zero-based fourth element. |
| 94 / 14B, preserved initial case | `[0,8,1,2,1,7]` | `7` | `8` | Even-composite rejection omitted. |
| 98 / 7B, preserved initial case | `"aBCdEf"` | `1` | `0` | Index parity shifted after conversion to zero-based indexing. |
| 119 / 7B | `["()(",")"]` | `"Yes"` | `StringIndexOutOfBoundsException` | Combined length is used without constructing the combined strings. |
| 143 / 7B | `"This is a test"` | Normal string return | `IndexOutOfBoundsException` | String append uses a length where Java requires an end index. |

All strong cases have successful actual COBOL and agreeing canonical Java executions on the same frozen input. Program exceptions are distinguished from compilation, timeout, resource and adapter failures. Suspected causes/spans are AI-supported inspection, not independently reviewed localization labels.

## Why several screening failures were excluded

- Fixed `OCCURS` inputs do not establish behavior for arbitrary Java list lengths. Tasks 35/43/70/73/85/88/105/110/120/128/145 agree on the tested fixed-size shared inputs despite Java-only screening flags.
- Task 74 initializes only part of two ten-element string arrays. We did not invent missing Java values or infer a logical return length from the expected answer.
- Task 99 uses quoted text MOVEs into a COBOL `COMP-2` field while the declared Java template takes `String`; one candidate also exposes a different method. This interface is unresolved, and no candidate method was renamed to make it pass.
- `COMP-2` is mapped consistently to Java `Double`. Integer-looking MOVE spelling does not justify creating Java `Integer` objects. Tasks 92 and 151 demonstrate why this matters.
- Tasks 103 and 113 disagree with the source while canonical Java also follows another behavior. They are retained as source/reference-policy conflicts, not silently promoted into the strong defect queue.
- Tasks 126 and 134 can agree with the actual COBOL while differing from the canonical Java policy. A failed benchmark assertion alone is insufficient to label the candidate a mistranslation.

List lengths/projections come from source declarations, source loops or input grammar, never expected-answer length. Full native output records and unused-tail checks are retained. These are explicitly scoped contracts, including return-value-only median observation and declared storage-padding treatment; they do not establish unrestricted source equivalence or all side effects.

## Coverage and evidence

The expansion accounts for 109 original drivers: **108 were executed**, with one empty music literal rejected before execution. **101 drivers have an eligible shared-input mapping**, across 21 families; the other seven executed drivers belong to unsupported mapping evidence. Combined with the initial audit, shared-input replay covers **40 development source tasks and 228 original driver cases**. This is a selected corpus-curation sample, not an unbiased performance or defect-prevalence estimate.

- [Overall frozen run plan](run-plan-2026-10-18.json).
- Numeric A: [frozen contract](numeric-a/frozen-contract-2026-10-18.json), [execution report](numeric-a/adjudication-2026-10-18.json), [family dispositions and witnesses](numeric-a/family-dispositions.json).
- Numeric B: [frozen plan](numeric-b/replay-2026-10-18/frozen-plan.json), [execution report](numeric-b/replay-2026-10-18/replay-report.json), [evidence checks](numeric-b/replay-2026-10-18/evidence-check.json), [cause inspection](numeric-b/replay-2026-10-18/cause-inspection.json).
- Text: [frozen plan](text/frozen-plan.json), [execution report](text/replay-report.json), [evidence checks](text/evidence-check.json), [triage notes](text/triage-notes.json).
- [Consolidated summary](consolidated-2026-10-18/summary.json) and [pending review packets](consolidated-2026-10-18/review-queue.json).

Raw source, drivers, probes and process logs remain in the ignored corpus cache. Reports bind them with SHA256; exact script/helper/test snapshots accompany each cohort. The original 120/23 partition, active model, original programs and previous execution reports are preserved. The 23 reserved families were not executed. Prior retrieval exposure of those tasks remains disclosed.

The review packets group all witnesses under one source/candidate pair, retain frozen graph-component groups and contain no fabricated human approvals. `trainingEligible` is false and each human decision remains `PENDING`. Review the exact source, mapping, output scope and program exception before admitting a defect; intentional migration-policy changes need a separate decision. A different test-compatible model output is a control, not a reviewed historical fix.

## Reproduction

Run from `ml-engine/`, using the pinned cached artifacts, GnuCOBOL 3.2 and Java 21 documented in the [initial audit](../README.md). Each new adjudicator has `prepare` and `run` stages; inspect its `--help` for contract/report/toolchain paths. Use new output locations: frozen/completed evidence refuses overwrite. No application API or extension executes these corpus programs.

Rebuild the consolidated metadata without executing either language:

```sh
.venv/bin/python scripts/summarize_c2j_adjudication.py --output evaluation/defect-corpus/expanded-c2j/new-consolidation
```

The summary validates complete 23-family coverage, reserved-family exclusion, pinned input bytes, normalized-report linkage, graph-component membership and original driver hashes. Its output includes an exact source snapshot for reproduction.

## Training readiness

This step expands strong machine-reproduced evidence from two to six source tasks and provides concrete review packets. It does **not** turn six tasks into 25 independent defects or hundreds of independent fragments. Six positive source groups still support only a small exploratory training experiment, not a credible claim of reliable COBOL-specific generalization. Independent human adjudication remains pending; no replacement model, accuracy estimate or gold localization labels were produced. Broader natural COBOL-to-Java failures and separately reviewed evaluation cases are still needed.
