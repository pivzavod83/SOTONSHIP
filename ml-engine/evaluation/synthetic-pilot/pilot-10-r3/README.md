# Complete synthetic defect pilot: ten families, forty pairs

Dataset generation and offline quality checks are complete. `dataset.json`
contains ten COBOL algorithm families, four Java candidates each, with twenty
proposed equivalent and twenty deliberately defective pairs. This is an
AI-generated feasibility corpus; it is not production bank code or an accuracy
benchmark with independently reviewed gold labels.

| Split | Families | Candidate pairs |
| --- | --- | --- |
| Training | F001, F002, F003, F006, F007, F008 | 24 |
| Validation | F004, F009 | 8 |
| Final testing | F005-R2, F010 | 8 |

`split-plan.json` binds these assignments to the exact dataset bytes and fifty
source hashes before model training. All variants, fragments and derivatives
stay in their source family. F011-F020 are outside this reduced scope. Archived
original F005 is not included; the active F005 is explicitly revision R2.

## Final-batch checks and repair

Both final COBOL references and all eight Java candidates compiled with
GnuCOBOL 3.2 / Java 21. The sixty supplied-case executions produced no reference
prediction, Java prediction or mismatch-flag error. Each of the four deliberately
defective variants has at least two actual supplied mismatch witnesses. No extra
validation/test probes were generated. These checks are not model evaluation.

The only new repair removes copied references to an absolute-value insertion
from F009-V1's bounds/safety explanation. That correct candidate contains no such
operation. `provenance.json` records both metadata edits. Sources, predictions,
alignments, split assignments and equivalence labels are unchanged. Every prior
eight-family record is preserved exactly from pilot-10-r2.

Earlier F004 formula metadata and explicit canonical input-contract revisions
remain versioned. Each included source hash matches its recorded offline runtime
evidence. Original uploads and historical reports remain unchanged; runtime
observations are attached only to the exact source version that was executed.

## Model status and boundaries

No defect model has been trained, selected or evaluated. Existing active weights
still perform program matching. The next work is implementing the pairwise defect
model, training on the six training families, selecting settings without test
feedback, assessing the frozen model once, and integrating advisory predictions
with the UI. Formal/runtime evidence remains separate from learned predictions.

Features may use source code and public contract/type information. IDs, ordering,
splits, clone groups, defect labels, explanations, supplied tests and runtime
outcomes must not be features. Supplied alignments may supervise training but
are unavailable as inference inputs and remain AI-proposed annotations.

Finite passing tests do not prove universal equivalence. Eight test pairs are
only two source families and cannot establish reliable real-world accuracy.
Validation/test sources were inspected for dataset quality, so this is not a
pristine blind benchmark. Report future results with exact counts and per-family
outcomes. Keep the original 143-pair matching corpus and reserved 23 families separate.
All curation, repair and review work is AI-assisted, not independent human gold.
